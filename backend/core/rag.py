"""RAG 检索模块（ChromaDB）：知识库文档入库分块 + Top-K 相似度检索。

- 向量持久化目录与集合名取自 .env（CHROMA_PERSIST_DIR / CHROMA_COLLECTION）
- embedding 使用 ChromaDB 内置 ONNX MiniLM（首次运行自动下载模型，离线可用、不依赖外部 key）
- 每个 chunk 的 metadata 记录所属数据库文档 id 与项目 id，支持按项目过滤检索
"""
from typing import Optional

import chromadb
from chromadb.utils import embedding_functions

from core.config import settings

_client = None
_collection = None

CHUNK_SIZE = 500      # 每个分块字符数
CHUNK_OVERLAP = 60    # 相邻分块重叠字符数（保留上下文衔接）
DEFAULT_TOP_K = 3


def _get_collection():
    global _client, _collection
    if _collection is None:
        _client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
        ef = embedding_functions.ONNXMiniLM_L6_V2()  # 内置模型，首次自动下载
        _collection = _client.get_or_create_collection(
            name=settings.CHROMA_COLLECTION,
            embedding_function=ef,
        )
    return _collection


def _chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """固定窗口分块（含重叠），中文按字符切分。"""
    text = text.strip()
    if len(text) <= size:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return chunks


def index_document(doc_db_id: int, project_id: int, title: str, content: str,
                   doc_type: str = "doc") -> int:
    """将一篇知识库文档分块写入向量库。返回分块数。可重复调用（先删旧 chunk 再写）。"""
    col = _get_collection()
    # 若该文档此前已入库（重新上传场景），先清理旧分块
    old = col.get(where={"doc_db_id": doc_db_id})
    if old and old.get("ids"):
        col.delete(ids=old["ids"])

    chunks = _chunk_text(content)
    ids = [f"doc-{doc_db_id}-c{i}" for i in range(len(chunks))]
    metadatas = [
        {"doc_db_id": doc_db_id, "project_id": project_id, "title": title,
         "doc_type": doc_type, "chunk": i}
        for i in range(len(chunks))
    ]
    col.add(ids=ids, documents=chunks, metadatas=metadatas)
    return len(chunks)


def search(
    query: str,
    project_id: Optional[int] = None,
    top_k: int = DEFAULT_TOP_K,
) -> list[dict]:
    """向量检索：返回 [{text, title, project_id, doc_db_id, doc_type, chunk, distance}]"""
    col = _get_collection()
    where = {"project_id": project_id} if project_id is not None else None
    result = col.query(
        query_texts=[query],
        n_results=top_k,
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    out = []
    docs = (result.get("documents") or [[]])[0]
    metas = (result.get("metadatas") or [[]])[0]
    dists = (result.get("distances") or [[]])[0]
    for text, meta, dist in zip(docs, metas, dists):
        out.append({
            "text": text,
            "title": meta.get("title", ""),
            "project_id": meta.get("project_id"),
            "doc_db_id": meta.get("doc_db_id"),
            "doc_type": meta.get("doc_type", "doc"),
            "chunk": meta.get("chunk"),
            "distance": dist,
        })
    return out


def delete_document(doc_db_id: int) -> None:
    """文档从业务库删除时，同步清理其全部向量分块。"""
    col = _get_collection()
    old = col.get(where={"doc_db_id": doc_db_id})
    if old and old.get("ids"):
        col.delete(ids=old["ids"])
