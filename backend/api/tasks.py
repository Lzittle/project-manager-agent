"""任务接口 /api/tasks（含 /api/tasks/{id}/comments 评论子资源）

列表/创建通过 ?project_id= 定位项目；user_id 用于记录创建人/评论人。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from models.database import get_db
from models.schemas import TaskCreate, TaskUpdate, TaskOut, CommentCreate, CommentOut
from services import task_service

router = APIRouter()


@router.get("", response_model=list[TaskOut])
def list_tasks(project_id: int = Query(..., description="项目 id"), db: Session = Depends(get_db)):
    return task_service.list_tasks(db, project_id)


@router.post("", response_model=TaskOut, status_code=201)
def create_task(
    body: TaskCreate,
    user_id: int = Query(..., description="当前用户 id"),
    db: Session = Depends(get_db),
):
    t = task_service.create_task(
        db, body.project_id, user_id, body.title,
        description=body.description, status=body.status,
        priority=body.priority, due_date=body.due_date,
    )
    if t is None:
        raise HTTPException(404, f"项目 {body.project_id} 不存在")
    return t


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: int, db: Session = Depends(get_db)):
    t = task_service.get_task(db, task_id)
    if t is None:
        raise HTTPException(404, f"任务 {task_id} 不存在")
    return t


@router.patch("/{task_id}", response_model=TaskOut)
def update_task(task_id: int, body: TaskUpdate, db: Session = Depends(get_db)):
    t = task_service.update_task(
        db, task_id,
        title=body.title, description=body.description, status=body.status,
        priority=body.priority, assignee_id=body.assignee_id, due_date=body.due_date,
    )
    if t is None:
        raise HTTPException(404, f"任务 {task_id} 不存在")
    return t


@router.delete("/{task_id}")
def delete_task(task_id: int, db: Session = Depends(get_db)):
    t = task_service.delete_task(db, task_id)
    if t is None:
        raise HTTPException(404, f"任务 {task_id} 不存在")
    return {"deleted": True, "id": task_id}


# ---------- 任务评论 ----------
@router.get("/{task_id}/comments", response_model=list[CommentOut])
def list_comments(task_id: int, db: Session = Depends(get_db)):
    return task_service.list_comments(db, task_id)


@router.post("/{task_id}/comments", response_model=CommentOut, status_code=201)
def add_comment(
    task_id: int,
    body: CommentCreate,
    user_id: int = Query(..., description="当前用户 id"),
    db: Session = Depends(get_db),
):
    # 以 URL 的 task_id 为准，忽略 body 中的冗余字段
    c = task_service.add_comment(db, task_id, user_id, body.content)
    if c is None:
        raise HTTPException(404, f"任务 {task_id} 不存在")
    return c
