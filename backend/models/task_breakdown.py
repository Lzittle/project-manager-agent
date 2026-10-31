"""任务小块模型。

小块是挂在父任务下面的轻量执行记录：组员可以拆分和推进，父任务只展示汇总。
不引入计时字段，避免把本阶段变成工时系统。
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func

from models.database import Base


class Subtask(Base):
    """父任务下的可推进小块。"""

    __tablename__ = "subtasks"

    id = Column(Integer, primary_key=True, index=True)
    parent_task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, default="")
    status = Column(String(20), nullable=False, default="todo", index=True)
    assignee_id = Column(Integer, ForeignKey("members.id"), nullable=True, index=True)
    creator_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=datetime.now)
