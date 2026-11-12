# Muse Video Studio

Tool chạy trên macOS: gửi prompt vào chat Muse (muse.ai) bằng trình duyệt tự động, chờ Muse tạo video, tải video về, rồi ghép thành video hoàn chỉnh.

## Mở tool

Nhấp đúp `start.command`, hoặc chạy trong Terminal:

```bash
cd ~/muse-video-tool
./start.command
```

Trình duyệt sẽ mở http://127.0.0.1:8765. Lần đầu chạy, tool tự cài thư viện. Cần có Google Chrome và ffmpeg (`brew install ffmpeg`).

## Đăng nhập (Cài đặt)

Chọn một trong hai cách:
- **Mở Chrome để đăng nhập**: một cửa sổ Chrome hiện ra. Đăng nhập muse.ai trong cửa sổ đó, rồi bấm "Tôi đã đăng nhập xong". Phiên đăng nhập được lưu trong `browser_profile/`.
- **Dán cookie JSON** (Cài đặt → Đăng nhập Muse): export bằng extension Cookie-Editor khi đang ở muse.ai, dán vào ô rồi bấm "Đăng nhập bằng cookie". Có thể đặt tên để lưu **nhiều tài khoản** và bấm "Chuyển sang" để đổi; trùng tên thì cập nhật cookie cho tài khoản đó. Mỗi tài khoản lưu ở `secrets/accounts/<tên>.json`, tài khoản đang dùng được chép ra `secrets/cookies.json` (chỉ tài khoản máy của bạn đọc được). Khi đổi, phiên cũ trong trình duyệt của tool bị xoá trước rồi mới nạp cookie mới. Nếu đang chạy job thì job sau mới dùng tài khoản mới.
- Đăng nhập bằng nút "Mở Chrome để đăng nhập" cũng được lưu thành tài khoản "Đăng nhập Chrome".

## Các tab

| Tab | Chức năng |
|---|---|
| Tạo video | Nhập 1 prompt hoặc nhiều prompt (mỗi dòng 1 prompt, hoặc ngăn bằng dòng `---`), hoặc nhập từ file .txt/.csv. Chọn gửi vào chat chính hay một thread cụ thể. |
| Hàng đợi | Job chạy lần lượt. Bấm vào một job để xem nhật ký, câu trả lời của Muse, video và ảnh chụp màn hình khi lỗi. Có các nút Huỷ, Chạy lại, Xoá. Có thể tạm dừng hoặc tiếp tục cả hàng đợi. |
| Thư viện | Xem, tải và xoá video. Nhập video có sẵn. Chọn clip để ghép. |
| Ghép video | Sắp thứ tự clip, chọn khung hình 16:9, 9:16 hoặc 1:1, chuyển cảnh mờ dần, giữ hoặc tắt âm thanh gốc, thêm nhạc nền. |
| Cài đặt | Đăng nhập, chat mặc định, chạy ẩn hoặc hiện Chrome, thời gian chờ, số lần tự gửi lại, câu tự thêm vào cuối prompt. |

## MV âm nhạc (Tạo video → MV âm nhạc)

Tạo dự án bằng 1 file nhạc (mp3/wav/m4a…), rồi đi qua 5 bước:

1. **Nhạc & lời** — "Chép lời + timeline" chạy ngay trên máy bằng Whisper (lần đầu tải model ~1.6GB, sau đó ~1 phút/bài), cho mốc thời gian từng câu. "Nhờ Muse sửa lời" sửa chữ nghe nhầm và gắn tên đoạn (verse/chorus…). Sửa tay được trong bảng.
   *Vì sao không gửi file nhạc lên Muse:* đã thử, Muse nhận file nhạc nhưng treo không trả lời (bài 3 phút chờ 15 phút, đoạn 30 giây chờ 10 phút).
2. **Kịch bản** — chọn mức lip sync (0–100%), phong cách (mặc định hoạt hình 2D), khung hình, độ dài tối đa mỗi short; rồi "Nhờ Muse viết kịch bản" hoặc tự nhập.
3. **Nhân vật & bối cảnh** — Muse liệt kê nhân vật/bối cảnh chính từ kịch bản. Mỗi mục: Import ảnh tự thiết kế, hoặc "Muse vẽ" / "Sửa ảnh…" (nhập điểm cần sửa). Ưng thì **Khoá** — ảnh khoá được gửi kèm mọi short để giữ đồng nhất.
4. **Plan short** — Muse chia bài thành các short (≤ độ dài tối đa), gắn nhân vật/bối cảnh, đánh dấu short lip sync đúng theo %. Sửa mô tả / lip sync từng short rồi "Lưu & bắt đầu tạo short" — Muse tạo **3 short cùng lúc**, tự chạy tiếp tới hết.
5. **Duyệt & xuất** — trái: danh sách short (trạng thái, Xem, Tạo lại…); phải: xem trước liên tục như đã ghép, nhạc gốc chạy làm nền. Short nào chưa đúng bấm "Tạo lại…", nhập điểm cần sửa. "Xuất MV" ghép các short đúng mốc thời gian và lồng nhạc gốc → có trong Thư viện.

Cách gửi short (chọn ở bước 2):
- **Mỗi short 1 chat mới** (mặc định): 3 short chạy cùng lúc, nhanh; short lỗi không ảnh hưởng short khác.
- **1 chat cho cả MV**: mọi short gửi lần lượt vào cùng 1 chat Muse (gọn, có link "mở chat MV trên Muse" ở bước 5), chậm hơn ~3 lần. Short nào Muse từ chối trong chat chung được tự thử lại 1 lần ở chat riêng (đã gặp: Muse từ chối trong chat chung nhưng làm được ngay ở chat mới).
Dù chọn cách nào, ảnh nhân vật/bối cảnh đã khoá luôn được gửi kèm từng short để giữ đồng nhất.

