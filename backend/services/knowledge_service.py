"""知识库业务服务：文档增删查，写入/删除时同步维护 ChromaDB 向量。

上传流程：落库拿 doc.id -> RAG 分块向量化；任一失败则回滚并清理孤儿向量。
"""
from typing import Optional

from sqlalchemy.orm import Session

from core import rag
from models.database import KnowledgeDocument


def create_document(
    db: Session,
    project_id: int,
    title: str,
    content: str,
    file_type: str = "txt",
    doc_type: str = "doc",
) -> Optional[KnowledgeDocument]:
    from models.database import Project
    if db.get(Project, project_id) is None:
        return None
    if doc_type not in ("doc", "meeting"):
        doc_type = "doc"

    doc = KnowledgeDocument(title=title, content=content,
                            file_type=file_type, project_id=project_id,
                            doc_type=doc_type)
    db.add(doc)
    db.flush()  # 先拿到 doc.id 供向量库使用
    try:
        rag.index_document(doc.id, project_id, title, content)
    except Exception:
        db.rollback()
        rag.delete_document(doc.id)  # 清理可能写入的孤儿向量
        raise
    db.commit()
    db.refresh(doc)
    return doc


def list_documents(db: Session, project_id: int) -> list[KnowledgeDocument]:
    return (db.query(KnowledgeDocument)
            .filter_by(project_id=project_id)
            .order_by(KnowledgeDocument.id.desc())
            .all())


def get_document(db: Session, doc_id: int) -> Optional[KnowledgeDocument]:
    return db.get(KnowledgeDocument, doc_id)


def delete_document(db: Session, doc_id: int) -> Optional[KnowledgeDocument]:
    doc = db.get(KnowledgeDocument, doc_id)
    if doc is None:
        return None
    rag.delete_document(doc.id)
    db.delete(doc)
    db.commit()
    return doc
