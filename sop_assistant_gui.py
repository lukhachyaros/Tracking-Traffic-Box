"""
SOP Assistant GUI - tool HO TRO gan nhan den giao thong (khong gan ho).

- Panel dieu khien nam canh man hinh (luon on top), co nut bam + phim tat toan cuc.
- Box/ghi chu ve truc tiep len man hinh bang overlay trong suot, click xuyen qua.
- Panel va overlay bi LOAI KHOI anh chup (Windows 10 2004+), nen khong con loi "guong soi".
- Den SOP bao KHONG gan (qua nho, bulb bi che >75%...) mac dinh KHONG ve box.

Cai dat:  pip uninstall -y opencv-python-headless
          pip install mss ultralytics opencv-python numpy keyboard
Chay:     python sop_assistant_gui.py            (them --model duong_dan.pt neu co model rieng)

Phim tat toan cuc:
  Ctrl+Alt+S      bat dau / dung quet lien tuc
  Ctrl+Alt+Space  quet 1 lan
  Ctrl+Alt+R      chon vung quet
  Ctrl+Alt+H      an / hien overlay
  Ctrl+Alt+E      luu bao cao
"""
import argparse
import ctypes
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import font as tkfont, ttk

import cv2
import mss
import numpy as np
from ultralytics import YOLO

try:
    import keyboard
except ImportError:  # phim tat toan cuc la tuy chon
    keyboard = None

TRAFFIC_LIGHT_CLASS = 9   # COCO "traffic light"
MIN_PX = 8                # SOP 2.2.1.5: nguong 8x8 px (tren anh GOC)
PANEL_W = 360
KEY_COLOR = "#010101"     # mau "trong suot" cua overlay
KIND_COLOR = {"ok": "#00d000", "lbonly": "#f0c800", "skip": "#a0a0a0"}   # mau CHU nhan
LB_COLOR, BULB_COLOR = "#3a86ff", "#ff2b2b"   # khung: Lightbox xanh duong, Bulb do (giong tool gan nhan)
DEFAULTS = {"conf": 0.25, "interval": 0.8, "thick": 3, "show_skip": False, "orig_w": "", "orient": "Tự động"}


# ------------------------------------------------------------------ Windows helpers
def set_dpi_aware():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _hwnd(win):
    win.update_idletasks()
    return ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()


def exclude_from_capture(win):
    """Loai cua so khoi anh chup man hinh (WDA_EXCLUDEFROMCAPTURE)."""
    try:
        return bool(ctypes.windll.user32.SetWindowDisplayAffinity(_hwnd(win), 0x11))
    except Exception:
        return False


def make_click_through(win):
    try:
        u = ctypes.windll.user32
        h = _hwnd(win)
        style = u.GetWindowLongW(h, -20)
        # LAYERED | TRANSPARENT | TOOLWINDOW | NOACTIVATE
        u.SetWindowLongW(h, -20, style | 0x80000 | 0x20 | 0x80 | 0x08000000)
    except Exception:
        pass


# ------------------------------------------------------------------ Phan tich theo SOP
def find_lit_bulbs(crop):
    """Tim vung sang (do/vang/xanh) trong crop Lightbox bang HSV.
    Dung kernel noi theo kich thuoc crop de gom den LED dang cham (hinh nguoi di bo) thanh 1 khoi."""
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    H, W = crop.shape[:2]
    bright = (v > 140) & (s > 60)
    hue = {
        "Red": (h <= 12) | (h >= 170),
        "Yellow": (h >= 13) & (h <= 34),
        "Green": (h >= 35) & (h <= 100),
    }
    k3 = np.ones((3, 3), np.uint8)
    kc = max(5, int(0.04 * max(H, W)) | 1)
    kclose = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kc, kc))
    found = []
    for name, hm in hue.items():
        mask = (bright & hm).astype(np.uint8) * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k3)      # bo net mong (box ve san)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kclose)  # noi manh vo / cham LED
        n, _, st, _ = cv2.connectedComponentsWithStats(mask)
        comps = [{"color": name, "x": int(st[i][0]), "y": int(st[i][1]), "w": int(st[i][2]),
                  "h": int(st[i][3]), "area": int(st[i][4])} for i in range(1, n) if st[i][4] >= 4]
        if comps:   # loc nhieu THEO TUNG MAU (den do mo khong bi den xanh sang hon nuot mat)
            m = max(c["area"] for c in comps)
            found += [c for c in comps if c["area"] >= 0.25 * m]
    return found


