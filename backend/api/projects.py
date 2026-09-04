"""项目接口 /api/projects

demo 阶段无登录体系：列表/创建通过 ?user_id= 传当前用户（seed 用户 id=1）。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from models.database import get_db
from models.schemas import ProjectCreate, ProjectUpdate, ProjectOut
from services import project_service, task_service
from core.agent import _ToolExecutor

router = APIRouter()


@router.get("", response_model=list[ProjectOut])
def list_projects(user_id: int = Query(..., description="当前用户 id"), db: Session = Depends(get_db)):
    projects = project_service.list_projects(db, user_id)
    # 附任务数便于看板展示
    return projects


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(
    body: ProjectCreate,
    user_id: int = Query(..., description="当前用户 id"),
    db: Session = Depends(get_db),
):
    return project_service.create_project(db, user_id, body.name, body.description)


@router.get("/{project_id}/dependencies")
def list_project_dependencies(project_id: int, db: Session = Depends(get_db)):
    """项目全部任务依赖边（含标题/状态），前端画依赖图或 Agent 分析用。"""
    p = project_service.get_project(db, project_id)
    if p is None:
        raise HTTPException(404, f"项目 {project_id} 不存在")
    return task_service.list_project_dependencies(db, project_id)


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db)):
    p = project_service.get_project(db, project_id)
    if p is None:
        raise HTTPException(404, f"项目 {project_id} 不存在")
    return p


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(project_id: int, body: ProjectUpdate, db: Session = Depends(get_db)):
    p = project_service.update_project(
        db, project_id,
        name=body.name, description=body.description, status=body.status,
    )
    if p is None:
        raise HTTPException(404, f"项目 {project_id} 不存在")
    return p


@router.post("/{project_id}/plan")
def plan_project_tasks(project_id: int,
                       user_id: int = Query(..., description="当前用户 id"),
                       db: Session = Depends(get_db)):
    """看板「一键规划」：按项目主题让 AI 自动生成并创建任务（与对话内规划同一条代码路径）。

    供新建项目弹窗勾选「创建后由 AI 自动规划任务」调用；LLM 生成失败等异常返回 400。
    """
    if project_service.get_project(db, project_id) is None:
        raise HTTPException(404, f"项目 {project_id} 不存在")
    res = _ToolExecutor(user_id, project_id).plan_tasks()
    if not res.get("ok"):
        raise HTTPException(400, res.get("error", "任务规划失败"))
    return {"planned": len(res["data"]), "tasks": res["data"],
            "note": res.get("note", "")}


@router.delete("/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db)):
    p = project_service.delete_project(db, project_id)
    if p is None:
        raise HTTPException(404, f"项目 {project_id} 不存在")
    return {"deleted": True, "id": project_id}
