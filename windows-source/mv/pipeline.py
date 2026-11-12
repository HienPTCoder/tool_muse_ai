"""Các bước MV âm nhạc (mỗi bước Muse là 1 chat mới):
lời + timeline (Whisper trên máy, Muse sửa chữ) -> kịch bản -> nhân vật/bối cảnh -> ảnh khoá -> plan short -> tạo short (3 cái song song)."""

import json
import math
import random
import re
import shutil
import ssl
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

from jobs.worker import is_blocked_error, is_quota_error, is_service_error
from muse.browser import Cancelled, MuseBrowser
from mv import store
from post import color, ffmpeg

ROOT = Path(__file__).resolve().parent.parent
MV_DIR = ROOT / "output" / "mv"
BATCH_SHORTS = 6  # tối đa số short trong 1 prompt/1 chat (6 x 10s = 1 phút)
BATCH = 3  # số short gửi Muse cùng lúc
SHORT_RETRY = 3  # số lần tool tự gửi lại 1 short khi Muse không trả về video

# Muse từ chối brief (cảnh đánh nhau, va chạm, nhân vật có bản quyền…) và trả lời bằng chữ,
# thường kèm 1 bản "an toàn hơn" đã soạn sẵn và chờ mình đồng ý.
_REFUSAL = re.compile(
    r"\bI (couldn't|could not|can't|cannot|won't|will not|didn't|did not)\b|"
    r"\b(can't|cannot|couldn't) (generate|create|make|produce|render)\b|"
    r"already refused|same brief|safer (take|version|rework|option)|\brework\b|"
    r"(mình|tôi) không thể (tạo|làm)|đã bị từ chối|bản an toàn",
    re.IGNORECASE)

# Đồng ý bản "an toàn hơn" Muse vừa đề xuất, gửi tiếp vào đúng chat đó.
REWORK_OK = ("Yes — go ahead with that safer rework now. Rules that still apply, unchanged:\n"
             "- CHARACTER LOCK: every character must still look EXACTLY like the reference sheet images I attached "
             "(same face, hairstyle, outfit, colours, body build). Do not redesign or replace anyone.\n"
             "- Keep the same duration, aspect ratio, art style, location and camera work.\n"
             "- Keep the EMOTION and dramatic intent of my original scene (if the character was sad, tense, lonely "
             "or humiliated, he stays that way — do not turn it into a happy or friendly scene).\n"
             "- No text, letters, words, numbers, signs, labels, captions or watermarks anywhere in the frame.\n"
             "Do not ask anything else and do not reply with text only: generate it now and output exactly 1 video file.")

# Nhắc trước cho lần gửi lại, để Muse không từ chối ngay từ đầu.
SAFE_RULES = ("Prompt clarification (keep the same scene, character design and art style):\n"
              "- This is a non-violent, hand-drawn sports animation. Show the described football action only.\n"
              "- Keep the supplied character sheet as the visual reference; use a rear or three-quarter view "
              "when that best fits the camera direction.\n"
              "- Preserve kit colours and the shirt number shown in the reference. No captions, subtitles, "
              "watermarks or readable signs. Do not add unrelated text or events.")


def is_refusal(text: str | None) -> bool:
    """Muse trả lời bằng chữ để từ chối / đề xuất bản khác, thay vì xuất video."""
    return bool(text and _REFUSAL.search(text))
MIN_CLIP_SEC = 5

SOUND_CUES = [
    (("explod", "blast", "missile", "shot down", "exploding", "fireball", "crash"), "powerful explosions with deep bass impact, debris and a rolling aftershock"),
    (("laser", "beam", "slices", "slash", "fires", "firing", "shoots", "shot"), "sharp laser zaps and energy-weapon bursts with charging whines"),
    (("mothership", "orbit", "modules rotate", "lock into", "bays", "sky"), "a colossal low rumbling roar from the mothership, deep sub-bass hum, metallic groans of modules locking"),
    (("thruster", "drop", "jet", "fly", "drone"), "jet-thruster roars and the buzzing whir of drones passing overhead"),
    (("march", "columns", "army", "combat robot", "security robot", "patrol", "guard"), "heavy synchronized mechanical footsteps, armor clanks and servo whines of a marching machine army"),
    (("engine", "truck", "vehicle", "car", "carrier", "convoy"), "engine and motor sounds with tires and metal rattling"),
    (("screen", "console", "computer", "data", "server", "signal", "system", "monitor", "phone", "hud", "scanner", "scan"), "electronic beeps, data blips, digital hums and glitches"),
    (("robot", "arm", "joint", "weld", "factory", "conveyor", "production", "machine"), "servo whirs, hydraulic hisses, metal clanks and factory machinery"),
    (("crowd", "people run", "scream", "panic", "herd", "truck door", "prison"), "panicked crowd, distant screams, running footsteps and slamming metal doors"),
    (("alarm", "siren", "alert", "emergency"), "blaring alarms and sirens"),
    (("glass", "shatter", "debris", "tower", "building"), "shattering glass, rattling concrete and falling debris"),
    (("fire", "burning", "flames"), "crackling fire and roaring flames"),
]


def sound_design(description: str) -> str:
    """Gợi ý hiệu ứng âm thanh cụ thể theo nội dung short để Muse không chỉ tạo tiếng nền chung chung."""
    d = (description or "").lower()
    cues = [c for keys, c in SOUND_CUES if any(k in d for k in keys)]
    return "; ".join(cues[:5])

MAX_CLIP_SEC = 10   # Muse tạo tối đa 10 giây mỗi lần
MAX_STORY_SEC = 900.0  # phim theo kịch bản dài tối đa 15 phút (trước đây bị chặn 180s nên kịch bản dài bị rút gọn)
RATIO = {"16:9": "16:9 (ngang)", "9:16": "9:16 (dọc)", "1:1": "1:1 (vuông)"}
RATIO_EN = {"16:9": "16:9 widescreen", "9:16": "9:16 vertical full screen", "1:1": "1:1 square"}
NO_ASK = "Làm luôn, không cần hỏi lại."
NO_ASK_EN = "Proceed immediately without asking questions."


def to_en(text: str) -> str:
    """Tự động dịch văn bản tiếng Việt sang tiếng Anh ngắn gọn cho prompt Muse."""
    if not text or not any(ord(c) > 127 for c in text):
        return (text or "").strip()
    try:
        ctx = ssl._create_unverified_context()
        url = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=en&dt=t&q=" + urllib.parse.quote(text)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=3.5, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            res = "".join(part[0] for part in data[0] if part and part[0]).strip()
            return res if res else text.strip()
    except Exception:
        return text.strip()


STICKER_STYLES_EN = {
    "diecut": "2D Die-cut Sticker Animation, bold white cutout border outline, clean modern cartoon vector art, subtle drop shadow, expressive funny meme animations.",
    "doodle": "Minimalist Black Line Doodle Stickman, classic hand-drawn ink line art, clean white background, hilarious expressive meme faces, lively stickman motion.",
    "colorful": "Colorful Cute Chibi Sticker Animation, vibrant pastel colors, funny exaggerated meme expressions, playful Douyin/TikTok sticker style.",
    "comic": "Dynamic Comic Strip Manga Sticker, bold ink outlines, action speed lines, dramatic cinematic comic poses, high energy motion.",
    "epic": "Epic Martial Arts Stickman Fighter, sleek stylized stick figure, glowing neon energy trails, dynamic anime martial arts combat choreography.",
}

# Người mẫu tạo dáng: yêu cầu quan trọng nhất là trông như quay bằng máy quay phim chuyên nghiệp, không có cảm giác AI
REAL_LOOK = ("YÊU CẦU QUAN TRỌNG NHẤT — MÀU SẮC VÀ ÁNH SÁNG TỰ NHIÊN NHƯ VIDEO THẬT, KHÔNG ĐƯỢC TRÔNG NHƯ AI: "
             "giống clip thời trang đường phố quay thật bằng máy ảnh/điện thoại cao cấp. Ánh sáng ban ngày tự nhiên, dịu "
             "(trời nhiều mây, bóng râm sáng hoặc nắng nhẹ), cân bằng trắng trung tính, màu trung thực như mắt thường thấy, "
             "tương phản thấp–vừa, vùng tối không bị đen đặc, độ bão hoà vừa phải. KHÔNG color grade điện ảnh, KHÔNG tông "
             "cam–xanh (teal & orange), KHÔNG nắng hoàng hôn vàng cam rực, KHÔNG ánh sáng kịch tính/ngược sáng gắt, KHÔNG HDR, "
             "không glow, không bóng bẩy kiểu render 3D. Da người thật có kết cấu, không mịn nhựa; tóc tự nhiên; quần áo có nếp "
             "nhăn và chất vải thật; tay và ngón tay đúng giải phẫu. Bối cảnh là địa điểm có thật, đời thường, không méo hình. "
             "Không chữ, không logo.")
# Người mẫu được Muse thiết kế như 1 stylist thời trang chuyên nghiệp — tránh đồ cơ bản, trơn, nhạt
STYLIST_BRIEF = """BẠN LÀ STYLIST + MAKEUP ARTIST hàng đầu cho tạp chí thời trang (Vogue, Elle, Harper's Bazaar) và KOL Douyin/Instagram triệu follower.
Bộ đồ phải ĐẸP NỔI BẬT, có gu, khiến người xem dừng lại — KHÔNG được là đồ cơ bản, trơn, nhạt (áo phông trơn, áo ống trơn + chân váy trơn…):
- Có 1 MÓN ĐIỂM NHẤN (statement piece): chi tiết thiết kế đặc biệt — cut-out, xẻ tà, cổ yếm, vai lệch, corset, xếp nếp draping, nơ lớn,
  tay phồng, ren, đính hạt/ngọc trai, áo khoác cấu trúc, chân váy bất đối xứng…
- PHỐI CHẤT LIỆU có chiều sâu: ít nhất 2 chất liệu tương phản (lụa satin + len dệt kim, ren + denim, da + voan, tweed + lụa…).
- BẢNG MÀU có chủ đích 2–3 màu hài hoà (ví dụ kem–nâu mocha–vàng gold; đen–trắng–bạc; hồng phấn–trắng–ngọc trai), ghi rõ sắc độ.
- PHÁ CÁCH LAYERING hoặc tỷ lệ: áo khoác khoác hờ vai, áo croptop + quần cạp cao, váy ngắn + boots cao, đồ rộng + đồ ôm…
- PHỤ KIỆN tầng lớp, tinh tế (không logo): khuyên tai statement, vòng cổ nhiều tầng, nhẫn, thắt lưng, kính râm, kẹp/nơ tóc, túi có kiểu
  dáng đặc biệt (túi hộp, túi bán nguyệt, túi chần trám…), giày hợp gu (boots cao, slingback, Mary Jane, sandal quai mảnh…).
- Ghi rõ form dáng/độ dài từng món (ôm, rộng, cạp cao, dài tới đâu) để vẽ đúng.
VẺ ĐẸP:
- Gương mặt: tỷ lệ hài hoà kiểu người mẫu/diễn viên hạng A — mắt to sáng có hồn, sống mũi cao thanh, môi đầy rõ viền, đường hàm V-line mềm,
  gò má cao nhẹ; có 1–2 nét riêng (nốt ruồi duyên, lúm đồng tiền, mắt cười, lông mày sắc…) để không na ná gương mặt AI.
- Kiểu tóc được stylist làm: ghi rõ kỹ thuật (uốn sóng lơi to bản, sấy phồng chân tóc, mái bay, tóc layer, highlight/balayage màu gì…).
- Makeup chuyên nghiệp chi tiết: nền da căng bóng hay mịn lì, má hồng vị trí nào, kẻ mắt kiểu gì, màu môi cụ thể, highlight.
- Vóc dáng chuẩn người mẫu, dáng đứng tự tin, thần thái rõ (sang chảnh / ngọt ngào / cá tính… theo gu đã chọn).
Vẫn phải là NGƯỜI THẬT: da có kết cấu, không mịn nhựa, không mặt búp bê AI."""
# Ảnh người mẫu chuẩn: kiểu lookbook tạp chí (không phải ảnh thẻ/catalog nền trơn ánh sáng phẳng)
MODEL_PORTRAIT = ("Ảnh lookbook thời trang chất lượng tạp chí, chụp bằng máy ảnh full-frame ống 85mm: TOÀN THÂN thấy rõ từ đầu tới giày, "
                  "người mẫu tạo dáng nhẹ có thần (dồn trọng tâm 1 chân, vai thả lỏng, 1 tay đặt có chủ đích), mặt nhìn về ống kính, "
                  "khuôn mặt rõ nét, sắc sảo. Phông studio màu trung tính ấm có gradient nhẹ (hoặc tường thạch cao trơn), ánh sáng "
                  "studio mềm có chiều sâu: key light softbox lớn chếch 45°, fill nhẹ, rim light tách tóc khỏi nền; màu da tự nhiên "
                  "hồng hào, màu trang phục chuẩn và giàu chất liệu (thấy rõ vân vải, ren, độ bóng satin). Da thật có lỗ chân lông, "
                  "tóc có sợi tơ tự nhiên, tay đúng giải phẫu. Không chữ, không logo, không người khác.")
# Giữ đúng người mẫu: chỉ dựa vào ảnh, không thêm mô tả "đẹp" (làm Muse vẽ mặt mới)
IDENTITY = ("Ảnh {f} là người mẫu CHUẨN: khuôn mặt, đường nét, kiểu tóc, màu da, vóc dáng (độ gầy/đầy đặn), chiều cao và "
            "trang phục phải GIỐNG HỆT ảnh này trong suốt video. Không thay khuôn mặt, không làm đẹp thêm, không làm gầy "
            "hay kéo dài người, không đổi trang phục.")
COLOR_REF = ("Ảnh {f} là khung hình từ video thật của người dùng: MÀU SẮC, ÁNH SÁNG, độ tương phản, cân bằng trắng và độ "
             "nét phải giống hệt ảnh này (chỉ lấy màu và ánh sáng, không chép bối cảnh).")
REAL_MOTION = ("Chuyển động người mẫu tự nhiên như người thật (trọng lượng cơ thể, tóc và vải chuyển động đúng vật lý). "
               "Máy quay cầm tay/gimbal ổn định, có chút rung rất nhẹ như người quay thật, 24fps với motion blur "
               "tự nhiên; không chuyển động trơn tuột, không biến dạng, không morph, không đổi mặt giữa video.")
# Kiểu tạo dáng mặc định: đứng yên 1 chỗ đổi pose như buổi chụp ảnh; "move" = có đi lại, xoay người
POSE_STILL = ("Người mẫu ĐỨNG YÊN TẠI 1 CHỖ suốt video, không đi lại, không đổi vị trí — chỉ chuyển từ tư thế chụp ảnh này "
              "sang tư thế khác (đổi tay, nghiêng đầu, xoay vai/hông nhẹ, đổi chân trụ, đổi ánh nhìn) rồi giữ dáng 1–2 giây như "
              "đang chụp ảnh thật. Máy quay gần như cố định trên chân máy, chỉ push-in hoặc lia rất chậm.")
POSE_MOVE = "Người mẫu có thể đi vài bước, xoay người, đổi vị trí trong bối cảnh như phim thời trang."
# Thư viện pose để Muse viết kịch bản đa dạng, có phong cách như buổi chụp lookbook/editorial thật
POSE_LIBRARY = """KIỂU TẠO DÁNG — phải đa dạng, có phong cách như người mẫu chuyên nghiệp chụp lookbook/tạp chí, KHÔNG được chỉ đứng thẳng vẫy tay/cười:
- Dáng chữ S / contrapposto: dồn trọng tâm 1 chân, hông đẩy nhẹ sang bên, vai nghiêng ngược chiều.
- Bắt chéo chân khi đứng, mũi chân trước chạm đất, một gối hơi khuỵu.
- Tay: 1 tay chống hông, tay kia buông tự nhiên; tay vuốt tóc / vén tóc sau tai; hai tay giữ cổ áo hoặc vạt áo; tay chạm nhẹ cằm/xương quai xanh; đút 1 tay túi quần; tay cầm túi xách đưa ra trước hoặc vắt túi lên vai; tay chỉnh kính râm/mũ/khuyên tai.
- Đầu và ánh mắt: nghiêng đầu, cằm hơi hạ nhìn thẳng ống kính (ánh mắt "fierce"); quay mặt nhìn qua vai; nhìn xa ra ngoài khung hình; cúi nhìn xuống rồi ngước lên ống kính; nụ cười mỉm nhẹ ↔ biểu cảm lạnh lùng sang chảnh.
- Thân: xoay 3/4 người về ống kính; xoay lưng nhìn qua vai khoe trang phục; vai hơi rụt về trước cho dáng thanh; ưỡn ngực nhẹ, cổ dài.
- Dùng bối cảnh (không rời chỗ đứng): tựa lưng/vai vào tường, cột, lan can; ngồi trên ghế/bậc thềm/mép bàn vắt chân; ngồi xổm kiểu street style; một tay vịn vào vật bên cạnh.
- Khoảnh khắc "candid": cười bật ra rồi quay đi, gió thổi tóc, chỉnh trang phục như vô tình.
Góc máy cũng phải đa dạng: toàn thân (thấy giày), trung cảnh, cận mặt/cận chi tiết (tay, túi, phụ kiện); góc thấp làm chân dài, góc ngang tầm mắt; mỗi cảnh liền kề đổi cỡ cảnh hoặc góc máy.
Mỗi cảnh ghi RÕ: tư thế tay, chân, thân, hướng đầu, ánh mắt, biểu cảm, cỡ cảnh + góc máy. Không lặp lại pose giữa các cảnh."""
POSE_STYLE = ("Tạo dáng có phong cách như người mẫu chuyên nghiệp chụp lookbook/tạp chí: dáng chữ S, đường nét cơ thể thanh, tay "
              "đặt có chủ đích, chuyển pose dứt khoát rồi giữ dáng, ánh mắt và biểu cảm thần thái.")
# Người mẫu phải rất đẹp nhưng là vẻ đẹp người thật (như người mẫu/diễn viên chuyên nghiệp), không phải đẹp kiểu AI
MODEL_BEAUTY = ("Người mẫu RẤT ĐẸP, cuốn hút như người mẫu thời trang / diễn viên hàng đầu: gương mặt cân đối, đường nét thanh tú "
                "và có thần, ánh mắt sáng, nụ cười tự tin; vóc dáng chuẩn người mẫu, dáng đứng chuyên nghiệp; tóc được tạo kiểu "
                "bởi stylist, makeup chuyên nghiệp tinh tế làm nổi bật nét đẹp; trang phục vừa vặn, phối đồ sang và hợp xu hướng. "
                "Đẹp như NGƯỜI THẬT trên tạp chí thời trang (da thật có kết cấu, nét mặt có cá tính riêng), không phải gương mặt "
                "AI búp bê na ná nhau.")
# Kiểu "Đi dạo OOTD" (lookbook đường phố kiểu Douyin/Xiaohongshu): người mẫu đi về phía máy, xoay người, tạo dáng với
# phụ kiện; vài cú máy ngắn có cắt cảnh; quay bằng điện thoại cầm tay — đúng kiểu video mẫu người dùng muốn làm
POSE_OOTD = ("KIỂU VIDEO: lookbook OOTD đường phố quay bằng điện thoại (kiểu Douyin/Xiaohongshu). Người mẫu đi bộ tự nhiên, thong "
             "thả, xoay người, tạo dáng với phụ kiện (túi xách, tóc, quần áo); người quay cầm điện thoại đi lùi trước mặt hoặc "
             "vòng quanh người mẫu.")
OOTD_STRUCTURE = """CẤU TRÚC KỊCH BẢN OOTD (bám theo, giữ đúng thời lượng từng cảnh như video mẫu nếu có):
- Cảnh mở (3–5s): người mẫu ĐI THẲNG về phía máy, toàn thân → trung cảnh, người quay đi lùi giữ khoảng cách; tay cầm túi đung đưa
  tự nhiên, tay kia vuốt tóc hoặc đút túi quần; ánh mắt lúc nhìn ống kính lúc nhìn đi chỗ khác, cười nhẹ.
- CẮT CẢNH sang 1 góc khác của cùng địa điểm. Cảnh giữa (3–4s): người mẫu xoay người 3/4 rồi quay mặt về máy / nhìn qua vai,
  máy vòng nhanh nửa vòng quanh người mẫu (orbit) hoặc lia theo, tóc bay theo chuyển động.
- CẮT CẢNH. Cảnh tạo dáng (4–7s): đứng hoặc bước rất chậm, khoe phụ kiện (2 tay cầm túi đưa ra trước, chỉnh túi, chỉnh tóc,
  chạm dây chuyền), nhìn thẳng ống kính, biểu cảm dễ thương/tự tin; máy chính diện trung cảnh, đẩy vào (push-in) chậm.
- Kết (1–2s): người mẫu bước lướt qua sát ống kính rồi ra khỏi khung (chuyển cảnh tự nhiên), hoặc quay lưng bước đi.
Mỗi cảnh ghi rõ: hành động tay/chân/đầu, ánh mắt, biểu cảm, cỡ cảnh, chuyển động máy, vị trí trong địa điểm (góc nào)."""
# Kiểu "Chụp ảnh nhiều pose": mỗi cảnh người mẫu vào 2 pose khác nhau (vào dáng → giữ 1–1,5s như bấm máy → chuyển dáng),
# các cảnh cắt sang góc/vị trí khác; pose bốc ngẫu nhiên theo phong cách người dùng chọn để video không lặp lại
POSE_PHOTO = ("KIỂU VIDEO: hậu trường buổi chụp ảnh thời trang thật quay bằng điện thoại. Mỗi cảnh người mẫu vào 2 pose khác nhau: "
              "chuyển dáng dứt khoát nhưng mềm mại, GIỮ mỗi pose khoảng 1–1,5 giây như đang được bấm máy, rồi chuyển pose tiếp "
              "(đổi tay, đổi chân trụ, xoay hông/vai, đổi hướng đầu và ánh mắt). Giữa các cảnh CẮT sang góc máy hoặc vị trí khác "
              "trong cùng địa điểm. Mỗi pose phải có phong cách, đường nét cơ thể đẹp, tay đặt có chủ đích, thần thái rõ ràng — "
              "KHÔNG đứng thẳng đơ, không vẫy tay, không lặp lại pose.")
POSE_BANK = {
    "Sang chảnh": [
        "dáng chữ S: dồn trọng tâm 1 chân, hông đẩy sang bên, 1 tay chống hông, cằm hơi nâng, ánh mắt lạnh lùng nhìn ống kính",
        "xoay lưng 3/4, nhìn qua vai về ống kính, 1 tay vén tóc sang bên vai kia",
        "tay chỉnh khuyên tai/kính râm, đầu nghiêng, mắt khép hờ nhìn xuống rồi ngước lên ống kính",
        "tựa vai vào tường/cột, chéo chân, tay cầm túi buông dọc thân, mặt nghiêng 3/4",
        "bước chéo chân như catwalk rồi dừng, 1 tay đặt nhẹ lên xương quai xanh",
    ],
    "Dễ thương": [
        "nghiêng đầu cười tươi, 2 tay ôm túi trước ngực, vai hơi nhún",
        "chụm 2 tay dưới cằm, mắt to nhìn ống kính, cười híp mắt",
        "nhón 1 chân ra sau, người hơi nghiêng về trước, tay vẫy nhẹ bên má",
        "vén tóc sau tai, cười e thẹn nhìn xuống rồi nhìn ống kính",
        "2 tay nắm vạt váy/vạt áo, xoay nhẹ người sang bên, cười",
    ],
    "Gợi cảm nhẹ": [
        "1 tay luồn vào tóc kéo nhẹ ra sau, cổ dài, vai thả lỏng, ánh mắt sâu nhìn ống kính, môi hé",
        "tựa lưng vào tường, 1 gối co chạm tường, tay đặt lên đùi, cằm hạ nhẹ",
        "xoay hông 3/4 khoe eo thon, 1 tay đặt ở eo, tay kia buông, nhìn qua vai",
        "ngồi mép ghế/bậc thềm vắt chân, người hơi ngả về sau, 2 tay chống phía sau",
        "vuốt tóc từ đỉnh đầu xuống, mắt khép hờ rồi mở nhìn ống kính",
    ],
    "Quyến rũ": [
        "đứng chữ S sâu, hông đẩy mạnh sang bên, 1 tay lướt chậm từ cổ xuống xương quai xanh, ánh mắt khép hờ nhìn ống kính, môi hé",
        "quay lưng về máy, ngoái đầu qua vai, 1 tay vén tóc lên để lộ lưng/gáy, nụ cười nửa miệng",
        "ngồi vắt chéo chân dài, người ngả về sau chống 1 tay, tay kia vuốt tóc, góc máy thấp khoe chân",
        "2 tay luồn vào tóc nâng lên đỉnh đầu, ưỡn nhẹ, eo xoay 3/4, nhìn thẳng ống kính đầy tự tin",
        "tựa vai vào tường, 1 tay đặt ở hông kéo nhẹ vạt váy, cằm hạ, mắt nhìn lên ống kính",
        "bước chậm về phía máy kiểu catwalk, hông lắc nhẹ, dừng lại cắn nhẹ môi dưới rồi cười",
        "cúi người nhẹ về trước, 2 tay đặt trên đùi, ánh mắt mạnh và nụ cười ẩn ý",
    ],
    "Cool / cá tính": [
        "đút 2 tay túi quần/áo khoác, chân đứng rộng bằng vai, mặt không cười nhìn thẳng ống kính",
        "ngồi xổm kiểu street style, 2 khuỷu tay đặt lên gối, nhìn lên ống kính",
        "kéo kính râm xuống sống mũi, nhìn qua mép kính",
        "quay mặt đi nhìn ra ngoài khung hình, gió thổi tóc, tay xách túi hờ hững",
        "dựa lưng vào xe/lan can, khoanh tay, 1 chân bắt chéo",
    ],
    "Thanh lịch": [
        "đứng thẳng vai mở, 2 tay cầm túi trước người, cằm nâng nhẹ, mỉm cười nhẹ",
        "bước 1 bước nhỏ, váy/áo đung đưa, 1 tay chỉnh cổ áo, nhìn xa",
        "ngồi trên ghế quán, chân khép nghiêng một bên, tay đặt trên đầu gối, nhìn ra cửa sổ",
        "cầm tách cà phê/hoa trước ngực, nghiêng đầu nhìn ống kính",
    ],
    "Năng động": [
        "xoay 1 vòng làm váy/tóc bay rồi dừng lại cười",
        "nhảy nhẹ 1 bước, 2 tay mở rộng, cười lớn",
        "đi nhanh về phía máy rồi dừng đột ngột, hất tóc",
        "chống 2 tay lên gối hơi cúi người về ống kính, cười tinh nghịch",
    ],
    "Candid tự nhiên": [
        "cười bật ra rồi quay mặt đi, tay che miệng",
        "đang chỉnh túi/áo như vô tình, chợt ngước lên nhìn ống kính",
        "nhìn xuống điện thoại rồi ngẩng lên cười",
        "gió thổi tóc che mặt, đưa tay gạt tóc, cười",
    ],
    "Editorial tạp chí": [
        "dáng góc cạnh: 1 khuỷu tay giơ cao đặt sau đầu, tay kia chống hông, thân xoay 45°",
        "đứng 1 chân, chân kia co gối hướng vào trong, 2 tay đặt trên đầu gối, mặt nghiêng",
        "cúi người về trước, 2 tay đặt lên đầu gối, ánh mắt mạnh nhìn thẳng ống kính",
        "quay hẳn lưng về máy, xoay đầu nhìn qua vai, 1 tay đặt sau gáy",
        "ngồi xổm 1 gối chạm đất, tay chống cằm, nhìn lên",
    ],
}
CAMERA_VARIETY = ("Góc máy đa dạng giữa các cảnh: toàn thân góc thấp (chân dài), trung cảnh ngang tầm mắt, cận mặt/cận chi tiết "
                  "(tay, túi, phụ kiện, tóc), góc nghiêng 45°, góc từ trên xuống nhẹ; máy cầm tay đẩy vào chậm, lia nhẹ hoặc "
                  "vòng nửa vòng. 2 cảnh liền nhau phải khác cỡ cảnh hoặc góc máy.")


