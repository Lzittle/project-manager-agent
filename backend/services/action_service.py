"""批量动作方案 + 撤销台账（阶段 3，D-028）。

两件事都在这里，因为它们是同一份数据的两个阶段：

1. **待确认方案**：批量改状态 / 批量删除先写一条 pending 的 ActionRun，不碰 tasks；
   用户确认后才由执行器落库（「先方案后落库」，和按名单分配同一套节奏）。
2. **撤销台账**：每次落库都把「动作之前的原样」存进 ActionRun.undo，
   一句话「撤销」按它回滚 —— 批量改状态改回原状态、指派改回原负责人、
   删除按快照把任务放回来（含原 id、负责人、依赖边与评论）。

本层只管数据和回滚，不懂对话；db 由调用方传入、ORM 对象返回，与其它 service 一致。
"""
import json
from datetime import date, datetime
from typing import Optional

from sqlalchemy.orm import Session

from models.database import ActionRun, Task, TaskComment, TaskDependency

# 台账里 kind 的中文说法（给用户看的回复里要用）
KIND_CN = {
    "bulk_status": "批量改状态",
    "bulk_delete": "批量删除",
    "assign": "指派",
    "assign_batch": "按名单分配",
    "task_update": "编辑任务",
    "task_delete": "删除任务",
}


# ---------- 待确认方案 ----------
def create_plan(db: Session, project_id: int, user_id: int, kind: str,
                items: list[dict]) -> ActionRun:
    """写一条待确认的批量方案；同一项目同时只留一条（新方案作废旧方案）。"""
    db.query(ActionRun).filter_by(project_id=project_id, user_id=user_id,
                                  status="pending").delete(synchronize_session=False)
    run = ActionRun(project_id=project_id, user_id=user_id, kind=kind,
                    items=json.dumps(items, ensure_ascii=False), status="pending")
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def get_run(db: Session, run_id: int) -> Optional[ActionRun]:
    return db.get(ActionRun, run_id)


def get_pending(db: Session, user_id: int,
                project_id: Optional[int] = None) -> Optional[ActionRun]:
    """最近一份还没落库的批量方案（可限定项目）。"""
    q = db.query(ActionRun).filter_by(user_id=user_id, status="pending")
    if project_id is not None:
        q = q.filter(ActionRun.project_id == project_id)
    return q.order_by(ActionRun.id.desc()).first()


# ---------- 落库台账 ----------
def record_applied(db: Session, project_id: Optional[int], user_id: int, kind: str,
                   items: list[dict], undo: list[dict]) -> ActionRun:
    """把一次「已经落库」的动作记进台账（撤销用）。

    直接写库的单任务动作（改状态/编辑/删除/指派）走这里，没有 pending 阶段 ——
    台账只负责留一份"怎么改回去"。
    """
    run = ActionRun(project_id=project_id, user_id=user_id, kind=kind,
                    items=json.dumps(items, ensure_ascii=False),
                    undo=json.dumps(undo, ensure_ascii=False),
                    status="applied", applied_count=len(items))
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def mark_applied(db: Session, run: ActionRun, undo: list[dict],
                 applied_count: int) -> ActionRun:
    """方案落库：记下撤销快照并置为 applied。"""
    run.undo = json.dumps(undo, ensure_ascii=False)
    run.status = "applied"
    run.applied_count = applied_count
    db.commit()
    db.refresh(run)
    return run


def latest_undoable(db: Session, user_id: int,
                    project_id: Optional[int] = None) -> Optional[ActionRun]:
    """最近一次可以撤销的落库动作（已经撤销过的不算）。"""
    q = db.query(ActionRun).filter_by(user_id=user_id, status="applied")
    if project_id is not None:
        q = q.filter(ActionRun.project_id == project_id)
    return q.order_by(ActionRun.id.desc()).first()


