"""成员名册业务服务：小队里的「人」（D-018）。

三种来路最终都落在同一张 members 名册上（PLAN §5.1）：
    - 注册入队：账号注册后登记为 active 成员
    - 占位后认领：队长手填占位成员（placeholder + 邀请码），人注册后认领
    - 上传名单：Agent 读名单认人后写进同一条名册

本层只管名册本身；「用邀请码认领」属于轮 3，「读名单认人」属于轮 2。
"""
import secrets
from typing import Optional

from sqlalchemy.orm import Session

from models.database import Member

# 邀请码字符集：去掉 I/O/0/1 这些容易看错的字符
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LEN = 6


def _gen_invite_code(db: Session) -> str:
    """生成未被占用的邀请码（撞码就重试，最多 20 次）。"""
    for _ in range(20):
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))
        if db.query(Member).filter_by(invite_code=code).first() is None:
            return code
    raise RuntimeError("邀请码生成失败：连续 20 次撞码，检查名册规模")


def list_members(db: Session) -> list[Member]:
    """全队名册：已注册（active）在前，待认领（placeholder）在后，各按名字排。"""
    return db.query(Member).order_by(Member.status.asc(), Member.name).all()


def get_member(db: Session, member_id: int) -> Optional[Member]:
    return db.get(Member, member_id)


def find_by_name(db: Session, name: str) -> list[Member]:
    """按名字精确匹配；可能返回多条 —— 重名时调用方必须问人，不许猜（PLAN §5）。"""
    return db.query(Member).filter(Member.name == (name or "").strip()).all()


def member_for_user(db: Session, user_id: Optional[int]) -> Optional[Member]:
    """账号对应的成员（认领之后）。名册里没有就返回 None —— 这里不自动造人。"""
    if not user_id:
        return None
    return db.query(Member).filter_by(user_id=user_id).first()


def create_member(db: Session, name: str, user_id: Optional[int] = None,
                  status: str = "placeholder") -> Member:
    """写进名册。占位成员（默认）带邀请码；已注册成员（有账号）不带邀请码。"""
    m = Member(
        name=name.strip(),
        user_id=user_id,
        status=status,
        invite_code=None if user_id else _gen_invite_code(db),
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def ensure_member_for_user(db: Session, user_id: int, name: str) -> Member:
    """把账号登记成成员（已有则复用）。种子脚本与老库回填走同一口径。"""
    m = member_for_user(db, user_id)
    if m is not None:
        return m
    return create_member(db, name, user_id=user_id, status="active")
