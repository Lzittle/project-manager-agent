"""项目接口 /api/projects

demo 阶段无登录体系：列表/创建通过 ?user_id= 传当前用户（seed 用户 id=1）。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from models.database import get_db
from models.schemas import ProjectCreate, ProjectUpdate, ProjectOut
from services import project_service

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


@router.delete("/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db)):
    p = project_service.delete_project(db, project_id)
    if p is None:
        raise HTTPException(404, f"项目 {project_id} 不存在")
    return {"deleted": True, "id": project_id}
