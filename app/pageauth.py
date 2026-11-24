# -*- coding: utf-8 -*-
"""页面访问密码认证：HMAC 签名的持久化会话 Cookie。

- 密码优先读取数据库（页面修改后入库，升级不会重置）；
  数据库未设置时回退到环境变量 PAGE_PASSWORD（首次部署的初始密码）
- 会话令牌 = 过期时间戳 + HMAC 签名，签名内容绑定当前密码指纹，
  修改密码后旧会话自动失效；签名密钥持久化在 data/page_secret.key
- Cookie 有效期 30 天，浏览器自动携带，实现"记住认证信息"
"""
import hashlib
import hmac
import os
import secrets
import time

from . import db

SESSION_COOKIE = "fsdoc_session"
SESSION_TTL = 30 * 24 * 3600  # 30 天

SECRET_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "page_secret.key")


def get_page_password() -> str:
    """初始密码：仅当数据库中未保存过密码时生效。"""
    return os.environ.get("PAGE_PASSWORD", "admin123")


def _hash_password(plain: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", plain.encode(), salt.encode(), 100_000).hex()


def get_stored_hash() -> str | None:
    row = db.get_page_auth()
    return row["password_hash"] if row else None


def verify_page_password(plain: str) -> bool:
    stored = get_stored_hash()
    if stored is None:
        return plain == get_page_password()
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    return hmac.compare_digest(_hash_password(plain, salt), digest)


def set_page_password(plain: str):
    """修改密码并入库（PBKDF2 加盐哈希存储）。"""
    salt = secrets.token_hex(16)
    db.save_page_password(f"{salt}${_hash_password(plain, salt)}")


# ---------- API 认证密码（独立于页面访问密码，存库） ----------

def get_api_stored_hash() -> str | None:
    row = db.get_api_auth()
    return row["password_hash"] if row else None


def api_password_configured() -> bool:
    return get_api_stored_hash() is not None


def verify_api_password(plain: str) -> bool:
    stored = get_api_stored_hash()
    if stored is None:
        return False
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    return hmac.compare_digest(_hash_password(plain, salt), digest)


def set_api_password(plain: str):
    salt = secrets.token_hex(16)
    db.save_api_password(f"{salt}${_hash_password(plain, salt)}")


def clear_api_password():
    db.clear_api_password()


def _password_fingerprint() -> str:
    """当前密码的指纹，用于会话令牌签名（改密后旧令牌失效）。"""
    stored = get_stored_hash()
    if stored:
        return stored
    return hashlib.sha256(("env:" + get_page_password()).encode()).hexdigest()


def _secret() -> str:
    os.makedirs(os.path.dirname(os.path.abspath(SECRET_FILE)), exist_ok=True)
    if not os.path.exists(SECRET_FILE):
        with open(SECRET_FILE, "w") as f:
            f.write(secrets.token_hex(32))
    with open(SECRET_FILE) as f:
        return f.read().strip()


def _sign(payload: str) -> str:
    return hmac.new(_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_token() -> str:
    exp = str(int(time.time()) + SESSION_TTL)
    return f"{exp}.{_sign(f'{exp}.{_password_fingerprint()}')}"


def verify_token(token: str) -> bool:
    if not token or "." not in token:
        return False
    exp, sig = token.split(".", 1)
    if not hmac.compare_digest(sig, _sign(f"{exp}.{_password_fingerprint()}")):
        return False
    try:
        return int(exp) > time.time()
    except ValueError:
        return False
