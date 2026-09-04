"""SQLAlchemy 数据库模型：业务表 + 引擎/Session 管理。

表清单：users / projects / tasks / task_dependencies / task_comments /
       chat_messages / knowledge_documents
关联：用户 1-N 项目；项目 1-N 任务；任务 1-N 评论；任务 N-N 任务（依赖，经
      task_dependencies 桥接）；用户 1-N 任务(assignee)；项目 1-N 知识库文档；
      用户 1-N 聊天消息
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
        _ensure_column(conn, "chat_messages", "project_id", "INTEGER", "chat_messages 新增 project_id 列")
        _ensure_column(conn, "chat_messages", "trace", "TEXT", "chat_messages 新增 trace 列（Agent 执行轨迹 meta JSON）")
        _ensure_column(conn, "knowledge_documents", "doc_type", "VARCHAR(20)",
                       "knowledge_documents 新增 doc_type 列（doc=文档 / meeting=会议纪要）")


def _ensure_column(conn, table: str, column: str, ddl_type: str, log_msg: str) -> None:
    """轻量迁移：若表缺列则 ALTER 补上（SQLite 仅支持 ADD COLUMN）。"""
    cols = [row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")]
    if column not in cols:
        conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")
        conn.commit()
        print(f"[migrate] {log_msg}")


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
    trace = Column(Text, nullable=True)  # Agent 执行轨迹 JSON（步骤列表），仅 assistant 消息有
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
    # 依赖：task 依赖哪些前置任务；被哪些任务依赖（按需懒加载）
    dependencies = relationship(
        "TaskDependency", back_populates="task",
        foreign_keys="TaskDependency.task_id",
        cascade="all, delete-orphan",
    )


class TaskDependency(Base):
    """任务依赖表：task_id 依赖 depends_on_id（即 depends_on 是前置任务，需先完成）。

    示例：任务 3「联调」依赖任务 2「后端接口」→ (task_id=3, depends_on_id=2)。
    语义上等价「3 → 2」，做影响分析时从某任务沿 depends_on 反向（或沿下游）遍历。
    约束：同项目内任务；禁止自依赖；禁止成环（服务层校验）。
    """
    __tablename__ = "task_dependencies"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False, index=True)
    depends_on_id = Column(Integer, ForeignKey("tasks.id"), nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now())

    # 关系：task_dependencies.task_id → tasks.id（task 的依赖）
    task = relationship("Task", back_populates="dependencies",
                        foreign_keys=[task_id])
    # 前置任务本身（方便读 depends_on 的标题/状态）
    depends_on = relationship("Task", foreign_keys=[depends_on_id])


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
    doc_type = Column(String(20), default="doc", index=True)  # doc=需求/方案文档, meeting=会议纪要
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now())

    project = relationship("Project", back_populates="documents")
