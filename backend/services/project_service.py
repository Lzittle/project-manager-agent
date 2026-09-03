"""项目业务服务：项目增删改查。

约定：函数接收 db(Session) 与业务参数，ORM 对象为返回值，提交事务由本层完成。
     查询不到返回 None（由调用方决定 404 或错误文案）。
"""
from typing import Optional

from sqlalchemy.orm import Session

from core import rag
from models.database import Project, Task, TaskComment, KnowledgeDocument


def list_projects(db: Session, user_id: int) -> list[Project]:
    return (db.query(Project)
            .filter_by(creator_id=user_id)
            .order_by(Project.id.desc())
            .all())


def get_project(db: Session, project_id: int) -> Optional[Project]:
    return db.get(Project, project_id)


def create_project(db: Session, user_id: int, name: str, description: str = "") -> Project:
    p = Project(name=name, description=description or "", status="active", creator_id=user_id)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def update_project(db: Session, project_id: int, **fields) -> Optional[Project]:
    """fields 中值为 None 的键跳过（支持部分更新）。"""
    p = db.get(Project, project_id)
    if p is None:
        return None
    for key, value in fields.items():
        if value is not None and hasattr(p, key):
            setattr(p, key, value)
    db.commit()
    db.refresh(p)
    return p


def delete_project(db: Session, project_id: int) -> Optional[dict]:
    """删除项目及其全部从属数据（任务/评论/文档），文档向量同步清理。
    返回删除前快照 dict；commit 后 ORM 对象已失效不可读。"""
    p = db.get(Project, project_id)
    if p is None:
        return None
    snapshot = {"id": p.id, "name": p.name, "description": p.description, "status": p.status}

    # 1) 文档及其向量
    for doc in db.query(KnowledgeDocument).filter_by(project_id=project_id).all():
        rag.delete_document(doc.id)
    db.query(KnowledgeDocument).filter_by(project_id=project_id).delete(synchronize_session=False)

    # 2) 任务与任务评论
    task_ids = [t.id for t in db.query(Task).filter_by(project_id=project_id).all()]
    if task_ids:
        db.query(TaskComment).filter(TaskComment.task_id.in_(task_ids)).delete(
            synchronize_session=False)
        db.query(Task).filter(Task.id.in_(task_ids)).delete(synchronize_session=False)

    # 3) 项目本身
    db.delete(p)
    db.commit()
    return snapshot
