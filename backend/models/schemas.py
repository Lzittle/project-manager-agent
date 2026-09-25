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


# ---------- 成员（小队名册，D-018） ----------
MemberStatus = Literal["placeholder", "active"]


class MemberCreate(BaseModel):
    """队长手填成员：只给名字，就能先被指派（占位成员，注册后认领）。"""
    name: str = Field(min_length=1, max_length=50)


class MemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    user_id: Optional[int] = None          # 认领后指向账号；占位成员为空
    status: str                             # placeholder / active
    invite_code: Optional[str] = None       # 占位成员的邀请码
    created_at: Optional[datetime] = None


# ---------- 项目 ----------
ProjectStatus = Literal["active", "archived"]


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = ""
    status: ProjectStatus = "active"
    parent_id: Optional[int] = None  # 父项目 id：非空表示创建子项目/小项目


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[ProjectStatus] = None
    parent_id: Optional[int] = None  # None 表示不动；要置空父级需要单独字段语义（当前不支持改挂靠）


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str] = ""
    status: str
    creator_id: int
    parent_id: Optional[int] = None  # 子项目层级：根项目为空
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
    # 下面两个字段由接口层从 members 名册填充（不是 tasks 表的列）
    assignee_name: Optional[str] = None    # 负责人名字（占位成员也有名字）
    assignee_status: Optional[str] = None  # placeholder=待认领 / active=已注册
    due_date: Optional[date] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # 依赖摘要（由接口层填充，非 ORM 列）：本任务的前置任务 id 列表
    depends_on: Optional[list[int]] = None
    # 阻塞角标：尚未完成的前置任务数（>0 表示本任务被依赖阻塞，无法开工）
    blocked_by_count: Optional[int] = 0


# ---------- 任务依赖 ----------
class DependencyCreate(BaseModel):
    task_id: int
    depends_on_id: int


class TaskDependencyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    depends_on_id: int
    created_at: Optional[datetime] = None


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
    doc_type: Optional[str] = "doc"  # doc=文档 / meeting=会议纪要
    project_id: int
    created_at: Optional[datetime] = None


# ---------- 对话 ----------
class ChatRequest(BaseModel):
    """前端 POST /api/chat/send 的请求体"""
    message: str = Field(min_length=1)
    user_id: int
    project_id: Optional[int] = None  # 传入时：对话绑定某项目（用于 RAG 检索该项目的文档）


class MeetingSummaryRequest(BaseModel):
    """前端「把本次对话存为纪要」按钮 → POST /api/chat/meeting-summary"""
    user_id: int
    project_id: int  # 纪要按项目归档，必须显式指定绑定项目


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str
    trace: Optional[list] = None  # 助手消息的 Agent 执行轨迹（工具步骤），由 DB JSON 文本解析而来
    created_at: Optional[datetime] = None
