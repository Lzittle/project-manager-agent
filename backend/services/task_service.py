"""任务业务服务：任务增删改查 + 评论。

与 project_service 相同约定：db 由调用方传入，ORM 对象返回，本层提交事务。
"""
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from models.database import Project, Task, TaskComment


# ---------- 任务 ----------
def list_tasks(db: Session, project_id: int) -> list[Task]:
    return (db.query(Task)
            .filter_by(project_id=project_id)
            .order_by(Task.id.desc())
            .all())


def get_task(db: Session, task_id: int) -> Optional[Task]:
    return db.get(Task, task_id)


def create_task(
    db: Session,
    project_id: int,
    user_id: int,
    title: str,
    description: str = "",
    status: str = "todo",
    priority: str = "medium",
    due_date: Optional[date] = None,
) -> Task:
    """在指定项目下创建任务；项目不存在返回 None。"""
    if db.get(Project, project_id) is None:
        return None
    t = Task(title=title, description=description or "", status=status,
             priority=priority, project_id=project_id,
             assignee_id=user_id, due_date=due_date)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def update_task(db: Session, task_id: int, **fields) -> Optional[Task]:
    t = db.get(Task, task_id)
    if t is None:
        return None
    for key, value in fields.items():
        if value is not None and hasattr(t, key):
            setattr(t, key, value)
    db.commit()
    db.refresh(t)
    return t


def delete_task(db: Session, task_id: int) -> Optional[Task]:
    t = db.get(Task, task_id)
    if t is None:
        return None
    db.query(TaskComment).filter_by(task_id=task_id).delete(synchronize_session=False)
    db.delete(t)
    db.commit()
    return t


# ---------- 任务评论 ----------
def list_comments(db: Session, task_id: int) -> list[TaskComment]:
    return (db.query(TaskComment)
            .filter_by(task_id=task_id)
            .order_by(TaskComment.id.asc())
            .all())


def add_comment(db: Session, task_id: int, user_id: int, content: str) -> Optional[TaskComment]:
    if db.get(Task, task_id) is None:
        return None
    c = TaskComment(content=content, task_id=task_id, user_id=user_id)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c