def refine_bulb(crop, b):
    """Khung bulb om het vung sang nhin thay (ranh gioi o 50% do sang giua nen va dinh)."""
    x, y, w, h = b["x"], b["y"], b["w"], b["h"]
    H, W = crop.shape[:2]
    p = max(3, int(0.4 * max(w, h)))
    x0, y0, x1, y1 = max(x - p, 0), max(y - p, 0), min(x + w + p, W), min(y + h + p, H)
    sub = crop[y0:y1, x0:x1]
    fallback = (x, y, w, h, b["area"])
    if sub.size == 0:
        return fallback
    v = cv2.cvtColor(sub, cv2.COLOR_BGR2HSV)[:, :, 2].astype(np.float32)
    bg, pk = float(np.percentile(v, 10)), float(np.percentile(v, 98))
    if pk - bg < 30:
        return fallback
    mask = (v >= bg + 0.5 * (pk - bg)).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(mask)
    if n <= 1:
        return fallback
    cx, cy = min(max(x + w // 2 - x0, 0), mask.shape[1] - 1), min(max(y + h // 2 - y0, 0), mask.shape[0] - 1)
    i = int(lab[cy, cx]) or 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    rx, ry, rw, rh, ra = (int(t) for t in st[i][:5])
    if rw > 1.6 * w or rh > 1.6 * h or rw < 0.5 * w or rh < 0.5 * h:   # tran hao quang / co lap -> giu khung goc
        return fallback
    return x0 + rx, y0 + ry, rw, rh, ra


def refine_lightbox(frame, box, bulbs_abs):
    """Khoanh vua khit than hop den (vung toi quanh bulb), khong lech xa khung YOLO."""
    x1, y1, x2, y2 = box
    fh, fw = frame.shape[:2]
    bw, bh = x2 - x1, y2 - y1
    if bw < 12 or bh < 12:
        return box
    pw, ph = int(bw * 0.1) + 2, int(bh * 0.1) + 2
    X1, Y1, X2, Y2 = max(x1 - pw, 0), max(y1 - ph, 0), min(x2 + pw, fw), min(y2 + ph, fh)
    sub = frame[Y1:Y2, X1:X2]
    v = cv2.cvtColor(sub, cv2.COLOR_BGR2HSV)[:, :, 2]
    mask = (v < 95).astype(np.uint8)
    for a, b, c, d in bulbs_abs:
        mask[max(b - Y1, 0):max(d - Y1, 0), max(a - X1, 0):max(c - X1, 0)] = 1
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(mask)
    if n <= 1:
        return box
    inside = lab[y1 - Y1:y2 - Y1, x1 - X1:x2 - X1]
    cnt = np.bincount(inside.ravel(), minlength=n)
    cnt[0] = 0
    i = int(np.argmax(cnt))
    if cnt[i] == 0:
        return box
    cx, cy, cw, ch = (int(t) for t in st[i][:4])
    if not 0.5 <= (cw * ch) / (bw * bh) <= 1.5:   # nen toi (ban dem...) -> giu khung YOLO
        return box
    rx1, ry1, rx2, ry2 = X1 + cx, Y1 + cy, X1 + cx + cw, Y1 + cy + ch
    for a, b, c, d in bulbs_abs:                    # bulb phai nam trong Lightbox
        rx1, ry1, rx2, ry2 = min(rx1, a), min(ry1, b), max(rx2, c), max(ry2, d)
    return max(rx1, 0), max(ry1, 0), min(rx2, fw), min(ry2, fh)


def guess_orientation(frame, bulb):
    """Doan huong hop den tu vung toi (than hop) noi lien voi bulb. Tra ve 'Ngang'/'Dọc'/None."""
    fh, fw = frame.shape[:2]
    a, b, c, d = bulb
    bw, bh = c - a, d - b
    m = int(2.5 * max(bw, bh)) + 2
    X1, Y1, X2, Y2 = max(a - m, 0), max(b - m, 0), min(c + m, fw), min(d + m, fh)
    v = cv2.cvtColor(frame[Y1:Y2, X1:X2], cv2.COLOR_BGR2HSV)[:, :, 2]
    mask = (v < 95).astype(np.uint8)
    mask[max(b - Y1, 0):max(d - Y1, 0), max(a - X1, 0):max(c - X1, 0)] = 1
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(mask)
    cy, cx = min(max((b + d) // 2 - Y1, 0), mask.shape[0] - 1), min(max((a + c) // 2 - X1, 0), mask.shape[1] - 1)
    i = int(lab[cy, cx])
    if i == 0:
        return None
    cw, ch = int(st[i][2]), int(st[i][3])
    if cw >= 1.5 * ch and cw >= 1.8 * bw:
        return "Ngang"
    if ch >= 1.5 * cw and ch >= 1.8 * bh:
        return "Dọc"
    return None


def ensure_housing(frame, box, kept, bulbs_abs, fw, fh, orient):
    """Neu khung chi om bulb (khong thay than hop), uoc luong ca hop 3 bong theo ti le mau SOP/vi du:
    rong ~1.57x bulb, cao ~3.8x bulb (doc); do o tren, vang giua, xanh o duoi (ngang: do trai, xanh phai).
    Tra ve (box, da_uoc_luong, huong_da_dung)."""
    if orient == "Tắt":
        return box, False, orient
    k = max(range(len(bulbs_abs)), key=lambda t: (bulbs_abs[t][2] - bulbs_abs[t][0]) * (bulbs_abs[t][3] - bulbs_abs[t][1]))
    a, b, c, d = bulbs_abs[k]
    bw, bh = c - a, d - b
    # khung da om than hop theo BAT KY chieu nao (hop doc HOAC ngang) -> khong uoc luong
    if (box[3] - box[1]) >= 2.2 * bh or (box[2] - box[0]) >= 2.2 * bw:
        return box, False, orient
    used = orient
    if orient == "Tự động":
        used = guess_orientation(frame, bulbs_abs[k]) or "Dọc"
    slot = {"Red": 0, "Yellow": 1, "Green": 2}.get(kept[k]["color"], 0)
    if used != "Ngang":
        m, g, side = 0.23 * bh, 0.17 * bh, 0.28 * bw
        top = b - m - slot * (bh + g)
        r = (a - side, top, c + side, top + 3 * bh + 2 * g + 2 * m)
    else:
        m, g, side = 0.23 * bw, 0.17 * bw, 0.28 * bh
        left = a - m - slot * (bw + g)
        r = (left, b - side, left + 3 * bw + 2 * g + 2 * m, d + side)
    return (max(int(r[0]), 0), max(int(r[1]), 0), min(int(r[2]), fw), min(int(r[3]), fh)), True, used


def arrangement(w, h):
    r = w / max(h, 1)
    if r > 1.8:
        return "Xếp ngang", int(np.clip(round(r), 1, 6))
    if r < 0.55:
        return "Xếp dọc", int(np.clip(round(1 / r), 1, 6))
    return "Một bóng/khác", 1


def detect(frame, model, scale, conf, orient="Dọc"):
    res = model.predict(frame, classes=[TRAFFIC_LIGHT_CLASS], conf=conf, imgsz=1280, verbose=False)[0]
    fh, fw = frame.shape[:2]
    items = []
    boxes = res.boxes.xyxy.cpu().numpy().astype(int)
    confs = res.boxes.conf.cpu().numpy()
    for (bx1, by1, bx2, by2), cf in zip(boxes, confs):
        x1, y1, x2, y2 = max(bx1, 0), max(by1, 0), min(bx2, fw), min(by2, fh)
        crop = frame[y1:y2, x1:x2]
        if crop.shape[0] < 3 or crop.shape[1] < 3:
            continue

        bulbs = []
        for b in find_lit_bulbs(crop):
            rx, ry, rw, rh, ra = refine_bulb(crop, b)
            ref = np.pi / 4 * max(rw, rh) ** 2
            roundish = 0.6 <= rw / max(rh, 1) <= 1.6   # hinh nguoi/mui ten dai: khong ap dung uoc luong tron
            visible = min(ra / ref, 1.0) if (ref > 0 and roundish) else 1.0
            bulbs.append({"color": b["color"], "x": rx, "y": ry, "w": rw, "h": rh, "hidden": 1.0 - visible})

        notes, kept, desc, countdown = [], [], "", False
        big = [b for b in bulbs if b["w"] * scale >= MIN_PX and b["h"] * scale >= MIN_PX]
        if not bulbs:      # SOP 2.2.1.5.1: bulb tat -> xet kich thuoc Lightbox
            if (x2 - x1) * scale <= MIN_PX and (y2 - y1) * scale <= MIN_PX:
                kind, label = "skip", f"Bỏ qua: Lightbox tắt ≤{MIN_PX}×{MIN_PX}"
            else:
                kind, label = "lbonly", "black_lightbox → chỉ vẽ 1 khung Lightbox"
                notes.append("Nếu chỉ thấy mặt sau, hoặc Lightbox bị che/cắt >75% → KHÔNG vẽ")
                if cf < 0.4:
                    notes.append(f"Độ tin cậy nhận diện thấp ({cf:.2f}): kiểm tra có bị che nhiều không")
        elif not big:      # SOP 2.2.1.5.2: bulb sang <8x8 -> khong gan ca Bulb va Lightbox
            kind, label = "skip", f"Bỏ qua: bulb sáng <{MIN_PX}×{MIN_PX} (không vẽ Bulb lẫn Lightbox)"
        else:
            kept = [b for b in big if b["hidden"] <= 0.75]
            if not kept:   # SOP 2.2.4.3: bulb bi che >75% -> chi gan Lightbox
                kind, label = "lbonly", "Bulb bị che >75% (ước lượng) → chỉ vẽ Lightbox"
                notes.append("Nếu bulb hoàn toàn không thấy do bị che từ bên cạnh → KHÔNG vẽ cả Lightbox")
            else:
                if (len(kept) >= 2 and len({b["color"] for b in kept}) == 1
                        and 0.6 <= (x2 - x1) / max(y2 - y1, 1) <= 1.4):
                    ux1, uy1 = min(b["x"] for b in kept), min(b["y"] for b in kept)
                    ux2, uy2 = max(b["x"] + b["w"] for b in kept), max(b["y"] + b["h"] for b in kept)
                    countdown = True
                    kept = [{"color": kept[0]["color"], "x": ux1, "y": uy1, "w": ux2 - ux1, "h": uy2 - uy1, "hidden": 0.0}]
                    notes.append("Đèn đếm ngược? → 1 khung Lightbox + 1 khung Bulb ôm cả số; điền Hundreds/Tens/Units (SOP mục 6)")
                kind, label = "ok", ""
                desc = ", ".join(f'{b["color"]} {int(b["w"]*scale)}×{int(b["h"]*scale)}' for b in kept)
                if any(0.25 <= b["w"] / max(b["h"], 1) <= 0.7 for b in kept):
                    notes.append("Hình người? → Lightbox: pedestrian_lightbox, Shape: Pedestrian")
                if len({b["color"] for b in kept}) > 1:
                    notes.append("Nhiều màu sáng: kiểm tra Other/luân phiên")
                for b in kept:
                    if b["hidden"] >= 0.30:
                        lvl = "heavily_occlude" if b["hidden"] > 0.5 else "occluded"
                        notes.append(f"Bulb {b['color']} nghi bị che ~{int(b['hidden']*100)}% ({lvl}), ước lượng")

        bulbs_abs = [(x1 + b["x"], y1 + b["y"], x1 + b["x"] + b["w"], y1 + b["y"] + b["h"]) for b in kept]
        lb_box, est, used, tag = (x1, y1, x2, y2), False, orient, "Bỏ qua"
        if kind != "skip":
            lb_box = refine_lightbox(frame, lb_box, bulbs_abs)
            if kind == "ok" and not countdown:   # hop so dem nguoc: giu khung hop that, khong uoc luong 3 bong
                lb_box, est, used = ensure_housing(frame, lb_box, kept, bulbs_abs, fw, fh, orient)
                if est:
                    how = " tự đoán" if orient == "Tự động" else ""
                    notes.append(f"Lightbox ƯỚC LƯỢNG từ vị trí bulb (hộp 3 bóng, {used.lower()}{how}): "
                                 "chỉnh lại cho khớp thân hộp; nếu sai hướng hãy chọn Dọc/Ngang trong Cài đặt")
            lw, lh = int((lb_box[2] - lb_box[0]) * scale), int((lb_box[3] - lb_box[1]) * scale)
            label = f"Lightbox {lw}×{lh} · Bulb {desc}" if kind == "ok" else f"{label} ({lw}×{lh})"
            tag = f"Lightbox {lw}×{lh}" if kind == "ok" else f"Lightbox chỉ hộp {lw}×{lh}"
            arr, nb = arrangement(lb_box[2] - lb_box[0], lb_box[3] - lb_box[1])
            nb = 3 if est else nb
            if countdown:   # SOP muc 12: dem nguoc don -> Number of Bulbs = 1, Single or Other
                arr, nb = "Một bóng/khác (Single or Other)", 1
            notes.append(f"{arr}, ~{nb} bulb")
        if x1 <= 2 or y1 <= 2 or x2 >= fw - 2 or y2 >= fh - 2:
            notes.append("Sát mép vùng quét (nếu là mép ảnh: truncation, khung sát mép)")
        items.append({"kind": kind, "label": label, "tag": tag, "notes": notes, "box": lb_box,
                      "bulbs": bulbs_abs if kind == "ok" else [],
                      "bulb_tags": [f'{b["color"]} {int(b["w"]*scale)}×{int(b["h"]*scale)}' for b in kept] if kind == "ok" else []})
    items.sort(key=lambda it: (it["box"][0], it["box"][1]))   # danh so #1, #2... tu trai sang phai
    return items


# ------------------------------------------------------------------ Worker thread
class Shared:
    def __init__(self, roi):
        self.lock = threading.Lock()
        self.roi, self.scale = roi, 1.0
        self.conf, self.interval = DEFAULTS["conf"], DEFAULTS["interval"]
        self.orient = DEFAULTS["orient"]
        self.running, self.once, self.stop = False, False, False
        self.wake = threading.Event()


class Worker(threading.Thread):
    def __init__(self, model_path, shared, out_q):
        super().__init__(daemon=True)
        self.model_path, self.sh, self.q = model_path, shared, out_q

    def run(self):
        try:
            self.q.put(("status", "Đang tải model…"))
            model = YOLO(self.model_path)
            self.q.put(("status", "Sẵn sàng"))
            with (getattr(mss, "MSS", None) or mss.mss)() as sct:
                while not self.sh.stop:
                    with self.sh.lock:
                        run, once = self.sh.running, self.sh.once
                        self.sh.once = False
                        roi, scale, conf, itv, orient = dict(self.sh.roi), self.sh.scale, self.sh.conf, self.sh.interval, self.sh.orient
                    if run or once:
                        try:
                            frame = np.ascontiguousarray(np.array(sct.grab(roi))[:, :, :3])
                            self.q.put(("result", roi, detect(frame, model, scale, conf, orient)))
                        except Exception as e:  # loi 1 lan quet khong lam sap tool
                            self.q.put(("status", f"Lỗi quét: {e}"))
                    self.sh.wake.wait(timeout=itv if run else 0.2)
                    self.sh.wake.clear()
        except Exception as e:
            self.q.put(("status", f"Lỗi khởi tạo: {e}"))


# ------------------------------------------------------------------ Overlay + chon vung
def place_labels(specs, W, H):
    """specs: [(tw, th, (x1,y1,x2,y2), prefer_below)] -> list rect (x1,y1,x2,y2) khong chong nhau,
    nam trong canvas. Thu lan luot cac vi tri phia tren/duoi khung, xep chong len cao dan."""
    placed, out = [], []
    for tw, th, (x1, y1, x2, y2), below in specs:
        x = min(max(x1, 0), max(W - tw, 0))
        above = [y1 - th - 1 - k * (th + 1) for k in range(8)]
        under = [y2 + 1 + k * (th + 1) for k in range(8)]
        cands = under + above if below else above + under
        pick = None
        for y in cands:
            if y < 0 or y + th > H:
                continue
            r = (x, y, x + tw, y + th)
            if all(r[2] <= q[0] or r[0] >= q[2] or r[3] <= q[1] or r[1] >= q[3] for q in placed):
                pick = r
                break
        if pick is None:
            yy = min(max(y1 - th - 1, 0), max(H - th, 0))
            pick = (x, yy, x + tw, yy + th)
        placed.append(pick)
        out.append(pick)
    return out


class Overlay:
    def __init__(self, root):
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=KEY_COLOR)
        self.win.attributes("-transparentcolor", KEY_COLOR)
        self.cv = tk.Canvas(self.win, bg=KEY_COLOR, highlightthickness=0)
        self.cv.pack(fill="both", expand=True)
        self.win.geometry("1x1+0+0")
        self.font = tkfont.Font(family="Segoe UI", size=9, weight="bold")
        self.font_s = tkfont.Font(family="Segoe UI", size=8, weight="bold")
        self.styled = False
        self.excluded = False

    def place(self, roi):
        self.win.geometry(f"{roi['width']}x{roi['height']}+{roi['left']}+{roi['top']}")
        self.win.update()
        if not self.styled:
            make_click_through(self.win)
            self.excluded = exclude_from_capture(self.win)
            self.styled = True

    def draw(self, items, thick=3, show_skip=False):
        c = self.cv
        c.delete("all")
        W = c.winfo_width() if c.winfo_width() > 1 else 10 ** 5
        H = c.winfo_height() if c.winfo_height() > 1 else 10 ** 5
        labels = []   # (text, mau, font, khung, uu_tien_duoi)
        for n, it in enumerate(items, 1):
            if it["kind"] == "skip" and not show_skip:
                continue   # SOP bao khong gan -> khong ve box
            box_col = "#a0a0a0" if it["kind"] == "skip" else LB_COLOR
            c.create_rectangle(*it["box"], outline=box_col, width=thick)
            labels.append((f"#{n} {it['tag']}", KIND_COLOR[it["kind"]], self.font, it["box"], False))
            for bb, tg in zip(it["bulbs"], it["bulb_tags"]):
                c.create_rectangle(*bb, outline=BULB_COLOR, width=thick)
                labels.append((tg, BULB_COLOR, self.font_s, bb, True))
        specs = [(f.measure(t) + 6, f.metrics("linespace") + 2, box, below) for t, _, f, box, below in labels]
        for (t, col, f, _, _), r in zip(labels, place_labels(specs, W, H)):
            c.create_rectangle(*r, fill="#202020", outline="")
            c.create_text(r[0] + 3, r[1] + 1, text=t, anchor="nw", fill=col, font=f)

    def clear(self):
        self.cv.delete("all")

    def show(self):
        self.win.deiconify()
        make_click_through(self.win)

    def hide(self):
        self.win.withdraw()


def select_region(root, callback):
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    sel = tk.Toplevel(root)
    sel.overrideredirect(True)
    sel.attributes("-topmost", True)
    sel.attributes("-alpha", 0.3)
    sel.geometry(f"{sw}x{sh}+0+0")
    sel.configure(bg="black", cursor="crosshair")
    cv = tk.Canvas(sel, bg="black", highlightthickness=0, cursor="crosshair")
    cv.pack(fill="both", expand=True)
    cv.create_text(sw // 2, 40, fill="white", font=("Segoe UI", 16, "bold"),
                   text="Kéo chuột chọn vùng chứa ảnh  ·  Esc: huỷ")
    exclude_from_capture(sel)
    state = {"x": 0, "y": 0, "r": None}

    def press(e):
        state["x"], state["y"] = e.x, e.y
        state["r"] = cv.create_rectangle(e.x, e.y, e.x, e.y, outline="#00ff00", width=2)

    def drag(e):
        if state["r"]:
            cv.coords(state["r"], state["x"], state["y"], e.x, e.y)

    def release(e):
        x1, x2 = sorted((state["x"], e.x))
        y1, y2 = sorted((state["y"], e.y))
        sel.destroy()
        callback({"left": x1, "top": y1, "width": x2 - x1, "height": y2 - y1} if x2 - x1 > 30 and y2 - y1 > 30 else None)

    def cancel(_e=None):
        sel.destroy()
        callback(None)

    cv.bind("<ButtonPress-1>", press)
    cv.bind("<B1-Motion>", drag)
    cv.bind("<ButtonRelease-1>", release)
    sel.bind("<Escape>", cancel)
    sel.focus_force()


# ------------------------------------------------------------------ Ung dung chinh
def _get(var, fallback):
    try:
        return var.get()
    except tk.TclError:   # nguoi dung dang go do trong o nhap
        return fallback


class App:
    def __init__(self, model_path):
        self.root = tk.Tk()
        self.root.title("SOP Assistant")
        self.root.attributes("-topmost", True)
        self.sw, self.sh_ = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.side = "right"
        self.roi_default = True
        self.shared = Shared(self.default_roi())
        self.q, self.cmd_q = queue.Queue(), queue.Queue()
        self.overlay = Overlay(self.root)
        self.overlay_roi, self.overlay_on = None, True
        self.items = []
        self._scan_params, self._draw_params = None, None
        self.worker = Worker(model_path, self.shared, self.q)
        self.build_ui()
        self.place_panel()
        self.root.update()
        exclude_from_capture(self.root)
        self.register_hotkeys()
        self.worker.start()
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self.root.after(100, self.poll)

    # ---- UI
    def build_ui(self):
        r = self.root
        pad = {"padx": 10, "pady": 3}
        ttk.Label(r, text="SOP Assistant · Đèn giao thông", font=("Segoe UI", 12, "bold")).pack(anchor="w", **pad)
        self.status = tk.StringVar(value="Đang khởi động…")
        ttk.Label(r, textvariable=self.status, foreground="#0a64c8", wraplength=PANEL_W - 24).pack(anchor="w", **pad)

        bf = ttk.Frame(r)
        bf.pack(fill="x", padx=10, pady=4)
        self.btn_run = ttk.Button(bf, text="▶ Bắt đầu quét   (Ctrl+Alt+S)", command=self.toggle_run)
        self.btn_run.pack(fill="x", pady=2, ipady=4)
        for text, cmd in [("Quét 1 lần   (Ctrl+Alt+Space)", self.scan_once),
                          ("Chọn vùng quét   (Ctrl+Alt+R)", self.pick_region),
                          ("Ẩn/hiện overlay   (Ctrl+Alt+H)", self.toggle_overlay),
                          ("Lưu báo cáo   (Ctrl+Alt+E)", self.export)]:
            ttk.Button(bf, text=text, command=cmd).pack(fill="x", pady=2, ipady=2)
        row = ttk.Frame(bf)
        row.pack(fill="x", pady=2)
        ttk.Button(row, text="⇄ Đổi bên", command=self.flip_side).pack(side="left", expand=True, fill="x", padx=(0, 2))
        ttk.Button(row, text="Thoát", command=self.quit).pack(side="left", expand=True, fill="x", padx=(2, 0))

        sf = ttk.LabelFrame(r, text="Cài đặt")
        sf.pack(fill="x", padx=10, pady=6)
        self.orig_w = tk.StringVar(value=DEFAULTS["orig_w"])
        self.conf = tk.DoubleVar(value=DEFAULTS["conf"])
        self.itv = tk.DoubleVar(value=DEFAULTS["interval"])
        self.thick = tk.IntVar(value=DEFAULTS["thick"])
        self.show_skip = tk.BooleanVar(value=DEFAULTS["show_skip"])
        self.orient = tk.StringVar(value=DEFAULTS["orient"])

        ttk.Label(sf, text="Rộng ảnh gốc (px), để trống = dùng vùng chọn:", wraplength=PANEL_W - 40).pack(anchor="w", padx=6)
        ttk.Entry(sf, textvariable=self.orig_w, width=10).pack(anchor="w", padx=6, pady=2)

        ttk.Label(sf, text="Độ nhạy nhận diện (thấp = nhạy hơn, bước 0.01):").pack(anchor="w", padx=6)
        cr = ttk.Frame(sf)
        cr.pack(fill="x", padx=6)
        tk.Scale(cr, from_=0.10, to=0.60, resolution=0.01, bigincrement=0.01, orient="horizontal",
                 variable=self.conf, showvalue=False).pack(side="left", fill="x", expand=True)
        ttk.Spinbox(cr, from_=0.10, to=0.60, increment=0.01, textvariable=self.conf, format="%.2f", width=5).pack(side="left", padx=(6, 0))

        orow = ttk.Frame(sf)
        orow.pack(fill="x", padx=6, pady=2)
        ttk.Label(orow, text="Ước lượng Lightbox khi khung chỉ ôm bulb:").pack(side="left")
        ttk.Combobox(orow, values=["Tự động", "Dọc", "Ngang", "Tắt"], textvariable=self.orient, state="readonly", width=9).pack(side="left", padx=6)
        ttk.Label(sf, text="Chu kỳ quét (giây):").pack(anchor="w", padx=6)
        tk.Scale(sf, from_=0.3, to=3.0, resolution=0.1, bigincrement=0.1, orient="horizontal",
                 variable=self.itv).pack(fill="x", padx=6)
        ttk.Label(sf, text="Độ dày box (px):").pack(anchor="w", padx=6)
        tk.Scale(sf, from_=1, to=6, resolution=1, orient="horizontal", variable=self.thick).pack(fill="x", padx=6)
        ttk.Checkbutton(sf, text="Hiện cả đèn SOP bảo không gán (box xám)", variable=self.show_skip).pack(anchor="w", padx=6, pady=2)
        ttk.Button(sf, text="Đặt lại cài đặt gốc", command=self.reset_settings).pack(fill="x", padx=6, pady=(2, 6))

        self.summary = tk.StringVar(value="Chưa có kết quả")
        ttk.Label(r, textvariable=self.summary, font=("Segoe UI", 10, "bold"), wraplength=PANEL_W - 24).pack(anchor="w", **pad)
        ttk.Label(r, text="Khung xanh dương = Lightbox, khung đỏ = Bulb. Chữ xanh lá: vẽ cả hai · chữ vàng: chỉ vẽ Lightbox",
                  wraplength=PANEL_W - 24, foreground="#555").pack(anchor="w", padx=10)

        tf = ttk.Frame(r)
        tf.pack(fill="both", expand=True, padx=10, pady=6)
        self.txt = tk.Text(tf, wrap="word", font=("Segoe UI", 9), state="disabled", height=8)
        sb = ttk.Scrollbar(tf, command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.txt.pack(side="left", fill="both", expand=True)

    def place_panel(self):
        x = self.sw - PANEL_W if self.side == "right" else 0
        self.root.geometry(f"{PANEL_W}x{self.sh_ - 60}+{x}+0")

    def default_roi(self):
        left = 0 if self.side == "right" else PANEL_W
        return {"left": left, "top": 0, "width": self.sw - PANEL_W, "height": self.sh_}

    # ---- hanh dong
    def request_scan(self):
        with self.shared.lock:
            self.shared.once = True
        self.shared.wake.set()

    def sync(self):
        s = self.shared
        conf = round(float(_get(self.conf, s.conf)), 2)
        itv = float(_get(self.itv, s.interval))
        try:
            ow = int(self.orig_w.get())
        except ValueError:
            ow = 0
        with s.lock:
            s.conf, s.interval = conf, itv
            s.orient = self.orient.get()
            s.scale = (ow / s.roi["width"]) if ow > 0 else 1.0
            running = s.running
        scan_params = (conf, ow, self.orient.get())
        if self._scan_params is not None and scan_params != self._scan_params and not running and self.items:
            self.request_scan()          # doi do nhay/anh goc khi dang dung -> quet lai ngay
        self._scan_params = scan_params
        draw_params = (int(_get(self.thick, 3)), bool(self.show_skip.get()))
        if draw_params != self._draw_params:
            self._draw_params = draw_params
            self.redraw()

    def redraw(self):
        if self.overlay_on and self.overlay_roi:
            self.overlay.draw(self.items, int(_get(self.thick, 3)), bool(self.show_skip.get()))

    def reset_settings(self):
        self.orig_w.set(DEFAULTS["orig_w"])
        self.conf.set(DEFAULTS["conf"])
        self.itv.set(DEFAULTS["interval"])
        self.thick.set(DEFAULTS["thick"])
        self.show_skip.set(DEFAULTS["show_skip"])
        self.orient.set(DEFAULTS["orient"])
        self.roi_default = True
        with self.shared.lock:
            self.shared.roi = self.default_roi()
        self.items = []
        self.overlay.clear()
        self.summary.set("Chưa có kết quả")
        self.status.set("Đã đặt lại cài đặt gốc (vùng quét về mặc định)")

    def toggle_run(self):
        with self.shared.lock:
            self.shared.running = not self.shared.running
            run = self.shared.running
        self.btn_run.config(text=("■ Dừng quét   (Ctrl+Alt+S)" if run else "▶ Bắt đầu quét   (Ctrl+Alt+S)"))
        if not run:
            self.status.set("Đã dừng (kết quả cuối vẫn hiển thị)")
        self.shared.wake.set()

    def scan_once(self):
        self.sync()
        self.request_scan()

    def pick_region(self):
        self.overlay.hide()

        def done(roi):
            if self.overlay_on:
                self.overlay.show()
            if roi:
                with self.shared.lock:
                    self.shared.roi = roi
                self.roi_default = False
                self.items = []
                self.overlay.clear()
                self.status.set(f"Vùng quét: {roi['width']}×{roi['height']} px")
        select_region(self.root, done)

    def toggle_overlay(self):
        self.overlay_on = not self.overlay_on
        if self.overlay_on:
            self.overlay.show()
            self.redraw()
        else:
            self.overlay.hide()

    def flip_side(self):
        self.side = "left" if self.side == "right" else "right"
        self.place_panel()
        if self.roi_default:
            with self.shared.lock:
                self.shared.roi = self.default_roi()
            self.items = []
            self.overlay.clear()

    def export(self):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), time.strftime("sop_report_%Y%m%d_%H%M%S.txt"))
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"SOP Assistant report {time.strftime('%Y-%m-%d %H:%M:%S')}\nVùng quét: {self.shared.roi}\n\n")
            f.write(self.report_text())
        self.status.set(f"Đã lưu: {path}")

    def quit(self):
        self.shared.stop = True
        self.shared.wake.set()
        if keyboard:
            try:
                keyboard.unhook_all()
            except Exception:
                pass
        self.root.destroy()

    def register_hotkeys(self):
        if not keyboard:
            self.status.set("Chưa có phím tắt toàn cục: pip install keyboard")
            return
        for combo, cmd in {"ctrl+alt+s": "run", "ctrl+alt+space": "once", "ctrl+alt+r": "region",
                           "ctrl+alt+h": "overlay", "ctrl+alt+e": "export"}.items():
            try:
                keyboard.add_hotkey(combo, lambda c=cmd: self.cmd_q.put(c))
            except Exception:
                pass

    # ---- ket qua
    def report_text(self):
        if not self.items:
            return "Không thấy đèn giao thông trong vùng quét.\n"
        out = []
        for i, it in enumerate(self.items, 1):
            out.append(f"#{i}  {it['label']}" + ("   (không vẽ)" if it["kind"] == "skip" else ""))
            out += [f"      • {n}" for n in it["notes"]]
        return "\n".join(out) + "\n"

    def on_result(self, roi, items):
        if roi != self.overlay_roi:
            self.overlay.place(roi)
            self.overlay_roi = roi
        self.items = items
        self.redraw()
        n = {k: sum(1 for i in items if i["kind"] == k) for k in KIND_COLOR}
        self.summary.set(f"{len(items)} đèn · {n['ok']} Lightbox+Bulb · {n['lbonly']} chỉ Lightbox · {n['skip']} không vẽ")
        self.txt.config(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.insert("end", self.report_text())
        self.txt.config(state="disabled")
        warn = "" if self.overlay.excluded else "  ⚠ Windows không hỗ trợ loại overlay khỏi ảnh chụp"
        self.status.set(f"Quét lúc {time.strftime('%H:%M:%S')}{warn}")

    def poll(self):
        self.sync()
        last = None
        try:
            while True:
                msg = self.q.get_nowait()
                if msg[0] == "status":
                    self.status.set(msg[1])
                else:
                    last = msg
        except queue.Empty:
            pass
        if last:
            self.on_result(last[1], last[2])
        try:
            while True:
                {"run": self.toggle_run, "once": self.scan_once, "region": self.pick_region,
                 "overlay": self.toggle_overlay, "export": self.export}[self.cmd_q.get_nowait()]()
        except queue.Empty:
            pass
        self.root.after(100, self.poll)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="yolov8s.pt", help="có thể thay bằng model tự train (Lightbox/Bulb)")
    args = ap.parse_args()
    set_dpi_aware()
    App(args.model).root.mainloop()


if __name__ == "__main__":
    main()
