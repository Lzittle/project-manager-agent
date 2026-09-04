# Docker 一键部署指南

> 解决你反复遇到的痛点：**每次启动前后端、杀不干净旧进程、端口被占**。
> 容器化后：端口由 Docker 管理，`docker compose up -d` 一键起、`down` 一键停，**不再有僵尸进程问题**。

---

## 一、为什么这样设计（关键）

| 痛点 | Docker 解法 |
|---|---|
| 本地 8000/8001 端口被旧进程占、杀不掉 | **后端容器不映射宿主端口**——只在 Docker 内部网络以 `backend:8000` 供 nginx 反代，与宿主端口零冲突 |
| 前端 / 后端分别手动启动 | `docker compose up -d` 一条命令起全部 |
| 起错版本、旧进程没重启 | 镜像不可变，`up -d --build` 重建即换新代码，无"旧进程服务旧代码" |
| 数据丢失 | SQLite + Chroma 挂载到宿主 `./docker_data/`，容器删了数据还在 |

## 二、架构

```
浏览器 → http://localhost:8080 (nginx, 容器 pma-frontend)
              ├── /          → Vue 静态资源（镜像内构建的 dist）
              └── /api/*     → 反代到 backend:8000 (容器 pma-backend, 仅内网)
                                  ├── FastAPI + SQLite (/data/project_manager.db)
                                  └── ChromaDB (/data/chroma_db)
                                        │
                        宿主 ./docker_data/  ← volume 持久化
```

## 三、首次部署（你只需要执行这一节）

前置条件：本机已装 Docker Desktop 并启动。

```bash
# 1. 确认 backend/.env 已配置（LLM 密钥等，已存在则跳过）
#    容器运行时从 backend/.env 注入，密钥不会烧进镜像

# 2. 构建并启动（首次构建较慢：拉 python/node 镜像 + 装依赖）
cd /d/project/project-manager-agent
docker compose up -d --build

# 3. 等后端就绪后验证
curl -s http://localhost:8080/api/health        # 期望 {"status":"ok",...}
```

**打开浏览器访问 http://localhost:8080** 即可使用。

## 四、可选：灌入演示数据

```bash
docker compose exec backend python seed.py       # 幂等，可重复执行
```

## 五、日常运维命令

```bash
docker compose ps                # 看容器状态
docker compose logs -f backend   # 跟踪后端日志（排查用）
docker compose logs -f frontend  # 跟踪前端/nginx 日志

# 改完代码后更新到新版本：
docker compose up -d --build backend    # 只重建后端
docker compose up -d --build            # 全部重建

docker compose stop                     # 停止（保留容器与数据）
docker compose down                     # 停止并移除容器（数据保留在 docker_data/）
docker compose down -v                  # ⚠️ 连同数据卷一起清空（= 重置数据库，慎用！）
```

> 想看后端进程的实时状态确认没有僵尸？`docker compose ps` 的 STATUS 即真相，无需再 netstat 猜进程。

## 六、数据备份 / 迁移

- 所有业务数据（SQLite 库 + Chroma 向量库）都在宿主机 **`./docker_data/`** 目录。
- 备份 = 拷贝该目录；恢复 = 放回后 `docker compose up -d`。
- 注意：首次在容器内做 RAG 上传文档时，Chroma 内置 ONNX 模型会从外网下载一次
  （国内网络可能超时）——模型缓存落在容器内。如需离线，可在 `.env` 配置
  `CHROMA_ONNX_CACHE` 或按 README 第八章放置模型缓存后挂载（进阶，暂可不处理）。

## 七、直连后端 API（调试用，可选）

后端默认不暴露宿主端口。若需用 Postman/curl 直连（绕过 nginx）：

```bash
# 临时起一个暴露端口的实例（示例用宿主 8002，避开 8000/8001）：
docker compose run --rm -p 8002:8000 backend
# 或编辑 docker-compose.yml 中 backend 服务，取消 ports 注释后 docker compose up -d backend
```

## 八、常见问题

| 现象 | 处理 |
|---|---|
| `docker compose up` 报端口被占用 8080 | 换映射端口：编辑 compose 中 `"8080:80"` 为 `"8081:80"` |
| 构建时 pip/npm 下载慢 | 已内置清华 PyPI 源与 npmmirror，仍慢可检查代理 |
| 改了后端代码但行为没变 | `docker compose up -d --build backend` 强制重建（镜像不可变，不存在旧进程问题） |
| 想彻底重置演示数据 | `docker compose down -v` 后重新 `up -d` 并跑 seed |

---

## 变更记录

| 日期 | 内容 |
|---|---|
| 2026-09-04 | 初稿：前后端容器化 + nginx 反代 + 数据卷持久化 |
