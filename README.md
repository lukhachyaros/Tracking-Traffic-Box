# 🚦 Tracking-Traffic-Box · SOP Assistant GUI

> **Công cụ hỗ trợ thông minh cho việc gán nhãn đèn giao thông theo quy chuẩn SOP (Standard Operating Procedures).**  
> *Lưu ý: Đây là công cụ trợ lực (hỗ trợ kiểm tra, gợi ý và canh khung), không tự động gán nhãn thay thế con người.*

---

## 📖 Giới thiệu

Trong các dự án gán nhãn dữ liệu xe tự hành và thị giác máy tính, việc gán nhãn đèn giao thông đòi hỏi tuân thủ các quy tắc SOP rất khắt khe (kích thước tối thiểu $8 \times 8$ px, phân biệt `black_lightbox`, phân loại trạng thái bóng sáng, phát hiện che khuất $>75\%$, đếm ngược, đèn người đi bộ, ước lượng thân hộp,...).

**SOP Assistant GUI** là ứng dụng chạy ngầm trên Windows, quét trực tiếp vùng làm việc trên màn hình thông qua mô hình YOLOv8 kết hợp xử lý ảnh thị giác máy tính (Computer Vision) để:
1. Phát hiện vị trí hộp đèn (**Lightbox**) và các bóng đèn sáng (**Bulb** - Đỏ, Vàng, Xanh).
2. Tự động kiểm tra và đối chiếu với các điều kiện trong tài liệu SOP.
3. Vẽ khung gợi ý và ghi chú trực tiếp lên màn hình bằng lớp phủ trong suốt (**Transparent Overlay**) có tính năng **Click-through** (cho phép thao tác chuột xuyên qua màn hình để vẽ nhãn bình thường).
4. Áp dụng cơ chế loại trừ cửa sổ khỏi ảnh chụp màn hình (`WDA_EXCLUDEFROMCAPTURE`), loại bỏ hoàn toàn hiện tượng "gương soi lặp vô tận" khi chụp ảnh liên tục.

---

## ✨ Tính năng nổi bật

### 1. Phủ thông tin trực quan & Không gây cản trở
* **Overlay trong suốt & Click-Through**: Các khung viền và nhãn hiển thị nổi trên màn hình mà không chặn bất kỳ cú nhấp chuột hay thao tác vẽ nhãn nào trên công cụ dán nhãn của bạn.
* **Chống hiệu ứng gương soi (Anti-mirroring)**: Panel và Overlay tự động được loại trừ khỏi ảnh chụp màn hình trên Windows 10 (bản 2004+) và Windows 11 nhờ Windows Display Affinity API.
* **Panel điều khiển linh hoạt**: Luôn nổi trên cùng (*Always-on-top*), hỗ trợ chuyển đổi vị trí sang mép trái hoặc mép phải màn hình (`⇄ Đổi bên`) để tránh che khuất không gian làm việc.

### 2. Đối chiếu chuẩn SOP tự động & Chính xác
* **Ngưỡng kích thước tối thiểu ($8 \times 8$ px - SOP 2.2.1.5)**:
  * Đèn tắt hoặc mờ: Kiểm tra kích thước Lightbox, nếu $\le 8 \times 8$ px sẽ gợi ý **Bỏ qua**.
  * Bóng sáng $< 8 \times 8$ px: Gợi ý **Bỏ qua** cả Bulb lẫn Lightbox (theo SOP 2.2.1.5.2).
* **Đèn tắt (`black_lightbox`)**: Khi không phát hiện bóng sáng, công cụ hướng dẫn chỉ vẽ 1 khung Lightbox nếu thấy rõ hộp đèn.
* **Tự động đo mức độ che khuất (Occlusion)**: Tính toán diện tích thực so với hình dáng chuẩn; nếu bóng bị che $> 75\%$, công cụ chuyển sang chế độ chỉ vẽ Lightbox (theo SOP 2.2.4.3).
* **Nhận diện loại đèn đặc thù**:
  * **Đèn đếm ngược (Countdown Timer)**: Nhận diện cụm số hiển thị, gom nhóm thành 1 Lightbox + 1 Bulb ôm trọn số, nhắc nhở gán nhãn `Hundreds`/`Tens`/`Units` (SOP mục 6 & 12).
  * **Đèn người đi bộ (Pedestrian)**: Gợi ý gán nhãn `pedestrian_lightbox` và shape `Pedestrian`.
  * **Cảnh báo mép ảnh (Truncation)**: Cảnh báo khi đối tượng nằm sát viền vùng quét.
