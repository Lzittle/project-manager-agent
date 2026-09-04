# ---------- 后端镜像：FastAPI + SQLite + ChromaDB ----------
# 本地开发与容器内保持一致的依赖清单；数据（SQLite/Chroma）通过 volume 挂载到 /data，
# 不进镜像层 —— 容器 down/up 不丢数据。
# 国内网络建议保留下方清华源；海外可去掉 -i 参数。
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 1) 先装依赖（利用层缓存：requirements 不变则此层不重建）
COPY requirements.txt .
RUN pip install -r requirements.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple

# 2) 拷贝源码
COPY . .

# 3) 运行端口（容器内固定 8000；对外映射由 docker-compose 决定）
EXPOSE 8000

# 启动即建表/轻量迁移（main.py 内置 init_db）；不依赖 --reload，行为可预期
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
