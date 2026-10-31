"""任务小块子资源 /api/tasks/{task_id}/subtasks。"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api.auth import optional_viewer
from models.database import Member, Task, get_db
from models.schemas import SubtaskCreate, SubtaskOut, SubtaskUpdate
from models.task_breakdown import Subtask
from services import subtask_service, visibility

router = APIRouter()


def _parent_or_404(db: Session, task_id: int) -> Task:
    parent = db.get(Task, task_id)
    if parent is None:
        raise HTTPException(404, f"任务 {task_id} 不存在")
    return parent


def _can_use_parent(db: Session, parent: Task, viewer: Optional[visibility.Viewer]) -> bool:
    """登录身份只能操作队长或自己负责的父任务；无令牌保持老路径兼容。"""
    if viewer is None:
        return True
    if visibility.is_captain(db, viewer, parent.project_id):
        return True
    return viewer.member_id is not None and viewer.member_id == parent.assignee_id


def _require_parent_access(db: Session, parent: Task,
                           viewer: Optional[visibility.Viewer]) -> None:
    if not _can_use_parent(db, parent, viewer):
        raise HTTPException(403, "只能操作自己负责的父任务小块")


def _actor_id(viewer: Optional[visibility.Viewer], user_id: Optional[int]) -> int:
    return viewer.user_id if viewer is not None else (user_id or 1)


def _row_dict(db: Session, row: Subtask) -> dict:
    member = db.get(Member, row.assignee_id) if row.assignee_id else None
    return {
        "id": row.id,
        "parent_task_id": row.parent_task_id,
        "title": row.title,
        "description": row.description,
        "status": row.status,
        "assignee_id": row.assignee_id,
        "assignee_name": member.name if member else None,
        "assignee_status": member.status if member else None,
        "creator_id": row.creator_id,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("/{task_id}/subtasks", response_model=list[SubtaskOut])
def list_task_subtasks(task_id: int,
                       viewer: Optional[visibility.Viewer] = Depends(optional_viewer),
                       db: Session = Depends(get_db)):
    parent = _parent_or_404(db, task_id)
    _require_parent_access(db, parent, viewer)
    return [_row_dict(db, row) for row in subtask_service.list_subtasks(db, task_id)]


@router.post("/{task_id}/subtasks", response_model=SubtaskOut, status_code=201)
def create_task_subtask(
    task_id: int,
    body: SubtaskCreate,
    viewer: Optional[visibility.Viewer] = Depends(optional_viewer),
    user_id: Optional[int] = Query(None, description="兼容未登录演示路径的当前用户 id"),
    db: Session = Depends(get_db),
):
    parent = _parent_or_404(db, task_id)
    _require_parent_access(db, parent, viewer)
    actor_id = _actor_id(viewer, user_id)
    assignee_id = body.assignee_id
    if assignee_id is not None and db.get(Member, assignee_id) is None:
        raise HTTPException(404, f"成员 {assignee_id} 不在名册里")
    if assignee_id is None and viewer is not None:
        assignee_id = viewer.member_id
    if viewer is not None and not visibility.is_captain(db, viewer, parent.project_id):
        if assignee_id not in (None, viewer.member_id):
            raise HTTPException(403, "组员只能把小块指派给自己")
    row = subtask_service.create_subtask(
        db, task_id, actor_id, body.title, body.description, body.status, assignee_id)
    return _row_dict(db, row)


@router.patch("/subtasks/{subtask_id}", response_model=SubtaskOut)
def update_task_subtask(
    subtask_id: int,
    body: SubtaskUpdate,
    viewer: Optional[visibility.Viewer] = Depends(optional_viewer),
    db: Session = Depends(get_db),
):
    row = subtask_service.get_subtask(db, subtask_id)
    if row is None:
        raise HTTPException(404, f"小块 {subtask_id} 不存在")
    parent = _parent_or_404(db, row.parent_task_id)
    _require_parent_access(db, parent, viewer)
    if viewer is not None and not visibility.is_captain(db, viewer, parent.project_id):
        allowed = {row.assignee_id, parent.assignee_id}
        if viewer.member_id not in allowed and viewer.user_id != row.creator_id:
            raise HTTPException(403, "只能推进自己负责的小块")
        if body.assignee_id is not None and body.assignee_id != viewer.member_id:
            raise HTTPException(403, "组员只能把小块指派给自己")
    if body.assignee_id is not None and db.get(Member, body.assignee_id) is None:
        raise HTTPException(404, f"成员 {body.assignee_id} 不在名册里")
    updated = subtask_service.update_subtask(
        db, subtask_id, title=body.title, description=body.description,
        status=body.status, assignee_id=body.assignee_id)
    return _row_dict(db, updated)