Lip sync: Muse không nhận được audio, nên prompt ghi rõ câu nào hát ở giây thứ mấy trong short để nhân vật hát nhép theo; khi xuất, tiếng trong clip được thay bằng nhạc gốc. Độ khớp khẩu hình vì vậy là gần đúng, không tuyệt đối.

File của dự án nằm ở `output/mv/<id>/` (nhạc, ảnh nhân vật/bối cảnh, các short).

## Phim ngắn Sticker Man (Tạo video → Phim ngắn Sticker Man)

Tạo phim hoạt hình ngắn dạng sticker man / người que vui nhộn, kịch tính viral TikTok/Shorts:
1. **Kịch bản & Ý tưởng**: Chọn thời lượng phim mong muốn (từ 10s đến tối đa 3 phút / 180s, có sẵn các mốc nhanh: 15s, 30s, 45s, 1 phút, 1.5 phút, 2 phút, 2.5 phút, 3 phút), chọn thể loại (Hài hước meme, Công sở, Võ thuật, Trinh thám, Triết lý), chọn preset phong cách (Sticker 2D viền trắng die-cut, Stickman nét đen doodle, Chibi Douyin màu sắc, Manga comic, Võ thuật neon), chọn tỷ lệ 9:16 hoặc 16:9, bấm "Muse viết kịch bản phim sticker" hoặc tự nhập. Kịch bản phim dài (1–3 phút) được tự động phân bổ theo cấu trúc 4 hồi chuẩn điện ảnh (Mở đầu, Phát triển, Cao trào, Cú twist).
2. **Đồng bộ nhân vật & Bối cảnh**: Muse tự động trích xuất nhân vật/bối cảnh từ kịch bản (hoặc thêm thủ công). Vẽ ảnh hoặc tải ảnh lên rồi bấm **"Khoá" (🔒)**. Ảnh nhân vật đã khoá sẽ được gửi kèm làm mẫu tham chiếu cho **mọi phân cảnh** để giữ đồng bộ 100% hình ảnh nhân vật xuyên suốt phim.
3. **Bảng phân cảnh**: Muse tự động chia thành các short (4–7s/cảnh), gắn tag nhân vật tham gia cảnh, mô tả cử chỉ biểu cảm phóng đại, lời thoại và nối cảnh mượt mà.
4. **Tạo video & Duyệt**: Muse tạo video hoạt hình 2D theo nhân vật đã khoá. Xem trước liên tục toàn phim, tạo lại short nếu muốn.
5. **Dựng & Xuất phim**: Ghép các cảnh thành video hoàn chỉnh, thêm nhạc nền BGM tùy chọn và bật/tắt phụ đề lời thoại.

## Video affiliate / quy trình (Tạo video → Video affiliate / quy trình 1 phút)

Chọn quảng cáo affiliate hoặc quy trình nấu ăn, đặt thời lượng 10–180 giây theo bước 10 giây và số video muốn tạo (1–20). Nhập chủ đề, sản phẩm hoặc món ăn rồi bấm **Tạo / cập nhật kịch bản**. Với chủ đề chung “nấu ăn”, tool chọn món khác nhau cho từng video; với tên món cụ thể, tạo các phiên bản theo góc khai thác khác nhau. Prompt khoá mô tả người dẫn/bối cảnh, nêu thứ tự thao tác và trạng thái đầu/cuối cảnh, đồng thời chọn nhạc bắt tai, lời dẫn hoặc ASMR.

Mỗi video được chia thành các cảnh khoảng 10 giây. Bật **Nối cảnh liên mạch** để các cảnh của cùng video được gửi lần lượt trong một chat Muse, giúp Muse tham chiếu ngữ cảnh cảnh trước và giữ nhân vật, đạo cụ, địa điểm, ánh sáng, màu sắc đồng nhất. Mỗi video dùng một chat riêng. Khi Muse hoàn tất, chọn các clip theo thứ tự trong **Thư viện** rồi ghép video.

Phần **Duyệt short & ghép thành video** hiển thị các cảnh đã tạo theo thứ tự. Tại đây có thể xem lần lượt toàn bộ cảnh, đổi thứ tự bằng nút lên/xuống, chọn tỷ lệ và độ dài chuyển cảnh, giữ tiếng gốc của short hoặc trộn thêm nhạc nền, rồi ghép và xem trước file cuối cùng.

## Cách hoạt động

1. Trước khi gửi prompt, tool đánh dấu các tin nhắn đang có trong chat.
2. Tool gửi prompt và theo dõi các tin trả lời mới của Muse.
3. Muse được coi là trả lời xong khi đã có video và im lặng 15 giây, hoặc im lặng quá thời gian đặt trong Cài đặt (mặc định 120 giây).
4. Video được lấy trực tiếp trong trang: từ thẻ `<video>`, từ thẻ file `.mp4` hoặc từ link `.mp4`. File lưu ở `output/clips/`, video đã ghép lưu ở `output/merged/`.
5. Nếu Muse không trả về video, tool lưu ảnh chụp màn hình và câu trả lời vào `output/debug/` rồi tự gửi lại theo số lần đặt trong Cài đặt.

## Lưu ý

- Muse không có API công khai. Tool thao tác giao diện web, nên có thể hỏng khi Muse thay đổi giao diện. Khi đó hãy xem `output/debug/` để biết lỗi ở đâu.
- Mỗi lượt Muse tạo tối đa khoảng 6 clip, mỗi clip khoảng 10 giây. Đừng chạy quá dày, vì tài khoản có thể bị coi là bot.
- Không chia sẻ thư mục `secrets/` và `browser_profile/`: trong đó có phiên đăng nhập của bạn.
