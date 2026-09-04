"""任务接口 /api/tasks（含评论子资源与依赖子资源）

列表/创建通过 ?project_id= 定位项目；user_id 用于记录创建人/评论人。
"""

def _with_deps(task) -> dict:
    """给 Task ORM 补 depends_on 摘要（前置任务 id 列表）后转 dict，
    使列表/详情接口都能直接看到依赖关系，前端无需二次请求。"""
    d = {c.name: getattr(task, c.name) for c in task.__table__.columns}
    d["depends_on"] = [dep.depends_on_id for dep in task.dependencies]
    return d


from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from models.database import get_db
from models.schemas import TaskCreate, TaskUpdate, TaskOut, CommentCreate, CommentOut, DependencyCreate
from services import task_service

router = APIRouter()


@router.get("", response_model=list[TaskOut])
def list_tasks(project_id: int = Query(..., description="项目 id"), db: Session = Depends(get_db)):
    tasks = task_service.list_tasks(db, project_id)
    return [_with_deps(t) for t in tasks]


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
    return _with_deps(t)


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: int, db: Session = Depends(get_db)):
    t = task_service.get_task(db, task_id)
    if t is None:
        raise HTTPException(404, f"任务 {task_id} 不存在")
    return _with_deps(t)


@router.patch("/{task_id}", response_model=TaskOut)
def update_task(task_id: int, body: TaskUpdate, db: Session = Depends(get_db)):
    t = task_service.update_task(
        db, task_id,
        title=body.title, description=body.description, status=body.status,
        priority=body.priority, assignee_id=body.assignee_id, due_date=body.due_date,
    )
    if t is None:
        raise HTTPException(404, f"任务 {task_id} 不存在")
    return _with_deps(t)


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


# ---------- 任务依赖 ----------
@router.get("/{task_id}/dependencies", response_model=list[dict])
def get_task_dependencies(task_id: int, db: Session = Depends(get_db)):
    """某任务的全部前置依赖（需等它们完成后本任务才能开始）。"""
    if task_service.get_task(db, task_id) is None:
        raise HTTPException(404, f"任务 {task_id} 不存在")
    deps = task_service.list_task_dependencies(db, task_id)
    return [{"task_id": d.task_id, "depends_on_id": d.depends_on_id} for d in deps]


@router.post("/{task_id}/dependencies", response_model=dict, status_code=201)
def add_task_dependency(task_id: int, body: DependencyCreate, db: Session = Depends(get_db)):
    """建立依赖：URL 的 task_id 依赖 body.depends_on_id。

    - 新建成功 → 201；已存在同一条 → 200（幂等，Agent 重试不报错）；
    - 自依赖 / 成环 → 400；任务不存在 / 跨项目 → 404/400。
    """
    # 以 URL task_id 为准
    dep, created = task_service.add_dependency(db, task_id, body.depends_on_id)
    if dep is not None:
        if created:
            return {"ok": True, "task_id": task_id, "depends_on_id": body.depends_on_id,
                    "created": True}
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=200,
            content={"ok": True, "task_id": task_id, "depends_on_id": body.depends_on_id,
                     "created": False, "note": "依赖已存在（幂等）"},
        )
    # 失败：区分 404（任务不存在/跨项目）与 400（自依赖/成环）
    t = task_service.get_task(db, task_id)
    pre = task_service.get_task(db, body.depends_on_id)
    if t is None:
        raise HTTPException(404, f"任务 {task_id} 不存在")
    if pre is None:
        raise HTTPException(404, f"前置任务 {body.depends_on_id} 不存在")
    if t.project_id != pre.project_id:
        raise HTTPException(400, "不能跨项目建立任务依赖")
    raise HTTPException(400, "依赖不合法：自依赖 / 会成环")


@router.delete("/{task_id}/dependencies/{depends_on_id}")
def remove_task_dependency(task_id: int, depends_on_id: int, db: Session = Depends(get_db)):
    ok = task_service.remove_dependency(db, task_id, depends_on_id)
    if not ok:
        raise HTTPException(404, f"依赖 {task_id}→{depends_on_id} 不存在")
    return {"deleted": True, "task_id": task_id, "depends_on_id": depends_on_id}


@router.get("/{task_id}/impact")
def get_downstream_impact(task_id: int, db: Session = Depends(get_db)):
    """影响分析：本任务未完成会阻塞哪些下游任务（直接+间接依赖它的任务）。"""
    if task_service.get_task(db, task_id) is None:
        raise HTTPException(404, f"任务 {task_id} 不存在")
    blocked = task_service.downstream_impact(db, task_id)
    return {
        "task_id": task_id,
        "blocked_count": len(blocked),
        "blocked_tasks": [
            {"id": t.id, "title": t.title, "status": t.status} for t in blocked
        ],
    }
