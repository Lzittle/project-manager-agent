"""项目业务服务：项目增删改查。

约定：函数接收 db(Session) 与业务参数，ORM 对象为返回值，提交事务由本层完成。
     查询不到返回 None（由调用方决定 404 或错误文案）。
"""
from typing import Optional

from sqlalchemy.orm import Session

from core import rag
from models.database import Project, Task, TaskComment, KnowledgeDocument

MAX_PROJECT_DEPTH = 3  # 项目层级上限：根(1 级) → 子项目(2 级) → 孙项目(3 级)


def list_projects(db: Session, user_id: int) -> list[Project]:
    return (db.query(Project)
            .filter_by(creator_id=user_id)
            .order_by(Project.id.desc())
            .all())


def get_project(db: Session, project_id: int) -> Optional[Project]:
    return db.get(Project, project_id)


def _parent_level(db: Session, project: Project) -> int:
    """沿 parent 链向上数项目所处层级（根=1）。带防环保护，遇环/缺引用即停。"""
    level = 1
    seen = set()
    cur = project
    while cur.parent_id is not None:
        if cur.id in seen:
            break
        seen.add(cur.id)
        cur = db.get(Project, cur.parent_id)
        if cur is None:
            break
        level += 1
    return level


def create_project(db: Session, user_id: int, name: str, description: str = "",
                   parent_id: Optional[int] = None) -> Project:
    """创建项目；parent_id 非空时创建为某项目的「子项目/小项目」。

    校验：父项目必须存在、属于同一用户、未归档，且层级未达上限
    （避免跨用户挂靠与无限嵌套）。
    """
    if parent_id is not None:
        parent = db.get(Project, parent_id)
        if parent is None:
            raise ValueError(f"父项目 {parent_id} 不存在")
        if parent.creator_id != user_id:
            raise ValueError("不能在其他用户的项目下创建子项目")
        if parent.status == "archived":
            raise ValueError("已归档的项目不能再挂子项目")
        if _parent_level(db, parent) + 1 > MAX_PROJECT_DEPTH:
            raise ValueError(f"项目层级已达 {MAX_PROJECT_DEPTH} 级上限，无法继续创建子项目")
    p = Project(name=name, description=description or "", status="active",
                creator_id=user_id, parent_id=parent_id)
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


def _descendant_postorder(db: Session, project_id: int) -> list[int]:
    """整棵子树的「后序」项目 id（先子后父，最深优先）。

    删除级联用：先删干净每个子项目（任务/评论/文档/向量），最后删根，
    保证任意层级都不留孤儿数据。
    """
    out: list[int] = []

    def walk(pid: int) -> None:
        for c in db.query(Project).filter_by(parent_id=pid).all():
            walk(c.id)
        out.append(pid)

    walk(project_id)
    return out


def _delete_one(db: Session, project_id: int) -> Optional[dict]:
    """删除单个项目及其从属数据（任务/评论/文档），文档向量同步清理。"""
    p = db.get(Project, project_id)
    if p is None:
        return None
    snapshot = {"id": p.id, "name": p.name, "description": p.description,
                "status": p.status, "parent_id": p.parent_id}

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


def delete_project(db: Session, project_id: int) -> Optional[dict]:
    """删除项目及其整棵子树（子项目 → 子任务的从属数据一并清理）。

    后序遍历保证先删叶子子项目、最后删根；返回被删根项目的删除前快照。
    """
    root = db.get(Project, project_id)
    if root is None:
        return None
    snapshot = {"id": root.id, "name": root.name,
                "description": root.description, "status": root.status}
    order = _descendant_postorder(db, project_id)  # 含根，位于末尾
    for pid in order:
        _delete_one(db, pid)
    return snapshot
