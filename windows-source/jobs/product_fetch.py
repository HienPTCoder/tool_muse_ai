"""Phân tích link sản phẩm + chọn ảnh sản phẩm chuẩn (chạy trong tab phụ của Playwright).

Tách riêng khỏi worker để dễ kiểm thử: chuẩn hoá link, chặn địa chỉ nội bộ (kể cả sau redirect),
trích thông tin trang (tên/mô tả/giá/thương hiệu), xếp hạng ảnh ứng viên, nâng ảnh thumbnail lên ảnh lớn.
"""

import base64
import ipaddress
import re
import socket
import time
from pathlib import Path
from urllib.parse import urlparse

URL_RE = re.compile(r"https?://[^\s<>\"'“”‘’]+", re.I)
BARE_RE = re.compile(r"^(?:www\.)?[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)+(?:[/?#]\S*)?$", re.I)
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MIN_IMAGE_BYTES = 4 * 1024


def normalize_url(raw) -> str:
    """Lấy link từ chuỗi người dùng dán (có thể kèm chữ, thiếu https://, dính dấu câu cuối)."""
    s = str(raw or "").strip()
    if not s:
        raise ValueError("Link trống")
    m = URL_RE.search(s)
    if m:
        url = m.group(0)
    else:
        first = s.split()[0]
        if not BARE_RE.match(first):
            raise ValueError("Không tìm thấy link http/https hợp lệ")
        url = "https://" + first
    url = url.rstrip(".,;:!?)]}»”’")
    return url


def check_public_url(url: str) -> None:
    """Chỉ cho phép địa chỉ công khai: chặn localhost, IP riêng và tên miền trỏ về IP riêng."""
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if p.scheme not in ("http", "https") or not host or p.username or p.password:
        raise ValueError("Link phải là địa chỉ http/https hợp lệ")
    if host in ("localhost", "localhost.localdomain") or host.endswith((".local", ".internal", ".localhost")):
        raise ValueError("Không hỗ trợ địa chỉ mạng nội bộ")
    try:
        if not ipaddress.ip_address(host).is_global:
            raise ValueError("Không hỗ trợ địa chỉ mạng nội bộ")
        return
    except ValueError as exc:
        if "mạng nội bộ" in str(exc):
            raise
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return  # không phân giải được ở đây thì để trình duyệt báo lỗi cụ thể
    for info in infos:
        try:
            if not ipaddress.ip_address(info[4][0].split("%")[0]).is_global:
                raise ValueError("Không hỗ trợ địa chỉ mạng nội bộ")
        except ValueError as exc:
            if "mạng nội bộ" in str(exc):
                raise


# ---- ảnh: nâng thumbnail lên bản lớn ----
_SHOPEE_TN = re.compile(r"(susercontent\.com/file/[^/?#]+|cf\.shopee\.[a-z.]+/file/[^/?#]+)_tn(?=$|[?#])", re.I)
_ALICDN_SIZE = re.compile(r"(\.(?:jpe?g|png|webp))_\d+x\d+[^/?#]*(?=$|[?#])", re.I)
_TIKI_CACHE = re.compile(r"/cache/\d+x\d+/", re.I)


def upgrade_image_url(src: str) -> list[str]:
    """Trả [bản lớn..., bản gốc]; thử bản lớn trước, lỗi thì quay về bản gốc."""
    out = []
    u = _SHOPEE_TN.sub(r"\1", src)
    if u != src:
        out.append(u)
    u = _ALICDN_SIZE.sub(r"\1", src)
    if u != src:
        out.append(u)
    if _TIKI_CACHE.search(src):
        out.append(_TIKI_CACHE.sub("/cache/750x750/", src))
    out.append(src)
    return list(dict.fromkeys(out))


def sniff_image(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:12] in (b"ftypavif", b"ftypavis"):
        return "image/avif"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return None


BLOCK_URL = re.compile(r"/(login|signin|sign-in|verify|captcha|challenge|buyer/login)\b|[?&]captcha", re.I)
BLOCK_TEXT = re.compile(
    r"captcha|are you a (robot|human)|verify you are human|access denied|unusual traffic|"
    r"xác minh bạn là người|kéo thanh trượt|đăng nhập để tiếp tục|just a moment", re.I)

