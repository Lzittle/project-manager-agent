"""SQLAlchemy 数据库模型：六张业务表 + 引擎/Session 管理。

表清单：users / projects / tasks / task_comments / chat_messages / knowledge_documents
关联：用户 1-N 项目；项目 1-N 任务；任务 1-N 评论；
      用户 1-N 任务(assignee)；项目 1-N 知识库文档；用户 1-N 聊天消息
"""
from datetime import datetime, date
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Date, ForeignKey,
    create_engine, func,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

from core.config import settings

# ---------- 引擎与会话 ----------
# SQLite 需要 check_same_thread=False 以支持 FastAPI 多线程访问
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

Base = declarative_base()


def get_db():
    """FastAPI 依赖注入：每个请求独立 session，用完即关。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """启动时调用：按模型定义建表（已存在则跳过），随后执行轻量迁移（补列等）。"""
    Base.metadata.create_all(bind=engine)
    _run_light_migrations(engine)


def _run_light_migrations(engine) -> None:
    """存量库轻量迁移：新增字段用 ALTER TABLE 补齐，避免删库。

    说明：SQLite 的 ALTER 仅支持加列；加列需允许 NULL 且无默认值约束。
    """
    with engine.connect() as conn:
        cols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(chat_messages)")]
        if "project_id" not in cols:
            conn.exec_driver_sql(
                "ALTER TABLE chat_messages ADD COLUMN project_id INTEGER")
            conn.commit()
            print("[migrate] chat_messages 新增 project_id 列")


# ---------- 数据表 ----------
class User(Base):
    """用户表"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(120), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    # 关系（不含级联删除，避免误删数据）
    projects = relationship("Project", back_populates="creator")
    assigned_tasks = relationship("Task", back_populates="assignee", foreign_keys="Task.assignee_id")
    comments = relationship("TaskComment", back_populates="user")
    messages = relationship("ChatMessage", back_populates="user")


class ChatMessage(Base):
    """聊天消息表"""
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    role = Column(String(20), nullable=False)  # system / user / assistant
    content = Column(Text, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)  # 对话所属项目（可为空）
    created_at = Column(DateTime, server_default=func.now())

    user = relationship("User", back_populates="messages")


class Project(Base):
    """项目表"""
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, index=True)
    description = Column(Text, default="")
    status = Column(String(20), nullable=False, default="active", index=True)  # active / archived
    creator_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    creator = relationship("User", back_populates="projects")
    tasks = relationship("Task", back_populates="project")
    documents = relationship("KnowledgeDocument", back_populates="project")


class Task(Base):
    """任务表"""
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, default="")
    status = Column(String(20), nullable=False, default="todo", index=True)  # todo / doing / done
    priority = Column(String(10), nullable=False, default="medium", index=True)  # high / medium / low
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    assignee_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    due_date = Column(Date, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    project = relationship("Project", back_populates="tasks")
    assignee = relationship("User", back_populates="assigned_tasks", foreign_keys=[assignee_id])
    comments = relationship("TaskComment", back_populates="task")


class TaskComment(Base):
    """任务评论表"""
    __tablename__ = "task_comments"

    id = Column(Integer, primary_key=True, index=True)
    content = Column(Text, nullable=False)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    task = relationship("Task", back_populates="comments")
    user = relationship("User", back_populates="comments")


class KnowledgeDocument(Base):
    """知识库文档表"""
    __tablename__ = "knowledge_documents"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    file_type = Column(String(20), default="txt")  # txt / md / pdf ...
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now())

    project = relationship("Project", back_populates="documents")
