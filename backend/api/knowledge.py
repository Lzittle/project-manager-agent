"""知识库接口：项目文档上传/列表/删除

- 上传：multipart/form-data，file 必传（txt/md 等文本），title 可选（默认文件名）
- 落库后自动分块写入 ChromaDB，供 Agent RAG 检索
"""
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from sqlalchemy.orm import Session

from models.database import get_db
from models.schemas import KnowledgeDocOut
from services import knowledge_service, project_service

router = APIRouter()


@router.get("/projects/{project_id}/documents", response_model=list[KnowledgeDocOut])
def list_documents(project_id: int, db: Session = Depends(get_db)):
    if project_service.get_project(db, project_id) is None:
        raise HTTPException(404, f"项目 {project_id} 不存在")
    return knowledge_service.list_documents(db, project_id)


@router.post("/projects/{project_id}/documents", response_model=KnowledgeDocOut, status_code=201)
async def upload_document(
    project_id: int,
    file: UploadFile = File(...),
    title: str | None = Form(None),
    db: Session = Depends(get_db),
):
    raw = await file.read()
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(400, "仅支持 UTF-8 文本文件（txt/md）")

    filename = file.filename or "untitled.txt"
    doc_title = title or filename
    # 扩展名推断 file_type
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "txt"

    doc = knowledge_service.create_document(db, project_id, doc_title, content, ext)
    if doc is None:
        raise HTTPException(404, f"项目 {project_id} 不存在")
    return doc


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: int, db: Session = Depends(get_db)):
    doc = knowledge_service.delete_document(db, doc_id)
    if doc is None:
        raise HTTPException(404, f"文档 {doc_id} 不存在")
    return {"deleted": True, "id": doc_id}
