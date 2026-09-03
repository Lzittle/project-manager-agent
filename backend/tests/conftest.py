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


@pytest.fixture(scope="session")
def client():
    """应用测试客户端（with 进入时触发 lifespan 自动建表）。"""
    with TestClient(app) as c:
        yield c


def pytest_sessionfinish(session, exitstatus):
    """测试结束后清理测试库文件与向量目录（失败不影响测试结论）。"""
    for path in (TEST_DB, TEST_CHROMA_DIR):
        try:
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            elif os.path.exists(path):
                os.remove(path)
        except Exception:
            pass  # 沙箱/权限原因清理失败时静默，不掩盖测试结果
