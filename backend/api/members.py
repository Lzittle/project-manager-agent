"""成员名册接口 /api/members

队长在这里手填成员（先有名册、后有人注册）：占位成员「只有名字、没有账号」，
可以立刻被指派；对方登录后用邀请码认领这条占位身份（轮 3 已实现，见 /claim）。
"""
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from models.database import get_db, Member
from models.schemas import ClaimRequest, MemberCreate, MemberOut
from services import auth_service, member_service

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


@router.post("/claim", response_model=MemberOut)
def claim_member(body: ClaimRequest, authorization: str = Header(default=""),
                 db: Session = Depends(get_db)):
    """用邀请码认领占位成员（轮 3，D-030）。

    认领后：这条名册归到当前账号名下、变成 active，邀请码作废。
    因为任务的 assignee_id 指向**成员 id**、认领不改 id，原先指派给这个占位的活
    自动归位到本人 —— 不需要迁移任何任务数据。
    """
    token = auth_service.token_from_header(authorization)
    user = auth_service.resolve_user(db, token)
    if user is None:
        raise HTTPException(401, "请先登录再认领成员身份")

    try:
        return member_service.claim_placeholder(db, user, body.invite_code)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except PermissionError as e:
        raise HTTPException(409, str(e))
    except FileExistsError as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