# Lựa chọn thêm khi thiết kế người mẫu (khoá trong model_spec -> nhãn đưa vào prompt)
DESIGN_KEYS = {"topic": "chủ đề", "aesthetic": "gu thời trang", "hair": "kiểu tóc", "makeup": "makeup",
               "body": "dáng người", "sexy": "mức gợi cảm"}
SEXY = {
    "Kín đáo": "Trang phục kín đáo, thanh lịch.",
    "Vừa phải": "Trang phục khoe nhẹ đường nét (vai, xương quai xanh hoặc eo), thời trang, tinh tế.",
    "Gợi cảm": ("Trang phục gợi cảm kiểu thời trang đường phố/dạ tiệc: ôm dáng, khoe vai, eo hoặc chân dài (croptop, áo quây, váy "
                "ngắn, xẻ tà, hở lưng…), quyến rũ nhưng sang và phù hợp nơi công cộng, không phản cảm."),
    "Quyến rũ": ("Trang phục QUYẾN RŨ tôn tối đa đường cong: váy/đầm body ôm sát, cổ chữ V sâu hoặc cổ yếm, cut-out ở eo/hông, "
                 "xẻ tà cao tới đùi, hở lưng sâu, áo corset/bustier, váy mini, chất liệu ôm bóng (satin, lụa, thun gân, da) hoặc "
                 "voan/ren mỏng lớp ngoài có lót; giày cao gót quai mảnh làm chân dài. Kiểu ảnh người mẫu Instagram/Douyin hot."),
    "Nóng bỏng": ("Trang phục NÓNG BỎNG kiểu bìa tạp chí Maxim/GQ, Victoria's Secret runway: đầm mini siêu ôm, crop top ngắn + váy "
                  "ngắn cạp trễ khoe eo thon và bụng phẳng, xẻ ngực sâu, hở lưng trần, cut-out táo bạo, lớp voan/lưới xuyên thấu "
                  "khoác ngoài bralette; đồ bơi/bikini thời trang chỉ khi bối cảnh biển/hồ bơi. Táo bạo nhưng vẫn là thời trang "
                  "cao cấp — luôn che kín vùng nhạy cảm, không khoả thân."),
}
# Độ cuốn hút: phần quyết định "hot" không nằm ở hở nhiều mà ở thần thái, ánh mắt, đường cong và làn da
ALLURE = """ĐỘ CUỐN HÚT (rất quan trọng — người xem phải bị hút mắt ngay giây đầu):
- Ánh mắt: sâu, có lửa, nhìn thẳng ống kính đầy tự tin và mời gọi; mắt khép hờ quyến rũ, đuôi mắt kẻ kéo dài, mi dày cong.
- Môi: căng mọng, bóng nhẹ (glossy) hoặc màu đỏ/rượu vang/nude hồng, hơi hé mở; nụ cười nửa miệng đầy ẩn ý.
- Làn da: căng bóng khoẻ (dewy glow), highlight ở xương quai xanh, vai, sống mũi, xương ống chân; da thật có kết cấu.
- Vóc dáng: đồng hồ cát — vòng eo thon, hông cong, vòng 1 đầy đặn cân đối, chân dài thẳng, cổ và xương quai xanh thanh; dáng tự tin.
- Tóc: dày bồng bềnh, có độ bóng, kiểu "vừa xoã ra" hơi rối có chủ đích, vài sợi rơi trước mặt.
- Thần thái: tự tin, quyến rũ chủ động, sang và "đắt" — không ngây ngô, không cứng đờ.
Người mẫu là phụ nữ trưởng thành (từ 21 tuổi)."""
ALLURE_MOTION = ("Thần thái quyến rũ trong mọi cảnh: ánh mắt sâu nhìn thẳng ống kính, khép hờ rồi mở; môi hé, nụ cười nửa miệng; "
                 "chuyển động chậm, mềm, uyển chuyển (lướt tay dọc cổ/xương quai xanh/eo, vuốt tóc chậm, xoay hông chữ S, ngả "
                 "người); khoe đường cong eo–hông–chân bằng góc 3/4 và góc thấp; tóc và vải chuyển động mềm.")
HOT_LEVELS = ("Gợi cảm", "Quyến rũ", "Nóng bỏng")
# người mẫu nam: mức gợi cảm + độ cuốn hút riêng (bản nữ nói về váy, bralette, dáng đồng hồ cát)
SEXY_MALE = {
    "Kín đáo": "Trang phục nam lịch lãm, kín đáo.",
    "Vừa phải": "Trang phục nam vừa vặn tôn dáng: sơ mi mở 1–2 cúc, áo thun ôm vừa, quần âu/jeans ống đứng.",
    "Gợi cảm": "Trang phục nam gợi cảm: sơ mi mở 3 cúc khoe xương quai xanh và ngực, áo thun/tank top ôm khoe bắp tay, quần cạp cao vừa vặn.",
    "Quyến rũ": ("Trang phục nam QUYẾN RŨ: sơ mi lụa/linen mở gần hết cúc khoe ngực săn chắc, hoặc tank top ôm sát + áo khoác vắt vai, "
                 "quần âu cạp cao ống rộng hoặc quần da ôm, phụ kiện dây chuyền mảnh, nhẫn bạc."),
    "Nóng bỏng": ("Trang phục nam NÓNG BỎNG kiểu bìa tạp chí GQ/Men's Health: blazer hoặc sơ mi mở hoàn toàn khoe cơ ngực và cơ bụng, "
                  "quần âu ôm; bối cảnh biển/hồ bơi thì quần short bơi thời trang + sơ mi lụa mở. Luôn là thời trang cao cấp, không khoả thân."),
}
ALLURE_MALE = """ĐỘ CUỐN HÚT (rất quan trọng — người xem phải bị hút mắt ngay giây đầu):
- Gương mặt nam tính điển trai: hàm sắc, gò má cao, ánh mắt sâu nhìn thẳng ống kính tự tin, nụ cười nửa miệng; râu tỉa gọn hoặc mặt sạch.
- Vóc dáng tam giác ngược: vai rộng, ngực săn chắc, eo thon, cơ bụng rõ nhẹ, tay có gân, chân dài; da khoẻ có kết cấu thật, hơi bóng.
- Tóc tạo kiểu có texture (vuốt rủ, side part, xoăn nhẹ), vài sợi rơi trước trán.
- Thần thái: tự tin, phong trần, sang và "đắt" — không cứng đờ.
Người mẫu là nam giới trưởng thành (từ 21 tuổi)."""


BEAUTY_REF = ("Ảnh chuan_dep.jpg là CHUẨN VẺ ĐẸP tôi muốn: lấy theo mức độ xinh đẹp, thần thái, tỷ lệ gương mặt và cơ thể, phong cách "
              "makeup, kiểu tóc, gu thời trang và cảm giác tổng thể của ảnh này. Tạo người mẫu đẹp ngang hoặc hơn chuẩn đó, cùng "
              "'gu' đó, nhưng là 1 gương mặt riêng (không sao chép y hệt khuôn mặt người trong ảnh). Những lựa chọn cụ thể ở trên "
              "(tuổi, tóc, trang phục…) được ưu tiên hơn ảnh.")

# Bật "giữ gương mặt": ảnh chuẩn không còn là "gu" mà là đúng gương mặt người mẫu — chỉ đổi trang phục/tóc/makeup
BEAUTY_FACE = ("KHOÁ GƯƠNG MẶT — ưu tiên cao nhất: người mẫu phải là ĐÚNG người trong ảnh chuan_dep.jpg (ảnh thật). Giữ chính "
               "xác 100% nét mặt: hình dáng khuôn mặt, xương hàm, gò má, cằm, trán, mắt (hình dáng, mí, khoảng cách, màu mắt), "
               "lông mày, mũi, môi (độ dày, viền môi), tai, màu da, nốt ruồi/đặc điểm riêng, tuổi và dân tộc. Nhìn vào phải nhận "
               "ra ngay là người này. KHÔNG làm đẹp thêm, không chỉnh mặt thon/mắt to hơn, không đổi tỷ lệ mặt, không biến thành "
               "gương mặt AI chung chung. Makeup chỉ thêm màu (môi, má, mắt) lên đúng nét mặt đó, không đổi cấu trúc mặt. Được "
               "đổi: trang phục, phụ kiện, kiểu tóc/màu tóc (nếu có yêu cầu kiểu tóc, không thì giữ tóc như ảnh), tư thế.")


def face_copy(p: dict) -> bool:
    sp = p.get("model_spec") or {}
    return bool(sp.get("beauty_ref")) and sp.get("face_copy", True) is not False


def no_face_beauty(brief: str) -> str:
    """Bỏ dòng mô tả "gương mặt chuẩn đẹp" khi đã khoá gương mặt theo ảnh — dòng đó làm Muse sửa lại mặt."""
    return re.sub(r"- Gương mặt:.*?(?=\n- Kiểu tóc)", "- Gương mặt: GIỮ ĐÚNG nét mặt người trong ảnh chuan_dep.jpg, không chỉnh sửa.", brief, flags=re.S)


# ---------- video hướng dẫn tạo dáng (quảng cáo app tạo dáng: dáng sai -> app gợi ý pose -> ảnh đẹp) ----------
POSE_WRONG = ("TƯ THẾ SAI (ảnh 'trước' để so sánh, cố tình kém ăn ảnh): đứng thẳng đơ giữa khung, 2 tay buông thõng sát người, "
              "vai hơi so, mặt vô cảm nhìn thẳng máy. Chụp bằng điện thoại ngang tầm mắt, TOÀN THÂN người mẫu đứng giữa khung "
              "và chiếm khoảng 50% chiều cao ảnh (không đứng quá xa, thấy rõ mặt), thấy nền đất phía trước, ánh sáng phẳng, "
              "không xoá phông — kiểu ảnh chụp vội của người không biết tạo dáng.")
POSE_SHOT_LOOK = ("Ảnh chụp thật của nhiếp ảnh gia street style bằng máy full-frame ống 85mm f/1.8: góc máy thấp ngang hông làm "
                  "chân dài, TOÀN THÂN thấy rõ từ đầu tới giày, người mẫu ở giữa khung chiếm 55–70% chiều cao ảnh; hậu cảnh xoá "
                  "phông mạnh với các đốm đèn vàng ấm (bokeh); màu điện ảnh moody: tiền cảnh xám lạnh, hậu cảnh cam ấm, tương "
                  "phản vừa; da thật có kết cấu, tóc có sợi tơ, tay và ngón tay đúng giải phẫu. Không chữ, không logo, không người khác.")
POSE_AD_BANK = [
    "ngồi trên bậc thềm/khán đài bê tông, bắt chéo chân dài, 1 tay chống cằm, mắt nhìn nghiêng xa xăm",
    "đi về phía máy, 1 tay vuốt tóc ra sau, bước chéo chân như catwalk, ánh mắt nhìn thẳng ống kính",
    "tựa vai vào cột, 1 chân co gác lên cột, 2 tay đút túi áo khoác, nghiêng đầu cười nhẹ",
    "quay lưng 3/4 về máy, ngoái đầu nhìn qua vai, 1 tay vén tóc sang vai bên kia",
    "ngồi xổm kiểu street style, 2 khuỷu tay đặt lên gối, cằm tựa mu bàn tay, nhìn lên ống kính",
    "đứng chữ S, hông đẩy sang bên, 1 tay chống hông, tay kia chỉnh kính râm/khuyên tai, cằm hơi nâng",
    "ngồi bệt trên nền, 2 tay chống phía sau, 1 chân duỗi 1 chân co, ngửa mặt cười",
    "đang bước đi rồi ngoái lại nhìn máy, tóc bay, tay xách túi hờ hững",
    "đứng bắt chéo chân, cúi nhìn điện thoại, tay kia vén tóc sau tai",
    "dựa lưng vào tường, 1 tay đặt lên ngực, 1 gối co chạm tường, mắt khép hờ",
]


def pick_poses(styles: list[str], n: int) -> list[str]:
    """Bốc n pose ngẫu nhiên từ các phong cách người dùng chọn (không chọn thì lấy từ mọi phong cách)."""
    groups = [g for g in styles if g in POSE_BANK] or list(POSE_BANK)
    pool = [f"[{g}] {x}" for g in groups for x in POSE_BANK[g]]
    random.shuffle(pool)
    return pool[:n]


# Chống "trông như AI" khi người mẫu đi bộ/chuyển động — các lỗi hay gặp nhất của video AI
ANTI_AI = ("CHỐNG LỘ AI: bàn chân tiếp đất chắc chắn theo từng bước, KHÔNG trượt chân/lướt trên mặt đất, sải chân và nhịp đi tự "
           "nhiên; hông, vai, tay đung đưa ngược nhịp chân như người thật; tay cầm túi đúng cách, ngón tay đủ và không dính vào túi; "
           "tóc có sợi tơ lòa xòa và bay theo gió/chuyển động; vải có nếp và đung đưa theo bước đi; khuôn mặt không bất đối xứng "
           "kỳ lạ, không đổi mặt khi quay đầu, chớp mắt tự nhiên; nền (vạch kẻ đường, tường, cửa kính, xe) đứng yên và giữ nguyên "
           "hình dạng, không méo, không trôi, không mọc thêm/biến mất vật; không người lạ biến dạng phía sau; không chữ, không logo "
           "thương hiệu (kể cả trên túi, dây chuyền).")
PHONE_LOOK = ("CHẤT HÌNH: như quay thật bằng iPhone 30fps cầm tay: rung tay rất nhẹ tự nhiên khi người quay bước, đôi khi lấy nét/"
              "phơi sáng tự điều chỉnh nhẹ, có motion blur tự nhiên khi chuyển động nhanh, độ nét kiểu điện thoại (không mịn kiểu "
              "render), nhiễu hạt rất nhẹ ở vùng tối. Ánh sáng tự nhiên: ngày dịu hoặc nắng chiều muộn ấm nhẹ, mềm (như video mẫu "
              "nếu có), KHÔNG cam rực, KHÔNG color grade điện ảnh, KHÔNG HDR, không glow. Da thật có lỗ chân lông và kết cấu, má hồng "
              "kiểu makeup thật, không mịn nhựa.")
PHONE_STILL = ("CHẤT HÌNH: như 1 khung hình cắt ra từ video quay bằng iPhone: độ nét kiểu điện thoại, nhiễu hạt rất nhẹ ở vùng tối, "
               "ánh sáng tự nhiên ngày dịu hoặc nắng chiều muộn ấm nhẹ, KHÔNG cam rực, KHÔNG color grade điện ảnh, KHÔNG HDR. Da "
               "thật có lỗ chân lông và kết cấu, tóc có sợi tơ lòa xòa, vải có nếp thật, tay đúng giải phẫu.")

CHAIN_FRAME = ("Ảnh {f} là khung hình CUỐI của cảnh ngay trước. Video này phải BẮT ĐẦU đúng từ khung hình đó (cùng người mẫu, "
               "trang phục, tư thế, vị trí trong bối cảnh, góc máy, ánh sáng) rồi diễn tiếp liền mạch như cùng một cú máy liên tục.")


REGION = {
    "eu": ("PHONG CÁCH CHÂU ÂU (bắt buộc): nhân vật là người châu Âu — đường nét khuôn mặt, màu da, màu tóc, màu mắt và "
           "thời trang kiểu châu Âu; bối cảnh mang kiến trúc, đường phố, nội thất, cảnh quan châu Âu."),
    "asia": ("PHONG CÁCH CHÂU Á (bắt buộc): nhân vật là người châu Á (Đông Á/Đông Nam Á) — đường nét khuôn mặt, màu da, "
             "tóc đen hoặc nâu tối, thời trang kiểu châu Á; bối cảnh mang kiến trúc, đường phố, nội thất, cảnh quan châu Á."),
}

# Mỗi lần viết kịch bản MV bốc ngẫu nhiên 1 hướng kể + 1 thế giới + 1 kiểu nhân vật chính để các MV không na ná nhau
STORY_ANGLE = [
    "kể theo thời gian đảo ngược: mở đầu bằng kết cục, lùi dần về nguyên nhân",
    "hai dòng thời gian song song (quá khứ/hiện tại) đan xen, hội tụ ở điệp khúc cuối",
    "ẩn dụ siêu thực: cảm xúc trong lời hát được hiện thực hoá thành hiện tượng kỳ ảo trong thế giới",
    "kể qua góc nhìn của 1 đồ vật/con vật gắn bó với nhân vật chính",
    "hành trình đi đường: nhân vật di chuyển qua nhiều chặng, mỗi đoạn lời một chặng",
    "1 ngày duy nhất từ bình minh đến đêm, mỗi đoạn lời là 1 thời khắc",
    "câu chuyện bộ đôi/nhóm bạn, cảm xúc của lời hát nằm trong mối quan hệ giữa họ",
    "thể loại khác hẳn ý nghĩa bề mặt của lời (ví dụ khoa học viễn tưởng, cổ tích, phiêu lưu) nhưng cùng cảm xúc",
    "nhân vật theo đuổi 1 mục tiêu cụ thể (cuộc thi, chuyến đi, tác phẩm) và lời hát là nội tâm của họ",
    "vòng lặp: cảnh cuối nối lại cảnh đầu nhưng nhân vật đã thay đổi",
]
STORY_WORLD = [
    "thành phố ven biển nhiệt đới", "làng núi tuyết", "thành phố tương lai neon", "sa mạc và trạm dừng chân",
    "khu chợ đêm châu Á", "nông trại đồng quê mùa gặt", "trạm vũ trụ / hành tinh xa", "thị trấn châu Âu thập niên 60",
    "rừng nhiệt đới / thế giới cổ tích", "tàu hoả xuyên đêm", "đảo nhỏ và ngọn hải đăng", "thành phố dưới nước",
    "trường học / ký túc xá", "rạp xiếc / hội chợ lưu động", "phố cổ mưa phùn", "đường đua / gara xe",
]
STORY_HERO = [
    "nam thanh niên", "cô bé/cậu bé khoảng 10 tuổi", "cặp ông bà lớn tuổi", "nữ trung niên", "nhân vật không phải người (robot, động vật, sinh vật kỳ ảo)",
    "nhóm 2–3 người bạn", "nam trung niên", "nữ thiếu niên", "cặp đôi", "người lao động (ngư dân, tài xế, đầu bếp, thợ…)",
]


# Ngôn ngữ Whisper nhận ra -> tên gọi trong prompt
LANG_NAME = {"en": "tiếng Anh", "vi": "tiếng Việt", "ko": "tiếng Hàn", "ja": "tiếng Nhật", "zh": "tiếng Trung",
             "es": "tiếng Tây Ban Nha", "fr": "tiếng Pháp", "de": "tiếng Đức", "pt": "tiếng Bồ Đào Nha", "it": "tiếng Ý",
             "th": "tiếng Thái", "id": "tiếng Indonesia", "ru": "tiếng Nga", "hi": "tiếng Hindi", "tl": "tiếng Philippines"}

ASIAN_LANGS = {"vi", "ko", "ja", "zh", "th", "id", "tl", "hi"}

# Loại MV: chỉ kể chuyện / có ca sĩ + vài đoạn lip sync / ca sĩ lip sync cả bài
MV_MODE = {
    "story": ("MV KỂ CHUYỆN, KHÔNG CÓ CA SĨ: không có ai đứng hát, KHÔNG nhân vật nào hát nhép. Toàn bộ MV là 1 câu chuyện "
              "bằng hình ảnh minh hoạ ý nghĩa và cảm xúc của lời hát."),
    "singer": ("MV CÓ CA SĨ: có nhân vật CA SĨ trình bày bài hát (đúng giới tính, độ tuổi giọng hát và ngoại hình người trình bày ở "
               "phần phân tích bài hát). Các cảnh ca sĩ hát nhép xen kẽ với các cảnh câu chuyện; ca sĩ có thể chính là nhân vật "
               "chính của câu chuyện hoặc là người kể chuyện đứng ngoài, hát trong bối cảnh hợp với câu chuyện."),
    "full": ("MV CA SĨ HÁT NHÉP CẢ BÀI: nhân vật CA SĨ (đúng giới tính, độ tuổi giọng hát và ngoại hình người trình bày ở phần phân "
             "tích bài hát) hát nhép khớp khẩu hình TẤT CẢ các câu hát, quay rõ mặt. Câu chuyện của bài hát diễn ra quanh ca sĩ: "
             "ca sĩ là nhân vật chính, vừa hát vừa sống trong câu chuyện, hoặc hát trong bối cảnh của câu chuyện."),
}


STICKER_STYLES = {
    "diecut": "Hoạt hình 2D Sticker Die-cut: nhân vật dạng sticker bóc dán có viền trắng sắc nét bao quanh, đổ bóng nhẹ, hoạt hình hài hước sống động, nét vẽ sạch sẽ hiện đại.",
    "doodle": "Stickman nét đen tối giản (Black Doodle): người que kinh điển nét mực đen trên nền trắng sạch, đầu tròn biểu cảm phong phú dí dỏm, phong cách vẽ tay doodle hài hước.",
    "colorful": "Sticker Douyin màu sắc tươi sáng (Cute Chibi Sticker): nhân vật sticker chibi ngộ nghĩnh, màu pastel tươi tắn rực rỡ, biểu cảm meme phóng đại phong cách Douyin/TikTok.",
    "comic": "Manga Comic Sticker: phong cách truyện tranh comic strip, biểu cảm kịch tính, nét vẽ tốc độ, góc quay điện ảnh ấn tượng.",
    "epic": "Stickman Chiến đấu Võ thuật (Epic Battle Hero): stickman đường nét sắc sảo, hiệu ứng chưởng lực ánh sáng neon glow, hành động võ thuật hoành tráng kịch tính.",
}


def mv_mode(p: dict) -> str:
    return p.get("mv_mode") if p.get("mv_mode") in MV_MODE else "singer"


def lipsync_pct(p: dict) -> int:
    """Tỷ lệ cảnh hát nhép theo loại MV: kể chuyện 0%, lip sync cả bài 100%, có ca sĩ theo thanh trượt."""
    return {"story": 0, "full": 100}.get(mv_mode(p), p["lipsync_pct"])


def song_lang(p: dict) -> str:
    s = p.get("song") or {}
    return (s.get("language") or "").strip() or LANG_NAME.get(s.get("language_code") or "", "tiếng Anh")


def song_text(p: dict) -> str:
    """Phần phân tích bài hát đưa vào prompt kịch bản / nhân vật / plan."""
    s = p.get("song") or {}
    rows = [("Người trình bày (giọng)", s.get("singer_gender")), ("Độ tuổi giọng hát", s.get("voice_age")),
            ("Ngôn ngữ bài hát", song_lang(p)), ("Chủ đề", s.get("theme")), ("Cảm xúc", s.get("mood")),
            ("Ý chính câu chuyện trong lời", s.get("story_core")), ("Người trình bày phù hợp", s.get("performer"))]
    return "\n".join(f"- {k}: {v}" for k, v in rows if v)


