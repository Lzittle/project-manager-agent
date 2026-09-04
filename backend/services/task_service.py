"""任务业务服务：任务增删改查 + 依赖关系 + 评论。

与 project_service 相同约定：db 由调用方传入，ORM 对象返回，本层提交事务。
"""
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from models.database import Project, Task, TaskComment, TaskDependency


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


def delete_task(db: Session, task_id: int) -> Optional[dict]:
    """删除任务（级联删除评论 + 依赖关系双向清理）。

    返回删除前快照 dict；commit 后 ORM 对象已失效不可读。
    """
    t = db.get(Task, task_id)
    if t is None:
        return None
    snapshot = {"id": t.id, "title": t.title, "status": t.status, "project_id": t.project_id}
    # 本任务作为依赖方（task_id=本任务）与作为前置（depends_on_id=本任务）的行都删掉
    db.query(TaskDependency).filter(
        (TaskDependency.task_id == task_id) | (TaskDependency.depends_on_id == task_id)
    ).delete(synchronize_session=False)
    db.query(TaskComment).filter_by(task_id=task_id).delete(synchronize_session=False)
    db.delete(t)
    db.commit()
    return snapshot


# ---------- 任务依赖 ----------
def add_dependency(db: Session, task_id: int, depends_on_id: int):
    """建立依赖：task_id 依赖 depends_on_id（前置任务）。

    校验（面试可讲）：
      - 两个任务都必须存在，且属于同一项目（杜绝跨项目依赖）；
      - 禁止自依赖（任务不能依赖自己）；
      - 禁止重复（联合唯一语义，先查后插；重复视为幂等成功，不报错）；
      - 禁止成环（A→B 后再建 B→A 会形成死锁式的环，需拦截）。

    返回 (dep, created)：dep 为 TaskDependency 或 None（校验失败），
    created=True 表示新建、False 表示已存在（幂等）。
    """
    if task_id == depends_on_id:
        return None, False
    t1, t2 = db.get(Task, task_id), db.get(Task, depends_on_id)
    if t1 is None or t2 is None or t1.project_id != t2.project_id:
        return None, False
    exists = (db.query(TaskDependency)
              .filter_by(task_id=task_id, depends_on_id=depends_on_id).first())
    if exists:
        return exists, False  # 已存在：幂等成功
    if _would_create_cycle(db, task_id, depends_on_id):
        return None, False
    d = TaskDependency(task_id=task_id, depends_on_id=depends_on_id)
    db.add(d)
    db.commit()
    db.refresh(d)
    return d, True


def _would_create_cycle(db: Session, task_id: int, depends_on_id: int) -> bool:
    """加边 task_id→depends_on_id 前，判断是否成环。

    思路：若 depends_on_id 已经（直接或间接）依赖 task_id，
    则再加 task_id→depends_on_id 会闭环。沿「前置链」DFS/BFS 找环。
    """
    # 邻接：x -> x 依赖的所有前置任务 id
    adj = {}
    rows = db.query(TaskDependency).all()
    for r in rows:
        adj.setdefault(r.task_id, set()).add(r.depends_on_id)

    # 从 depends_on_id 出发沿前置链遍历，看能否回到 task_id
    stack, seen = [depends_on_id], set()
    while stack:
        cur = stack.pop()
        if cur == task_id:
            return True
        if cur in seen:
            continue
        seen.add(cur)
        for pre in adj.get(cur, set()):
            stack.append(pre)
    return False


def remove_dependency(db: Session, task_id: int, depends_on_id: int) -> bool:
    """移除依赖关系；返回是否确实删除了一条。"""
    d = (db.query(TaskDependency)
         .filter_by(task_id=task_id, depends_on_id=depends_on_id).first())
    if d is None:
        return False
    db.delete(d)
    db.commit()
    return True


def list_task_dependencies(db: Session, task_id: int) -> list[TaskDependency]:
    """某任务的全部前置依赖（task 需要等它们完成）。"""
    return (db.query(TaskDependency)
            .filter_by(task_id=task_id)
            .order_by(TaskDependency.id.asc())
            .all())


def list_project_dependencies(db: Session, project_id: int) -> list[dict]:
    """某项目全部依赖边，展开为可读 dict（含标题），供看板/Agent 展示。

    返回形如：[{"task_id":3,"task_title":"联调","depends_on_id":2,
               "depends_on_title":"后端接口","depends_on_status":"done"}, ...]
    """
    rows = (db.query(TaskDependency, Task)
            .join(Task, Task.id == TaskDependency.task_id)
            .filter(Task.project_id == project_id)
            .order_by(TaskDependency.id.asc())
            .all())
    out = []
    for d, t in rows:
        pre = db.get(Task, d.depends_on_id)
        out.append({
            "task_id": d.task_id,
            "task_title": t.title,
            "depends_on_id": d.depends_on_id,
            "depends_on_title": pre.title if pre else None,
            "depends_on_status": pre.status if pre else None,
        })
    return out


def downstream_impact(db: Session, task_id: int) -> list[Task]:
    """影响分析：某任务若延期/未完成，会阻塞哪些下游任务（直接+间接）。

    面试对应问题「前置任务延期怎么评估对里程碑的影响」：
    沿「被依赖」方向 BFS——所有直接依赖 task 的任务、以及依赖它们的任务……
    返回按拓扑层序的任务列表（不重复）。
    """
    # 反向邻接：x <- 依赖 x 的任务集合（x 是前置，谁依赖 x）
    rev = {}
    rows = db.query(TaskDependency).all()
    for r in rows:
        rev.setdefault(r.depends_on_id, set()).add(r.task_id)

    result, seen, queue = [], {task_id}, [task_id]
    while queue:
        cur = queue.pop(0)
        for nxt in rev.get(cur, set()):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
                t = db.get(Task, nxt)
                if t:
                    result.append(t)
    return result


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
