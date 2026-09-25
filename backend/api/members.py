"""成员名册接口 /api/members

队长在这里手填成员（先有名册、后有人注册）：占位成员「只有名字、没有账号」，
可以立刻被指派；对方注册后用邀请码认领（认领属于轮 3，接口暂不实现）。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from models.database import get_db
from models.schemas import MemberCreate, MemberOut
from services import member_service

router = APIRouter()


@router.get("", response_model=list[MemberOut])
def list_members(db: Session = Depends(get_db)):
    """全队名册（已注册在前、待认领在后）。"""
    return member_service.list_members(db)


@router.post("", response_model=MemberOut, status_code=201)
def create_member(body: MemberCreate, db: Session = Depends(get_db)):
    """手填一个成员（占位，带邀请码）。同名不自动合并，交给上层问人。"""
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "成员名字不能为空")
    same = member_service.find_by_name(db, name)
    if same:
        raise HTTPException(
            409, f"已有同名成员（id: {', '.join(str(m.id) for m in same)}）—— 请先确认是不是同一个人")
    return member_service.create_member(db, name)