# ---------- 快照 ----------
def task_snapshot(t: Task) -> dict:
    """任务全字段快照（删除后要按它原样放回来）。"""
    return {
        "id": t.id, "title": t.title, "description": t.description or "",
        "status": t.status, "priority": t.priority, "project_id": t.project_id,
        "assignee_id": t.assignee_id,
        "due_date": t.due_date.isoformat() if t.due_date else None,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


def task_restore_payload(db: Session, task_id: int) -> Optional[dict]:
    """删除前的完整留档：任务字段 + 双向依赖边 + 评论。"""
    t = db.get(Task, task_id)
    if t is None:
        return None
    deps = (db.query(TaskDependency)
            .filter((TaskDependency.task_id == task_id)
                    | (TaskDependency.depends_on_id == task_id)).all())
    comments = (db.query(TaskComment).filter_by(task_id=task_id)
                .order_by(TaskComment.id.asc()).all())
    return {
        "task": task_snapshot(t),
        "dependencies": [[d.task_id, d.depends_on_id] for d in deps],
        "comments": [{"content": c.content, "user_id": c.user_id} for c in comments],
    }


def field_undo(task_id: int, **before) -> dict:
    """「把某些字段改回原样」的撤销条目（只放要回滚的字段）。"""
    return {"type": "task_fields", "task_id": task_id, "before": before}


def restore_undo(payload: dict) -> dict:
    """「把删掉的任务放回来」的撤销条目。"""
    return {"type": "task_restore", **payload}


# ---------- 撤销 ----------
def undo(db: Session, run: ActionRun) -> dict:
    """按台账把这次动作回滚。返回恢复了什么、跳过了什么。"""
    entries = json.loads(run.undo or "[]")
    restored_tasks, restored_fields, skipped = [], [], []

    # 1) 先把被删的任务按原 id 放回来（依赖边与评论要等两端任务都在以后再补）
    for e in entries:
        if e.get("type") != "task_restore":
            continue
        snap = dict(e.get("task") or {})
        tid = snap.get("id")
        if tid is None:
            continue
        if db.get(Task, tid) is not None:
            skipped.append(f"#{tid}（已存在，没动）")
            continue
        due = snap.pop("due_date", None)
        created = snap.pop("created_at", None)
        t = Task(**snap)
        if due:
            try:
                t.due_date = date.fromisoformat(due)
            except ValueError:
                pass
        if created:
            try:
                t.created_at = datetime.fromisoformat(created)
            except ValueError:
                pass
        db.add(t)
        restored_tasks.append({"id": tid, "title": snap.get("title", "")})
    db.flush()

    # 2) 再把字段改回原样（状态 / 负责人 / 标题 / 描述 / 优先级）
    for e in entries:
        if e.get("type") != "task_fields":
            continue
        t = db.get(Task, e.get("task_id"))
        if t is None:
            skipped.append(f"#{e.get('task_id')}（任务已不存在，跳过）")
            continue
        before = e.get("before") or {}
        for key, value in before.items():
            if hasattr(t, key):
                setattr(t, key, value)
        restored_fields.append({"id": t.id, "title": t.title, "restored": before})
    db.flush()

    # 3) 最后补依赖边与评论（两端任务都在了才不会留下半条边）
    dep_restored, comments_restored = 0, 0
    for e in entries:
        if e.get("type") != "task_restore":
            continue
        for pair in e.get("dependencies") or []:
            try:
                a, b = int(pair[0]), int(pair[1])
            except (TypeError, ValueError, IndexError):
                continue
            if db.get(Task, a) is None or db.get(Task, b) is None:
                continue
            exists = (db.query(TaskDependency)
                      .filter_by(task_id=a, depends_on_id=b).first())
            if exists is None:
                db.add(TaskDependency(task_id=a, depends_on_id=b))
                dep_restored += 1
        for c in e.get("comments") or []:
            db.add(TaskComment(task_id=e["task"]["id"], user_id=c.get("user_id"),
                               content=c.get("content") or ""))
            comments_restored += 1

    db.commit()
    return {"restored_tasks": restored_tasks, "restored_fields": restored_fields,
            "dependencies_restored": dep_restored, "comments_restored": comments_restored,
            "skipped": skipped}


def mark_undone(db: Session, run: ActionRun) -> ActionRun:
    run.status = "undone"
    db.commit()
    db.refresh(run)
    return run
