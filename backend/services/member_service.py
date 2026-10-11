"""成员名册业务服务：小队里的「人」（D-018）。

三种来路最终都落在同一张 members 名册上（PLAN §5.1）：
    - 注册入队：账号注册后登记为 active 成员
    - 占位后认领：队长手填占位成员（placeholder + 邀请码），人注册后认领
    - 上传名单：Agent 读名单认人后写进同一条名册

本层只管名册本身；「读名单认人」属于轮 2；「用邀请码认领」在轮 3 已实现（见 claim_placeholder）。
"""
import secrets
from typing import Optional

from sqlalchemy.orm import Session

from models.database import Member, User

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


def unique_member_name(db: Session, name: str) -> str:
    """名册里取一个不撞名的名字：重名就加后缀（张三 → 张三(2)）。

    名册**不同于项目名**，不强制唯一（现实里本来就会重名，且重名由「问人」处理，
    见 find_by_name）。但注册时自动登记成成员这一步是系统行为、没人可问，
    所以只在这里加后缀消歧，保证新账号不会一注册就制造一条需要人工裁决的歧义。
    """
    base = (name or "").strip() or "新成员"
    if not find_by_name(db, base):
        return base
    n = 2
    while find_by_name(db, f"{base}({n})"):
        n += 1
    return f"{base}({n})"


def claim_placeholder(db: Session, user: User, invite_code: str) -> Member:
    """用邀请码把占位成员认领到账号上（轮 3，D-030）。

    认领只改 members 这一行（user_id 绑定、status 转 active、邀请码清空），
    **不改 member.id** —— 任务的 assignee_id 指向成员 id，所以认领完成后
    「之前被指派的活」自动归位到这本人身上，一条任务都不用改。

    调用方负责把异常翻译成 HTTP 状态码；这里只负责业务前提判断。
    """
    code = (invite_code or "").strip().upper()
    if not code:
        raise ValueError("邀请码不能为空")

    target = db.query(Member).filter(Member.invite_code == code).first()
    if target is None:
        raise LookupError("邀请码无效")
    if target.user_id is not None or target.status != "placeholder":
        raise PermissionError("这个邀请码已经被认领过了")

    # 一个人只占名册一个位置：已有成员身份时不许再认领第二条
    existing = member_for_user(db, user.id)
    if existing is not None and existing.id != target.id:
        raise FileExistsError(f"你已经以「{existing.name}」的身份在小队里了")

    target.user_id = user.id
    target.status = "active"
    target.invite_code = None
    db.commit()
    db.refresh(target)
    return target
