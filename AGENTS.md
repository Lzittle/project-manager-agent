# AGENTS.md · 在这个仓库里干活前先读这一页

> 产品：**Squad · 小队智脑**（对话式项目管理 Agent）。
> 事实源（有冲突以它们为准）：`PLAN.md`（要什么/不做什么/验收）· `DECISIONS.md`（为什么）·
> `docs/WORKFLOW.md`（每轮怎么推进）· `docs/DEV_OPS.md`（端口/重启/探针）· `docs/AGENT_ROADMAP.md`（Agent 自身完善）。

---

## 1. 代码组织（硬规矩，2026-09-27 立）

**一个文件一个职责；不许把新逻辑继续往已经很大的文件里塞。**

1. **单文件软上限 400 行**。超过就按职责拆，别等它长到 1000 行再动
   （实例：`core/agent.py` 曾到 1379 行，工具表、意图路由、执行器、主循环全挤在一起，改一处要在长文件里翻半天）。
2. **加新功能先找「家」**：这个能力属于哪个模块？找不到合适的家 → 先建那个模块，再写进去。
3. **按职责缝拆，不按行数对半砍**。参照现在的后端分层：

   - `core/tools.py` 给模型看的 schema · `core/intents.py` 意图与确定性路由 ·
     `core/executor*.py` 工具执行（核心/规划/团队/轨迹各一块）·
     `core/prompts.py` 提示词 · `core/utils.py` 小工具 · `core/agent.py` 只留主循环。
   - 前端：视图放 `views/`，可复用块放 `components/`，请求封装放 `api/`。

4. **例外要写明**：纯数据表（如 `TOOLS` 常量）、测试文件、评测用例 JSON 不受 400 行限制 ——
   但要么在文件头写清为什么，要么别在同一个文件里混第二件事。
5. **拆分必须是「逐行搬运」**，并且有核对手段，不能靠眼力。

   ⚠️ 教训（2026-09-27）：第一次只断言「原文块是新文件的子串」→ 漏搬了一行 `return` 也照样"通过"。
   **包含 ≠ 全等**。要用**多集校验**（原文每一行在新文件里出现同样次数）+ 行区间覆盖检查。
   现成脚本：`.workbuddy/tmp/verify_split_20260927.py`（工作区侧）。
6. **拆模块会动到「patch 点」**：`monkeypatch.setattr("core.agent.rag_search", …)` 这类测试拆分后会失效 ——
   **被 patch 的模块路径也是接口**，拆完记得同步测试。

## 2. 每轮怎么推进

- 一轮只推进**一个能验证的小步**：产出 → 人拍板 → 落盘 → 记忆 → 本地 commit。
- **先量后改**：改 Agent 行为前，先把用例补进评测（65 条，见 `backend/eval/README.md`）。
- **不给证据不算完成**：`pytest tests -q` + 离线评测（零 token）+ 需要的真模型用例 / 浏览器探针。
  改完代码 ≠ 服务已更新 —— 后端要显式重启（见 `docs/DEV_OPS.md`）。
- 决策与踩坑写进 `DECISIONS.md`（只追加）；结构变化先改 `PLAN.md`。

## 3. 仓库规范

- **仓库只放代码 + 开发文档**。资料原文、审计日志、截图一律留工作区
  （`.gitignore` 已覆盖 `docs/资料/`、`docs/Agent_Audit_Logs/`、`docs/screenshots/*`；README 在用的三张图例外）。
- commit 用 `feat|fix|chore|perf|test|docs|refactor(scope): 说明`；**本地提交，推送由用户决定**。
- 提交前看一眼 `git status`，确认没把资料 / 审计 / 截图带进仓库。

## 4. 长期项目必备

- 每次完成任务都要产出记忆：`.workbuddy/memory/{日期}.md`（daily log）+ `MEMORY.md`（增量）。
- 别人（或两个月后的你）只会读 `DECISIONS.md` 和记忆 —— 写清「为什么」和「代价」。
