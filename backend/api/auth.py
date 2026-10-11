"""认证接口 /api/auth（轮 3，D-030）

- POST /register  注册账号 → 同时登记为 active 成员（注册入队）→ 直接返回令牌
- POST /login     用户名 + 密码 → 令牌
- GET  /me        凭令牌返回当前账号 + 对应的名册成员

**兼容性说明（重要）**：本项目此前「无登录体系」，所有接口靠 `?user_id=` 传当前用户。
轮 3 只是**新增**登录能力，没有把老路径换掉 —— 演示脚本、79 条评测、只读探针
原先怎么调还怎么调，不因这次改动失效。
"""
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from models.database import get_db
from models.schemas import AuthOut, LoginRequest, MeOut, RegisterRequest
from services import auth_service, member_service

router = APIRouter()


def _me_payload(db: Session, user) -> dict:
    """账号 + 名册成员拼成 MeOut 需要的字典。"""
    member = member_service.member_for_user(db, user.id)
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "member_id": member.id if member else None,
        "member_name": member.name if member else None,
        "member_status": member.status if member else None,
    }


@router.post("/register", response_model=AuthOut, status_code=201)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    """注册。用户名/邮箱任一重复都回 409（不透露是哪一个被占，减少枚举）。"""
    username, email = body.username.strip(), body.email.strip()
    if not username or not email:
        raise HTTPException(400, "用户名和邮箱都不能为空")
    if auth_service.find_by_username(db, username):
        raise HTTPException(409, "这个用户名已经被注册了")
    if auth_service.find_by_email(db, email):
        raise HTTPException(409, "这个邮箱已经被注册了")

    user = auth_service.register(db, username, email, body.password)
    return {"token": auth_service.make_token(user.id), "user": _me_payload(db, user)}


@router.post("/login", response_model=AuthOut)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    """登录。失败统一回「用户名或密码不对」，不区分是哪个错（防账号枚举）。"""
    user = auth_service.authenticate(db, body.username, body.password)
    if user is None:
        raise HTTPException(401, "用户名或密码不对")
    return {"token": auth_service.make_token(user.id), "user": _me_payload(db, user)}


@router.get("/me", response_model=MeOut)
def me(authorization: str = Header(default=""),
       db: Session = Depends(get_db)):
    """当前身份。要求 `Authorization: Bearer <token>`。"""
    token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else authorization.strip()
    user = auth_service.resolve_user(db, token)
    if user is None:
        raise HTTPException(401, "登录状态已失效，请重新登录")
    return _me_payload(db, user)
