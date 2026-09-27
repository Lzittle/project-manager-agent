"""SQLAlchemy 数据库模型：业务表 + 引擎/Session 管理。

表清单：users / members / projects / tasks / task_dependencies / task_comments /
       chat_messages / knowledge_documents / plan_runs
关联：用户 1-N 项目；项目 1-N 任务；任务 1-N 评论；任务 N-N 任务（依赖，经
      task_dependencies 桥接）；成员 1-N 任务(assignee)；项目 1-N 知识库文档；
      用户 1-N 聊天消息；项目 1-N 规划批次(plan_runs)

「人」分两层（D-018）：**账号**（users）只管登录；**成员**（members）是小队名册上的
一条人。任务的 assignee_id 指向成员而不是账号 —— 这样队长可以先手填占位成员、
等人注册后再认领（PLAN §5.1）。
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
        _ensure_column(conn, "projects", "parent_id", "INTEGER",
                       "projects 新增 parent_id 列（子项目层级，根项目为空）")
        _ensure_member_roster(conn)


def _ensure_member_roster(conn) -> None:
    """老库兼容（2026-09-25）：把已有账号登记成成员名册，且让成员 id 与账号 id 对齐。

    为什么：任务的 assignee_id 语义从「账号 id」改成「成员 id」（D-018）。
    存量库里 assignee_id 存的是 users.id；只要成员 id 与账号 id 一致，
    存量任务不必改一个数字就继续指向同一个「人」。
    只在名册为空时执行：名册一旦用过（有手填成员），这里就不碰。
    """
    if conn.exec_driver_sql("SELECT COUNT(*) FROM members").scalar():
        return
    result = conn.exec_driver_sql(
        "INSERT INTO members (id, name, user_id, status) "
        "SELECT u.id, u.username, u.id, 'active' FROM users u"
    )
    conn.commit()
    if result.rowcount:
        print(f"[migrate] members 名册初始化：{result.rowcount} 个已有账号登记为成员（id 与账号对齐）")


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
    members = relationship("Member", back_populates="user")
    comments = relationship("TaskComment", back_populates="user")
    messages = relationship("ChatMessage", back_populates="user")


class Member(Base):
    """小队成员名册（队长眼里的「人」）。

    三种来路都落到这张表（PLAN §5.1）：
      - 注册入队：user_id 非空、status=active
      - 占位后认领：队长先手填（user_id 为空、status=placeholder，带邀请码），
        人注册后用邀请码认领这条占位身份（认领属于「轮 3」，尚未实现）
      - 上传名单：Agent 读名单认人后写进同一条名册（轮 2）

    任务的 assignee_id 指向本表（见 Task）。成员 id 与账号 id 不必相等，
    老库里恰好对齐（见 _ensure_member_roster），所以存量任务无需改数。
    """
    __tablename__ = "members"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)  # 认领后指向账号
    status = Column(String(20), nullable=False, default="placeholder",
                    index=True)  # placeholder=待认领 / active=已注册
    invite_code = Column(String(20), nullable=True, unique=True)  # 占位成员发给对方的邀请码
    created_at = Column(DateTime, server_default=func.now())

    user = relationship("User", back_populates="members")
    tasks = relationship("Task", back_populates="assignee", foreign_keys="Task.assignee_id")


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
    """项目表（parent_id 自关联：项目下可再拆「子项目/小项目」，形成层级树）"""
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, index=True)
    description = Column(Text, default="")
    status = Column(String(20), nullable=False, default="active", index=True)  # active / archived
    creator_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    parent_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)  # 父项目（根项目为空）
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    creator = relationship("User", back_populates="projects")
    tasks = relationship("Task", back_populates="project")
    documents = relationship("KnowledgeDocument", back_populates="project")
    # 层级：parent_id -> 父项目；children -> 直接子项目（删除用显式级联，见 project_service）
    parent = relationship("Project", remote_side=[id], back_populates="children")
    children = relationship("Project", back_populates="parent")


class Task(Base):
    """任务表"""
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, default="")
    status = Column(String(20), nullable=False, default="todo", index=True)  # todo / doing / done
    priority = Column(String(10), nullable=False, default="medium", index=True)  # high / medium / low
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    # 负责人 = 成员名册里的一条人（不是账号）：占位成员没有账号也能被指派（D-018）
    assignee_id = Column(Integer, ForeignKey("members.id"), nullable=True, index=True)
    due_date = Column(Date, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    project = relationship("Project", back_populates="tasks")
    assignee = relationship("Member", back_populates="tasks", foreign_keys=[assignee_id])
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


class PlanRun(Base):
    """任务规划批次表：记录每次「自动规划」落了哪些任务，供幂等复用与审计。

    用途：同一项目短时间内被重复触达规划时（用户以为卡住重发、连点两次按钮），
    直接复用上一批任务，而不是再建一批 —— 演示库里项目 1 涨到 21 条任务就是
    这么来的。
    时间戳取 Python 侧 datetime.now()：本表只与自身的时间做窗口比较，
    保持同一时钟，避免与 SQLite server_default 的 UTC 时间混用。
    """
    __tablename__ = "plan_runs"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    task_ids = Column(Text, default="[]")  # 本批次任务 id 的 JSON 数组（保序）
    task_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now, index=True)


class AssignmentRun(Base):
    """分配方案批次表：Agent 读「相关人员说明」后拟出的「任务 → 负责人」方案。

    为什么单独一张表：D-017 定了「先把方案给人过一眼、可微调，再落库」。
    方案在确认前不能碰 tasks.assignee_id，所以先以 pending 状态存在这里；
    用户确认（或有微调）后由 apply_assignment 逐条落库并置为 applied。
    时间戳同样取 Python 侧 datetime.now()，与 PlanRun 保持同一时钟口径。
    """
    __tablename__ = "assignment_runs"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    doc_id = Column(Integer, ForeignKey("knowledge_documents.id"), nullable=True)  # 读的是哪份资料
    items = Column(Text, default="[]")  # [{"task_id","title","member_name","member_id","needs_create","ambiguous","reason"}]
    status = Column(String(20), default="pending", index=True)  # pending=待确认 / applied=已落库
    applied_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now, index=True)


class NoteDraft(Base):
    """结论笔记草稿：Agent 从对话里认出「这是个决定」后先拟一份，等用户一句话确认再入库。

    为什么要有草稿态（D-027）：自动沉淀最大的风险不是"少记"，而是"记满噪音"。
    所以落库前给人一眼话；确认后写进 knowledge_documents（doc_type=note），
    它和资料/纪要一样会被向量化 —— 这样"记下的事"下次能被检索到，记忆才闭环。
    """
    __tablename__ = "note_drafts"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    status = Column(String(20), default="pending", index=True)  # pending / saved / discarded
    created_at = Column(DateTime, default=datetime.now, index=True)