* **Ước lượng thân hộp đèn (Housing Estimation)**:
  * Trong trường hợp YOLO chỉ nhận diện được bóng đèn sáng mà không ôm hết thân hộp tối, thuật toán tự động ước lượng kích thước hộp đèn 3 bóng chuẩn theo hướng **Dọc**, **Ngang** hoặc **Tự động đoán**.

### 3. Quy đổi kích thước theo ảnh gốc
* Hỗ trợ nhập **Chiều rộng ảnh gốc (`orig_w`)**: Khi phóng to/thu nhỏ ảnh trên trình duyệt/tool gán nhãn, bạn chỉ cần nhập độ rộng thực của ảnh gốc, ứng dụng sẽ tự động tính toán lại kích thước pixel chuẩn xác theo SOP.

### 4. Hệ thống phím tắt toàn cục (Global Hotkeys)
Hoạt động ngay cả khi đang thao tác trên cửa sổ khác:

| Phím tắt | Chức năng | Mô tả |
| :--- | :--- | :--- |
| `Ctrl + Alt + S` | **Bắt đầu / Dừng quét** | Bật/tắt chế độ quét liên tục theo chu kỳ đặt trước |
| `Ctrl + Alt + Space` | **Quét 1 lần** | Quét nhanh ảnh hiện tại trên màn hình một lần duy nhất |
| `Ctrl + Alt + R` | **Chọn vùng quét** | Kéo chuột để giới hạn vùng màn hình cần nhận diện |
| `Ctrl + Alt + H` | **Ẩn / Hiện overlay** | Bật/tắt nhanh lớp phủ khung trên màn hình |
| `Ctrl + Alt + E` | **Lưu báo cáo** | Xuất kết quả kiểm tra ra file `sop_report_YYYYMMDD_HHMMSS.txt` |

---

## 🎨 Quy ước màu sắc hiển thị

### Đường viền khung:
* 🟦 **Màu xanh dương (`#3a86ff`)**: Khung đại diện cho **Lightbox** (Hộp đèn).
* 🟥 **Màu đỏ (`#ff2b2b`)**: Khung đại diện cho **Bulb** (Bóng đèn phát sáng).
* ⬜ **Màu xám**: Đèn thuộc diện SOP yêu cầu **Bỏ qua** (chỉ hiển thị khi tích chọn *"Hiện cả đèn SOP bảo không gán"*).

### Nhãn trạng thái (Text Label):
* 🟩 **Chữ màu xanh lá (`ok`)**: Đèn đạt chuẩn, cần vẽ cả khung Lightbox và khung Bulb.
* 🟨 **Chữ màu vàng (`lbonly`)**: Chỉ vẽ 1 khung Lightbox (do bóng tắt, đèn đếm ngược hoặc bóng bị che $>75\%$).
* ⬜ **Chữ màu xám (`skip`)**: Bỏ qua, không vẽ theo quy tắc SOP.

---

## 🛠️ Yêu cầu hệ thống & Cài đặt

### Yêu cầu:
* **Hệ điều hành**: Windows 10 (bản Build 2004 trở lên) hoặc Windows 11 *(cần thiết để sử dụng tính năng loại trừ chụp màn hình `SetWindowDisplayAffinity`)*.
* **Python**: Khuyến nghị phiên bản `Python 3.8` - `3.11`.

### Các bước cài đặt:

1. **Clone repository về máy:**
   ```bash
   git clone https://gitlab.com/<your-username>/Tracking-Traffic-Box.git
   cd Tracking-Traffic-Box
   ```

2. **Tạo môi trường ảo (khuyến nghị):**
   ```bash
   python -m venv venv
   # Kích hoạt trên Windows PowerShell:
   .\venv\Scripts\Activate.ps1
   # Hoặc trên Command Prompt (cmd):
   .\venv\Scripts\activate.bat
   ```

3. **Cài đặt các gói phụ thuộc:**
   > **Lưu ý:** Nếu máy bạn đã cài `opencv-python-headless`, hãy gỡ bỏ trước để tránh xung đột với GUI Tkinter/OpenCV.
   ```bash
   pip uninstall -y opencv-python-headless
   pip install mss ultralytics opencv-python numpy keyboard
   ```

---

## 🚀 Hướng dẫn sử dụng

### 1. Khởi chạy ứng dụng

