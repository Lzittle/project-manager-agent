"""FastAPI 应用入口"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from core.config import settings
from models.database import init_db
from api import projects, tasks, knowledge, chat


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动时初始化数据库（幂等：表已存在则跳过）"""
    init_db()
    yield


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)


@app.get("/health")
def health_check():
    return {"status": "ok", "app_name": settings.APP_NAME}


# 业务路由
app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
app.include_router(tasks.router, prefix="/api/tasks", tags=["tasks"])
app.include_router(knowledge.router, prefix="/api", tags=["knowledge"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.APP_HOST, port=settings.APP_PORT)