# Dự án MV có thể là hoạt hình 2D (mặc định) hoặc phim quay người thật — đọc từ mô tả phong cách.
_NEG = re.compile(r"(tuyệt đối không|không|no)\s+[^,.;]*", re.I)
_ANIM = re.compile(r"hoạt hình|hoạt hoạ|hoạt họa|anime|cartoon|\b2d\b|\b3d\b|animation", re.I)
_LIVE = re.compile(r"người thật|live[- ]?action|điện ảnh|cinematic|photo ?real|chụp thật|quay thật|"
                   r"phim nhựa|realistic|documentary|phim tài liệu", re.I)


def video_kind(p: dict) -> str:
    """"live-action cinematic" nếu phong cách dự án là phim quay người thật, ngược lại "2D animation"."""
    st = _NEG.sub("", p.get("style") or "")
    if _ANIM.search(st):
        return "2D animation"
    return "live-action cinematic" if _LIVE.search(st) else "2D animation"


def style_2d(p: dict) -> str:
    """MV style guideline (hoạt hình 2D hoặc phim người thật)."""
    st = (p.get("style") or "").strip()
    st_en = to_en(st).strip()
    if video_kind(p) == "live-action cinematic":
        return (f"Art style: {st_en if st_en else 'Photorealistic live-action cinematic film still'}. "
                "Photorealistic live-action photography — real human skin, hair and fabric, real camera depth of field "
                "and film grain. Absolutely not a cartoon, not anime, not 2D/3D animation, not an illustration. "
                "Keep a consistent color grade across every image.")
    return f"Art style: {st_en if st_en else 'Clean 2D cartoon anime art style'}. Keep consistent 2D linework and color palette."


def text_rule(p: dict) -> str:
    return "No subtitles, no watermarks, no unwanted text overlays."


def ootd(p: dict) -> bool:
    """Người mẫu kiểu có cắt cảnh, quay bằng điện thoại: "Đi dạo OOTD" hoặc "Chụp ảnh nhiều pose" (mặc định)."""
    return p.get("kind") == "model" and (p.get("model_spec") or {}).get("pose", "photo") in ("ootd", "photo")


def pose_rules(pose: str | None) -> list[str]:
    pose = pose or "photo"
    if pose == "ootd":
        return [POSE_OOTD]
    if pose == "photo":
        return [POSE_PHOTO, POSE_STYLE]
    return [POSE_MOVE if pose == "move" else POSE_STILL, POSE_STYLE]


def project_dir(pid: int) -> Path:
    d = MV_DIR / str(pid)
    (d / "assets").mkdir(parents=True, exist_ok=True)
    (d / "shorts").mkdir(parents=True, exist_ok=True)
    (d / "tmp").mkdir(parents=True, exist_ok=True)
    return d


def parse_json(text: str):
    """Lấy khối JSON trong câu trả lời của Muse (có thể nằm trong ```json ... ``` hoặc lẫn chữ)."""
    cands = re.findall(r"```(?:json)?\s*([\s\S]*?)```", text or "")
    for opener, closer in (("{", "}"), ("[", "]")):
        a, b = (text or "").find(opener), (text or "").rfind(closer)
        if a != -1 and b > a:
            cands.append(text[a:b + 1])
    for c in cands:
        try:
            return json.loads(c.strip())
        except ValueError:
            continue
    raise RuntimeError("Muse không trả về JSON đọc được. Muse nói: " + (text or "(trống)")[:400])


def fmt_t(sec: float) -> str:
    return f"{int(sec // 60)}:{sec % 60:04.1f}"


def lyrics_text(lines: list[dict]) -> str:
    return "\n".join(f"[{fmt_t(l['start'])} - {fmt_t(l['end'])}] {l.get('text') or '(nhạc không lời)'}" for l in lines)


KIND_LABEL = {"character": "Nhân vật", "location": "Bối cảnh", "prop": "Đạo cụ"}

# Làm lại MV: khuôn mặt + kiểu tóc lấy từ ẢNH THẬT người dùng gửi (không chỉ ảnh Muse dựng), nhắc ở mọi bước để không lệch dần
FACE_LOCK = ("KHOÁ NHẬN DẠNG — ưu tiên cao nhất: {who} phải là ĐÚNG người trong {photos} (ảnh thật). Giữ chính xác 100%: hình "
             "dáng khuôn mặt, xương hàm, gò má, cằm, trán, mắt (hình dáng, mí, khoảng cách), lông mày, mũi, môi, tai, màu da, "
             "nốt ruồi/đặc điểm riêng. KIỂU TÓC giữ y hệt ảnh thật: độ dài, độ dày, mái, đường rẽ ngôi, độ xoăn/thẳng, màu "
             "tóc, cách vuốt — KHÔNG lấy kiểu tóc của người gốc trong MV, không đội mũ/khăn che tóc. Không làm đẹp, không "
             "trang điểm thay đổi nét, không làm trẻ/già, không đổi dân tộc. Mọi góc quay (chính diện, nghiêng, quay đầu, cận "
             "mặt) đều phải nhận ra ngay là người này; nếu khuôn mặt trong ảnh khác lệch thì ảnh thật {main} là chuẩn.")


def assets_text(assets: list[dict]) -> str:
    return "\n".join(f"- {KIND_LABEL.get(a['kind'], 'Bối cảnh')} \"{a['name']}\": {a.get('description') or ''}"
                     for a in assets)


def parse_script_scenes(script: str, max_short_sec: float = 6.0) -> list[dict]:
    """Trích xuất danh sách phân cảnh từ kịch bản có cấu trúc [Scene X: ...] hoặc [Cảnh X: ...]"""
    pattern = r"(?:\*\*|)?\[(?:Scene|Cảnh)\s*(\d+)(?::\s*([\d\.]+)s?\s*-\s*([\d\.]+)s?)?\](?:\*\*|)?(.*?)(?=(?:\*\*|)?\[(?:Scene|Cảnh)|\Z)"
    matches = re.findall(pattern, script, re.DOTALL | re.IGNORECASE)
    if not matches:
        return []
    shorts = []
    cur_t = 0.0
    for m in matches:
        idx = int(m[0])
        s_start = float(m[1]) if m[1] else cur_t
        s_end = float(m[2]) if m[2] else (s_start + max_short_sec)
        dur = max(3.0, min(max_short_sec, s_end - s_start))
        block = m[3]

        chars_m = re.search(r"-\s*(?:Characters?|Nhân vật):\s*(.*?)(?=\n-|\n\n|\Z)", block, re.IGNORECASE)
        loc_m = re.search(r"-\s*(?:Locations?|Environment|Bối cảnh):\s*(.*?)(?=\n-|\n\n|\Z)", block, re.IGNORECASE)
        action_m = re.search(r"-\s*(?:Actions?|Animation|Hành động):\s*(.*?)(?=\n-|\n\n|\Z)", block, re.IGNORECASE)
        lyric_m = re.search(r"-\s*(?:Dialogue|Subtitle|Lyrics?|Thoại|Lời thoại)[^\:]*:\s*(.*?)(?=\n-|\n\n|\Z)", block, re.IGNORECASE)

        chars_str = chars_m.group(1).strip() if chars_m else ""
        loc = loc_m.group(1).strip() if loc_m else ""
        action = action_m.group(1).strip() if action_m else ""
        lyric = lyric_m.group(1).strip().strip("\"*“”") if lyric_m else ""

        chars = [x.strip() for x in re.split(r"[,/]", chars_str) if x.strip() and not x.strip().startswith("(")]

        shorts.append({
            "idx": idx,
            "start": round(s_start, 1),
            "end": round(s_start + dur, 1),
            "lyric": lyric,
            "description": action,
            "characters": chars,
            "location": loc,
            "cont": False,
            "lipsync": False,
        })
        cur_t = round(s_start + dur, 1)
        if cur_t >= MAX_STORY_SEC:
            break
    return shorts


