"""Nạp cookie đăng nhập muse.ai (định dạng export của extension trình duyệt) vào Playwright."""

import json
from pathlib import Path

COOKIES_FILE = Path(__file__).resolve().parent.parent / "secrets" / "cookies.json"

_SAMESITE = {"lax": "Lax", "strict": "Strict", "no_restriction": "None", None: "Lax"}


def load_cookies(path: Path = COOKIES_FILE) -> list[dict]:
    raw = json.loads(path.read_text())
    cookies = []
    for c in raw:
        cookie = {
            "name": c["name"],
            "value": c["value"],
            "path": c.get("path", "/"),
            "secure": c.get("secure", True),
            "httpOnly": c.get("httpOnly", False),
            "sameSite": _SAMESITE.get(c.get("sameSite"), "Lax"),
        }
        if c.get("expirationDate"):
            cookie["expires"] = c["expirationDate"]
        # Cookie __Host- bắt buộc gắn với host, không có domain
        if c["name"].startswith("__Host-") or c.get("hostOnly"):
            cookie["url"] = f"https://{c['domain'].lstrip('.')}/"
            cookie.pop("path")
        else:
            cookie["domain"] = c["domain"]
        cookies.append(cookie)
    return cookies


def cookie_header(path: Path = COOKIES_FILE) -> str:
    return "; ".join(f"{c['name']}={c['value']}" for c in json.loads(path.read_text()))


# ---------- nhiều tài khoản ----------
# Mỗi tài khoản là 1 file secrets/accounts/<tên>.json; tài khoản đang dùng được chép ra COOKIES_FILE.

ACCOUNTS_DIR = COOKIES_FILE.parent / "accounts"
ACTIVE_FILE = COOKIES_FILE.parent / "active_account.txt"


def parse_cookie_text(text: str) -> list[dict]:
    """Nhận JSON export của Cookie-Editor / EditThisCookie (list hoặc {"cookies": [...]}),
    hoặc chuỗi header "a=1; b=2". Trả về list cookie dạng Cookie-Editor."""
    text = text.strip()
    try:
        data = json.loads(text)
    except ValueError:
        data = [{"name": k.strip(), "value": v.strip(), "domain": ".muse.ai", "path": "/"}
                for k, _, v in (p.partition("=") for p in text.split(";")) if k.strip() and v.strip()]
    if isinstance(data, dict):
        data = data.get("cookies", [])
    if not isinstance(data, list) or not all(isinstance(c, dict) and "name" in c and "value" in c for c in data):
        raise ValueError("Cookie phải là JSON dạng danh sách (export từ extension Cookie-Editor)")
    for c in data:
        c.setdefault("domain", ".muse.ai")
    if not any(c["name"] == "hatch_sess" for c in data):
        raise ValueError("Thiếu cookie hatch_sess — hãy export cookie khi đang đăng nhập muse.ai")
    return data


def _safe_name(name: str) -> str:
    name = "".join(ch for ch in name.strip() if ch.isalnum() or ch in " -_.@").strip(" .")
    if not name:
        raise ValueError("Tên tài khoản không hợp lệ")
    return name[:60]


def _write_secret(path: Path, data: list[dict]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1))
    path.chmod(0o600)


def _migrate() -> None:
    """Bản cũ chỉ có cookies.json: đưa nó thành tài khoản đầu tiên."""
    if not ACCOUNTS_DIR.exists() and COOKIES_FILE.exists():
        _write_secret(ACCOUNTS_DIR / "Tài khoản 1.json", json.loads(COOKIES_FILE.read_text()))
        ACTIVE_FILE.write_text("Tài khoản 1")


def active_account() -> str | None:
    _migrate()
    if not ACTIVE_FILE.exists():
        return None
    return ACTIVE_FILE.read_text().strip() or None


def list_accounts() -> list[dict]:
    _migrate()
    active, out = active_account(), []
    for p in sorted(ACCOUNTS_DIR.glob("*.json")) if ACCOUNTS_DIR.exists() else []:
        try:
            sess = next((c for c in json.loads(p.read_text()) if c["name"] == "hatch_sess"), {})
        except Exception:
            sess = {}
        out.append({"name": p.stem, "active": p.stem == active, "saved": p.stat().st_mtime,
                    "expires": sess.get("expirationDate")})
    return out


def save_account(name: str, text: str) -> str:
    data = parse_cookie_text(text)
    name = _safe_name(name)
    _write_secret(ACCOUNTS_DIR / f"{name}.json", data)
    return name


def activate_account(name: str) -> None:
    src = ACCOUNTS_DIR / f"{_safe_name(name)}.json"
    if not src.exists():
        raise FileNotFoundError(f"Không có tài khoản {name}")
    _write_secret(COOKIES_FILE, json.loads(src.read_text()))
    load_cookies()  # kiểm tra định dạng
    ACTIVE_FILE.write_text(src.stem)


def delete_account(name: str) -> None:
    name = _safe_name(name)
    (ACCOUNTS_DIR / f"{name}.json").unlink(missing_ok=True)
    if active_account() == name:
        ACTIVE_FILE.unlink(missing_ok=True)
        COOKIES_FILE.unlink(missing_ok=True)


def save_playwright_cookies(name: str, cookies: list[dict]) -> str | None:
    """Lưu phiên đăng nhập thủ công (cookie lấy từ Playwright) thành 1 tài khoản và chọn dùng nó."""
    data = [{"name": c["name"], "value": c["value"], "domain": c["domain"], "path": c.get("path", "/"),
             "secure": c.get("secure", True), "httpOnly": c.get("httpOnly", False),
             "sameSite": {"Strict": "strict", "None": "no_restriction"}.get(c.get("sameSite"), "lax"),
             "hostOnly": not c["domain"].startswith("."),
             **({"expirationDate": c["expires"]} if c.get("expires", -1) > 0 else {})}
            for c in cookies]
    sess = next((c["value"] for c in data if c["name"] == "hatch_sess"), None)
    if not sess:
        return None
    if COOKIES_FILE.exists() and any(c["name"] == "hatch_sess" and c["value"] == sess
                                     for c in json.loads(COOKIES_FILE.read_text())):
        return active_account()  # vẫn là tài khoản đang dùng
    name = _safe_name(name)
    _write_secret(ACCOUNTS_DIR / f"{name}.json", data)
    activate_account(name)
    return name