# JS chạy trong trang: trả {info, candidates:[{src, score, why}]}
EXTRACT_JS = r"""() => {
  const abs = u => { try { return new URL(u, location.href).href; } catch (_) { return ''; } };
  const meta = (k) => document.querySelector(`meta[property="${k}"],meta[name="${k}"]`)?.content?.trim() || '';
  const cand = new Map();
  const add = (u, score, why) => {
    if (typeof u !== 'string' || !u.trim()) return;
    u = abs(u.trim()); if (!/^https?:/i.test(u)) return;
    if (!cand.has(u) || cand.get(u).score < score) cand.set(u, {src: u, score, why});
  };
  const info = {title: '', description: '', price: '', currency: '', brand: '', siteName: meta('og:site_name'),
                finalUrl: location.href, canonical: document.querySelector('link[rel="canonical"]')?.href || ''};
  const BAD = /logo|sprite|icon|avatar|placeholder|loading|blank|pixel|spacer|badge|flag|banner|payment|app-?store|google-?play|\.svg(\?|$)|\.gif(\?|$)|^data:/i;

  // 1) JSON-LD Product (đáng tin nhất)
  const walk = x => {
    if (!x) return;
    if (Array.isArray(x)) return x.forEach(walk);
    if (typeof x !== 'object') return;
    const t = x['@type'];
    if (t === 'Product' || (Array.isArray(t) && t.includes('Product'))) {
      info.title = info.title || (x.name || '');
      info.description = info.description || (x.description || '');
      const b = x.brand; info.brand = info.brand || (typeof b === 'string' ? b : b?.name || '');
      const im = x.image; (Array.isArray(im) ? im : [im]).forEach((v, i) => add(typeof v === 'string' ? v : v?.url, 120 - i, 'jsonld'));
      const offers = Array.isArray(x.offers) ? x.offers[0] : x.offers;
      if (offers) { info.price = info.price || String(offers.price ?? offers.lowPrice ?? ''); info.currency = info.currency || (offers.priceCurrency || ''); }
    }
    Object.values(x).forEach(walk);
  };
  for (const el of document.querySelectorAll('script[type="application/ld+json"]')) { try { walk(JSON.parse(el.textContent)); } catch (_) {} }

  // 2) Meta
  add(meta('og:image:secure_url'), 100, 'og'); add(meta('og:image'), 100, 'og'); add(meta('twitter:image'), 90, 'twitter');
  add(document.querySelector('link[rel="image_src"]')?.href, 80, 'link');
  info.title = info.title || meta('og:title') || document.querySelector('h1')?.innerText?.trim() || document.title || '';
  info.description = info.description || meta('og:description') || meta('description');
  info.price = info.price || meta('product:price:amount') || meta('og:price:amount');
  info.currency = info.currency || meta('product:price:currency') || meta('og:price:currency');

  // 3) Ảnh trong trang (kể cả lazy-load / srcset)
  const lazyAttrs = ['data-src', 'data-original', 'data-lazy-src', 'data-lazy', 'data-zoom-image', 'data-large', 'data-image'];
  for (const img of document.images) {
    const rect = img.getBoundingClientRect();
    const w = Math.max(img.naturalWidth || 0, rect.width), h = Math.max(img.naturalHeight || 0, rect.height);
    if (w < 180 || h < 180) continue;
    const ratio = w / h; if (ratio < 0.4 || ratio > 2.5) continue;
    if (img.closest('header,footer,nav,aside,[class*="header"],[class*="footer"],[class*="recommend"],[class*="related"],[class*="similar"]')) continue;
    let best = img.currentSrc || img.src;
    for (const a of lazyAttrs) { const v = img.getAttribute(a); if (v && !/^data:/.test(v)) { best = v; break; } }
    const ss = img.getAttribute('srcset') || img.getAttribute('data-srcset');
    if (ss) {
      let top = 0, pick = '';
      for (const part of ss.split(',')) { const [u, d] = part.trim().split(/\s+/); const n = parseFloat(d) || 1; if (u && n >= top) { top = n; pick = u; } }
      if (pick) best = pick;
    }
    if (!best || BAD.test(best) || BAD.test(img.alt || '') || BAD.test(img.className || '')) continue;
    let score = Math.min(w * h, 1000000) / 20000;                       // tối đa 50
    if (img.closest('main,[class*="product"],[class*="gallery"],[id*="product"],[class*="pdp"],[class*="detail"]')) score += 20;
    if (rect.top < 1400) score += 10;
    add(best, score, 'dom');
  }
  const list = [...cand.values()].filter(c => !BAD.test(c.src) || c.why === 'jsonld').sort((a, b) => b.score - a.score).slice(0, 14);
  for (const k of ['title', 'description', 'brand']) info[k] = String(info[k] || '').replace(/\s+/g, ' ').trim();
  info.title = info.title.slice(0, 300); info.description = info.description.slice(0, 900);
  const body = (document.body?.innerText || '').slice(0, 1500);
  return {info, candidates: list, bodySample: body.slice(0, 400)};
}"""