class Runner:
    def __init__(self, b: MuseBrowser, task: dict, cancelled: Callable[[], bool], timeout_min: float):
        self.b, self.task, self.cancelled = b, task, cancelled
        self.pid = task["project_id"]
        self.p = store.get_project(self.pid)
        self.dir = project_dir(self.pid)
        self.timeout = timeout_min * 60

    def log(self, s: str) -> None:
        store.task_log(self.task["id"], s)

    def sleep(self, secs: float) -> None:
        """Chờ nhưng vẫn bấm huỷ được."""
        for _ in range(int(secs)):
            if self.cancelled():
                raise Cancelled()
            time.sleep(1)

    def ask(self, prompt: str, atts: list[dict] | None = None, label: str = "trả lời") -> dict:
        res = self.b.generate_new_thread(prompt, self.timeout, self.log, self.cancelled, atts=atts, label=label)
        if res["text"]:
            self.log("Muse: " + res["text"][:300].replace("\n", " ") + ("…" if len(res["text"]) > 300 else ""))
        return res

    def run(self) -> None:
        getattr(self, "do_" + self.task["kind"])(**self.task["args"])

    # ---------- 1. lời bài hát + timeline ----------

    def do_lyrics(self):
        """Chạy trên máy (Whisper), không qua Muse — xem mv/transcribe.py."""
        from mv import transcribe
        lines, lang = transcribe.transcribe(self.p["audio_path"], self.log)
        if not any(l["text"] for l in lines):
            raise RuntimeError("Không nghe ra lời hát nào")
        song = {**(self.p.get("song") or {}), "language_code": lang}
        if not (self.p.get("song") or {}).get("language"):
            song["language"] = LANG_NAME.get(lang, lang)
        store.update_project(self.pid, lyrics=lines, song=song)
        self.log(f"Xong: {sum(1 for l in lines if l['text'])} câu hát · ngôn ngữ: {LANG_NAME.get(lang, lang)}")

    def do_song_analysis(self):
        """Muse nhận định bài hát: giọng nam/nữ, độ tuổi giọng, chủ đề, ai trình bày là hợp.
        Muse không nghe được file nhạc (gửi audio thì treo) nên suy luận từ tên bài + lời; người dùng sửa lại được trên giao diện."""
        p = self.p
        lang = (p.get("song") or {}).get("language_code")
        prompt = f"""Phân tích bài hát "{p['title']}" (dài {p['duration']:.0f} giây{f', máy nhận ra ngôn ngữ: {LANG_NAME.get(lang, lang)}' if lang else ''}).
Lời bài hát:
{chr(10).join(l['text'] for l in p['lyrics'] if l['text'])}

Hãy nhận định để làm MV hoạt hình 2D:
1. Bài hát do NAM hay NỮ trình bày (hoặc song ca nam–nữ / nhóm). Nếu bạn biết bài hát và ca sĩ gốc thì theo ca sĩ gốc; nếu không,
   suy luận từ lời: ngôi xưng, cách gọi người yêu (he/she, boy/girl…), góc nhìn người kể.
2. Giọng hát trẻ hay già: thiếu niên / thanh niên (20–30) / trưởng thành (30–45) / lớn tuổi — dựa vào nội dung, cách dùng từ, thể loại.
3. Ngôn ngữ bài hát.
4. Chủ đề chính và cảm xúc chủ đạo.
5. Câu chuyện/ý chính mà lời hát kể.
6. Ai trình bày là phù hợp nhất để làm nhân vật ca sĩ trong MV: giới tính, độ tuổi, ngoại hình, khí chất, phong cách trang phục.

Chỉ trả về DUY NHẤT 1 khối JSON (viết bằng tiếng Việt, riêng "language" ghi tên ngôn ngữ bằng tiếng Việt, ví dụ "tiếng Anh"):
{{"singer_gender": "nam | nữ | song ca nam nữ | nhóm", "voice_age": "...", "language": "...", "theme": "...", "mood": "...",
"story_core": "...", "performer": "...", "reason": "căn cứ ngắn gọn cho nhận định giới tính và độ tuổi"}}
{NO_ASK}"""
        data = parse_json(self.ask(prompt, label="phân tích bài hát").get("text"))
        if not isinstance(data, dict):
            raise RuntimeError("Muse trả về phân tích không đúng dạng")
        keep = ("singer_gender", "voice_age", "language", "theme", "mood", "story_core", "performer", "reason")
        song = {**(p.get("song") or {}), **{k: str(data[k]).strip() for k in keep if data.get(k)}}
        store.update_project(self.pid, song=song)
        self.log(f"Xong: giọng {song.get('singer_gender', '?')}, {song.get('voice_age', '?')}, {song.get('language', '?')} — "
                 f"chủ đề: {song.get('theme', '?')}")

    def do_lyrics_fix(self, title_hint: str = ""):
        """Nhờ Muse sửa chữ nghe nhầm + gắn tên đoạn (verse/chorus…), giữ nguyên mốc thời gian."""
        lines = self.p["lyrics"]
        numbered = "\n".join(f"{i}. [{fmt_t(l['start'])} - {fmt_t(l['end'])}] {l['text'] or '(nhạc không lời)'}"
                             for i, l in enumerate(lines))
        prompt = f"""Đây là lời bài hát "{title_hint or self.p['title']}" do máy tự nghe nên có chỗ sai chính tả / nghe nhầm.
Hãy sửa lại cho đúng lời gốc của bài (nếu bạn biết bài này), giữ NGUYÊN số dòng, thứ tự và mốc thời gian; dòng nhạc không lời giữ text rỗng.
Gắn tên đoạn cho mỗi dòng: intro, verse, pre-chorus, chorus, bridge, outro hoặc nhạc.

{numbered}

Chỉ trả về DUY NHẤT 1 khối JSON: {{"lines": [{{"i": 0, "text": "...", "section": "..."}}]}}
{NO_ASK}"""
        data = parse_json(self.ask(prompt, label="sửa lời").get("text"))
        fixed = 0
        for row in data.get("lines", []) if isinstance(data, dict) else data:
            i = row.get("i")
            if isinstance(i, int) and 0 <= i < len(lines):
                if lines[i]["text"] and (row.get("text") or "").strip() and row["text"].strip() != lines[i]["text"]:
                    lines[i]["text"] = row["text"].strip()
                    fixed += 1
                lines[i]["section"] = row.get("section") or lines[i]["section"]
        store.update_project(self.pid, lyrics=lines)
        self.log(f"Muse đã sửa {fixed} câu")

    # ---------- 2. kịch bản ----------

    def used_before(self, include_self: bool = True) -> str:
        """Tóm tắt câu chuyện + nhân vật + bối cảnh của các MV trước (và kịch bản cũ của chính dự án này)
        để Muse tránh lặp lại."""
        rows = []
        for q in store.list_projects():
            if q["kind"] != "mv" or (q["id"] == self.pid and not include_self):
                continue
            full = store.get_project(q["id"])
            assets = store.list_assets(q["id"])
            if not (full.get("script") or assets):
                continue
            chars = "; ".join(f"{a['name']} ({(a.get('description') or '')[:90]})" for a in assets if a["kind"] != "location")
            locs = ", ".join(a["name"] for a in assets if a["kind"] == "location")
            sc = full.get("script") or ""
            idea = re.search(r"Ý tưởng:\s*(.+)", sc)
            # bỏ dòng thông số đầu kịch bản (khổ hình, thời lượng…) để phần tóm tắt là nội dung câu chuyện
            body = "\n".join(l for l in sc.splitlines()
                              if not re.search(r"Kịch bản MV|Phủ kín|Thông số|khung hình|thời lượng", l, re.I))
            story = idea.group(1).strip()[:350] if idea else re.sub(r"[*#]+|\s+", " ", body).strip()[:350]
            rows.append(f"- MV \"{q['title']}\"{' (kịch bản cũ của chính bài này)' if q['id'] == self.pid else ''}: {story}"
                        + (f"\n  Nhân vật: {chars}" if chars else "") + (f"\n  Bối cảnh: {locs}" if locs else ""))
            if len(rows) >= 10:
                break
        return "\n".join(rows)

    def do_script(self):
        p = self.p
        mode, pct = mv_mode(p), lipsync_pct(p)
        worlds = STORY_WORLD
        if p.get("region") != "asia" and (p.get("song") or {}).get("language_code") not in ASIAN_LANGS:
            worlds = [w for w in STORY_WORLD if "châu Á" not in w]  # bối cảnh phải hợp ngôn ngữ bài hát
        angle, world, hero = random.choice(STORY_ANGLE), random.choice(worlds), random.choice(STORY_HERO)
        if mode != "story":  # có ca sĩ: nhân vật chính phải hợp với người trình bày, không bốc ngẫu nhiên
            hero = "ca sĩ đúng như phần phân tích bài hát (hoặc nhân vật khác hợp chủ đề, ca sĩ đứng ngoài kể chuyện)"
        self.log(f"Loại MV: {mode} · hướng sáng tạo lần này: {angle} · {world} · nhân vật chính: {hero}")
        used = self.used_before()
        song = song_text(p)
        prompt = f"""Viết kịch bản MV ca nhạc ngắn, khung hình {RATIO.get(p['aspect'], p['aspect'])}, dài đúng {p['duration']:.1f} giây theo file nhạc.
{style_2d(p)}
{("PHÂN TÍCH BÀI HÁT (kịch bản phải bám sát chủ đề, cảm xúc và người trình bày này):" + chr(10) + song) if song else ""}

LOẠI MV: {MV_MODE[mode]}

Lời bài hát và timeline:
{lyrics_text(p['lyrics'])}

Yêu cầu:
- Chia kịch bản thành các cảnh theo đúng mốc thời gian của lời bài hát, ghi rõ [mm:ss - mm:ss] cho từng cảnh, phủ kín toàn bài.
- Mỗi cảnh: bối cảnh, nhân vật, hành động, góc máy; hình ảnh minh hoạ đúng ý nghĩa lời hát.
- Đây phải là một câu chuyện có chiều sâu, không chỉ là chuỗi hình minh hoạ lời ca: có nhân vật với mong muốn và mâu thuẫn nội tâm cụ thể, lựa chọn có cái giá phải trả, thay đổi nhận thức/hành động, và kết thúc tạo dư âm.
- Dựng mạch truyện nhân-quả rõ: mở ra một câu hỏi hoặc vết thương cảm xúc, tăng dần hệ quả, có một phát hiện/lựa chọn làm đổi hướng, rồi trả lại hình ảnh hoặc biểu tượng mở đầu với ý nghĩa mới.
- Dùng một mô-típ hình ảnh xuyên suốt (vật thể, cử chỉ, màu sắc hoặc không gian) để thể hiện sự biến đổi nội tâm; điệp khúc có thể lặp mô-típ nhưng mỗi lần phải tiến triển câu chuyện.
- Diễn giải tinh thần lời hát bằng hành động và hình ảnh giàu ẩn dụ; tránh diễn lại từng câu theo nghĩa đen, tránh kết thúc sáo rỗng hoặc giải quyết mọi thứ đột ngột.
- Nhịp câu chuyện phải khớp năng lượng âm nhạc; từng cảnh có hành động nhìn thấy được, nối logic với cảnh trước và chuẩn bị trạng thái cho cảnh sau.
- Lip sync {pct}%: {lipsync_rule(pct)}{" Chỉ CA SĨ hát nhép. Đánh dấu (LIPSYNC) ở các cảnh ca sĩ hát nhép." if pct else ""}
- {text_rule(p)}
- Giữ ít nhân vật chính và ít bối cảnh để dễ đồng nhất hình ảnh; gọi mỗi nhân vật/bối cảnh bằng 1 tên cố định xuyên suốt kịch bản.
- Mở đầu bằng các dòng "Ý tưởng:", "Ý nghĩa:", "Hành trình nhân vật:" (tóm tắt biến đổi từ đầu đến cuối), và "Nhân vật & bối cảnh:" liệt kê ngắn{" (ghi rõ nhân vật nào là CA SĨ)" if mode != "story" else ""}.

CÂU CHUYỆN PHẢI MỚI HOÀN TOÀN, viết riêng cho lời bài hát này:
- Đọc kỹ ý nghĩa lời hát rồi mới nghĩ câu chuyện; KHÔNG dùng lại bất kỳ câu chuyện, nhân vật, bối cảnh nào từ các cuộc trò chuyện
  hay MV trước (kể cả trong bộ nhớ của bạn).
- Hướng sáng tạo bắt buộc cho lần này (diễn giải lời hát theo hướng này, vẫn phải hợp chủ đề và cảm xúc bài hát):
  · Cách kể: {angle}
  · Thế giới/bối cảnh: {world}
  · Nhân vật chính: {hero}
- Tránh lối mòn: cô gái buồn một mình trong căn nhà/phòng trống, bóng ma người yêu cũ, mưa bên cửa sổ, cà phê nguội, vali dọn nhà,
  trừ khi lời hát bắt buộc.
{("- " + REGION[p["region"]]) if p.get("region") in REGION else ""}
{("- Các MV ĐÃ LÀM dưới đây — câu chuyện, nhân vật (giới tính, tuổi, kiểu tóc, trang phục) và bối cảnh của MV mới phải KHÁC HẲN, không na ná:" + chr(10) + used) if used else ""}

Output the screenplay in English text format (no JSON). {NO_ASK_EN}"""
        res = self.ask(prompt, label="viết kịch bản")
        if not res["text"].strip():
            raise RuntimeError("Muse không trả về kịch bản")
        store.update_project(self.pid, script=res["text"].strip())
        self.log("Xong kịch bản")

    # ---------- 3. nhân vật & bối cảnh ----------

    def do_assets(self):
        p = self.p
        if p["kind"] == "scriptvideo":
            style_preset = (p.get("model_spec") or {}).get("style_preset", "stick2d")
            style_name = {"stick2d": "2D stick figure cartoon", "toon2d": "2D cartoon", "toon3d": "3D cartoon", "clay3d": "3D clay cartoon"}.get(style_preset, "2D stick figure cartoon")
            prompt = f"""Read the user-provided screenplay and extract the principal characters and locations needed for consistent short video references.
Animation style: {style_name}. Stick-figure characters must have a round solid black head, a simple stick-figure body, and recognizable clothing/accessories. Do not rewrite the story or invent new plot events.
Return at most 4 characters and 5 locations. Describe each character's silhouette, clothes, colors and signature accessories. Describe location layout, key props and palette.
Output ONLY valid JSON: {{"characters":[{{"name":"...","description":"..."}}],"locations":[{{"name":"...","description":"..."}}]}}
SCREENPLAY:\n{p['script']}\n{NO_ASK_EN}"""
            data = parse_json(self.ask(prompt, label="phân tích nhân vật theo kịch bản").get("text"))
            items = [{"kind": "character", **c} for c in data.get("characters", [])] + [{"kind": "location", **c} for c in data.get("locations", [])]
            store.replace_unlocked_assets(self.pid, [i for i in items if i.get("name")])
            self.log(f"Xong: {len(data.get('characters', []))} nhân vật, {len(data.get('locations', []))} bối cảnh")
            return
        if p["kind"] == "stickerman":
            spec = p.get("model_spec") or {}
            style_preset = spec.get("style_preset", "diecut")
            style_desc_en = STICKER_STYLES_EN.get(style_preset, "2D Die-cut Sticker Animation")
            prompt = f"""Read the screenplay and extract CHARACTERS and LOCATIONS for visual consistency design.

Art Style: {style_desc_en}

REQUIREMENTS:
- Up to 3 main characters. For each character, provide short name and distinct visual identifier (body shape, clothing color, accessories, meme facial expression).
- Up to 2 minimalist 2D cartoon environments.

Output ONLY valid JSON:
{{"characters": [{{"name": "Short Name", "description": "Specific visual details, outfit colors, accessories for 100% consistency..."}}],
  "locations": [{{"name": "Location Name", "description": "Minimalist background details, lighting, color palette..."}}]}}

SCREENPLAY:
{p['script']}
{NO_ASK_EN}"""
            data = parse_json(self.ask(prompt, label="phân tích nhân vật sticker").get("text"))
            items = [{"kind": "character", **c} for c in data.get("characters", [])] + \
                    [{"kind": "location", **c} for c in data.get("locations", [])]
            store.replace_unlocked_assets(self.pid, [i for i in items if i.get("name")])
            self.log(f"Xong: {len(data.get('characters', []))} nhân vật sticker, {len(data.get('locations', []))} bối cảnh")
            return
        mode = mv_mode(p)
        others = self.used_before(include_self=False)
        s = p.get("song") or {}
        singer = (f"BẮT BUỘC có nhân vật ca sĩ (tên bắt đầu bằng \"Ca sĩ\", ví dụ \"Ca sĩ Mia\"; nếu kịch bản đã đặt tên thì dùng "
                  f"\"Ca sĩ <tên trong kịch bản>\"): giới tính {s.get('singer_gender') or 'theo giọng hát'}, độ tuổi "
                  f"{s.get('voice_age') or 'hợp giọng hát'}; {s.get('performer') or ''} Khuôn mặt vẽ rõ để hát nhép.") if mode != "story" else \
                 "MV này KHÔNG có ca sĩ: không tạo nhân vật ca sĩ."
        prompt = f"""Đọc kịch bản MV dưới đây và liệt kê các NHÂN VẬT CHÍNH và BỐI CẢNH CHÍNH cần thiết kế cố định để mọi cảnh đồng nhất.
{style_2d(p)}
{("PHÂN TÍCH BÀI HÁT:" + chr(10) + song_text(p)) if song_text(p) else ""}
{singer}
Mô tả mỗi mục thật cụ thể để vẽ lại giống hệt nhau: nhân vật (giới tính, tuổi, kiểu tóc, màu tóc, khuôn mặt, trang phục, màu sắc, phụ kiện); bối cảnh (không gian, đồ vật, ánh sáng, màu chủ đạo).
BÁM SÁT KỊCH BẢN: chỉ những nhân vật/bối cảnh CÓ TRONG kịch bản và xuất hiện nhiều lần (tối đa 4 nhân vật, 5 bối cảnh); giữ đúng
tên gọi như trong kịch bản; tuổi, giới tính, nghề nghiệp, trang phục, thời đại, mùa, thời tiết, giờ trong ngày đúng như kịch bản tả.
{text_rule(p)}
Thiết kế phải KHÁC HẲN nhân vật/bối cảnh của các MV trước (không lặp lại khuôn mặt, kiểu tóc, màu tóc,
trang phục, bảng màu, không gian); không lấy từ bộ nhớ hay cuộc trò chuyện cũ.
{REGION.get(p.get("region") or "", "")}
{("NHÂN VẬT/BỐI CẢNH CÁC MV TRƯỚC (KHÔNG được giống):" + chr(10) + others) if others else ""}
Chỉ trả về DUY NHẤT 1 khối JSON:
{{"characters": [{{"name": "tên ngắn", "description": "..."}}], "locations": [{{"name": "tên ngắn", "description": "..."}}]}}

KỊCH BẢN:
{p['script']}
{NO_ASK}"""
        data = parse_json(self.ask(prompt, label="phân tích nhân vật").get("text"))
        items = [{"kind": "character", **c} for c in data.get("characters", [])] + \
                [{"kind": "location", **c} for c in data.get("locations", [])]
        store.replace_unlocked_assets(self.pid, [i for i in items if i.get("name")])
        self.log(f"Xong: {len(data.get('characters', []))} nhân vật, {len(data.get('locations', []))} bối cảnh")

    def do_asset_image(self, asset_id: int, feedback: str = "", ref_frames: list[str] | None = None, beauty: bool = False):
        a = store.get_asset(asset_id)
        if not a:
            raise RuntimeError("Mục này đã bị xoá")
        if a["locked"]:
            raise RuntimeError(f"\"{a['name']}\" đang khoá — mở khoá trước khi tạo lại")
        prompt, atts, cref = self.asset_prompt(a, feedback, ref_frames)
        if beauty:
            prompt, atts = self.with_beauty(prompt, atts)
        self.save_asset_image(a, self.ask(prompt, atts, "tạo ảnh"), cref)

    def with_beauty(self, prompt: str, atts: list) -> tuple[str, list]:
        """Vẽ người mẫu mới theo chuẩn vẻ đẹp của ảnh người dùng gửi (nếu có)."""
        ref = (self.p.get("model_spec") or {}).get("beauty_ref")
        if not ref or not Path(ref).exists():
            return prompt, atts
        atts = atts + [MuseBrowser.attachment(ffmpeg.small_jpeg(Path(ref), self.dir / "tmp" / "beauty.jpg", 1024), "chuan_dep.jpg")]
        rule = BEAUTY_FACE if face_copy(self.p) else BEAUTY_REF
        return prompt.replace(f"\n\n{NO_ASK}", "\n" + rule + f"\n\n{NO_ASK}"), atts

    def do_asset_images(self, kind: str = "character"):
        """Vẽ tất cả nhân vật (hoặc bối cảnh) chưa khoá, gửi Muse BATCH ảnh cùng lúc."""
        todo = [a for a in store.list_assets(self.pid) if a["kind"] == kind and not a["locked"]]
        if not todo:
            raise RuntimeError("Không có mục nào chưa khoá để vẽ")
        self.log(f"Vẽ {len(todo)} {'nhân vật' if kind == 'character' else 'bối cảnh'}, {BATCH} ảnh cùng lúc")
        self.draw_assets(todo)

    def draw_assets(self, todo: list[dict], beauty: bool = False):
        """Vẽ ảnh cho các mục, gửi Muse BATCH ảnh cùng lúc (mỗi ảnh 1 chat)."""
        failed = []
        for i in range(0, len(todo), BATCH):
            if self.cancelled():
                raise Cancelled()
            sids = {}
            for a in todo[i:i + BATCH]:
                prompt, atts, cref = self.asset_prompt(a)
                if beauty:
                    prompt, atts = self.with_beauty(prompt, atts)
                sids[self.b.start_thread(prompt, atts)] = (a, cref)
            for sid, res in self.b.wait_threads(list(sids), self.timeout, self.log, self.cancelled, "vẽ ảnh").items():
                a, cref = sids[sid]
                try:
                    self.save_asset_image(a, res, cref)
                except Exception as e:
                    failed.append(a["name"])
                    self.log(f"{a['name']}: {e}")
        if failed:
            raise RuntimeError(f"Chưa vẽ được: {', '.join(failed)} — bấm Muse vẽ lại từng mục")

    def asset_prompt(self, a: dict, feedback: str = "", ref_frames: list[str] | None = None):
        asset_id, style = a["id"], self.p["style"]
        if self.p["kind"] == "remake":
            return self.remake_asset_prompt(a, feedback)
        if self.p["kind"] in ("stickerman", "scriptvideo"):
            spec = self.p.get("model_spec") or {}
            style_preset = spec.get("style_preset", "diecut")
            style_desc_en = {"stick2d": "2D stick figure animation with a round solid black head, black line limbs, recognizable clothing and accessories",
                             "toon2d": "polished 2D cartoon animation with clean outlines and expressive poses",
                             "toon3d": "polished stylized 3D cartoon animation with expressive shapes and soft cinematic lighting",
                             "clay3d": "stylized 3D clay animation with tactile surfaces and consistent handmade materials"}.get(
                                 style_preset, STICKER_STYLES_EN.get(style_preset, "2D cartoon animation"))
            desc_en = to_en(a["description"])
            if a["kind"] == "character":
                head = "Generate 1 image. Aspect ratio: 1:1."
                body = (f"Character Sheet: \"{a['name']}\"\n"
                        f"Art style: {style_desc_en}\n"
                        f"Description: {desc_en}\n"
                        "Requirements:\n"
                        "- Create a 3-by-3 production character reference sheet on a plain white background. Every panel must show the same identity.\n"
                        "- Keep a round solid black head and simple stick-figure body; convey emotion with body pose and small graphic marks, not human facial features.\n"
                        "- Preserve the exact outfit, clothing colors and signature accessories in every view. Include front, three-quarter, side, back and expressive poses.\n"
                        "- No text, scenery, extra characters or redesigns; clear separated panels, high-clarity cartoon design.")
            else:
                head = f"Generate 1 image. Aspect ratio: {RATIO_EN.get(self.p['aspect'], self.p['aspect'])}."
                body = (f"Environment Background: \"{a['name']}\"\n"
                        f"Art style: {style_desc_en}\n"
                        f"Description: {desc_en}\n"
                        "Requirements: Minimalist cartoon background matching the chosen 2D or 3D medium, clean perspective and lighting, no characters, no text.")
        elif a["kind"] == "character" and self.p["kind"] in ("model", "pose"):
            head = "Tạo 1 ảnh · tỷ lệ 3:4 (dọc)"
            body = (f"Ảnh tham chiếu người mẫu \"{a['name']}\", phong cách {style}: {a['description']}\n"
                    + ("" if face_copy(self.p) else MODEL_BEAUTY + "\n") + MODEL_PORTRAIT + "\n"
                    "Vẽ ĐÚNG và ĐỦ từng món đồ, chất liệu, màu, phụ kiện, kiểu tóc, makeup như mô tả — không đơn giản hoá.")
        elif a["kind"] == "character":
            head = "Generate 1 image (1:1 square aspect ratio)."
            desc_en = to_en(a['description']).strip()
            style_en = to_en(style or "2D animation").strip()
            body = (f"Character design sheet: \"{a['name']}\"\n"
                    f"Style: {style_en}\n"
                    f"Description: {desc_en}\n"
                    "Requirements: Create one clean 3-by-3 character reference contact sheet on a plain white background. Every panel MUST show the exact same person with the same face, age, body proportions, hairstyle, hair colour, outfit, accessories and palette; no redesigns or alternate costumes. "
                    "Panels: (1) full-body front view, neutral; (2) full-body three-quarter view; (3) full-body side profile; (4) full-body back view; (5) close-up calm/neutral face; (6) close-up joyful face; (7) close-up worried/sad face; (8) close-up determined/hopeful face; (9) close-up crying or emotionally vulnerable face. "
                    "Keep facial identity unmistakably consistent across all panels; vary only camera angle or expression. Keep the complete outfit visible in full-body panels. Thin unobtrusive panel separation, no labels, no text, no scenery, no extra people. This is a production reference sheet, not a scene to reproduce.")
        else:
            ratio = RATIO_EN.get(self.p.get("aspect"), "16:9 widescreen")
            head = f"Generate 1 image ({ratio})."
            desc_en = to_en(a['description']).strip()
            style_en = to_en(style or "2D animation").strip()
            body = (f"Environment concept art: \"{a['name']}\"\n"
                    f"Style: {style_en}\n"
                    f"Description: {desc_en}\n"
                    "Requirements: Clean scenery without characters, no text overlays.")
            if self.p["kind"] in ("model", "pose"):
                body = (f"Environment photo: \"{a['name']}\": {desc_en}\n"
                        "No people, no text overlays.")
        atts = []
        # Khung hình cắt từ video gốc (dự án dựng lại từ phim): vẽ theo HÌNH, không chỉ theo chữ — bám sát hơn hẳn mô tả.
        if self.p["kind"] == "mv" and a.get("orig_path") and Path(a["orig_path"]).exists():
            atts.append(MuseBrowser.attachment(
                ffmpeg.small_jpeg(Path(a["orig_path"]), self.dir / "tmp" / f"orig{a['id']}.jpg", 1024), "khung_goc.jpg"))
            body += ("\nAttached khung_goc.jpg is a frame from the source film showing this "
                     + ("character" if a["kind"] == "character" else "place") + ". "
                     + ("Reproduce the SAME face shape, hairstyle, hair colour, skin tone, body build, outfit and colours "
                        "as that person, redrawn cleanly as a full-body design sheet."
                        if a["kind"] == "character" else
                        "Reproduce the SAME architecture, layout, materials, colour palette and lighting, with no people in it."))
        spec = self.p.get("model_spec") or {}
        cref = (self.color_ref() if self.p["kind"] in ("model", "pose")
                and (a["kind"] == "location" or spec.get("source") == "video") else None)
        if cref:
            atts.append(MuseBrowser.attachment(cref, "mau_sac.jpg"))
            body += "\n" + COLOR_REF.format(f="mau_sac.jpg")
        if ref_frames:
            for i, f in enumerate(ref_frames, 1):
                atts.append(MuseBrowser.attachment(ffmpeg.small_jpeg(Path(f), Path(f).with_suffix(".s.jpg")), f"nguoi_mau_{i}.jpg"))
            body += ("\nCác ảnh đính kèm là khung hình từ video mẫu: vẽ lại ĐÚNG người mẫu này "
                     "(cùng khuôn mặt, kiểu tóc, vóc dáng, trang phục).")
        if feedback:
            body += f"\nRevision: {to_en(feedback)}"
            if a["image_path"] and Path(a["image_path"]).exists():
                ref = ffmpeg.small_jpeg(Path(a["image_path"]), self.dir / "tmp" / f"asset{asset_id}_ref.jpg")
                atts.append(MuseBrowser.attachment(ref, "ban_truoc.jpg"))
                body += "\nAttached ban_truoc.jpg: keep everything unchanged except requested revisions."
        if self.p["kind"] in ("stickerman", "scriptvideo"):
            anchor = next((x for x in store.list_assets(self.pid) if x["locked"] and x["id"] != asset_id
                           and x.get("image_path") and Path(x["image_path"]).exists()), None)
            if anchor and not feedback:
                ref = ffmpeg.small_jpeg(Path(anchor["image_path"]), self.dir / "tmp" / f"style{anchor['id']}.jpg", 768)
                atts.append(MuseBrowser.attachment(ref, "phong_cach_nhan_vat.jpg"))
                body += ("\nReference style: Match the outline thickness, color palette, and vector feel of attached phong_cach_nhan_vat.jpg.")
        if self.p["kind"] == "mv" and self.p.get("region") in REGION:
            body += "\n" + REGION[self.p["region"]] + " Nếu mô tả có chi tiết trái với phong cách này, ưu tiên phong cách này."
        if self.p["kind"] == "mv":
            body += "\n" + style_2d(self.p) + "\n" + text_rule(self.p)
            # vẽ theo nét của ảnh đã khoá để cả bộ nhân vật/bối cảnh cùng 1 phong cách
            anchor = next((x for x in store.list_assets(self.pid) if x["locked"] and x["id"] != asset_id
                           and x.get("image_path") and Path(x["image_path"]).exists()), None)
            if anchor and not feedback:
                ref = ffmpeg.small_jpeg(Path(anchor["image_path"]), self.dir / "tmp" / f"style{anchor['id']}.jpg", 768)
                atts.append(MuseBrowser.attachment(ref, "phong_cach.jpg"))
                body += ("\nReference style: Match the color grade, lighting and photographic look of attached phong_cach.jpg."
                         if video_kind(self.p) == "live-action cinematic" else
                         "\nReference style: Match the outline thickness, color palette, and vector feel of attached phong_cach.jpg.")
        return f"{head}\n{body}\n\n{NO_ASK_EN} Output only 1 image file.", atts, cref

    def save_asset_image(self, a: dict, res: dict, cref) -> None:
        asset_id = a["id"]
        img = next((f for f in res["files"] if (f.get("mime") or "").startswith("image/")), None)
        if not img:
            raise RuntimeError("Muse không trả về ảnh")
        ext = img["mime"].split("/")[1].replace("jpeg", "jpg")
        dest = self.dir / "assets" / f"a{asset_id}_{int(time.time())}.{ext}"
        self.b.download_runtime_file(img, dest)
        if cref:  # đưa màu ảnh về giống video mẫu; short sau đó vẽ theo ảnh này nên màu cũng gần video mẫu hơn
            dest = self.match_color(dest, dest.with_name(dest.stem + "_m.jpg"))
        store.update_asset(asset_id, image_path=str(dest), source="muse")
        self.log(f"Đã tải ảnh {a['name']}")

    # ---------- làm lại MV có sẵn ----------

    def do_remake_analysis(self):
        """Muse xem MV gốc: liệt kê nhân vật, bối cảnh, đạo cụ (kèm giây xuất hiện rõ nhất để cắt ảnh gốc)
        và chia timeline thành các phân cảnh -> plan short bám đúng MV gốc."""
        p = self.p
        small = ffmpeg.video_small(Path(p["ref_video_path"]), self.dir / "tmp" / "ref_small.mp4")
        dur = p["duration"]
        lyr = lyrics_text(p["lyrics"]) if p.get("lyrics") else ""
        prompt = f"""Xem MV ca nhạc / nhảy đính kèm (dài {dur:.1f} giây). Tôi sẽ LÀM LẠI MV này: giữ nguyên vũ đạo, bố cục, góc máy,
nhịp dựng, nhưng thay một số nhân vật, bối cảnh, đạo cụ bằng hình ảnh của tôi. Hãy phân tích thật chi tiết:
1. "characters": mọi người xuất hiện (ca sĩ, vũ công…). Đặt tên ngắn dễ phân biệt (ví dụ "Ca sĩ chính", "Vũ công áo đỏ").
   Mô tả: vai trò, giới tính, tuổi, khuôn mặt, kiểu tóc, trang phục, phụ kiện, vị trí trong đội hình.
2. "locations": các bối cảnh (không gian, đồ vật, ánh sáng, màu chủ đạo).
3. "props": đạo cụ đáng chú ý (micro, xe, đồ cầm tay, đồ trang trí lớn…).
   Mỗi mục có "t": giây mà mục đó hiện RÕ NHẤT trong video (để cắt ảnh).
4. "scenes": chia TOÀN BỘ video thành các phân cảnh theo đúng điểm cắt cảnh của MV, phủ kín 0 → {dur:.1f} giây.
   Mỗi phân cảnh: "start", "end" (giây), "description" (động tác nhảy/hát cụ thể, hướng di chuyển, biểu cảm, cỡ cảnh,
   góc máy và chuyển động máy), "characters" (tên nhân vật có mặt), "location" (tên bối cảnh), "props" (tên đạo cụ),
   "singing": true nếu có người đang hát nhép rõ mặt.
5. "summary": tóm tắt MV (vibe, phong cách hình ảnh: người thật/hoạt hình, màu sắc, ánh sáng, nhịp dựng).
{("Lời bài hát và timeline (để biết đoạn nào có hát):" + chr(10) + lyr) if lyr else ""}
Viết mô tả bằng tiếng Việt. Chỉ trả về DUY NHẤT 1 khối JSON:
{{"summary": "...", "characters": [{{"name": "...", "description": "...", "t": 3.5}}], "locations": [{{"name": "...", "description": "...", "t": 1.0}}],
"props": [{{"name": "...", "description": "...", "t": 8.0}}],
"scenes": [{{"start": 0.0, "end": 4.2, "description": "...", "characters": ["..."], "location": "...", "props": ["..."], "singing": false}}]}}
{NO_ASK}"""
        self.log("Gửi MV gốc lên Muse")
        res = self.ask(prompt, [{**MuseBrowser.attachment(small, "mv_goc.mp4"), "mimeType": "video/mp4",
                                 "category": "video"}], "xem MV gốc")
        data = parse_json(res.get("text"))
        if not isinstance(data, dict):
            raise RuntimeError("Muse trả về phân tích không đúng dạng")
        items = []
        for key, kind in (("characters", "character"), ("locations", "location"), ("props", "prop")):
            for i, x in enumerate(data.get(key) or []):
                if not (x.get("name") or "").strip():
                    continue
                t = min(max(0.0, float(x.get("t") or 0)), max(0.0, dur - 0.1))
                img = self.dir / "assets" / f"orig_{kind}{i}_{int(time.time())}.jpg"
                try:
                    ffmpeg.frame(Path(p["ref_video_path"]), t, img)
                except RuntimeError:
                    img = None
                items.append({"kind": kind, "name": x["name"].strip(), "description": x.get("description", ""),
                              "orig_path": str(img) if img else None})
        store.replace_unlocked_assets(self.pid, items)
        shorts = remake_plan(data.get("scenes") or [], dur, p["max_short_sec"], p.get("lyrics") or [])
        store.replace_shorts(self.pid, shorts)
        store.update_project(self.pid, analysis=(data.get("summary") or "").strip())
        self.log(f"Xong: {sum(i['kind'] == 'character' for i in items)} nhân vật, "
                 f"{sum(i['kind'] == 'location' for i in items)} bối cảnh, {sum(i['kind'] == 'prop' for i in items)} đạo cụ · "
                 f"{len(shorts)} short ({sum(s['lipsync'] for s in shorts)} short hát nhép)")

    def remake_asset_prompt(self, a: dict, feedback: str = ""):
        """Ảnh thay thế cho 1 mục của MV gốc: dựng từ ảnh người dùng tải lên, đặt vào vai/kiểu của mục gốc."""
        atts, tmp = [], self.dir / "tmp"
        refs = [r for r in a.get("refs") or [] if Path(r).exists()][:4]
        if not refs:
            raise RuntimeError(f"\"{a['name']}\": chưa tải ảnh của bạn lên để thay thế")
        names = []
        for i, r in enumerate(refs, 1):
            atts.append(MuseBrowser.attachment(ffmpeg.small_jpeg(Path(r), tmp / f"ref{a['id']}_{i}.jpg", 1024), f"cua_toi_{i}.jpg"))
            names.append(f"cua_toi_{i}.jpg")
        orig = a.get("orig_path") if a.get("orig_path") and Path(a["orig_path"]).exists() else None
        if orig:
            atts.append(MuseBrowser.attachment(ffmpeg.small_jpeg(Path(orig), tmp / f"orig{a['id']}.jpg", 1024), "goc.jpg"))
        mine = ", ".join(names)
        if a["kind"] == "character":
            head = "Tạo 1 ảnh · tỷ lệ 4:3 (ngang)"
            body = (f"Ảnh {mine} là CÙNG MỘT NGƯỜI THẬT (chính tôi) chụp ở nhiều góc; {names[0]} là ảnh mặt chuẩn. Tạo ảnh "
                    "nhân vật của ĐÚNG người này để thay vào vai \"" + a["name"] + "\" trong MV.\n"
                    + FACE_LOCK.format(who="Nhân vật", photos=mine, main=names[0]) + " Vóc dáng, chiều cao như ảnh của tôi.\n"
                    + (f"Ảnh goc.jpg là nhân vật gốc trong MV: CHỈ lấy TRANG PHỤC, giày, phụ kiện (trừ mũ/khăn che tóc) và phong "
                       "cách ánh sáng/màu từ ảnh này. KHÔNG lấy khuôn mặt, KHÔNG lấy kiểu tóc của người trong goc.jpg.\n" if orig else "")
                    + f"Mô tả vai gốc (bỏ qua mọi chi tiết về mặt/tóc trong mô tả này): {a.get('description') or ''}\n"
                    "Bố cục 2 phần trên cùng 1 ảnh: bên trái toàn thân đứng thẳng nhìn thẳng ống kính (thấy rõ trang phục, giày); "
                    "bên phải ảnh cận mặt chính diện thấy rõ từng đường nét và kiểu tóc. Nền trơn sáng, ánh sáng đều dịu, không chữ, không logo.")
        else:
            label = "bối cảnh" if a["kind"] == "location" else "đạo cụ"
            head = f"Tạo 1 ảnh · tỷ lệ {RATIO.get(self.p['aspect'], self.p['aspect'])}" if a["kind"] == "location" else "Tạo 1 ảnh · tỷ lệ 1:1"
            body = (f"Ảnh {mine} là {label} THẬT của tôi. Tạo ảnh {label} này để thay cho {label} \"{a['name']}\" trong MV: "
                    f"giữ ĐÚNG hình dáng, màu sắc, chất liệu, chi tiết như ảnh của tôi.\n"
                    + (f"Ảnh goc.jpg là {label} gốc trong MV: lấy góc nhìn, bố cục, ánh sáng và phong cách hình ảnh theo ảnh này.\n" if orig else "")
                    + ("Không có người. " if a["kind"] == "location" else "Đạo cụ đặt trên nền trơn sáng, thấy toàn bộ. ")
                    + "Không chữ, không logo.")
        if feedback:
            body += f"\nSửa theo yêu cầu: {feedback}"
            if a.get("image_path") and Path(a["image_path"]).exists():
                atts.append(MuseBrowser.attachment(ffmpeg.small_jpeg(Path(a["image_path"]), tmp / f"asset{a['id']}_ref.jpg"), "ban_truoc.jpg"))
                body += "\nẢnh ban_truoc.jpg là bản trước — giữ những gì không được yêu cầu sửa."
        return f"{head}\n{body}\n\n{NO_ASK} Chỉ trả về đúng 1 file ảnh.", atts, None

    def face_photos(self, a: dict, atts: list, prefix: str, n: int = 2) -> list[str]:
        """Đính kèm n ảnh thật người dùng gửi (ảnh đầu = mặt chuẩn) để mọi bước so trực tiếp với ảnh thật, không chỉ ảnh Muse dựng."""
        names = []
        for i, r in enumerate([r for r in a.get("refs") or [] if Path(r).exists()][:n], 1):
            fname = f"{prefix}_that_{i}.jpg"
            atts.append(MuseBrowser.attachment(ffmpeg.small_jpeg(Path(r), self.dir / "tmp" / f"face{a['id']}_{i}.jpg", 1024), fname))
            names.append(fname)
        return names

    def remake_swaps(self, s: dict, assets: dict) -> list[dict]:
        """Các mục trong short này được thay bằng ảnh của người dùng (đã có ảnh thay thế)."""
        names = list(s["characters"] or []) + ([s["location"]] if s.get("location") else [])
        out = [assets[n.lower()] for n in names if n.lower() in assets]
        return [a for a in out if a.get("mode") == "replace" and a.get("image_path") and Path(a["image_path"]).exists()]

    def remake_keep_original(self, s: dict) -> bool:
        """Short không có mục nào cần thay -> dùng luôn đoạn video gốc, không tốn lượt Muse."""
        assets = {a["name"].lower(): a for a in store.list_assets(self.pid)}
        if self.remake_swaps(s, assets):
            return False
        version = s["version"] + 1
        dest = self.dir / "shorts" / f"s{s['id']}_v{version}.mp4"
        ffmpeg.cut(Path(self.p["ref_video_path"]), s["start"], s["end"] - s["start"], dest)
        thumb = ffmpeg.thumbnail(dest, dest.with_suffix(".jpg"))
        store.update_short(s["id"], status="done", video_path=str(dest), thumb_path=str(thumb) if thumb else None,
                           version=version, error=None, retries=0)
        self.log(f"Short #{s['idx']}: không có gì cần thay — dùng đoạn MV gốc")
        return True

    def remake_short_prompt(self, s: dict, assets: dict, first_frame: Path | None) -> tuple[str, list[dict]]:
        """Short làm lại: khung đầu = khung gốc đã thay nhân vật/bối cảnh/đạo cụ (hoặc khung cuối short trước nếu nối cảnh),
        kèm đoạn MV gốc làm mẫu động tác + ảnh người thay thế để giữ đúng mặt."""
        p, dur = self.p, s["end"] - s["start"]
        swaps = self.remake_swaps(s, assets)
        if any(a["kind"] == "character" for a in swaps):
            # có người được thay: luôn vẽ khung đầu mới từ ảnh thật thay vì nối khung cuối short trước (mặt lệch dồn qua từng short)
            first_frame = None
        chained = first_frame is not None
        if not chained:
            first_frame = self.remake_keyframe(s, swaps)
        tmp = self.dir / "tmp"
        atts = [MuseBrowser.attachment(ffmpeg.small_jpeg(first_frame, first_frame.with_suffix(".s.jpg")), "khung_dau.jpg")]
        clip = ffmpeg.clip_small(Path(p["ref_video_path"]), s["start"], dur, tmp / f"orig_clip{s['id']}.mp4")
        atts.append({**MuseBrowser.attachment(clip, "doan_goc.mp4"), "mimeType": "video/mp4", "category": "video"})
        req = max(MIN_CLIP_SEC, math.ceil(dur))
        text = [f"Tạo 1 video dài {req} giây · tỷ lệ {RATIO.get(p['aspect'], p['aspect'])} từ ảnh khung_dau.jpg (image-to-video).",
                (CHAIN_FRAME if chained else "Ảnh {f} là khung hình ĐẦU TIÊN: video bắt đầu đúng từ ảnh này.").format(f="khung_dau.jpg"),
                "Video doan_goc.mp4 là đoạn tương ứng của MV gốc: làm lại ĐÚNG vũ đạo/động tác, nhịp theo nhạc, hướng di chuyển, "
                "đội hình, biểu cảm, cỡ cảnh, góc máy và chuyển động máy như đoạn này — nhưng nhân vật, bối cảnh, đạo cụ phải "
                "giống khung_dau.jpg (không lấy lại người/vật gốc đã được thay).",
                f"Nội dung: {s['description']}"]
        people = [a for a in swaps if a["kind"] == "character"]
        if people:
            a = people[0]
            atts.append(MuseBrowser.attachment(ffmpeg.small_jpeg(Path(a["image_path"]), tmp / f"ref{a['id']}.jpg", 1024), "nguoi_thay.jpg"))
            real = self.face_photos(a, atts, "mat", 1)
            text.append(f"Ảnh nguoi_thay.jpg là \"{a['name']}\" (trang phục, vóc dáng)"
                        + (f"; {real[0]} là ảnh thật khuôn mặt + kiểu tóc chuẩn" if real else "") + ".")
            text.append(FACE_LOCK.format(who=f"\"{a['name']}\"", photos=", ".join(["nguoi_thay.jpg", *real]),
                                         main=(real or ["nguoi_thay.jpg"])[0])
                        + " Suốt video không đổi mặt, không biến dạng khuôn mặt khi nhảy, xoay người, cúi đầu hay hát; tóc chuyển "
                          "động tự nhiên nhưng giữ đúng kiểu. Nếu khung_dau.jpg có mặt hơi khác ảnh thật, sửa theo ảnh thật."
                        + (" Đây là short nối tiếp: KHÔNG được để khuôn mặt lệch dần so với ảnh thật." if chained else ""))
        if s["lipsync"]:
            who = next((a["name"] for a in people), (s["characters"] or ["ca sĩ"])[0])
            timed = [f"  {max(0, l['start'] - s['start']):.1f}s–{min(dur, l['end'] - s['start']):.1f}s: \"{l['text']}\""
                     for l in p.get("lyrics") or [] if l["text"] and l["end"] > s["start"] and l["start"] < s["end"]]
            text.append(f"{who} vừa nhảy vừa hát, quay rõ mặt, khẩu hình miệng khớp lời hát"
                        + (" theo đúng mốc giây:\n" + "\n".join(timed) if timed and s.get("lyric_mode") != "plain"
                           else " như trong đoạn gốc (nhạc sẽ được ghép sau)."))
        text.append("Giữ đúng phong cách hình ảnh, màu sắc, ánh sáng của MV gốc. Không thêm chữ, không logo.")
        if s["feedback"]:
            text.append(f"Bản trước chưa đạt, lần này hãy sửa: {s['feedback']}")
        text.append(f"\n{NO_ASK} Chỉ trả về đúng 1 file video.")
        return "\n".join(text), atts

    def remake_keyframe(self, s: dict, swaps: list[dict]) -> Path:
        """Vẽ lại khung hình gốc ở đầu short, thay đúng các nhân vật/bối cảnh/đạo cụ bằng ảnh của người dùng."""
        tmp = self.dir / "tmp"
        orig = ffmpeg.frame(Path(self.p["ref_video_path"]), s["start"] + 0.05, tmp / f"origf{s['id']}.jpg")
        atts = [MuseBrowser.attachment(ffmpeg.small_jpeg(orig, orig.with_suffix(".s.jpg"), 1024), "khung_goc.jpg")]
        lines, locks = [], []
        # nhân vật trước để chắc chắn ảnh thật của người được gửi kèm
        for i, a in enumerate(sorted(swaps, key=lambda a: a["kind"] != "character")[:3], 1):
            fname = f"thay_{i}.jpg"
            atts.append(MuseBrowser.attachment(ffmpeg.small_jpeg(Path(a["image_path"]), tmp / f"ref{a['id']}.jpg", 1024), fname))
            what = {"character": "người", "location": "bối cảnh", "prop": "đạo cụ"}[a["kind"]]
            real = self.face_photos(a, atts, f"nguoi{i}", 2 if i == 1 else 1) if a["kind"] == "character" else []
            lines.append(f"- {KIND_LABEL[a['kind']]} \"{a['name']}\" trong khung gốc → thay bằng {what} trong {fname}"
                         + (f" (trang phục theo {fname}; khuôn mặt + kiểu tóc theo ảnh thật {', '.join(real)})" if real else ""))
            if a["kind"] == "character":
                locks.append(FACE_LOCK.format(who=f"\"{a['name']}\"", photos=", ".join([*real, fname]), main=(real or [fname])[0]))
        prompt = "\n".join([
            f"Tạo 1 ảnh · tỷ lệ {RATIO.get(self.p['aspect'], self.p['aspect'])}",
            "Vẽ lại ĐÚNG khung hình khung_goc.jpg (cùng bố cục, tư thế, đội hình, góc máy, cỡ cảnh, ánh sáng, màu sắc, phong cách "
            "hình ảnh) nhưng THAY các mục sau:",
            *lines,
            *locks,
            "Chỉ giữ tư thế, góc đầu, biểu cảm của người gốc — KHÔNG giữ khuôn mặt hay kiểu tóc của người gốc. Khuôn mặt phải "
            "đủ rõ nét, không bị che, không mờ.",
            "Mọi thứ không được nêu ở trên giữ nguyên như khung gốc. Không thêm chữ, không logo.",
            f"\n{NO_ASK} Chỉ trả về đúng 1 file ảnh."])
        self.log(f"Short #{s['idx']}: vẽ lại khung gốc với {len(swaps)} mục thay thế")
        res = self.ask(prompt, atts, "tạo khung đầu")
        img = next((f for f in res["files"] if (f.get("mime") or "").startswith("image/")), None)
        if not img:
            raise RuntimeError(f"Muse không tạo được khung đầu: {(res.get('text') or '')[:200]}")
        dest = tmp / f"key{s['id']}_{int(time.time())}.{img['mime'].split('/')[1].replace('jpeg', 'jpg')}"
        self.b.download_runtime_file(img, dest)
        return dest

    # ---------- người mẫu tạo dáng ----------

    def do_video_analysis(self):
        small = ffmpeg.video_small(Path(self.p["ref_video_path"]), self.dir / "tmp" / "ref_small.mp4")
        dur = self.p["duration"]
        prompt = f"""Xem video người mẫu tạo dáng đính kèm (dài {dur:.1f} giây). Phân tích chi tiết để tôi làm lại video cùng kiểu:
1. Người mẫu: giới tính, độ tuổi, nét châu Á/châu Âu…, khuôn mặt, kiểu tóc, vóc dáng.
2. Trang phục & phụ kiện.
3. Bối cảnh, ánh sáng, màu sắc/tông màu.
4. Timeline từng cảnh theo giây [mm:ss - mm:ss]: tư thế/động tác (đi bộ, xoay người, cầm phụ kiện…), biểu cảm, ánh mắt, cỡ cảnh,
   góc máy và chuyển động máy (người quay đi lùi, vòng quanh, push-in…), điểm cắt cảnh và kiểu chuyển cảnh.
5. Nhịp dựng (nhanh/chậm, mỗi cảnh dài khoảng bao nhiêu giây) và cảm giác chung (vibe).
Trả lời bằng tiếng Việt, gạch đầu dòng ngắn gọn. {NO_ASK}"""
        self.log("Gửi video mẫu lên Muse")
        res = self.ask(prompt, [{**MuseBrowser.attachment(small, "video_mau.mp4"), "mimeType": "video/mp4",
                                 "category": "video"}], "xem video")
        if not res["text"].strip():
            raise RuntimeError("Muse không trả về phân tích")
        store.update_project(self.pid, analysis=res["text"].strip())
        self.log("Xong phân tích video")

    def do_model_design(self, source: str = "new", gender: str = "", region: str = "", age: str = "",
                        style: str = "", outfit: str = "", notes: str = "", variants: int = 3, **more):
        """more: topic, aesthetic, hair, makeup, body, sexy (lựa chọn thêm trên giao diện); beauty_ref nằm trong model_spec."""
        spec = {**(self.p.get("model_spec") or {}), "source": source, "gender": gender, "region": region, "age": age,
                "style": style, "outfit": outfit, "notes": notes, **{k: v for k, v in more.items() if k in DESIGN_KEYS or k == "face_copy"}}
        store.update_project(self.pid, model_spec=spec)
        if source == "video" and not self.p.get("ref_video_path"):
            raise RuntimeError("Dự án không có video mẫu — chọn \"Thiết kế người mẫu mới\"")
        if source == "video":
            want = (f"Dùng lại ĐÚNG người mẫu trong video mẫu (theo phần phân tích bên dưới)."
                    + (f" Trang phục: {outfit}." if outfit else " Giữ trang phục như trong video.")
                    + (f" Ghi chú: {notes}." if notes else ""))
        else:
            want = ", ".join(x for x in (gender and f"giới tính {gender}", region and f"người {region}",
                                         age and f"độ tuổi {age}", style and f"chủ đề/bối cảnh {style}",
                                         *(spec.get(k) and f"{label} {spec[k]}" for k, label in DESIGN_KEYS.items()),
                                         outfit and f"trang phục {outfit}", notes) if x)
        atts, beauty = [], spec.get("beauty_ref")
        if beauty and Path(beauty).exists() and source != "video":
            atts.append(MuseBrowser.attachment(ffmpeg.small_jpeg(Path(beauty), self.dir / "tmp" / "beauty.jpg", 1024), "chuan_dep.jpg"))
        variants = 1 if source == "video" else max(1, min(4, int(variants or 1)))
        lock = bool(atts) and spec.get("face_copy", True) is not False
        male = (spec.get("gender") or "").strip().lower() == "nam"
        prompt = f"""Thiết kế {variants} người mẫu cho video tạo dáng chụp ảnh. Yêu cầu: {want or 'tự chọn phù hợp phong cách'}.
{(no_face_beauty(STYLIST_BRIEF) if lock else STYLIST_BRIEF) if source != "video" else ""}
{(f"{variants} phương án CÙNG 1 GƯƠNG MẶT (đúng người trong chuan_dep.jpg) nhưng KHÁC HẲN nhau về trang phục, bảng màu, món điểm nhấn, chất liệu, kiểu tóc/makeup — để tôi chọn phương án đẹp nhất." if lock else f"{variants} phương án phải KHÁC HẲN nhau (gương mặt, kiểu tóc, bảng màu, món điểm nhấn, chất liệu) nhưng đều bám yêu cầu trên — để tôi chọn phương án đẹp nhất.") if variants > 1 else ""}
{"" if lock else MODEL_BEAUTY}{" Giữ đúng người trong video mẫu nhưng ở phiên bản đẹp nhất (makeup, tóc, trang phục được chăm chút)." if source == "video" else ""}
{(BEAUTY_FACE + " Phần gương mặt trong description: tả THẬT KỸ đúng nét mặt người trong ảnh (không tả theo chuẩn đẹp chung)." if lock else BEAUTY_REF) if atts else ""}
{(SEXY_MALE if male else SEXY).get(spec.get("sexy") or "", "")}
{(ALLURE_MALE if male else ALLURE) if spec.get("sexy") in HOT_LEVELS else ""}
Người mẫu phải trông như người thật (ảnh chụp thật, không kiểu AI/búp bê). Phối đồ hợp chủ đề và gu đã chọn (mặc định OOTD đường phố) theo xu hướng, phụ kiện (túi, trang sức) KHÔNG có logo thương hiệu. Mô tả thật cụ thể để vẽ lại giống hệt nhau ở mọi cảnh: giới tính, tuổi, nét mặt, màu da, kiểu và màu tóc, vóc dáng, trang phục chi tiết (màu, chất liệu), giày, phụ kiện.

{self.ref_text()}

Mỗi "description" viết thành 1 đoạn liền, cụ thể tới từng chi tiết (gương mặt, tóc, makeup, từng món đồ + chất liệu + màu + form,
phụ kiện, giày) để vẽ lại giống hệt nhau ở mọi cảnh.
Chỉ trả về DUY NHẤT 1 khối JSON: {{"models": [{{"name": "tên ngắn gợi tả bộ đồ", "description": "..."}}]}}
{NO_ASK}"""
        data = parse_json(self.ask(prompt, atts, label="thiết kế người mẫu").get("text"))
        models = data.get("models") if isinstance(data, dict) and data.get("models") else [data] if isinstance(data, dict) else data
        models = [m for m in models or [] if isinstance(m, dict) and (m.get("description") or m.get("name"))][:variants]
        if not models:
            raise RuntimeError("Muse không trả về thiết kế người mẫu")
        # mọi người mẫu Muse đã tạo đều giữ lại để chọn; phương án đầu được chọn sẵn
        n = sum(a["kind"] == "character" for a in store.list_assets(self.pid))
        ids = [store.add_asset(self.pid, "character", m.get("name") or f"Người mẫu {n + i + 1}", m.get("description", ""))
               for i, m in enumerate(models)]
        store.update_project(self.pid, sel_model=ids[0])
        self.log(f"Xong {len(ids)} phương án: {', '.join(m.get('name') or '?' for m in models)} — đang vẽ ảnh")
        if source == "video":
            dur = self.p["duration"]
            frames = [str(ffmpeg.frame(Path(self.p["ref_video_path"]), dur * k, self.dir / "tmp" / f"frame{i}.jpg"))
                      for i, k in enumerate((0.2, 0.5, 0.8))]
            return self.do_asset_image(ids[0], ref_frames=frames)
        self.draw_assets([store.get_asset(i) for i in ids], beauty=bool(atts))

    def do_locations(self, count: int = 3, notes: str = ""):
        spec = self.p.get("model_spec") or {}
        prompt = f"""Đề xuất {count} bối cảnh chụp ảnh/quay video cho người mẫu tạo dáng, hợp với phong cách "{spec.get('style') or 'theo video mẫu'}"{f', ghi chú: {notes}' if notes else ''}.
{("Phải KHÁC các bối cảnh đã có: " + ", ".join(a["name"] for a in store.list_assets(self.pid) if a["kind"] == "location") + ".") if any(a["kind"] == "location" for a in store.list_assets(self.pid)) else ""}
Bối cảnh phải là địa điểm thật, đời thường, trông như ảnh chụp bằng điện thoại (ví dụ: đường phố trước toà nhà/cửa hàng, vỉa hè có vạch kẻ đường, quán cà phê, phố mua sắm), đủ rộng để người mẫu đi bộ về phía máy và có vài góc khác nhau để cắt cảnh. Ánh sáng: ban ngày dịu hoặc nắng chiều muộn ấm nhẹ, mềm — không hoàng hôn cam rực/ánh sáng kịch tính trừ khi ghi chú yêu cầu. Mỗi bối cảnh mô tả cụ thể để vẽ lại giống hệt nhau: địa điểm, đồ vật, ánh sáng, thời điểm trong ngày, màu chủ đạo. Không có người.

{self.ref_text()}

Chỉ trả về DUY NHẤT 1 khối JSON: {{"locations": [{{"name": "tên ngắn", "description": "..."}}]}}
{NO_ASK}"""
        data = parse_json(self.ask(prompt, label="đề xuất bối cảnh").get("text"))
        items = [l for l in data.get("locations", []) if l.get("name")]
        for l in items:  # thêm vào danh sách, không xoá bối cảnh đã tạo trước đó
            store.add_asset(self.pid, "location", l["name"], l.get("description", ""))
        self.log(f"Xong: thêm {len(items)} bối cảnh — bấm Muse vẽ để tạo ảnh từng bối cảnh")

    def do_model_scripts(self, count: int = 1, duration: float = 15, notes: str = "", pose: str = "photo",
                         pose_styles: list[str] | None = None):
        store.update_project(self.pid, model_spec={**(self.p.get("model_spec") or {}), "pose": pose,
                                                   "pose_styles": pose_styles or []})
        hot = (self.p.get("model_spec") or {}).get("sexy") in HOT_LEVELS
        if hot and not pose_styles:
            pose_styles = ["Quyến rũ", "Gợi cảm nhẹ", "Sang chảnh", "Editorial tạp chí"]
        poses = pick_poses(pose_styles or [], max(6, round(duration / 2.5) + 3)) if pose == "photo" else []
        if poses:
            self.log(f"Bốc {len(poses)} pose từ phong cách: {', '.join(pose_styles or []) or 'tất cả'}")
        p = self.p
        model, loc = store.get_asset(p.get("sel_model") or 0), store.get_asset(p.get("sel_location") or 0)
        if not model or not loc:
            raise RuntimeError("Chưa chọn người mẫu và bối cảnh ở bước 2")
        max_sec = p["max_short_sec"]
        old = store.list_scripts(self.pid)
        prompt = f"""Viết {count} kịch bản cho video người mẫu tạo dáng chụp ảnh, dài đúng {duration:.0f} giây, khung hình {RATIO.get(p['aspect'], p['aspect'])}.
Toàn bộ kịch bản quay 1 người mẫu tại 1 bối cảnh (bên dưới). {'Bám theo nhịp dựng và kiểu tạo dáng của video mẫu.' if p.get('analysis') else ''}{f' Ghi chú: {notes}.' if notes else ''}
{("Ý tưởng phải KHÁC các kịch bản đã có: " + "; ".join(f"{o['title']} ({o['concept'] or ''})" for o in old) + ".") if old else ""}
{("Phong cách người mẫu/chủ đề: " + ", ".join(str(v) for k, v in (p.get("model_spec") or {}).items() if k in ("style", *DESIGN_KEYS) and v) + ".") if p.get("model_spec") else ""}
Quay như clip thời trang thật, ánh sáng ban ngày tự nhiên (không hoàng hôn rực, không ánh sáng kịch tính trừ khi ghi chú yêu cầu), không cảnh kỳ ảo/hiệu ứng AI.
{(POSE_PHOTO + chr(10) + "POSE GỢI Ý cho kịch bản này (dùng phần lớn trong số này, mỗi pose 1 lần, có thể biến tấu cho hợp bối cảnh/trang phục; cảnh đầu nên là người mẫu bước vào vị trí rồi vào pose):" + chr(10) + chr(10).join("- " + x for x in poses) + chr(10) + CAMERA_VARIETY + chr(10) + "Mỗi cảnh có số \"scene\" riêng (cắt cảnh); ghi rõ 2 pose của cảnh theo thứ tự.") if pose == "photo" else (POSE_OOTD + chr(10) + OOTD_STRUCTURE + chr(10) + "Các cảnh cách nhau bằng CẮT CẢNH thì đặt \"scene\" khác nhau; cảnh dài bị chia nhỏ giữ cùng \"scene\".") if pose == "ootd" else (POSE_STILL + " Mỗi cảnh là 1–2 pose chụp ảnh khác nhau tại cùng chỗ đứng (được tựa, ngồi, ngồi xổm ngay tại chỗ), cả kịch bản giữ nguyên 1 vị trí.") if pose == "still" else POSE_MOVE}
{"Động tác phải tự nhiên như người thật đi dạo được bạn quay lại, không tạo dáng cứng kiểu studio." if pose == "ootd" else "" if pose == "photo" else POSE_LIBRARY}
{ALLURE_MOTION if hot else ""}
Chia mỗi kịch bản thành các cảnh (shot) dài 3–{max_sec} giây nối liền từ 0 đến {duration:.0f} giây. Mỗi cảnh: tư thế/động tác tạo dáng, biểu cảm, góc máy + chuyển động máy.

NGƯỜI MẪU: {model['name']} — {model['description'] or ''}
BỐI CẢNH: {loc['name']} — {loc['description'] or ''}

{self.ref_text()}

Chỉ trả về DUY NHẤT 1 khối JSON:
{{"scripts": [{{"title": "tên ngắn", "concept": "1-2 câu ý tưởng", "shots": [{{"start": 0, "end": 4, "scene": 1, "description": "..."}}]}}]}}
{NO_ASK}"""
        data = parse_json(self.ask(prompt, label="viết kịch bản").get("text"))
        scripts = data.get("scripts", data) if isinstance(data, dict) else data
        n = 0
        for sc in scripts or []:
            shots = normalize_plan(sc.get("shots") or [], duration, max_sec, 0)
            for i, sh in enumerate(shots):
                if pose not in ("ootd", "photo"):  # kiểu cũ: cả kịch bản là 1 cú máy liền
                    sh["cont"] = False
                elif i and re.search(r"tiếp nối|nối tiếp|không cắt", (sh.get("description") or "")[:80], re.I):
                    sh["cont"] = True  # Muse ghi "tiếp nối không cắt" nhưng hay quên giữ cùng số "scene"
            for sh in shots:
                sh["characters"], sh["location"] = [model["name"]], loc["name"]
            store.add_script(self.pid, sc.get("title") or f"Kịch bản {len(old) + n + 1}", sc.get("concept", ""), shots,
                             model["id"], loc["id"])
            n += 1
        if not n:
            raise RuntimeError("Muse không trả về kịch bản nào")
        self.log(f"Xong: {n} kịch bản")

    # ---------- 4. plan short ----------

    def do_plan(self):
        p = self.p
        mode, pct = mv_mode(p), lipsync_pct(p)
        assets = store.list_assets(self.pid)
        singer = singer_name(assets)
        prompt = f"""Divide music video into sequential video SHORTS ({p['duration']:.1f}s total).
Style: {to_en(p.get('style') or '2D animation')}
Rules:
- Each short: 3 to {p['max_short_sec']}s, seamless timestamps from 0.0s to {p['duration']:.1f}s.
- These shorts form ONE continuous, emotionally meaningful story, not separate illustrations. Preserve cause-and-effect and the protagonist's emotional transformation across every short.
- For every short after the first, set "cont": true. The video tool will attach the actual final frame of the prior short; write each description as the next story beat that grows naturally from that visual state.
- Make each description concrete and mention the intended end-state (pose, screen position, expression, important prop) so the next short can continue it. A change of place/time must be motivated by the story and visually bridge from the attached prior frame.
- "lipsync": true for singing shorts ({pct}% total), clear face view.
- "description": concise physical animation action and camera movement in English.
- "characters" & "location": exact match to locked assets.
- "scene": scene index.

LYRICS & TIMELINE:
{lyrics_text(p['lyrics'])}

ASSETS:
{to_en(assets_text(assets))}

SCRIPT:
{p['script']}

Output ONLY valid JSON:
{{"shorts": [{{"start": 0.0, "end": 6.0, "scene": 1, "lyric": "...", "description": "...", "lipsync": false, "characters": ["..."], "location": "..."}}]}}
{NO_ASK_EN}"""
        data = parse_json(self.ask(prompt, label="lên plan").get("text"))
        shorts = normalize_plan(data.get("shorts", data) if isinstance(data, dict) else data,
                                p["duration"], p["max_short_sec"], pct)
        if p["kind"] == "mv":
            # Mọi short MV tiếp diễn từ khung cuối short trước để giữ mạch hình ảnh và diễn biến.
            for i, short in enumerate(shorts):
                short["cont"] = i > 0
        if singer:  # short hát nhép: ca sĩ luôn đứng đầu danh sách nhân vật (người hát)
            for x in shorts:
                if x["lipsync"]:
                    x["characters"] = [singer] + [c for c in x["characters"] if c.lower() != singer.lower()]
        store.replace_shorts(self.pid, shorts)
        self.log(f"Xong plan: {len(shorts)} short, {sum(s['lipsync'] for s in shorts)} short lip sync, "
                 f"{sum(1 for s in shorts if s['cont'])} short nối tiếp phân cảnh trước")

    # ---------- thumbnail ----------

    def do_thumbnail(self, prompt: str = ""):
        """Muse thiết kế thumbnail: theo yêu cầu người dùng, hoặc tự nghĩ bố cục thu hút người xem bấm vào.
        Gửi kèm ảnh nhân vật chính (giữ đúng mặt) + 1 khung hình trong MV (giữ đúng phong cách, màu)."""
        p, atts, refs = self.p, [], []
        tmp = self.dir / "tmp"
        tmp.mkdir(parents=True, exist_ok=True)
        chars = [a for a in store.list_assets(self.pid) if a["kind"] != "location" and a.get("image_path")
                 and Path(a["image_path"]).exists()]
        for a in sorted(chars, key=lambda a: not a.get("locked"))[:2]:
            fname = f"nhan_vat_{len(atts) + 1}.jpg"
            atts.append(MuseBrowser.attachment(ffmpeg.small_jpeg(Path(a["image_path"]), tmp / f"ref{a['id']}.jpg", 1024), fname))
            refs.append(f"- {fname}: nhân vật \"{a['name']}\" — giữ ĐÚNG khuôn mặt, kiểu tóc, trang phục")
        done = [s for s in store.list_shorts(self.pid) if s["status"] == "done" and s.get("thumb_path")
                and Path(s["thumb_path"]).exists()]
        if done:
            pick = done[len(done) // 2]
            atts.append(MuseBrowser.attachment(ffmpeg.small_jpeg(Path(pick["thumb_path"]), tmp / "thumb_frame.jpg", 1024),
                                               "khung_mv.jpg"))
            refs.append("- khung_mv.jpg: 1 khung hình trong video — giữ đúng phong cách hình ảnh, màu sắc, bối cảnh")
        story = p.get("script") or "\n".join(f"{x['title']}: {x.get('concept') or ''}" for x in store.list_scripts(self.pid))
        ratio = "16:9 (ngang, 1280x720)" if p["aspect"] != "9:16" else "9:16 (dọc)"
        ask = prompt.strip() or (
            "Hãy TỰ thiết kế thumbnail khiến người lướt YouTube muốn bấm vào ngay: 1 điểm nhấn chính rõ ràng (nhân vật chính "
            "cận cảnh, cảm xúc mạnh, ánh mắt hướng về người xem hoặc về chi tiết gây tò mò), khoảnh khắc kịch tính/cảm xúc nhất "
            "của câu chuyện, bố cục đơn giản đọc được ngay ở kích thước nhỏ, tương phản cao, màu nổi bật nhưng hài hoà, nền gọn, "
            "ánh sáng có chiều sâu. Nếu thêm chữ: tối đa 2–4 chữ thật to, đậm, dễ đọc, đúng chính tả (có thể là tên bài hát), "
            "không che mặt nhân vật.")
        text = "\n".join([
            f"Generate 2 YouTube THUMBNAIL design options for \"{p['title']}\" ({RATIO_EN.get(p['aspect'], p['aspect'])}).",
            f"Art Style: {to_en(p.get('style') or '2D animation')}",
            ("Story context:\n" + to_en(story[:800])) if story else "",
            ("Reference attachments:\n" + "\n".join(refs)) if refs else "",
            f"Requirements: {to_en(ask)}",
            f"\n{NO_ASK_EN} Output only image files."])
        self.log("Muse đang thiết kế thumbnail" + (" theo yêu cầu" if prompt.strip() else " (tự đề xuất)"))
        res = self.ask(text, atts, "tạo thumbnail")
        imgs = [f for f in res["files"] if (f.get("mime") or "").startswith("image/")]
        if not imgs:
            raise RuntimeError(f"Muse không trả về ảnh thumbnail: {(res.get('text') or '')[:200]}")
        out = self.dir / "thumbs"
        out.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        for i, f in enumerate(imgs, 1):
            ext = f["mime"].split("/")[1].replace("jpeg", "jpg")
            self.b.download_runtime_file(f, out / f"thumb_{ts}_{i}.{ext}")
        self.log(f"Xong: {len(imgs)} thumbnail")

    # ---------- stickerman: kịch bản & phân cảnh ----------

    def do_stickerman_script(self, topic: str = "", genre: str = "comedy", style_preset: str = "diecut",
                             scenes_count: int | None = None, duration_sec: float | None = None):
        p = self.p
        spec = p.get("model_spec") or {}
        genre = genre or spec.get("genre", "comedy")
        style_preset = style_preset or spec.get("style_preset", "diecut")
        max_sec = float(p.get("max_short_sec") or 6)

        # Hỗ trợ chọn thời lượng phim từ 10s đến 180s (tối đa 3 phút)
        dur = float(duration_sec or spec.get("target_duration") or p.get("duration") or 30.0)
        dur = max(10.0, min(180.0, dur))  # Giới hạn tối đa 3 phút (180 giây)

        if scenes_count:
            n_scenes = max(2, min(36, int(scenes_count)))
        else:
            n_scenes = max(3, min(36, round(dur / max(4.0, max_sec - 1.0))))

        mins = int(dur // 60)
        secs = int(dur % 60)
        dur_label = f"{mins} phút {f'{secs}s' if secs else ''}".strip() if mins else f"{secs} giây"

        genre_desc = {
            "comedy": "Hài hước / Meme đời sống: tình huống bất ngờ, hiểu lầm ngớ ngẩn, biểu cảm phóng đại cực bựa, cái kết twist bất ngờ.",
            "workplace": "Công sở / Học đường: mâu thuẫn sếp - nhân viên, phỏng vấn xin việc, thi cử, drama văn phòng dí dỏm.",
            "action": "Võ thuật / Hành động kịch tính: stickman thách đấu võ đài, thi triển chiêu thức võ thuật hài hước hoặc hoành tráng, giải cứu bạn bè.",
            "mystery": "Trinh thám / Kịch tính bí ẩn: truy tìm kẻ trộm đồ ăn trong tủ lạnh, phòng thoát hiểm, plot twist không ngờ tới.",
            "life": "Bài học cuộc sống / Kể chuyện triết lý: câu chuyện ngắn ý nghĩa nhưng truyền tải theo góc nhìn stickman hài hước, ấm áp.",
        }.get(genre, genre)

        genre_en = {
            "comedy": "Fast-paced viral comedy with exaggerated meme reactions and physical humor",
            "action": "Martial arts combat with flashy moves, comedic impacts, and high energy choreography",
            "drama": "Emotional journey with high-stakes moments, dramatic turns, and heartwarming triumph",
            "horror_comedy": "Spooky encounters with hilarious panic, ridiculous reactions, and funny twists",
            "daily": "Relatable everyday struggles, awkward situations, witty satire, and surprise twist",
        }.get(genre, genre)
        style_desc_en = STICKER_STYLES_EN.get(style_preset, "2D Die-cut Sticker Animation, bold white outline.")

        prompt = f"""Write a viral 2D STICKER MAN short animation film screenplay.
Title: "{p['title']}"
Genre: {genre_en}
Style: {style_desc_en}
Aspect ratio: {RATIO_EN.get(p['aspect'], p['aspect'])}
Total duration: Exactly {dur:.0f} seconds ({dur_label}, up to 180s).
Scenes count: Exactly {n_scenes} sequential scenes (approx 4–{max_sec:.0f}s per scene).
{f'Premise: {to_en(topic)}' if topic else 'Create an entertaining storyline with fast comedic pacing and a surprise plot twist at the climax.'}

Key Rules:
1. Characters: 1 to 3 distinct stickman/sticker characters with unmistakable visual traits (specific clothing color, hat, glasses, or accessories) and exaggerated meme expressions.
2. Environments: 1 to 2 minimalist 2D cartoon locations.
3. Dialogue: Punchy, humorous, viral meme lines.

Language Requirement: The screenplay MUST BE ENTIRELY WRITTEN IN ENGLISH (premise, character details, scene breakdowns, actions, and dialogues).

Output Structure (100% IN ENGLISH):
**MAIN PREMISE & TOTAL DURATION:** (1 sentence summary & twist, {dur:.0f}s / {dur_label})
**CHARACTERS & ENVIRONMENTS:** (Distinctive visual traits, colors, accessories)
**DETAILED SCREENPLAY - ALL {n_scenes} SCENES:**
**[Scene 1: 0s - {int(dur/n_scenes)}s]**
- Character: [Character name]
- Location: [Location name]
- Action: [Specific visual physical comedy / animation action]
- Dialogue/Subtitle: [Punchy dialogue / caption]

**[Scene 2: {int(dur/n_scenes)}s - {int(dur*2/n_scenes)}s]**
- Character: ...
- Location: ...
- Action: ...
- Dialogue/Subtitle: ...
...
{NO_ASK_EN}"""
        res = self.ask(prompt, label="viết kịch bản sticker")
        if not res["text"].strip():
            raise RuntimeError("Muse không trả về kịch bản")
        store.update_project(self.pid, script=res["text"].strip(),
                             duration=float(dur),
                             model_spec={**spec, "genre": genre, "style_preset": style_preset,
                                         "scenes_count": n_scenes, "target_duration": dur})
        self.log(f"Xong kịch bản phim sticker ({n_scenes} cảnh · {dur_label})")

    def do_stickerman_plan(self, count: int | None = None):
        p = self.p
        assets = store.list_assets(self.pid)
        assets_info = assets_text(assets)
        target_dur = float(p.get("duration") or 30.0)
        target_dur = max(10.0, min(MAX_STORY_SEC, target_dur))
        max_sec = float(p.get("max_short_sec") or 6)

        mins = int(target_dur // 60)
        secs = int(target_dur % 60)
        dur_label = f"{mins} phút {f'{secs}s' if secs else ''}".strip() if mins else f"{secs} giây"

        prompt = f"""Break down this animated screenplay into exact sequential video SHORTS:
Title: "{p['title']}"
Aspect ratio: {RATIO_EN.get(p['aspect'], p['aspect'])}
Total duration: about {target_dur:.0f}s. If the screenplay needs more time to be told in full, extend the total instead of dropping content.
Short duration: 4 to {max_sec:.0f} seconds each, chosen by how much happens: about 5s for a single simple beat, 8 to {max_sec:.0f}s for a beat with several actions so it plays slowly and with depth. Never cram several events into a short clip.

CHARACTERS AND LOCATIONS:
{to_en(assets_info)}

SCREENPLAY:
{p['script']}

REQUIREMENTS:
- Sequential shots from 0.0s onward. COVER EVERY beat, line of dialogue and event of the screenplay in order; do NOT summarize, merge scenes or skip content to fit the duration.
- These shorts form one continuous story in screenplay order. Preserve cause-and-effect, character emotion and important props.
- Every short after the first MUST set "cont": true. The renderer will attach both the locked main character design sheet and the actual final frame of the preceding short.
- Describe the opening action as a direct continuation of the preceding short's final pose/state, then advance the screenplay to the next beat. End each description with a clear pose, expression and prop state that the next short can continue.
- "start" and "end": timestamps in seconds.
- "scene": scene index integer.
- "lyric": short dialogue or caption.
- "description": concise physical animation action in English.
- Every action a character performs must have a clear purpose and meaning in the story (an intention, emotion or consequence). In each "description" state briefly WHY the character does it; no random, filler or decorative movement.
- "characters": array of character names (exact match).
- "location": location name (exact match).
- "cont": true if seamless continuous camera/pose from previous shot, false otherwise.

Output ONLY valid JSON:
{{"shorts": [
  {{"start": 0.0, "end": 5.0, "scene": 1, "lyric": "...", "description": "...", "characters": ["..."], "location": "...", "cont": false}}
]}}
{NO_ASK_EN}"""
        # Nếu kịch bản đã có sẵn cấu trúc [Cảnh X: ...], ưu tiên trích xuất trực tiếp
        parsed_scenes = parse_script_scenes(p.get("script", ""), max_sec)
        if parsed_scenes and len(parsed_scenes) >= 3:
            shorts = parsed_scenes
            if p["kind"] == "scriptvideo":
                for i, short in enumerate(shorts):
                    short["cont"] = i > 0
            cur_t = shorts[-1]["end"]
            store.replace_shorts(self.pid, shorts)
            store.update_project(self.pid, duration=round(cur_t, 1))
            self.log(f"Đã trích xuất nhanh {len(shorts)} phân cảnh từ kịch bản ({cur_t:.1f}s)")
            return

        raw = self.ask(prompt, label="lên phân cảnh sticker").get("text")
        data = parse_json(raw)
        items = data.get("shorts", data) if isinstance(data, dict) else data
        if not isinstance(items, list) or not items:
            raise RuntimeError("Muse không trả về danh sách phân cảnh hợp lệ")
        shorts = []
        cur_t = 0.0
        for i, it in enumerate(items, 1):
            if cur_t >= MAX_STORY_SEC:
                break
            dur = max(3.0, min(float(min(MAX_CLIP_SEC, p.get("max_short_sec", 6))), float(it.get("end", 5.0) - it.get("start", 0.0)) if it.get("end") else 5.0))
            if cur_t + dur > MAX_STORY_SEC:
                dur = max(3.0, MAX_STORY_SEC - cur_t)
            shorts.append({
                "idx": i,
                "start": round(cur_t, 1),
                "end": round(cur_t + dur, 1),
                "lyric": (it.get("lyric") or "").strip(),
                "description": (it.get("description") or "").strip(),
                "lipsync": False,
                "characters": it.get("characters") or [],
                "location": (it.get("location") or "").strip(),
                "cont": bool(it.get("cont", False)),
            })
            cur_t += dur
            if cur_t >= MAX_STORY_SEC:
                break
        if p["kind"] == "scriptvideo":
            for i, short in enumerate(shorts):
                short["cont"] = i > 0
        store.replace_shorts(self.pid, shorts)
        store.update_project(self.pid, duration=round(cur_t, 1))
        self.log(f"Xong bảng phân cảnh: {len(shorts)} cảnh ({cur_t:.1f}s · tối đa 3 phút)")

    # ---------- 5. tạo short ----------

    def do_shorts(self):
        # Đưa các short kẹt ở 'running' từ lần chạy trước về lại 'queued'
        for s in store.list_shorts(self.pid):
            if s["status"] == "running":
                store.update_short(s["id"], status="queued")
        if self.p["kind"] in ("mv", "scriptvideo", "model", "stickerman") and self.p.get("chat_mode") != "chain" \
                and (self.p.get("chat_mode") == "batch" or self.p["kind"] in ("mv", "scriptvideo")):
            # Mặc định cho MV / video theo kịch bản: 1 prompt, 1 chat, Muse tự tạo lần lượt cả chuỗi short
            return self.shorts_batch()
        if self.p["kind"] in ("mv", "scriptvideo"):
            # MV phải tuần tự để short sau dùng được khung cuối của short ngay trước.
            for short in store.list_shorts(self.pid):
                if short["idx"] > 1 and not short.get("cont"):
                    store.update_short(short["id"], cont=1)
            return self.shorts_chain()
        if self.p.get("chat_mode") == "single":
            return self.shorts_single_chat()
        if self.p.get("chat_mode") == "chain" or self.p["kind"] == "remake":
            return self.shorts_chain()
        while True:
            if self.cancelled():
                raise Cancelled()
            if store.has_other_waiting_task(self.pid):
                self.log("Tạm nhường lượt cho tác vụ tương tác khác đang chờ…")
                break
            all_s = store.list_shorts(self.pid)
            queued = [s for s in all_s if s["status"] == "queued"]
            if not queued:
                break
            # short nối cảnh phải đợi short liền trước xong để lấy khung cuối của nó
            busy = {s["idx"] for s in all_s if s["status"] in ("queued", "running")}
            batch = [s for s in queued if not (s.get("cont") and s["idx"] - 1 in busy)][:BATCH]
            if not batch:
                batch = queued[:1]
            self.p = store.get_project(self.pid)
            assets = {a["name"].lower(): a for a in store.list_assets(self.pid)}
            sids = {}
            for s in batch:
                try:
                    prompt, atts = self.short_prompt(s, assets, self.prev_frame(s) if s.get("cont") else None)
                    sids[self.b.start_thread(prompt, atts)] = s
                    store.update_short(s["id"], status="running", error=None)
                    self.log(f"Đã gửi short #{s['idx']} ({fmt_t(s['start'])}–{fmt_t(s['end'])})")
                except Cancelled:  # bị huỷ khi đang tạo ảnh khung đầu
                    for x in [s, *sids.values()]:
                        store.update_short(x["id"], status="pending")
                    raise
                except Exception as e:
                    store.update_short(s["id"], status="failed", error=str(e)[:300])
                    self.log(f"Short #{s['idx']} lỗi khi gửi: {e}")
            if not sids:
                continue
            try:
                results = self.b.wait_threads(list(sids), self.timeout, self.log, self.cancelled, "tạo short")
            except Cancelled:
                for s in sids.values():
                    store.update_short(s["id"], status="pending")
                raise
            for sid, res in results.items():
                self.save_short(sids[sid], res)

    def shorts_single_chat(self):
        """Chế độ "1 chat cho cả MV": gửi lần lượt từng short vào cùng 1 chat Muse.
        Short bị Muse từ chối trong chat chung được thử lại 1 lần ở chat riêng, để lời từ chối
        không kéo các short sau trong chat chung theo."""
        while True:
            if self.cancelled():
                raise Cancelled()
            if store.has_other_waiting_task(self.pid):
                self.log("Tạm nhường lượt cho tác vụ tương tác khác đang chờ…")
                break
            s = next((s for s in store.list_shorts(self.pid) if s["status"] == "queued"), None)
            if not s:
                break
            self.p = store.get_project(self.pid)
            assets = {a["name"].lower(): a for a in store.list_assets(self.pid)}
            try:
                prompt, atts = self.short_prompt(s, assets, self.prev_frame(s) if s.get("cont") else None)
            except Cancelled:
                store.update_short(s["id"], status="pending")
                raise
            except Exception as e:
                store.update_short(s["id"], status="failed", error=str(e)[:300])
                continue
            store.update_short(s["id"], status="running", error=None)
            shared = self.p.get("chat_session")
            try:
                sid = self.b.start_thread(prompt, atts, shared)
            except RuntimeError:
                if not shared:
                    raise
                self.log("Không gửi được vào chat MV cũ — mở chat MV mới")
                sid = self.b.start_thread(prompt, atts)
            if sid != shared:
                store.update_project(self.pid, chat_session=sid)
            self.log(f"Đã gửi short #{s['idx']} ({fmt_t(s['start'])}–{fmt_t(s['end'])}) vào chat MV")
            try:
                res = self.b.wait_threads([sid], self.timeout, self.log, self.cancelled, "tạo short", last_turn=True)[sid]
                vid = any((f.get("mime") or "").startswith("video/") for f in res["files"])
                if not vid and is_refusal(res["text"]):
                    # Muse đã soạn sẵn bản an toàn hơn trong chính chat MV -> đồng ý luôn
                    out = self.accept_rework(s, res)
                    res, vid = (out, True) if out else (res, vid)
                if not vid and not is_service_error(res["text"]):
                    # chat MV đã có lời từ chối -> gửi lại y nguyên vào đó cũng bị từ chối tiếp;
                    # mở chat riêng và kèm luật an toàn để brief khác bản vừa bị từ chối
                    self.log(f"Short #{s['idx']}: Muse không trả video trong chat MV — thử lại ở chat riêng")
                    res = self.b.generate_new_thread(self.soften(prompt), self.timeout, self.log, self.cancelled,
                                                     atts=atts, label="tạo short")
            except Cancelled:
                store.update_short(s["id"], status="pending")
                raise
            self.save_short(s, res)

    def shorts_batch(self):
        """1 prompt -> 1 chat: gửi cả nhóm short (tối đa 6) trong MỘT tin nhắn, Muse tạo lần lượt từng short,
        short sau mở từ khung cuối của short trước (đã phân tích), mọi short khoá theo ảnh nhân vật/bối cảnh.
        Video trả về được gán theo thứ tự cho từng short; việc ghép thành clip cuối vẫn do bước Xuất đảm nhận."""
        import math as _math
        from mv import batch_prompt
        while True:
            if self.cancelled():
                raise Cancelled()
            if store.has_other_waiting_task(self.pid):
                self.log("Tạm nhường lượt cho tác vụ tương tác khác đang chờ…")
                break
            queued = sorted((s for s in store.list_shorts(self.pid) if s["status"] == "queued"),
                            key=lambda s: (s["script_id"] or 0, s["idx"]))
            if not queued:
                break
            group = [s for s in queued if s["script_id"] == queued[0]["script_id"]][:BATCH_SHORTS]
            # nhóm phải liền kề nhau theo idx: dừng ở chỗ đứt (short giữa đã lỗi) để không nhảy cóc kịch bản
            contiguous = [group[0]]
            for s in group[1:]:
                if s["idx"] == contiguous[-1]["idx"] + 1:
                    contiguous.append(s)
                else:
                    break
            group = contiguous
            first = group[0]
            if first["idx"] > 1:
                prev = next((x for x in store.list_shorts(self.pid, first["script_id"]) if x["idx"] == first["idx"] - 1), None)
                if not prev or prev["status"] != "done":
                    for later in queued:
                        store.update_short(later["id"], status="pending",
                                           error="Chờ short trước tạo xong để nối đúng khung hình cuối")
                    self.log(f"Tạm dừng từ short #{first['idx']}: short liền trước chưa có video thành công.")
                    break
            self.p = store.get_project(self.pid)
            assets = {a["name"].lower(): a for a in store.list_assets(self.pid)}
            items, ok = [], []
            for i, s in enumerate(group):
                try:
                    # chỉ short đầu của nhóm cần khung cuối thật từ short đã xong trước đó (nhóm sau / tạo lại)
                    link = i == 0 and first["idx"] > 1 and not (
                        self.p["kind"] == "scriptvideo" and not (s.get("characters") or []))
                    prompt, atts = self.short_prompt(s, assets, self.prev_frame(s) if link else None)
                except Cancelled:
                    for x in group:
                        store.update_short(x["id"], status="pending")
                    raise
                except Exception as e:
                    store.update_short(s["id"], status="failed", error=str(e)[:300])
                    continue
                items.append({"prompt": prompt, "atts": atts, "duration": max(MIN_CLIP_SEC, s["end"] - s["start"])})
                ok.append(s)
            if not ok:
                continue
            for s in ok:
                store.update_short(s["id"], status="running", error=None)
            max_sec = int(min(10, max(MIN_CLIP_SEC, float(self.p.get("max_short_sec") or 10))))
            master, atts, notes = batch_prompt.build_en(items, max_sec)
            for n in notes:
                self.log(n)
            self.log(f"Đã gửi 1 prompt gồm {len(ok)} short (#{ok[0]['idx']}–#{ok[-1]['idx']}) vào 1 chat Muse, "
                     f"{len(atts)} ảnh tham chiếu")
            try:
                res = self.b.generate_new_thread(master, self.timeout * max(1, _math.ceil(len(ok) / 2)), self.log,
                                                 self.cancelled, atts=atts, label="tạo các short")
            except Cancelled:
                for s in ok:
                    store.update_short(s["id"], status="pending")
                raise
            videos = [f for f in res["files"] if (f.get("mime") or "").startswith("video/")]
            self.log(f"Muse trả về {len(videos)}/{len(ok)} video")
            if not videos:
                # không có video nào: để save_short xử lý từ chối / hết lượt / lỗi máy chủ cho short đầu,
                # các short còn lại giữ hàng đợi (vòng lặp sau tự gửi lại)
                self.save_short(ok[0], res)
                for s in ok[1:]:
                    if store.get_short(s["id"])["status"] == "running":
                        store.update_short(s["id"], status="queued", error=None)
                continue
            for i, s in enumerate(ok):
                if i < len(videos):
                    self.save_short(s, {**res, "files": [videos[i]]})
                else:
                    n = (s.get("retries") or 0) + 1
                    if n <= SHORT_RETRY:
                        store.update_short(s["id"], status="queued", retries=n,
                                           error=f"Muse chưa trả đủ video — tự gửi lại ({n}/{SHORT_RETRY})")
                    else:
                        store.update_short(s["id"], status="failed", error="Muse không trả đủ video cho short này")

    def shorts_chain(self):
        """Chế độ "liền mạch": tạo lần lượt theo thứ tự kịch bản, mỗi short gửi kèm khung hình cuối của short liền trước
        để Muse quay tiếp từ đúng khung đó — người mẫu, bối cảnh, ánh sáng nối liền giữa các short."""
        while True:
            if self.cancelled():
                raise Cancelled()
            if store.has_other_waiting_task(self.pid):
                self.log("Tạm nhường lượt cho tác vụ tương tác khác đang chờ…")
                break
            queued = sorted((s for s in store.list_shorts(self.pid) if s["status"] == "queued"),
                            key=lambda s: (s["script_id"] or 0, s["idx"]))
            if not queued:
                break
            s = queued[0]
            self.p = store.get_project(self.pid)
            assets = {a["name"].lower(): a for a in store.list_assets(self.pid)}
            if self.p["kind"] in ("mv", "scriptvideo") and s["idx"] > 1:
                prev = next((x for x in store.list_shorts(self.pid) if x["idx"] == s["idx"] - 1), None)
                if not prev or prev["status"] != "done":
                    for later in queued:
                        store.update_short(later["id"], status="pending",
                                           error="Chờ short trước tạo xong để nối đúng khung hình cuối")
                    self.log(f"Tạm dừng từ short #{s['idx']}: short liền trước chưa có video thành công. "
                             "Các short sau đã để ở trạng thái chờ; tạo lại sau khi xử lý short lỗi.")
                    break
            store.update_short(s["id"], status="running", error=None)
            if self.p["kind"] == "remake":
                try:
                    if self.remake_keep_original(s):
                        continue
                except Exception as e:
                    store.update_short(s["id"], status="failed", error=str(e)[:300])
                    continue
            try:
                # MV và người mẫu OOTD (có cắt cảnh): chỉ nối khi cùng phân cảnh; người mẫu kiểu khác: luôn nối
                link = (self.p["kind"] == "model" and not ootd(self.p)) or s.get("cont")
                if self.p["kind"] == "scriptvideo" and not (s.get("characters") or []):
                    link = False  # montage không nhân vật: cảnh mới hoàn toàn, không nối khung cuối (khung đó có Eli nên Muse vẽ Eli vào)
                prompt, atts = self.short_prompt(s, assets, self.prev_frame(s) if link else None)
            except Cancelled:
                store.update_short(s["id"], status="pending")
                raise
            except Exception as e:
                store.update_short(s["id"], status="failed", error=str(e)[:300])
                continue
            self.log(f"Đã gửi short #{s['idx']} ({fmt_t(s['start'])}–{fmt_t(s['end'])})")
            try:
                res = self.b.generate_new_thread(prompt, self.timeout, self.log, self.cancelled, atts=atts, label="tạo short")
            except Cancelled:
                store.update_short(s["id"], status="pending")
                raise
            self.save_short(s, res)

    def prev_frame(self, s: dict) -> Path | None:
        """Khung hình cuối (đúng điểm cắt khi ghép) của short liền trước cùng kịch bản, lấy từ bản gốc chưa chỉnh màu."""
        prev = next((x for x in store.list_shorts(self.pid, s["script_id"]) if x["idx"] == s["idx"] - 1), None)
        if not prev or prev["status"] != "done" or not prev["video_path"]:
            return None
        v = Path(prev["video_path"])
        raw = v.with_name(v.stem + "_raw.mp4")
        v = raw if raw.exists() else v
        if not v.exists():
            return None
        t = max(0.0, min(prev["end"] - prev["start"], ffmpeg.probe(v)["duration"]) - 0.08)
        return ffmpeg.frame(v, t, self.dir / "tmp" / f"last{prev['id']}.jpg")

    def stickerman_short_prompt(self, s: dict, assets: dict, first_frame: Path | None = None) -> tuple[str, list[dict]]:
        p, dur = self.p, s["end"] - s["start"]
        req = max(MIN_CLIP_SEC, math.ceil(dur))
        lines, atts = [], []

        if first_frame:
            frame_name = "first_frame.jpg" if p["kind"] == "scriptvideo" else "khung_dau.jpg"
            atts.append(MuseBrowser.attachment(ffmpeg.small_jpeg(first_frame, first_frame.with_suffix(".s.jpg")), frame_name))

        chars = s.get("characters") or []
        if p["kind"] == "scriptvideo":
            # Luôn gửi ảnh khoá của nhân vật chính ở mọi short, kể cả khi Muse quên liệt kê nhân vật trong phân cảnh.
            main = next((a for a in assets.values() if a.get("kind") == "character" and a.get("locked")
                         and a.get("image_path") and Path(a["image_path"]).exists()), None)
            if main and chars and main["name"].lower() not in {str(n).lower() for n in chars}:  # montage không nhân vật thì không ép nhân vật chính vào
                chars = [main["name"], *chars]
        for name in chars:
            a = assets.get(str(name).lower())
            if a and (p["kind"] != "scriptvideo" or a.get("locked")) and a.get("image_path") and Path(a["image_path"]).exists():
                lines.append(self._ref(a, atts, f"char_{len(atts) + 1}.jpg", "Sticker character"))

        if not lines:
            main_chars = [a for a in assets.values() if a.get("kind") == "character" and a.get("image_path") and Path(a["image_path"]).exists()]
            if main_chars:
                a = main_chars[0]
                lines.append(self._ref(a, atts, f"char_{len(atts) + 1}.jpg", "Main character"))

        if p["kind"] == "scriptvideo":
            # Bắt buộc 2 loại ảnh tham chiếu: (1) ảnh thiết kế nhân vật đã khoá, (2) khung cuối short liền trước (từ short #2).
            if s["idx"] > 1 and not first_frame and (s.get("characters") or []):
                raise RuntimeError(f"Short #{s['idx']}: thiếu khung cuối của short trước — không gửi để tránh lệch nhân vật")
            if (s.get("characters") or []) and not any(str(a.get("filename", "")).startswith("char_") for a in atts):
                raise RuntimeError(f"Short #{s['idx']}: thiếu ảnh thiết kế nhân vật đã khoá — hãy khoá ảnh nhân vật chính")

        loc = assets.get(str(s.get("location") or "").lower())
        if loc and (not first_frame or p["kind"] == "scriptvideo") and loc.get("image_path") and Path(loc["image_path"]).exists():
            lines.append(self._ref(loc, atts, f"scene_{len(atts) + 1}.jpg", "Environment"))

        style_frame = None if first_frame else self.style_frame(s)
        if style_frame:
            atts.append(MuseBrowser.attachment(ffmpeg.small_jpeg(style_frame, style_frame.with_suffix(".s.jpg")), "style_ref.jpg"))

        spec = p.get("model_spec") or {}
        style_preset = spec.get("style_preset", "diecut")
        style_desc_en = {"stick2d": "2D stick figure cartoon with round black head, simple line body and recognizable clothing/accessories",
                         "toon2d": "polished 2D cartoon animation with expressive poses and consistent colors",
                         "toon3d": "stylized 3D cartoon animation with expressive shapes and soft cinematic lighting",
                         "clay3d": "stylized 3D clay cartoon animation with tactile surfaces"}.get(
                             style_preset, STICKER_STYLES_EN.get(style_preset, "2D cartoon animation"))

        action_en = to_en(s.get("description") or "").strip()
        lyric_en = to_en(s.get("lyric") or "").strip() if s.get("lyric") else ""

        text = [
            f"Generate a {req}-second cartoon animation video ({RATIO_EN.get(p['aspect'], p['aspect'])}).",
            f"Style: {style_desc_en}",
            f"Scene: {action_en}",
        ]

        if p["kind"] == "scriptvideo":
            text.append("PACING (IMPORTANT): slow, cinematic, contemplative pacing with emotional depth. Play the planned "
                        "beat at roughly 60% of normal action speed: unhurried character movement, held poses, lingering "
                        "reaction shots and small expressive details (breathing, eye movement, a pause before speaking). "
                        "Slow, smooth camera moves (gentle push-in, slow pan, steady holds) and long takes, never rapid "
                        "cuts or frantic motion. Show only the single main beat of this short and let it breathe; do not "
                        "rush through or cram extra events into the clip. Atmosphere (light, smoke, dust, ambient motion) "
                        "should add depth in the foreground and background.")

        if p["kind"] == "scriptvideo":
            text.append("ACTION RULE: every action a character performs must have a clear purpose and meaning in the story "
                        "(it shows an intention, emotion or consequence). No random, filler or decorative movements; "
                        "each gesture, glance and step must be motivated by what the character wants or feels in this beat.")

        if p["kind"] == "scriptvideo":
            text.append("AUDIO (REQUIRED): the video MUST have a soundtrack. Include natural ambient sound and sound effects that match "
                        "what happens on screen, plus a subtle emotional background score. If this beat has a spoken line, "
                        "voice it clearly in English with an expressive voice that matches the character and emotion, in sync with the animation. "
                        "Never output a silent video.")
            cues = sound_design(action_en)
            if cues:
                text.append("SOUND DESIGN for this beat (make these sounds clearly audible, with weight and punch, not just a faint background): " + cues
                            + ". Mix them so the sound effects and ambience are rich and cinematic, and any spoken line stays clearly intelligible on top.")

        if first_frame:
            text.append("Seamless continuation: Start precisely from the pose, framing, and camera angle of attached "
                        + ("first_frame.jpg." if p["kind"] == "scriptvideo" else "khung_dau.jpg."))
            if p["kind"] == "scriptvideo":
                text.append(self.continuity(s))

        if lines:
            text.append("Character consistency (MANDATORY):\n"
                        + "\n".join(lines) + "\n"
                        + ("- Strictly match the attached character sheet's silhouette, round black head, clothes, colors and accessories.\n" if p["kind"] == "scriptvideo" else "- Strictly match the attached character sheet reference: 2D stickman design, white outline, clothing colors, and exaggerated meme facial expressions.\n")
                        + ("- The attached locked character reference is mandatory in every short. Preserve the protagonist's round black head, stick-figure body, exact outfit and signature accessories; use the sheet only as a design reference, never reproduce its contact-sheet grid.\n" if p["kind"] == "scriptvideo" else "")
                        + ("- Do not turn into a realistic human, do not change outfits or body proportions." if p["kind"] == "scriptvideo" else "- Do not change outfits or body proportions."))

        if p["kind"] == "scriptvideo" and not (s.get("characters") or []):
            text.append("NO NAMED CHARACTER IN THIS SHOT: do NOT draw Eli, Noah, R-17 or any named main character, and do not reuse "
                        "a character from first_frame.jpg. Show only the described place, machines, screens and anonymous background "
                        "people or robots in the same flat 2D cartoon style, so the viewer sees what is happening in the world.")

        if p["kind"] == "scriptvideo":
            text.append(
                "DESIGN LOCK (HIGHEST PRIORITY, overrides first_frame.jpg wherever they disagree): the attached character "
                "sheets are the ONLY source of truth for how characters look. The previous frame may have drifted; silently "
                "correct it back to the sheets from the first second.\n"
                "- Human characters (Eli, Noah and the others): the head is a perfectly round, flat, solid pure-black circle. "
                "NO skin colour, NO brown or tan face, NO hair, NO nose, NO ears, NO eyebrows, NO shading on the head. Only two "
                "large round cream-white eyes with small black pupils and (at most) a tiny simple mouth line. Body is a simple "
                "cartoon stick-figure body with thin black limbs, not a realistic or anatomical human.\n"
                "- Do NOT add any item that is not on the sheet: no ID badge, no lanyard, no logos, no extra straps or accessories.\n"
                "- R-17 (robot): a round solid-black head with two large glowing blue eyes, slim body with flat matte grey "
                "armour plates and thin black limbs, in the same flat cartoon style as the sheet. NEVER a realistic chrome or "
                "metallic robot, NEVER a helmet, visor or mask, NEVER a 3D-rendered look.\n"
                "- Render everything in the same clean flat 2D cartoon style as the sheets: bold dark outlines, flat cel colours "
                "with minimal soft shading, simple readable shapes. Backgrounds follow the attached location art in the same flat "
                "style, not painterly, not photographic, not anime-detailed.")

        if style_frame:
            text.append("Match the art style, line thickness, and color palette of attached style_ref.jpg.")

        if lyric_en:
            text.append(f"Dialogue / Speech context: \"{lyric_en}\" (character expressive body language matching speech).")

        if s.get("feedback"):
            fb_en = to_en(s["feedback"]).strip()
            text.append(f"Revision note: {fb_en}")

        if p["kind"] == "scriptvideo":
            # Mỗi lần gửi là 1 yêu cầu mới: tránh Muse trả lại đúng video cũ của prompt tương tự (short tạo lại bị y hệt bản lệch).
            import uuid
            text.append(f"Fresh generation request id: {uuid.uuid4().hex[:10]}. Generate a NEW video now; never reuse or return any earlier output.")

        text.append(f"\n{NO_ASK_EN} Output only 1 video file.")
        return "\n".join(text), atts

    def short_prompt(self, s: dict, assets: dict, first_frame: Path | None = None) -> tuple[str, list[dict]]:
        """Prompt cho 1 short; lần gửi lại thì nhắc Muse đừng hỏi lại, phải xuất đúng 1 file video."""
        prompt, atts = self._short_prompt(s, assets, first_frame)
        if s.get("retries"):
            # Lần gửi lại phải KHÁC brief cũ: Muse nhận ra brief đã bị từ chối và từ chối tiếp.
            prompt = self.soften(prompt)
        return prompt, atts

    def _short_prompt(self, s: dict, assets: dict, first_frame: Path | None = None) -> tuple[str, list[dict]]:
        p, dur = self.p, s["end"] - s["start"]
        lines, atts = [], []
        sc = store.get_script(s["script_id"]) if s.get("script_id") else None
        if sc and sc.get("model_id"):
            m, l = store.get_asset(sc["model_id"]), store.get_asset(sc.get("location_id") or 0)
            if not m:
                raise RuntimeError("Người mẫu của kịch bản này đã bị xoá")
            assets = {m["name"].lower(): m, **({l["name"].lower(): l} if l else {})}
            s = {**s, "characters": [m["name"]], "location": l["name"] if l else ""}
        if p["kind"] == "remake":
            return self.remake_short_prompt(s, assets, first_frame)
        if p["kind"] == "model":
            m = next((assets[n.lower()] for n in s["characters"] or [] if n.lower() in assets), None)
            return self.model_short_prompt(s, m, assets.get((s["location"] or "").lower()), first_frame)
        if p["kind"] in ("stickerman", "scriptvideo"):
            return self.stickerman_short_prompt(s, assets, first_frame)
        if first_frame:
            atts.append(MuseBrowser.attachment(ffmpeg.small_jpeg(first_frame, first_frame.with_suffix(".s.jpg")), "first_frame.jpg"))
        for name in s["characters"] or []:
            a = assets.get(name.lower())
            if a:
                lines.append(self._ref(a, atts, f"character_{len(atts) + 1}.jpg", "Character"))
        loc = assets.get((s["location"] or "").lower())
        if loc and (not first_frame or p["kind"] == "mv"):  # MV: có thể cần bối cảnh đích mới, khung cuối chỉ neo trạng thái mở cảnh
            lines.append(self._ref(loc, atts, f"location_{len(atts) + 1}.jpg", "Location"))
        style_frame = None if first_frame else self.style_frame(s)
        if style_frame:  # khung hình short đã xong: giữ cùng nét vẽ/chất lượng 2D giữa các short
            atts.append(MuseBrowser.attachment(ffmpeg.small_jpeg(style_frame, style_frame.with_suffix(".s.jpg")), "style_ref.jpg"))
        # Muse từ chối clip quá ngắn / lẻ giây (đã gặp với 3.2s): xin số giây chẵn, tối thiểu 5; khi ghép tool tự cắt đúng độ dài
        req = max(MIN_CLIP_SEC, math.ceil(dur))
        ratio = RATIO_EN.get(p.get("aspect"), "16:9 widescreen")
        desc_en = to_en(s.get("description") or "").strip().rstrip(".")
        style_en = to_en(p.get("style") or "2D animation").strip().rstrip(".")
        kind_en = video_kind(p)
        text = [
            f"Generate a {req}-second {kind_en} video ({ratio}).",
            f"Art style: {style_en}.",
            f"Scene action: {desc_en}."
        ]
        if kind_en == "live-action cinematic":
            text.append("Photorealistic live-action footage with real actors — real skin texture, real hair, real fabric, "
                        "natural lighting, shallow depth of field, subtle film grain. "
                        "Absolutely not a cartoon, not anime, not 2D/3D animation, not an illustration.")
        if first_frame:
            text.append(self.continuity(s))
        if lines:
            text.append(
                "CHARACTER LOCK (MANDATORY) — the attached reference images are the ONLY valid design:\n"
                + "\n".join(lines) + "\n"
                "- Match every character to the attached reference sheet: preserve face design, hairstyle, skin tone, "
                "body build and height. Let the scene's camera angle determine how much of the face is visible.\n"
                "- The character sheet contains multiple views and expressions of one identity. Use it only as a design guide; "
                "never reproduce its grid or panels in the video. Select the view/expression appropriate to the planned shot while keeping identity fixed.\n"
                "- Same outfit, same colours, same shirt number. Do NOT redesign, restyle, beautify, age up or age down, "
                "and do NOT replace them with a different-looking person.\n"
                "- Keep the exact same art style and line work as the reference sheet.\n"
                "- Any location_*.jpg is an EMPTY background plate: it deliberately contains no people. "
                "Use it ONLY for architecture, materials, colour palette and lighting. "
                "Do NOT output it unchanged and do NOT copy its emptiness — the characters above must be placed into it.")
        if style_frame:
            text.append("Match the look and color grade of attached style_ref.jpg."
                        if kind_en == "live-action cinematic" else
                        "Match the art style, line thickness, and color palette of attached style_ref.jpg.")
        if lines and any(l.startswith("- character_") or 'Character "' in l for l in lines):
            who = ", ".join(s["characters"] or []) or "the main character"
            text.append(f"SUBJECT PRESENCE: show {who} clearly in the scene and keep the character's outfit and "
                        "silhouette readable. Follow the requested camera angle; do not force a face close-up. "
                        "An empty environment with no people is a failed result.")
        text.append("No captions, subtitles, watermarks, or readable signs/posters. Preserve the shirt number "
                    "visible in the supplied character reference; do not add other text. No voiceover.")
        if s.get("lipsync") and s.get("lyric_mode") == "plain":
            who = (s["characters"] or ["main character"])[0]
            text.append(f"Lip-sync: {who} is singing passionately, clear facial view, mouth movements synchronized.")
        elif s.get("lipsync"):
            who = (s["characters"] or ["main character"])[0]
            timed = [f"  {max(0, l['start'] - s['start']):.1f}s–{min(dur, l['end'] - s['start']):.1f}s: \"{l['text']}\""
                     for l in p.get("lyrics") or [] if l["text"] and l["end"] > s["start"] and l["start"] < s["end"]]
            text.append(f"Lip-sync: {who} sings with clear lip articulation matching lyrics timing:\n"
                        + ("\n".join(timed) or f"  \"{s['lyric']}\""))
        else:
            text.append("No lip-syncing required.")
        if s.get("feedback"):
            fb_en = to_en(s["feedback"]).strip()
            text.append(f"Revision note: {fb_en}")
        text.append(f"\n{NO_ASK_EN} Output only 1 video file.")
        return "\n".join(text), atts

    def style_frame(self, s: dict) -> Path | None:
        """Khung giữa của short đã xong đầu tiên trong MV (khác short đang tạo) — mẫu phong cách 2D chung cho mọi short."""
        ok = [x for x in store.list_shorts(self.pid) if x["status"] == "done" and x["id"] != s["id"]
              and x.get("thumb_path") and Path(x["thumb_path"]).exists()]
        # Khung mẫu PHẢI có người: lấy khung phong cảnh trống làm style_ref khiến Muse vẽ tiếp cảnh trống, mất nhân vật.
        done = next((x for x in ok if x.get("characters")), None) or next(iter(ok), None)
        return Path(done["thumb_path"]) if done else None

    def continuity(self, s: dict) -> str:
        """Short nối tiếp cùng phân cảnh: quay tiếp đúng từ khung cuối short trước như 1 cú máy không cắt."""
        prev = next((x for x in store.list_shorts(self.pid, s.get("script_id")) if x["idx"] == s["idx"] - 1), None)
        desc_en = to_en(prev.get("description") or "").strip() if prev else ""
        next_en = to_en(s.get("description") or "").strip()
        return ("CONTINUITY REFERENCE: attached first_frame.jpg is the actual final frame of the immediately previous short. "
                "Read it as the authoritative opening state: preserve exact character identity, pose, facial expression, "
                "screen position, important props and lighting. Begin from that frame without resetting the action. "
                + (f"Previous beat: {desc_en}. " if desc_en else "")
                + (f"Now advance the story into this next planned beat: {next_en}. " if next_en else "")
                + "Use the attached character sheet for the same identity and the location reference for the intended setting. "
                "If the planned beat changes place or time, begin with a motivated visual bridge (match cut, carried prop, movement or lighting transition) from the reference state, then establish the new setting. "
                "Infer only the physical details needed to connect the frame to the planned action. Keep lyric timing, emotional arc and cause-and-effect consistent; do not repeat the previous beat, invent a conflicting event, or change identity.")

    def model_short_prompt(self, s: dict, m: dict | None, loc: dict | None,
                           first_frame: Path | None) -> tuple[str, list[dict]]:
        """Short người mẫu: chỉ gửi 2 ảnh — khung hình bắt đầu + ảnh người mẫu chuẩn. Gửi nhiều ảnh (bối cảnh, ảnh màu…)
        cùng mô tả "gương mặt đẹp" làm Muse tự vẽ khuôn mặt mới; màu được khớp theo video mẫu ở bước hậu kỳ."""
        p, dur = self.p, s["end"] - s["start"]
        req = max(MIN_CLIP_SEC, math.ceil(dur))
        chained = first_frame is not None
        if not chained:
            first_frame = self.keyframe(s, m, loc)
        atts = [MuseBrowser.attachment(ffmpeg.small_jpeg(first_frame, first_frame.with_suffix(".s.jpg")), "khung_dau.jpg")]
        desc_en = to_en(s['description'])
        text = [
            f"Generate a {req}-second realistic video clip ({RATIO_EN.get(p['aspect'], p['aspect'])}) from attached khung_dau.jpg (image-to-video).",
            "Video must seamlessly start from the exact pose, outfit, model identity, environment, and lighting shown in khung_dau.jpg.",
            f"Scene action: {desc_en}",
        ]
        if m and m.get("image_path") and Path(m["image_path"]).exists():
            ref = ffmpeg.small_jpeg(Path(m["image_path"]), self.dir / "tmp" / f"ref{m['id']}.jpg", 768)
            atts.append(MuseBrowser.attachment(ref, "model_ref.jpg"))
            text.append("Model consistency: Keep 100% face identity, hairstyle, and body shape of attached model_ref.jpg.")
        text += ["No text, no watermarks, no speech.",
                 "Photorealistic cinematography, natural motion, sharp camera work."]
        if s["feedback"]:
            text.append(f"Revision note: {to_en(s['feedback'])}")
        text.append(f"\n{NO_ASK_EN} Output only 1 video file.")
        return "\n".join(text), atts

    def keyframe(self, s: dict, m: dict | None, loc: dict | None) -> Path:
        """Ảnh khung hình đầu cho short không nối từ short trước: Muse ghép đúng người mẫu vào đúng bối cảnh bằng ảnh tham chiếu
        (Muse giữ khuôn mặt tốt hơn nhiều khi tạo ảnh), rồi video được tạo từ ảnh này."""
        atts, refs = [], []
        for a, fname, label in ((m, "nguoi_mau.jpg", "người mẫu"), (loc, "boi_canh.jpg", "bối cảnh")):
            if a and a.get("image_path") and Path(a["image_path"]).exists():
                atts.append(MuseBrowser.attachment(
                    ffmpeg.small_jpeg(Path(a["image_path"]), self.dir / "tmp" / f"ref{a['id']}.jpg", 1024), fname))
                refs.append(f"- {fname}: {label} \"{a['name']}\"")
            elif a:
                refs.append(f"- {label} \"{a['name']}\": {a.get('description') or ''}")
        face = (self.p.get("model_spec") or {}).get("beauty_ref") if face_copy(self.p) else None
        if face and Path(face).exists():
            atts.append(MuseBrowser.attachment(ffmpeg.small_jpeg(Path(face), self.dir / "tmp" / "face.jpg", 1024), "guong_mat.jpg"))
            refs.append("- guong_mat.jpg: ảnh thật gương mặt người mẫu — nét mặt phải giống 100% ảnh này "
                        "(khuôn mặt, mắt, mũi, môi, cằm, màu da); trang phục và tóc lấy theo nguoi_mau.jpg")
        prompt = "\n".join([
            f"Tạo 1 ảnh · tỷ lệ {RATIO.get(self.p['aspect'], self.p['aspect'])}",
            "Ảnh chụp thật: đặt ĐÚNG người mẫu trong ảnh tham chiếu vào ĐÚNG bối cảnh trong ảnh tham chiếu.",
            *refs,
            f"Tư thế ở đầu cảnh: {s['description']}",
            ("Vị trí trong bối cảnh và góc máy theo đúng mô tả cảnh (có thể là 1 góc khác của cùng địa điểm trong boi_canh.jpg, "
             "giữ đúng kiến trúc, mặt đường, màu sắc, ánh sáng của địa điểm đó)." if ootd(self.p) else ""),
            IDENTITY.format(f="nguoi_mau.jpg") if m and m.get("image_path") else "",
            "Bối cảnh giữ đúng như ảnh boi_canh.jpg." if loc and loc.get("image_path") else "",
            PHONE_STILL if ootd(self.p) else REAL_LOOK,
            "Không logo thương hiệu, không chữ.", f"\n{NO_ASK} Chỉ trả về đúng 1 file ảnh."])
        self.log(f"Short #{s['idx']}: tạo ảnh khung đầu (người mẫu + bối cảnh)")
        res = self.ask(prompt, atts, "tạo khung đầu")
        img = next((f for f in res["files"] if (f.get("mime") or "").startswith("image/")), None)
        if not img:
            raise RuntimeError(f"Muse không tạo được ảnh khung đầu: {(res.get('text') or '')[:200]}")
        dest = self.dir / "tmp" / f"key{s['id']}_{int(time.time())}.{img['mime'].split('/')[1].replace('jpeg', 'jpg')}"
        self.b.download_runtime_file(img, dest)
        return dest

    def ref_text(self) -> str:
        """Phần phân tích video mẫu / mô tả phong cách đưa vào prompt (rỗng nếu không có)."""
        a = (self.p.get("analysis") or "").strip()
        if not a:
            return ""
        return ("PHÂN TÍCH VIDEO MẪU:\n" if self.p.get("ref_video_path") else "MÔ TẢ PHONG CÁCH MONG MUỐN:\n") + a

    # ---------- video hướng dẫn tạo dáng ----------

    def do_pose_list(self, count: int = 5, notes: str = "", source: str = "muse"):
        """Danh sách pose: dòng 0 là dáng sai mở đầu, sau đó `count` pose đẹp. source="bank": bốc từ thư viện, không cần Muse."""
        count = max(2, min(8, int(count)))
        model, loc = store.get_asset(self.p.get("sel_model") or 0), store.get_asset(self.p.get("sel_location") or 0)
        if source == "bank":
            picks = random.sample(POSE_AD_BANK, min(count, len(POSE_AD_BANK)))
            poses = [{"name": x.split(",")[0][:40], "description": x} for x in picks]
        else:
            prompt = f"""Tôi làm video quảng cáo app gợi ý tạo dáng chụp ảnh: mở đầu là 1 ảnh tạo dáng sai, sau đó app gợi ý {count} pose và mỗi pose ra 1 ảnh đẹp.
Hãy đề xuất {count} pose THẬT ĐẸP, gợi cảm và cuốn hút như người mẫu tạp chí/Instagram triệu follower nhưng người thường vẫn làm theo được, KHÁC HẲN nhau về dạng (đứng chữ S, ngồi, ngồi xổm, tựa tường/cột/lan can, bước đi, xoay lưng ngoái lại, nằm nghiêng/ngả người, dùng phụ kiện hoặc đồ vật trong bối cảnh…), khoe đường nét cơ thể và trang phục, hợp giới tính, người mẫu và bối cảnh dưới đây. Không lặp lại dạng pose giữa các pose.
{f"Ghi chú: {notes}" if notes else ""}
NGƯỜI MẪU: {model['name'] + ' — ' + (model['description'] or '') if model else 'chưa chọn'}
BỐI CẢNH: {loc['name'] + ' — ' + (loc['description'] or '') if loc else 'chưa chọn'}
Gợi ý tham khảo (có thể dùng hoặc sáng tạo khác): {"; ".join(POSE_AD_BANK)}
Mỗi pose mô tả rõ tay, chân, thân, hướng đầu, ánh mắt, biểu cảm, vị trí trong bối cảnh.
Chỉ trả về DUY NHẤT 1 khối JSON: {{"poses": [{{"name": "tên ngắn", "description": "..."}}]}}
{NO_ASK}"""
            data = parse_json(self.ask(prompt, label="đề xuất pose").get("text"))
            poses = [x for x in (data.get("poses") if isinstance(data, dict) else data) or [] if x.get("description")][:count]
            if not poses:
                raise RuntimeError("Muse không trả về pose nào")
        store.set_poses(self.pid, [{"name": "Dáng sai", "description": POSE_WRONG}] + poses)
        self.log(f"Xong: {len(poses)} pose + 1 dáng sai mở đầu")

    def pose_photo_prompt(self, s: dict, feedback: str = "") -> tuple[str, list[dict]]:
        model, loc = store.get_asset(self.p.get("sel_model") or 0), store.get_asset(self.p.get("sel_location") or 0)
        if not model or not model.get("image_path") or not loc or not loc.get("image_path"):
            raise RuntimeError("Chọn người mẫu và bối cảnh (đã có ảnh) ở bước 2 trước")
        atts = [MuseBrowser.attachment(ffmpeg.small_jpeg(Path(a["image_path"]), self.dir / "tmp" / f"ref{a['id']}.jpg", 1024), f)
                for a, f in ((model, "nguoi_mau.jpg"), (loc, "boi_canh.jpg"))]
        text = ["Tạo 1 ảnh · tỷ lệ 9:16 (dọc)",
                "Đặt ĐÚNG người mẫu trong nguoi_mau.jpg vào ĐÚNG bối cảnh boi_canh.jpg (có thể là góc khác của cùng địa điểm, "
                "giữ đúng kiến trúc, mặt nền, màu sắc).",
                IDENTITY.format(f="nguoi_mau.jpg")]
        face = (self.p.get("model_spec") or {}).get("beauty_ref") if face_copy(self.p) else None
        if face and Path(face).exists():
            atts.append(MuseBrowser.attachment(ffmpeg.small_jpeg(Path(face), self.dir / "tmp" / "face.jpg", 1024), "guong_mat.jpg"))
            text.append("Ảnh guong_mat.jpg là ảnh thật gương mặt người mẫu — nét mặt phải giống 100% ảnh này.")
        if s["idx"] == 0:
            text += [s["description"] or POSE_WRONG, "Ảnh chụp thật bằng điện thoại, trông bình thường, không nghệ thuật. "
                     "Không chữ, không logo, không người khác."]
        else:
            text += [f"TƯ THẾ: {s['description']}", POSE_SHOT_LOOK, ANTI_AI]
        if feedback:
            text.append(f"Bản trước chưa đạt, lần này sửa: {feedback}")
            if s.get("thumb_path") and Path(s["thumb_path"]).exists():
                atts.append(MuseBrowser.attachment(ffmpeg.small_jpeg(Path(s["thumb_path"]), self.dir / "tmp" / f"pose{s['id']}_old.jpg"), "ban_truoc.jpg"))
                text.append("Ảnh ban_truoc.jpg là bản trước — giữ những gì không được yêu cầu sửa.")
        text.append(f"\n{NO_ASK} Chỉ trả về đúng 1 file ảnh.")
        return "\n".join(text), atts

    def save_pose_photo(self, s: dict, res: dict) -> None:
        img = next((f for f in res["files"] if (f.get("mime") or "").startswith("image/")), None)
        if not img:
            raise RuntimeError(f"Muse không trả về ảnh: {(res.get('text') or '')[:150]}")
        dest = self.dir / "shorts" / f"pose{s['id']}_{int(time.time())}.{img['mime'].split('/')[1].replace('jpeg', 'jpg')}"
        self.b.download_runtime_file(img, dest)
        store.update_short(s["id"], thumb_path=str(dest), status="done", error="", feedback="")
        self.log(f"Đã có ảnh: {s['lyric'] or s['idx']}")

    def do_pose_images(self, redo: bool = False):
        """Vẽ ảnh mọi pose chưa có ảnh (redo=True: vẽ lại tất cả), gửi Muse BATCH ảnh cùng lúc."""
        todo = [s for s in store.list_shorts(self.pid) if redo or not s.get("thumb_path") or s["status"] == "queued"]
        if not todo:
            raise RuntimeError("Mọi pose đã có ảnh")
        self.log(f"Vẽ {len(todo)} ảnh pose, {BATCH} ảnh cùng lúc")
        failed = []
        for i in range(0, len(todo), BATCH):
            if self.cancelled():
                raise Cancelled()
            sids = {}
            for s in todo[i:i + BATCH]:
                store.update_short(s["id"], status="running")
                prompt, atts = self.pose_photo_prompt(s, s.get("feedback") or "")
                sids[self.b.start_thread(prompt, atts)] = s
            for sid, res in self.b.wait_threads(list(sids), self.timeout, self.log, self.cancelled, "vẽ pose").items():
                s = sids[sid]
                try:
                    self.save_pose_photo(s, res)
                except Exception as e:
                    failed.append(s["lyric"] or str(s["idx"]))
                    store.update_short(s["id"], status="error", error=str(e)[:300])
                    self.log(f"{s['lyric']}: {e}")
        if failed:
            raise RuntimeError(f"Chưa vẽ được: {', '.join(failed)} — bấm vẽ lại từng ảnh")

    def do_pose_image(self, short_id: int, feedback: str = ""):
        s = store.get_short(short_id)
        if not s:
            raise RuntimeError("Pose này đã bị xoá")
        store.update_short(short_id, status="running")
        try:
            prompt, atts = self.pose_photo_prompt(s, feedback)
            self.save_pose_photo(s, self.ask(prompt, atts, "vẽ pose"))
        except Exception as e:
            store.update_short(short_id, status="error", error=str(e)[:300])
            raise

    def pose_live_prompt(self, s: dict, wrong: dict, feedback: str = "") -> tuple[str, list[dict]]:
        """Video "màn hình camera": bắt đầu từ ảnh dáng sai, người mẫu chuyển dần vào pose (giống ảnh pose) rồi giữ dáng."""
        atts = [MuseBrowser.attachment(ffmpeg.small_jpeg(Path(wrong["thumb_path"]), self.dir / "tmp" / "live_start.jpg", 1024), "khung_dau.jpg"),
                MuseBrowser.attachment(ffmpeg.small_jpeg(Path(s["thumb_path"]), self.dir / "tmp" / f"live_pose{s['id']}.jpg", 768), "tu_the.jpg")]
        text = [f"Tạo 1 video dài {MIN_CLIP_SEC} giây · tỷ lệ 9:16 (dọc) từ ảnh khung_dau.jpg (image-to-video).",
                "Ảnh khung_dau.jpg là khung hình ĐẦU TIÊN: video bắt đầu đúng từ ảnh này (cùng người, trang phục, bối cảnh, góc máy, ánh sáng).",
                "Đây là hình trên màn hình camera điện thoại của người đang chụp ảnh cho người mẫu. Lúc đầu người mẫu đứng đơ như ảnh, "
                f"rồi trong khoảng 2–2,5 giây đầu tự nhiên chuyển sang tạo dáng: {s['description']}. Tư thế cuối phải GIỐNG ảnh tu_the.jpg "
                "(tay, chân, thân, hướng đầu, ánh mắt, biểu cảm) — chỉ lấy tư thế, giữ nguyên góc máy, khoảng cách, ánh sáng và bối cảnh "
                "của khung_dau.jpg. Nếu pose cần bậc thềm/lan can/cột thì người mẫu bước 1–2 bước tới chỗ gần nhất. Sau đó GIỮ pose như "
                "đang chờ bấm máy: chỉ thở, chớp mắt, mỉm cười, tóc và vải bay nhẹ.",
                "Máy quay: điện thoại cầm tay của người chụp đứng yên một chỗ, rung tay nhẹ tự nhiên, giữ người mẫu ở giữa khung, toàn thân.",
                IDENTITY.format(f="khung_dau.jpg"), REAL_MOTION,
                "Không chữ, không logo, không giao diện app, không thoại."]
        if feedback:
            text.append(f"Bản trước chưa đạt, lần này sửa: {feedback}")
        text.append(f"\n{NO_ASK} Chỉ trả về đúng 1 file video.")
        return "\n".join(text), atts

    def save_pose_live(self, s: dict, res: dict) -> None:
        vid = next((f for f in res["files"] if (f.get("mime") or "").startswith("video/")), None)
        if not vid:
            raise RuntimeError(("Muse đang lỗi máy chủ" if is_service_error(res["text"]) else "Muse không trả về video")
                               + f": {(res.get('text') or '')[:150]}")
        dest = self.dir / "shorts" / f"live{s['id']}_{int(time.time())}.mp4"
        self.b.download_runtime_file(vid, dest)
        store.update_short(s["id"], video_path=str(dest), version=s["version"] + 1, error="")
        self.log(f"Đã có video: {s['lyric'] or s['idx']}")

    def do_pose_videos(self, redo: bool = False, short_id: int | None = None, feedback: str = ""):
        """Muse tạo video "màn hình camera" cho từng pose (người mẫu chuyển từ dáng đứng đơ vào pose), BATCH video cùng lúc."""
        rows = store.list_shorts(self.pid)
        wrong = rows[0] if rows else None
        if not wrong or not wrong.get("thumb_path"):
            raise RuntimeError("Chưa có ảnh dáng sai")
        todo = [s for s in rows[1:] if s.get("thumb_path") and (s["id"] == short_id if short_id else
                                                                 redo or not s.get("video_path"))]
        if not todo:
            raise RuntimeError("Không có pose nào cần tạo video (pose phải có ảnh trước)")
        self.log(f"Tạo {len(todo)} video pose, {BATCH} video cùng lúc")
        failed = []
        for i in range(0, len(todo), BATCH):
            if self.cancelled():
                raise Cancelled()
            sids = {}
            for s in todo[i:i + BATCH]:
                prompt, atts = self.pose_live_prompt(s, wrong, feedback)
                sids[self.b.start_thread(prompt, atts)] = s
            for sid, res in self.b.wait_threads(list(sids), self.timeout, self.log, self.cancelled, "tạo video pose").items():
                s = sids[sid]
                try:
                    self.save_pose_live(s, res)
                except Exception as e:
                    failed.append(s["lyric"] or str(s["idx"]))
                    store.update_short(s["id"], error=str(e)[:300])
                    self.log(f"{s['lyric']}: {e}")
        if failed:
            raise RuntimeError(f"Chưa tạo được video: {', '.join(failed)} — bấm tạo lại từng video")

    def do_pose_render(self, brand: str = "", music: str = "", style: str = "classic"):
        """Dựng video quảng cáo trên máy (không cần Muse) — xem post/pose_ad.py. style "ai": mở bằng bấm nút Pose AI
        tạo pose + mỗi pose 1 kiểu hiển thị (viền / ảnh góc trên / pose tách nền cạnh người mẫu)."""
        from post import pose_ad
        rows = store.list_shorts(self.pid)
        if len(rows) < 2 or not all(s.get("thumb_path") and Path(s["thumb_path"]).exists() for s in rows):
            raise RuntimeError("Còn pose chưa có ảnh")
        out = ROOT / "output" / "merged" / f"pose{self.pid}_{time.strftime('%Y%m%d_%H%M%S')}.mp4"
        loc = store.get_asset(self.p.get("sel_location") or 0)
        lives = [Path(s["video_path"]) if s.get("video_path") and Path(s["video_path"]).exists() else None for s in rows[1:]]
        pose_ad.render(Path(rows[0]["thumb_path"]), [Path(s["thumb_path"]) for s in rows[1:]], out,
                       self.dir / "tmp" / "pose_ad", music=Path(music) if music else None, log=self.log, lives=lives,
                       bg=Path(loc["image_path"]) if loc and loc.get("image_path") else None,
                       style=style, overlay_shift=self.pid % 3)
        store.update_project(self.pid, exported_path=str(out))
        from jobs import store as jobstore
        thumb = ffmpeg.thumbnail(out, out.parent.parent / "thumbs" / (out.stem + ".jpg"))
        jobstore.add_video(None, str(out), ffmpeg.probe(out), kind="merged", thumb=str(thumb) if thumb else None)
        self.log(f"Xong video: {out.name}")

    def color_ref(self) -> Path | None:
        """1 khung hình thật từ video mẫu: chuẩn màu sắc/ánh sáng (và khuôn mặt khi dùng người mẫu trong video)."""
        if not self.p.get("ref_video_path") or not Path(self.p["ref_video_path"]).exists():
            return None
        f = self.dir / "tmp" / "face_real.jpg"
        if not f.exists():
            ffmpeg.frame(Path(self.p["ref_video_path"]), (self.p["duration"] or 2) * 0.2, f)
        return ffmpeg.small_jpeg(f, f.with_suffix(".s.jpg"), 768)

    def match_color(self, src: Path, out: Path) -> Path:
        """Khớp màu ảnh/clip `src` theo video mẫu (LUT 3D) + hạt nhẹ; lỗi thì giữ nguyên bản gốc."""
        if not self.p.get("ref_video_path"):
            return src
        try:
            lut = color.match_lut(src, Path(self.p["ref_video_path"]), self.dir / "tmp" / f"{src.stem}.cube")
            return ffmpeg.apply_lut(src, lut, out)
        except Exception as e:
            self.log(f"Không khớp màu được ({e}) — giữ màu gốc")
            return src

    def _ref(self, a: dict, atts: list, fname: str, label: str) -> str:
        desc_en = to_en(a.get('description') or '').strip()
        label_en = "Character" if "nhân vật" in label.lower() or "character" in label.lower() else ("Location" if "bối cảnh" in label.lower() or "location" in label.lower() or "scene" in label.lower() else label)
        if a.get("image_path") and Path(a["image_path"]).exists():
            # Ưu tiên sprite sheet (toàn thân + mặt phóng to + bảng màu). Ảnh mẫu cũ chỉ có 1 tư thế
            # chính diện lại bị ép còn 768px nên mặt chỉ ~120px — không đủ chi tiết để Muse chép,
            # đó là lý do nhân vật lệch ở các cảnh nhìn nghiêng, quỳ, hoặc cận mặt.
            sheet = Path(a["image_path"]).parent / f"sheet{a['id']}.jpg"
            src = sheet if sheet.exists() else Path(a["image_path"])
            ref = ffmpeg.small_jpeg(src, self.dir / "tmp" / f"ref{a['id']}.jpg", 1280)
            atts.append(MuseBrowser.attachment(ref, fname))
            extra = (" This is a model sheet: full body on the left, large face close-up on the right, "
                     "and the exact colour swatches below it. Copy the face shape, hairstyle, skin tone "
                     "and outfit colours from it exactly." if sheet.exists() else "")
            return f"- {fname}: {label_en} \"{a['name']}\" ({desc_en}).{extra}"
        return f"- {label_en} \"{a['name']}\": {desc_en}"

    def soften(self, prompt: str) -> str:
        """Thêm luật tránh bị từ chối, để brief gửi lại khác bản Muse vừa từ chối."""
        return (prompt + "\n\n" + SAFE_RULES +
                "\n\nDo not ask any question, do not reply with text only, do not propose an alternative — "
                "apply the safety rework above yourself and output exactly 1 video file now.")

    def accept_rework(self, s: dict, res: dict) -> dict | None:
        """Muse từ chối và tự đề xuất bản an toàn hơn -> trả lời "đồng ý" ngay trong chat đó
        và chờ video. Trả về kết quả có video, hoặc None nếu vẫn không được."""
        sid = res.get("session_id")
        if not sid:
            return None
        for _ in range(2):
            self.log(f"Short #{s['idx']}: Muse đề xuất bản an toàn hơn — đồng ý và yêu cầu xuất video")
            try:
                sid = self.b.start_thread(REWORK_OK, [], sid)
                out = self.b.wait_threads([sid], self.timeout, self.log, self.cancelled,
                                          "tạo short", last_turn=True)[sid]
            except Cancelled:
                raise
            except Exception as e:
                self.log(f"Short #{s['idx']}: không gửi được yêu cầu đồng ý ({e})")
                return None
            if any((f.get("mime") or "").startswith("video/") for f in out["files"]):
                self.log(f"Short #{s['idx']}: Muse đã làm bản an toàn hơn")
                return out
            if is_service_error(out["text"]) or not is_refusal(out["text"]):
                return None
        return None

    def save_short(self, s: dict, res: dict) -> None:
        vid = next((f for f in res["files"] if (f.get("mime") or "").startswith("video/")), None)
        if not vid:
            if is_blocked_error(res["text"]):
                # Muse chặn tạo video theo quốc gia/khu vực của tài khoản. Trước đây câu trả lời này
                # rơi vào nhánh "từ chối nội dung": tool xin bản an toàn hơn, Muse đồng ý bằng chữ
                # nhưng vẫn không có video, thử đủ 3 lần rồi đánh hỏng short — lặp cho mọi short còn
                # lại (MV 55 mất cả 8 cảnh kiểu này). Chờ không hết, nên dừng ngay và giữ hàng đợi.
                store.update_short(s["id"], status="queued", retries=0,
                                   error="Muse chặn tạo video với tài khoản này theo quốc gia/khu vực "
                                         "— đổi tài khoản Muse khác rồi chạy lại")
                self.log(f"Short #{s['idx']}: Muse CHẶN tạo video với tài khoản này theo quốc gia/khu vực. "
                         "Đây không phải sự cố tạm thời, chờ không hết. Dừng tác vụ, giữ nguyên các short chưa làm.")
                raise RuntimeError("Muse chặn tạo video với tài khoản này theo quốc gia/khu vực. "
                                   "Đổi sang tài khoản Muse khác trong Cài đặt rồi bấm tạo lại — "
                                   "các short chưa làm vẫn nằm trong hàng đợi.")
            if is_quota_error(res["text"]):
                # Tài khoản hết lượt tạo video 24h. Trước đây câu trả lời này lọt vào nhánh "từ chối nội dung":
                # tool xin "bản an toàn hơn", Muse đồng ý bằng chữ nhưng vẫn không có video, thử 3 lần rồi
                # đánh hỏng short — lặp lại cho mọi short còn lại. Giờ trả short về hàng đợi và dừng tác vụ.
                store.update_short(s["id"], status="queued", retries=0,
                                   error="Tài khoản Muse hết lượt tạo video 24 giờ — chờ hạn mức mở lại")
                self.log(f"Short #{s['idx']}: tài khoản Muse HẾT LƯỢT tạo video 24 giờ. "
                         "Dừng tác vụ, giữ nguyên các short chưa làm — chạy lại khi hạn mức mở lại.")
                raise RuntimeError("Tài khoản Muse hết lượt tạo video trong 24 giờ. "
                                   "Các short chưa làm vẫn nằm trong hàng đợi, bấm tạo lại sau khi hạn mức mở lại.")
            service = is_service_error(res["text"])
            if s["lipsync"] and s.get("lyric_mode", "quote") == "quote" and not service:
                # Muse thường từ chối hát lời bài hát có sẵn -> tự thử lại 1 lần, chỉ tả hát nhép theo nhịp
                store.update_short(s["id"], status="queued", lyric_mode="plain")
                self.log(f"Short #{s['idx']}: Muse từ chối hát đúng lời — thử lại kiểu hát nhép theo nhịp (không ghi lời)")
                return
            if not service and is_refusal(res["text"]):
                # Muse từ chối brief nhưng đã soạn sẵn bản "an toàn hơn" -> đồng ý ngay trong chat đó.
                # Gửi lại y nguyên brief cũ là vô ích: Muse nhận ra và từ chối tiếp.
                out = self.accept_rework(s, res)
                if out:
                    return self.save_short(s, out)
                if res.get("session_id") and res["session_id"] == self.p.get("chat_session"):
                    # lời từ chối nằm lại trong chat MV dùng chung sẽ kéo theo các short sau
                    store.update_project(self.pid, chat_session="")
                    self.p = store.get_project(self.pid)
                    self.log("Chat MV đã dính lời từ chối — các short sau sẽ mở chat MV mới")
            why = "Muse đang lỗi máy chủ" if service else "Muse không trả về video"
            n = (s.get("retries") or 0) + 1
            if n <= SHORT_RETRY:
                # Muse hay trả lời bằng chữ / lỗi máy chủ nhất thời -> tự gửi lại, không bắt bấm tay
                store.update_short(s["id"], status="queued", retries=n,
                                   error=f"{why} — đang tự gửi lại ({n}/{SHORT_RETRY})")
                self.log(f"Short #{s['idx']}: {why} — tự gửi lại lần {n}/{SHORT_RETRY}"
                         + (" (có kèm luật tránh bị từ chối)" if not service else " sau 60 giây"))
                if service:
                    self.sleep(60)
                return
            store.update_short(s["id"], status="failed",
                               error=f"{why} sau {SHORT_RETRY} lần thử: {(res['text'] or '')[:300]}")
            self.log(f"Short #{s['idx']}: {why} (đã thử {SHORT_RETRY} lần) — bấm tạo lại nếu muốn")
            return
        version = s["version"] + 1
        dest = self.dir / "shorts" / f"s{s['id']}_v{version}.mp4"
        try:
            if self.p["kind"] == "model" and self.p.get("ref_video_path"):
                # khớp màu theo video mẫu; giữ bản gốc _raw để nối khung hình cho short sau
                raw = dest.with_name(dest.stem + "_raw.mp4")
                self.b.download_runtime_file(vid, raw)
                if self.match_color(raw, dest) == raw:
                    shutil.copyfile(raw, dest)
            else:
                self.b.download_runtime_file(vid, dest)
            thumb = ffmpeg.thumbnail(dest, dest.with_suffix(".jpg"))
        except Exception as e:
            store.update_short(s["id"], status="failed", error=f"Tải video lỗi: {e}")
            return
        store.update_short(s["id"], status="done", video_path=str(dest), thumb_path=str(thumb) if thumb else None,
                           version=version, error=None, retries=0)
        self.log(f"Short #{s['idx']} xong")


def remake_plan(scenes: list[dict], duration: float, max_sec: float, lyrics: list[dict]) -> list[dict]:
    """Phân cảnh MV gốc -> short: phủ kín bài, phân cảnh dài hơn max_sec được chia đều (phần sau nối cảnh phần trước).
    Đạo cụ được gộp vào danh sách tên của short để tìm ảnh thay thế."""
    rows = sorted((x for x in scenes if "start" in x and "end" in x), key=lambda x: float(x["start"]))
    if not rows:
        raise RuntimeError("Muse không chia được phân cảnh")
    out = []
    for i, x in enumerate(rows):
        start = 0.0 if i == 0 else out[-1]["end"]
        end = duration if i == len(rows) - 1 else max(float(x["end"]), start + 1)
        n = max(1, round((end - start) / max_sec + 0.49))
        names = list(x.get("characters") or []) + [p for p in x.get("props") or [] if p]
        for k in range(n):
            a, b = round(start + (end - start) * k / n, 2), round(start + (end - start) * (k + 1) / n, 2)
            lyric = " ".join(l["text"] for l in lyrics if l.get("text") and l["end"] > a and l["start"] < b)
            out.append({"start": a, "end": b, "description": x.get("description", ""), "characters": names,
                        "location": x.get("location") or "", "lipsync": bool(x.get("singing")), "lyric": lyric,
                        "cont": k > 0})
    return out


def singer_name(assets: list[dict]) -> str:
    """Tên nhân vật ca sĩ (tên bắt đầu bằng "Ca sĩ"/"Singer"), rỗng nếu MV không có ca sĩ."""
    return next((a["name"] for a in assets if a["kind"] == "character"
                 and re.match(r"\s*(ca sĩ|singer)", a["name"], re.I)), "")


def lipsync_rule(pct: int) -> str:
    if pct >= 100:
        return "TẤT CẢ cảnh có lời đều phải có nhân vật hát nhép khớp khẩu hình với lời."
    if pct <= 0:
        return "Không cảnh nào cần hát nhép, chỉ minh hoạ bằng hình ảnh."
    return f"Khoảng {pct}% số cảnh có lời là cảnh nhân vật hát nhép khớp khẩu hình (ưu tiên điệp khúc), còn lại minh hoạ bằng hình ảnh."


def normalize_plan(shorts: list[dict], duration: float, max_sec: float, pct: int) -> list[dict]:
    """Sắp xếp, nối liền các short phủ kín bài, tách short quá dài và đặt đúng số short lip sync theo %."""
    rows = sorted((s for s in shorts if "start" in s and "end" in s), key=lambda s: float(s["start"]))
    if not rows:
        raise RuntimeError("Plan không có short nào")
    out, prev_scene = [], None
    for i, s in enumerate(rows):
        scene = s.get("scene")
        same = i > 0 and scene is not None and scene == prev_scene
        prev_scene = scene
        start = 0.0 if i == 0 else out[-1]["end"]
        end = duration if i == len(rows) - 1 else max(float(s["end"]), start + 1)
        n = max(1, round((end - start) / max_sec + 0.49))  # chia đều nếu dài hơn max_sec
        for k in range(n):
            out.append({**s, "start": round(start + (end - start) * k / n, 2),
                        "end": round(start + (end - start) * (k + 1) / n, 2),
                        "lipsync": bool(s.get("lipsync")) and bool((s.get("lyric") or "").strip()),
                        "cont": same or k > 0,  # cùng phân cảnh với short trước / phần sau của short bị chia
                        "characters": list(s.get("characters") or [])})
    sung = [s for s in out if (s.get("lyric") or "").strip()]
    target = round(len(sung) * pct / 100)
    on = [s for s in sung if s["lipsync"]]
    for s in on[target:]:
        s["lipsync"] = False
    for s in [s for s in sung if not s["lipsync"]][:max(0, target - len(on))]:
        s["lipsync"] = True
    return out