* Chạy với model mặc định (`yolov8s.pt` đi kèm):
  ```bash
  python sop_assistant_gui.py
  ```
* Chạy với model tùy chỉnh (ví dụ weights chuyên biệt cho đèn giao thông):
  ```bash
  python sop_assistant_gui.py --model duong_dan_model.pt
  ```

### 2. Quy trình làm việc đề xuất

1. **Khởi động tool**: Panel điều khiển xuất hiện ở mép phải màn hình (hoặc bấm `⇄ Đổi bên` nếu muốn chuyển sang mép trái).
2. **Chọn vùng quét**: Nhấn `Ctrl + Alt + R` (hoặc bấm nút *Chọn vùng quét*), màn hình sẽ mờ đi; kéo chuột khoanh vùng chứa ảnh gán nhãn cần theo dõi.
3. **Cấu hình ảnh gốc (nếu có)**: Nếu ảnh trên web/tool gán nhãn đang bị co giãn hoặc zoom, nhập chiều rộng thực của ảnh gốc vào ô `Rộng ảnh gốc (px)`.
4. **Quét dữ liệu**:
   * Nhấn `Ctrl + Alt + Space` để kiểm tra nhanh từng ảnh.
   * Hoặc nhấn `Ctrl + Alt + S` để quét tự động liên tục khi bạn cuộn qua nhiều ảnh.
5. **Đọc gợi ý**:
   * Xem khung và nhãn trực tiếp trên ảnh.
   * Đọc phần ghi chú chi tiết ở panel bên cạnh để biết lý do vì sao đèn cần vẽ hoặc bỏ qua, các lưu ý về góc nghiêng, bóng bị che, loại đèn đi bộ,...

---

## ⚙️ Các thông số trong bảng Cài đặt

* **Rộng ảnh gốc (px)**: Chiều rộng ảnh gốc để quy đổi tỉ lệ. Để trống nếu muốn tính trực tiếp theo pixel trên màn hình hiển thị.
* **Độ nhạy nhận diện (`conf`)**: Ngưỡng tin cậy của YOLO (mặc định: `0.25`). Giảm thấp nếu muốn bắt các đèn nhỏ/xa; tăng cao nếu bị nhận diện nhầm vật thể khác.
* **Ước lượng Lightbox**: Các chế độ `Tự động`, `Dọc`, `Ngang` hoặc `Tắt`. Giúp phóng to khung bao quanh thân hộp khi mô hình chỉ phát hiện được đốm sáng bóng đèn.
* **Chu kỳ quét (giây)**: Khoảng thời gian nghỉ giữa các lần quét liên tục (mặc định: `0.8` giây).
* **Độ dày box (px)**: Độ dày nét vẽ trên overlay màn hình (từ `1` đến `6` px).
* **Hiện cả đèn SOP bảo không gán**: Hiển thị các box xám bị loại bỏ để đối chiếu khi cần kiểm tra lại.
* **Đặt lại cài đặt gốc**: Đưa toàn bộ cấu hình và vùng quét về mặc định ban đầu.

---

## 📂 Cấu trúc dự án

```text
Tracking-Traffic-Box/
├── sop_assistant_gui.py    # Mã nguồn chính chứa GUI Tkinter, xử lý ảnh và quy tắc SOP
├── yolov8s.pt              # Trọng số mô hình YOLOv8s dùng để phát hiện đối tượng
├── .gitignore              # Danh sách loại trừ khi commit Git
├── LICENSE                 # Giấy phép mã nguồn mở (MIT)
└── README.md               # Tài liệu hướng dẫn sử dụng
```

---

## 📌 Khuyến cáo & Lưu ý

* **Quyền hạn Administrator**: Thư viện `keyboard` lắng nghe phím tắt toàn cục ở tầng hệ thống. Nếu bạn đang chạy tool gán nhãn trên cửa sổ có quyền Administrator, vui lòng chạy Terminal/Python với quyền Administrator để phím tắt hoạt động thông suốt.
* **Mục đích sử dụng**: Ứng dụng được thiết kế nhằm mục đích giảm tải áp lực ghi nhớ quy tắc SOP, hạn chế sai sót chủ quan (lỗi sót đèn nhỏ, nhầm lẫn đèn tắt, bóng che khuất). Quyết định gán nhãn cuối cùng vẫn thuộc về người thực hiện.

---

## 📄 License

Dự án được phân phối dưới giấy phép **MIT License**. Chi tiết xem tại file [LICENSE](LICENSE).