SCROLL_JS = "() => { window.scrollBy(0, Math.min(900, document.body.scrollHeight / 3)); }"


def scrape_product(ctx, page, raw_url, index, out_dir: Path, small_jpeg) -> dict:
    """Mở link, trả {url, finalUrl, info{...}, dataBase64,...} hoặc {url, error, info?}."""
    try:
        url = normalize_url(raw_url)
        check_public_url(url)
    except Exception as exc:
        return {"url": str(raw_url), "error": str(exc)[:200]}

    # mở trang (thử lại 1 lần khi lỗi mạng/timeout)
    last_exc = None
    for attempt in range(2):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            last_exc = None
            break
        except Exception as exc:
            last_exc = exc
            page.wait_for_timeout(800)
    if last_exc is not None:
        return {"url": url, "error": f"Không mở được trang: {str(last_exc)[:150]}"}

    final_url = page.url
    try:
        check_public_url(final_url)  # chặn redirect về địa chỉ nội bộ
    except Exception as exc:
        return {"url": url, "error": str(exc)[:200]}

    try:
        page.wait_for_load_state("networkidle", timeout=6000)
    except Exception:
        pass
    try:
        page.evaluate(SCROLL_JS)
        page.wait_for_timeout(700)
        data = page.evaluate(EXTRACT_JS)
    except Exception as exc:
        return {"url": url, "finalUrl": final_url, "error": f"Không đọc được trang: {str(exc)[:150]}"}

    info = data.get("info") or {}
    info["finalUrl"] = final_url
    blocked = bool(BLOCK_URL.search(final_url) or (not info.get("title") and BLOCK_TEXT.search(data.get("bodySample", "")))
                   or BLOCK_TEXT.search(info.get("title", "")))
    result = {"url": url, "finalUrl": final_url, "info": info, "blocked": blocked}

    last_error = ("Trang yêu cầu đăng nhập/xác minh chống bot, không đọc được sản phẩm"
                  if blocked else "Trang không có ảnh sản phẩm công khai")
    tried = 0
    for cand in data.get("candidates") or []:
        for src in upgrade_image_url(cand["src"]):
            if tried >= 16:
                break
            tried += 1
            try:
                check_public_url(src)
                resp = ctx.request.get(src, headers={"Referer": final_url}, timeout=20000)
                if not resp.ok:
                    last_error = f"Không tải được ảnh (HTTP {resp.status})"
                    continue
                body = resp.body()
                mime = sniff_image(body)
                if not mime:
                    continue
                if len(body) > MAX_IMAGE_BYTES or len(body) < MIN_IMAGE_BYTES:
                    last_error = "Ảnh quá nhỏ (có thể là icon/logo) hoặc vượt quá 12 MB"
                    continue
                out_dir.mkdir(parents=True, exist_ok=True)
                ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
                       "image/avif": ".avif", "image/gif": ".gif"}[mime]
                source = out_dir / f"source_{time.time_ns()}_{index}{ext}"
                compact = source.with_name(source.stem + "_preview.jpg")
                source.write_bytes(body)
                small_jpeg(source, compact, 1000)
                result.update({"sourceUrl": src, "filename": f"san_pham_{index}.jpg", "mimeType": "image/jpeg",
                               "category": "image", "dataBase64": base64.b64encode(compact.read_bytes()).decode("ascii")})
                return result
            except Exception as exc:
                last_error = str(exc)[:200]
    result["error"] = last_error
    return result
