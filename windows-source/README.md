# Muse Video Studio — mã nguồn cho Windows

Gói này chỉ có mã nguồn ứng dụng. Không chứa phiên trình duyệt, cookie, API key, thông tin tài khoản, cơ sở dữ liệu dự án, video đã tạo hoặc file kết xuất.

## Yêu cầu

- Windows 10 hoặc 11
- Python 3.11 trở lên, đã thêm vào `PATH`
- Google Chrome
- FFmpeg và FFprobe, đã thêm vào `PATH`

## Chạy ứng dụng

Nhấp đúp `start_windows.bat`. Lần đầu chạy, script tạo môi trường ảo và cài các thư viện trong `requirements.txt`. Ứng dụng mở tại `http://127.0.0.1:8765`.

Đăng nhập Muse trong tab **Cài đặt**. Cookie và video tạo ra sẽ được lưu trên máy trong `secrets/`, `browser_profile/` và `output/`; không chia sẻ các thư mục này.

## Giới hạn trên Windows

Tính năng dựng quảng cáo tạo dáng dùng Apple Vision thông qua chương trình Swift dành cho macOS. Tính năng đó cần thay bằng giải pháp tách người tương thích Windows trước khi chạy được. Các luồng còn lại dùng Muse trong Chrome và FFmpeg.
