"""任务小块业务服务：创建、查询、更新与父任务汇总。"""
from collections import defaultdict
from typing import Optional

from sqlalchemy.orm import Session

from models.database import Member, Task
from models.task_breakdown import Subtask


def list_subtasks(db: Session, parent_task_id: int) -> list[Subtask]:
    return (db.query(Subtask)
            .filter_by(parent_task_id=parent_task_id)
            .order_by(Subtask.id.asc())
            .all())


def get_subtask(db: Session, subtask_id: int) -> Optional[Subtask]:
    return db.get(Subtask, subtask_id)


def create_subtask(db: Session, parent_task_id: int, creator_id: int,
                   title: str, description: str = "", status: str = "todo",
                   assignee_id: Optional[int] = None) -> Optional[Subtask]:
    if db.get(Task, parent_task_id) is None:
        return None
    row = Subtask(parent_task_id=parent_task_id, creator_id=creator_id,
                  title=title.strip(), description=description or "",
                  status=status, assignee_id=assignee_id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_subtask(db: Session, subtask_id: int, **fields) -> Optional[Subtask]:
    row = db.get(Subtask, subtask_id)
    if row is None:
        return None
    for key, value in fields.items():
        if value is not None and hasattr(row, key):
            setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return row


def delete_for_parent(db: Session, parent_task_id: int) -> int:
    return db.query(Subtask).filter_by(parent_task_id=parent_task_id).delete(
        synchronize_session=False)


def delete_for_tasks(db: Session, task_ids: list[int]) -> int:
    if not task_ids:
        return 0
    return db.query(Subtask).filter(Subtask.parent_task_id.in_(task_ids)).delete(
        synchronize_session=False)


def summaries(db: Session, parent_task_ids: list[int]) -> dict[int, dict[str, int]]:
    """批量计算父任务的小块总数与完成数，避免列表接口 N+1。"""
    if not parent_task_ids:
        return {}
    counts = defaultdict(lambda: {"subtask_count": 0, "subtask_done_count": 0})
    rows = (db.query(Subtask.parent_task_id, Subtask.status)
            .filter(Subtask.parent_task_id.in_(parent_task_ids)).all())
    for parent_id, status in rows:
        counts[parent_id]["subtask_count"] += 1
        if status == "done":
            counts[parent_id]["subtask_done_count"] += 1
    return dict(counts)


def assignee_map(db: Session, rows: list[Subtask]) -> dict[int, Member]:
    ids = {row.assignee_id for row in rows if row.assignee_id}
    if not ids:
        return {}
    return {m.id: m for m in db.query(Member).filter(Member.id.in_(ids)).all()}
