"""Pydantic 数据模型（Pydantic v2 风格）：
- *Create  创建请求体
- *Update  更新请求体（全字段可选，支持部分更新）
- *Out     响应体（from_attributes=True 可直接从 ORM 对象转换）
"""
from datetime import datetime, date
from typing import Optional, Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------- 用户 ----------
class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    email: str
    password: str = Field(min_length=6)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    created_at: Optional[datetime] = None


# ---------- 项目 ----------
ProjectStatus = Literal["active", "archived"]


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = ""
    status: ProjectStatus = "active"


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[ProjectStatus] = None


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str] = ""
    status: str
    creator_id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ---------- 任务 ----------
TaskStatus = Literal["todo", "doing", "done"]
TaskPriority = Literal["high", "medium", "low"]


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    status: TaskStatus = "todo"
    priority: TaskPriority = "medium"
    project_id: int
    assignee_id: Optional[int] = None
    due_date: Optional[date] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[TaskStatus] = None
    priority: Optional[TaskPriority] = None
    assignee_id: Optional[int] = None
    due_date: Optional[date] = None


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: Optional[str] = ""
    status: str
    priority: str
    project_id: int
    assignee_id: Optional[int] = None
    due_date: Optional[date] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ---------- 任务评论 ----------
class CommentCreate(BaseModel):
    content: str = Field(min_length=1)
    task_id: int
    user_id: int


class CommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    content: str
    task_id: int
    user_id: int
    created_at: Optional[datetime] = None


# ---------- 知识库文档 ----------
class KnowledgeDocCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str
    file_type: str = "txt"
    project_id: int


class KnowledgeDocOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    content: str
    file_type: str
    project_id: int
    created_at: Optional[datetime] = None


# ---------- 对话 ----------
class ChatRequest(BaseModel):
    """前端 POST /api/chat/send 的请求体"""
    message: str = Field(min_length=1)
    user_id: int
    project_id: Optional[int] = None  # 传入时：对话绑定某项目（用于 RAG 检索该项目的文档）


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str
    created_at: Optional[datetime] = None
