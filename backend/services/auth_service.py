"""账号认证服务（轮 3，D-030）：注册 / 登录 / 会话令牌 / 邀请码认领。

「人」分两层（D-018）在这个模块里汇合：
    - **账号**（users）只管登录 —— 本模块负责密码与令牌；
    - **成员**（members）是名册上的「人」 —— 注册时同时登记为 active 成员，
      被邀请时用邀请码把 placeholder 成员认领到账号上。

设计取舍：
    - 密码哈希用标准库 `hashlib.pbkdf2_hmac` + 随机盐，**不引入 bcrypt/passlib**
      （项目是 demo，少一个依赖少一处安装坑）；同时兼容 seed 时代的老哈希
      （裸 sha256），校验通过后不主动改写，避免动演示库。
    - 会话令牌用标准库 `hmac` 签名的自包含串（`uid.过期时间.签名`），**不引入 JWT 库**。
      无状态、可验签、可过期；密钥来自 `settings.SECRET_KEY`，没配则用固定 demo 默认值
      （启动时会打一条提醒，生产必须覆盖）。
"""
import hashlib
import hmac
import os
import secrets
import time
from typing import Optional

from sqlalchemy.orm import Session

from core.config import settings
from models.database import Member, User
from services import member_service

# ---------- 密码 ----------
PBKDF2_ROUNDS = 120_000
SALT_BYTES = 16


def hash_password(password: str) -> str:
    """生成 `pbkdf2$轮数$盐$摘要` 格式的密码哈希（每次调用盐不同）。"""
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return f"pbkdf2${PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def _verify_pbkdf2(password: str, stored: str) -> bool:
    try:
        _, rounds, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


def _verify_legacy_sha256(password: str, stored: str) -> bool:
    """兼容 seed 时代写的裸 sha256（老库 alice 就是这个）。

    只在格式明显是 64 位十六进制、且不含 `$` 时才当老哈希试一次。
    """
    if "$" in stored or len(stored) != 64:
        return False
    return hmac.compare_digest(hashlib.sha256(password.encode()).hexdigest(), stored)


def verify_password(password: str, stored: str) -> bool:
    """校验密码：先按新格式，再兼容老哈希。"""
    if not stored:
        return False
    if stored.startswith("pbkdf2$"):
        return _verify_pbkdf2(password, stored)
    return _verify_legacy_sha256(password, stored)


# ---------- 会话令牌 ----------
TOKEN_TTL_SECONDS = 30 * 24 * 3600  # 30 天：演示项目，够用且省去频繁续期


def _secret() -> bytes:
    return (settings.SECRET_KEY or "squad-demo-secret-change-me").encode()


def make_token(user_id: int, ttl_seconds: int = TOKEN_TTL_SECONDS) -> str:
    """签发令牌：`uid.过期时间戳.签名`（签名覆盖前两段）。"""
    expires_at = int(time.time()) + ttl_seconds
    payload = f"{user_id}.{expires_at}"
    sig = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{payload}.{sig}"


def parse_token(token: str) -> Optional[int]:
    """验签并检查过期，返回 user_id；任何不合法一律返回 None（调用方回 401）。"""
    if not token:
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    uid_str, exp_str, sig = parts
    expected = hmac.new(_secret(), f"{uid_str}.{exp_str}".encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        if int(exp_str) < int(time.time()):
            return None
        return int(uid_str)
    except ValueError:
        return None


# ---------- 注册 / 登录 ----------
def find_by_username(db: Session, username: str) -> Optional[User]:
    return db.query(User).filter(User.username == (username or "").strip()).first()


def find_by_email(db: Session, email: str) -> Optional[User]:
    return db.query(User).filter(User.email == (email or "").strip()).first()


def register(db: Session, username: str, email: str, password: str) -> User:
    """注册账号，并**同时登记成 active 成员**（PLAN §5.1「注册入队」）。

    注册即入队是这个产品的前提：新账号马上就能被指派、能查自己的任务。

    注意：这里**不**强行让 members.id 等于 users.id。老库靠 `_ensure_member_roster`
    做过一次对齐（那是为了让存量任务的 assignee_id 继续指向同一个人），但名册上
    随时可能有手填的占位成员，id 序列并不空 —— 硬塞同一个 id 会撞主键。
    成员与账号的绑定关系一律走 `members.user_id`，不看 id 是否相等。
    """
    username, email = username.strip(), email.strip()
    user = User(username=username, email=email, password_hash=hash_password(password))
    db.add(user)
    db.flush()
    # 名册：账号注册即成为 active 成员；同名时加后缀避免撞名（名册不强制唯一）
    name = member_service.unique_member_name(db, username)
    db.add(Member(name=name, user_id=user.id, status="active"))
    db.commit()
    db.refresh(user)
    return user


def authenticate(db: Session, username: str, password: str) -> Optional[User]:
    """用户名 + 密码 → 账号；失败返回 None（调用方统一回「用户名或密码不对」）。"""
    user = find_by_username(db, username)
    if user is None or not verify_password(password, user.password_hash):
        return None
    return user


def resolve_user(db: Session, token: Optional[str]) -> Optional[User]:
    """从令牌解析当前账号；解析不出返回 None。"""
    uid = parse_token(token or "")
    if uid is None:
        return None
    return db.get(User, uid)
