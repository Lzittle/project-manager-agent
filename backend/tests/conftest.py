"""pytest 全局配置：使用独立测试库（SQLite + ChromaDB），不污染演示数据。

注意：必须在导入任何应用模块前设置环境变量 —— config 的 load_dotenv
不会覆盖已存在的环境变量，因此测试环境配置优先于 backend/.env。
"""
import os
import shutil

TEST_DB = "./test_project_manager.db"
TEST_CHROMA_DIR = "./chroma_db_test"

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["CHROMA_PERSIST_DIR"] = TEST_CHROMA_DIR

import pytest
from fastapi.testclient import TestClient

from main import app


def _cleanup_paths():
    """删掉测试库与测试向量目录（失败静默：文件被占用时下一轮开工前还会再试一次）。"""
    for path in (TEST_DB, TEST_CHROMA_DIR):
        try:
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            elif os.path.exists(path):
                os.remove(path)
        except Exception:
            pass


# 开工前先清一次：上一次运行若因为文件被占用没删掉，残留库会污染这一轮用例
# （实例：残留库里的「张三」让新增成员用例直接 409）。
_cleanup_paths()


@pytest.fixture(scope="session")
def client():
    """应用测试客户端（with 进入时触发 lifespan 自动建表）。"""
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def db_session():
    """直连测试库的 Session：给需要「绕过接口造数据」的用例用（如轮 3 的认领测试）。"""
    from models.database import SessionLocal

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# 清理顺序：先子表后主表（SQLite 默认不强制外键，但按依赖顺序更稳）
_ISOLATION_TABLES = None


def _isolation_tables():
    """懒加载表清单：避免 conftest 导入期就把模型全拉起来。"""
    global _ISOLATION_TABLES
    if _ISOLATION_TABLES is None:
        from models.database import (ActionRun, AssignmentRun, ChatMessage,
                                     KnowledgeDocument, Member, NoteDraft, PlanRun,
                                     Project, Task, TaskComment, TaskDependency, User)
        _ISOLATION_TABLES = [TaskDependency, TaskComment, ChatMessage, ActionRun, AssignmentRun,
                             PlanRun, NoteDraft, KnowledgeDocument, Task, Project, Member, User]
    return _ISOLATION_TABLES


@pytest.fixture()
def isolate_db(db_session):
    """「用完即清」隔离（opt-in）：记下各表 max(id)，用例结束后删掉新增行。

    为什么需要：本仓库的测试**共用一个文件库**（只在会话开始清一次），
    于是「注册一个账号」会占掉 `user_id=1`，而 `create_task` 会把创建者的成员身份
    默认设成负责人 —— 后续用例里 `user_id=1` 的含义就被悄悄改掉了
    （实例：`test_bulk_actions` 的「撤销后负责人为空」会被带偏成 6）。
    注册类 / 造账号类用例用这个夹具把自己的痕迹擦掉，就不必去改既有用例的假设。

    注意：它是 **opt-in** 而不是 autouse —— 有些模块的用例之间有数据依赖，
    全局清库会误伤。要用的模块自己声明 autouse 包一层。
    """
    from sqlalchemy import func

    models = _isolation_tables()
    baseline = {m: db_session.query(func.max(m.id)).scalar() or 0 for m in models}
    yield
    for model in models:
        db_session.query(model).filter(model.id > baseline[model]).delete(synchronize_session=False)
    db_session.commit()


def pytest_sessionfinish(session, exitstatus):
    """测试结束后清理测试库文件与向量目录（失败不影响测试结论）。"""
    _cleanup_paths()
