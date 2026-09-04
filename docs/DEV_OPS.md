# 开发运维规范（Windows 本地开发经验沉淀）

> 本文档记录本项目在 Windows 本地开发中反复踩坑后固化的**强制纪律**。
> 原则一句话：**改代码 → 重启服务 → 行为探针验证 → 才可宣称完成。**

---

## 1. 最痛的坑：改了代码，但旧进程还在服务

**事故现场**：给后端新增了 `POST /api/projects/{id}/plan` 路由，浏览器/Curl 依旧报 `404 Not Found`；
重启前端也无效。排查发现 8000 端口上有一个**跨会话残留的旧 uvicorn 实例**（PID 32704），
它加载的是旧代码，而且 `uvicorn --reload` 的热重载对它不生效。

**根因链**：
1. 曾用 `uvicorn main:app --reload` 启动 → 产生 reloader 主进程 + 工作子进程；
2. 会话结束后 reloader 已退，但**子进程成了僵尸**仍占着 8000；
3. 它由另一个会话/上下文启动，`taskkill` / `Stop-Process` 均无权终止（"进程不存在"/拒绝访问）；
4. 之后无论怎么改代码、怎么 `--reload`，8000 上服务的始终是**这个旧实例**。

### 强制纪律（防止重犯）

| # | 纪律 | 说明 |
|---|---|---|
| 1 | **改完后端代码必须显式重启服务进程** | 不依赖 `--reload` 兜底；reload 可能指向僵尸实例 |
| 2 | **重启后用行为探针验证运行版本** | 探针通过才允许向用户宣称"已完成/已修复" |
| 3 | **报 404/旧行为 → 先怀疑端口被旧进程占用** | 查 `netstat`，不要先改代码 |
| 4 | **跨会话僵尸杀不掉 → 换端口起新实例** | 后端 8001 + 前端 `VITE_API_TARGET` 覆盖代理，绕开旧实例 |
| 5 | **前端访问用 `localhost:5173`** | vite 监听 `[::1]`（IPv6），`127.0.0.1` 会 502 误报故障 |

## 2. 端口与进程排查命令

```bash
# 谁占着端口（Windows）
netstat -ano | grep -E ":8000.*LISTENING"     # git-bash 下用 grep
netstat -ano | findstr ":8000"                # cmd 下用 findstr

# 终止进程（本会话启动的实例可杀）
taskkill //PID <pid> //F                       # git-bash 需双斜杠转义
# 若 taskkill 报"无效参数"，改用 PowerShell：
#   Stop-Process -Id <pid> -Force -Confirm:$false
```

**注意**：`taskkill //PID` 在 git-bash 里双斜杠可能仍报错，直接切 PowerShell 执行最稳。

## 3. 后端启动 / 重启协议

```bash
cd /d/project/project-manager-agent/backend
../venv/Scripts/python.exe -m uvicorn main:app --host 127.0.0.1 --port 8001
```

- 启动**不带 `--reload`**：改代码后手动重启，行为可预期。
- 默认端口 8000 被僵尸占用时，固定改用 **8001**（勿反复试 8002/8003，避免每次环境都漂移）。
- 重启步骤：`netstat` 找到旧 PID → `Stop-Process` → 确认端口释放 → 再启动新实例。

## 4. 行为探针（验证"运行的是新代码"）

工具函数/新路由不在 openapi 之外可见时，用探针脚本直接验证注册与路由判定：

```bash
# 探针 1：HTTP 路由在位 + 健康
curl -s -o /dev/null -w "health=%{http_code}\n" http://127.0.0.1:8001/health
curl -s http://127.0.0.1:8001/openapi.json | python -c \
  "import sys,json;d=json.load(sys.stdin);print('plan route:','/api/projects/{project_id}/plan' in d['paths'])"
```

```bash
# 探针 2：离线检查 Agent 工具注册与路由判定（不耗 token，不起 HTTP）
cd backend && ../venv/Scripts/python.exe -c "
from core.agent import _ToolExecutor
import core.agent as A
names=[t['function']['name'] for t in A.TOOLS]
print('tools:', sorted({'delete_task','delete_project','update_task_fields','update_project_fields','plan_tasks','list_tasks','create_task'} & set(names)))
"
```

## 5. 前端启动 / 代理目标

```bash
cd /d/project/project-manager-agent/frontend
VITE_API_TARGET=http://127.0.0.1:8001 npm run dev    # 后端在 8001 时必须带此变量
```

- vite 代理目标默认 8000（见 `vite.config.js`），后端换端口后用 `VITE_API_TARGET` 覆盖，**无需改代码**。
- 页面访问统一用 `http://localhost:5173`。

## 6. 自动化测试（改完必跑）

```bash
cd /d/project/project-manager-agent/backend
../venv/Scripts/python.exe -m pytest tests -q        # 全量 19 passed（LLM 已 mock，离线）
```

## 7. 提交纪律

- 每个逻辑步骤一个本地 commit（不 push），便于回退：`feat/fix/chore(scope): 说明`
- 代码改动 + 对应测试**同一提交**内完成。
- 运维类经验沉淀到本文档或 `.workbuddy/memory/`，不进业务提交。

---

## 变更记录

| 日期 | 内容 |
|---|---|
| 2026-09-04 | 初稿：固化 8000 端口僵尸实例（PID 32704）事故的排查路径与强制纪律 |
