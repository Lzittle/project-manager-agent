"""FastAPI 应用入口"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from core.config import settings
from models.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动时初始化数据库（幂等：表已存在则跳过）"""
    init_db()
    yield


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)


@app.get("/health")
def health_check():
    return {"status": "ok", "app_name": settings.APP_NAME}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.APP_HOST, port=settings.APP_PORT)
