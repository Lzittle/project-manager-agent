# Agent 完善规划（v1 · 2026-09-27）

> 一句话结论：**现在缺的不是"功能没做出来"，而是"没度量证明它稳"。**
> 工具调用、读记忆、自然语言沟通这三件事都已经在跑，但除了 9/14 那一套 42 条评测，
> 之后新增的 8 个工具、2 条路由**没有进入任何回归**——所以"感觉没做出来"是可信的直观，
> 而它对应的真问题是：**评测与度量没跟上代码**。
>
> 本文的行事原则：**每一次完善，都先用评测量出来，再动代码。**

---

## 1. 现状盘点（每一条都能在代码或报告里查到）

| 维度 | 现状 | 证据 |
| --- | --- | --- |
| 工具 | **17 个**：项目 4（增删改查）+ 任务 5 + 知识 2（检索/存纪要）+ 规划 1 + 成员与指派 5 | `backend/core/agent.py` 的 `TOOLS` |
| 工具裁剪 | 绑定项目时自动摘掉项目级增删改，并移除 `project_id` 参数（模型看不到别的项目） | `build_tools()` |
| 控制流 | 代码层确定性路由 6 条：`conflict`（跨项目写拦截）/ `ask`（只给数量不给明细）/ `plan`（纯规划）/ `assign_plan`（按名单分配）/ `apply`（确认落库）/ `query`（只读进度先注入真实数据），其余交模型工具循环 | `resolve_bound_action()`、`api/chat.py` |
| 记忆（读） | 两条通道：会话上下文（最近 20 条）+ 项目记忆 RAG（资料/纪要向量检索，命中自动注入 system） | `_load_history()`、`_maybe_inject_memory()` |
| 记忆（写） | **只在用户明说时写**（「把结论记下来/存成纪要」→ `save_meeting`）；Agent 不会主动沉淀 | `save_meeting` |
| 自然语言 | 唯一入口。一句话建项目/规划/推进/指派/按名单分配都走对话 | 前端工作台 |
| 可观测 | 每条助手消息带 `trace`（工具名 + 耗时 + 影响实体 + 可点引用）；批次表 `plan_runs` / `assignment_runs` | `chat_messages.trace` |
| 评测 | **42 条真实话术、真模型**，2026-09-14 跑出 42/42、误写率 0/28；单测 59 条（mock 模型） | `docs/Agent_Audit_Logs/2026-09-14_agent-eval-review/` |
| 评测的缺口 | 那 42 条是**9/14 之前**的能力：之后新增的 `delete_*` / `update_*_fields` / `save_meeting` / `list_members` / `create_member` / `assign_task` / `plan_assignment_from_doc` / `apply_assignment` 都没进用例集 | 同上，用例集里只有 42 条 |

**一句话**：功能在跑，但**回归网是 9/14 的尺寸，罩不住今天的代码**。

---

## 2. 对照业界：四篇原文 + 我们的差距

抓下来的原文都在 `docs/资料/`（只去网页导航，正文未改）：

| 原文 | 核心主张 | 我们现在的状态 |
| --- | --- | --- |
| [Anthropic · Writing effective tools for agents](资料/2026-09-27_Anthropic-Writing-Tools-For-Agents.md)（2025-09-11） | 工具要**少而准**、命名有边界、**返回有意义的上下文而不是一堆 id**、为 token 效率做分页/裁剪、用评测量工具（记录耗时/调用次数/token/工具错误），并留 held-out 测试集 | 工具边界清楚 ✓；但 `list_tasks` 返回全字段、`plan_assignment` 一次吐 16 行，**没做裁剪与分页**；评测里也只有耗时，没有逐次工具错误统计 |
| [Anthropic · Effective context engineering](资料/2026-09-27_Anthropic-Effective-Context-Engineering.md)（2025-09-29） | 上下文是**有限资源**：压缩（compaction）、结构化笔记、子代理、按需检索 | 只带了最近 20 条历史，**没有压缩/摘要**；没有"结构化笔记"（结论沉淀）；按需检索 ✓（RAG） |
| [Anthropic · Multi-agent research system](资料/2026-09-27_Anthropic-Multi-Agent-Research-System.md) | 评测要**立刻开始、小样本**；能自动判的自动判，主观的用 **LLM-as-judge**；**人评**补漏；非确定性要有 tracing；**会改状态的 agent 要评"终态"** | 前三条基本做到了（真模型评测 + 人工复核档案）；**终态评测没有**（多轮改状态后的结果对不对，没人系统评过） |
| [12-Factor Agents](资料/2026-09-27_12-Factor-Agents.md) | 把自然语言→工具调用（①）、自己掌控提示与上下文（②③）、工具就是结构化输出（④）、执行状态与业务状态合一（⑤）、**需要人时用工具去问人**（⑦）、自己掌控控制流（⑧）、**压缩错误再回填上下文**（⑨）、小而专注的 agent（⑩） | ①④⑧ ✓（确定性路由 + 结构化工具返回）；**⑨ 没做**（工具异常原样回填，长堆栈会污染上下文）；⑦ 部分（方案确认），删除/批量写还缺"先给方案"；⑩ 工具数已到 17，**该考虑分组/分层** |

---

## 3. 你问的三件事，直接回答

**① 分配任务这类能力，算 MVP 吗？**

算。`PLAN.md` §8 验收标准第一条就是「从一句话到『任务在现场、有负责人』≤ 2 次交互」——**"有负责人"是 MVP 的硬指标**，所以指派属于 MVP 而不是锦上添花。现在「一句话指派」和「按名单批量分配」都已经能跑。
真正要在 MVP 之外的，是**分配的"质量"**（分得匀、分得对），那是 v1.1 的事。

**② 工具调用、读记忆、自然语言沟通，是不是没做出来？**

三件都做了，而且都跑在真实链路上：

- **工具调用**：17 个工具，模型自主选择 + 代码层 6 条确定性路由兜底（高风险动作用代码拍板，不给模型自由发挥）。
- **读记忆**：会话历史 + 项目记忆 RAG 自动注入（实测问"文档里 workflow 和 agent 的区别"，4 秒内命中 3 条原文片段）。
- **自然语言**：这是唯一入口——建项目、规划、推进、指派、按名单分配、存纪要，全是一句话。

**③ 那真正缺的是什么？**

缺两样，都是"工程"而不是"功能"：

1. **度量**：回归评测停留在 9/14 的 42 条，之后新增的能力没进网；没有终态评测、没有逐次工具错误与 token 统计、没有基线对比。→ 所以"稳不稳"只能靠感觉。
2. **人的参与点不完整**：目前只有"按名单分配"是"先方案后落库"；批量改状态、删除这类**影响面大的写操作**还是模型直接执行。业界共识（12-Factor ⑦、我们自己的 D-007）都是：该人拍板时必须停下来问。

---

## 4. 分四步走（每步都能单独验证）

### 阶段 0 · 先把尺子立起来（1 轮，最优先）

- 评测集从 42 条扩到 **65 条以上**：补齐删除/改字段/存纪要/成员/指派/按名单分配/确认落库，以及 **10 条"不该动数据"**的负例（如「生成任务清单」「看看进度」）。
- `eval/run_agent_eval.py` 增补指标：**逐次工具错误数、token、平均耗时、工具选择正确率**，每次跑自动存报告（保留历史，不覆盖）。
- **验收**：同一套用例能一键跑出报告；报告里能看到"这次比上次好在哪、差了哪"。

### 阶段 1 · 按文章原则修工具与上下文（2 轮）

- **工具返回瘦身**：`list_tasks` 默认只回必要字段 + 支持 `limit/分页`；`plan_assignment` 的返回按"给人看的表格 / 给模型看的条目"分开（模型不用读表格）。
- **错误压缩**（12-Factor ⑨）：工具异常只回填"类型 + 关键一句 + 建议动作"，不再把整段堆栈喂给模型。
- **上下文压缩**：对话超过 N 轮时，把早期历史压成一段摘要再进上下文（现在硬截 20 条）。
- **验收**：同一批评测的 token 与平均耗时**下降**，通过率不降；长对话（30 轮以上）能记住开头的决定。

### 阶段 2 · 记忆闭环：让 Agent 会主动沉淀（1 轮）

- 每轮对话结束时，若出现"已确认的结论/决定"，Agent 主动写一条**结构化笔记**（复用 `save_meeting` 的入库通道，但不再要求用户明说；写之前给一句话确认，避免噪音）。
- 补一组"记忆检索"评测：先写入结论，隔几轮再问，看能不能命中正确片段。
- **验收**：问答能复述上一轮定下的事，且笔记条数可控（不刷库）。

### 阶段 3 · 把"人拍板"补齐 + 可撤销（2 轮）

- 批量改状态、批量删除：**先给方案再落库**（沿用按名单分配那套：`plan_*` 不写库 → 确认 → `apply_*`）。
- 落库可撤销：每次 `apply_*` 记录 before/after，支持一句话"撤销上一次指派"。
- **验收**：端到端**终态评测**（多轮改状态后，最终状态与期望一致）+ 撤销后回到原样。

**暂不做**：多 agent 编排（先把单 agent 的工具与记忆打磨到有度量）、流式输出（另行排期）、自动删除（写操作一律要人确认）。

---

## 5. 评测体系（这次的重点，三层）

| 层 | 跑什么 | 模型 | 用途 | 现状 |
| --- | --- | --- | --- | --- |
| L1 单测 | `pytest tests`（59 条） | mock | 路由分支、数据流、不联网也能跑 | ✅ 有 |
| L2 离线路由评测 | `run_agent_eval.py`（默认模式） | 不调模型 | 只看代码层路由判定，零 token | ✅ 有 |
| L3 在线真模型评测 | `run_agent_eval.py --mode live` | 真模型 | 话术 → 路由/工具/写库/回复，四项核对 | ✅ 有，**但用例集停在 9/14** |
| L4 终态评测（**新增**） | 多轮脚本 + 断言最终状态 | 真模型 | 改状态的 agent 必须评"最终结果对不对" | ❌ 待做（阶段 3） |

指标口径（沿用行业做法，见 `docs/资料/2026-09-27_Anthropic-Writing-Tools-For-Agents.md`）：
通过率 · 工具选择正确率 · 误写率（只读请求被写库）· 越权写库 · 平均耗时 · token 消耗 · 工具错误数。

复现命令：

```bash
cd backend
../venv/Scripts/python.exe -m pytest tests -q                     # L1
../venv/Scripts/python.exe eval/run_agent_eval.py                  # L2
../venv/Scripts/python.exe eval/run_agent_eval.py --mode live      # L3（真模型，消耗 token）
```

---

## 6. 资料清单（原文都在仓库里，可随时查证）

| 文件 | 来源 |
| --- | --- |
| `docs/资料/2026-09-27_Anthropic-Writing-Tools-For-Agents.md` | anthropic.com/engineering/writing-tools-for-agents |
| `docs/资料/2026-09-27_Anthropic-Effective-Context-Engineering.md` | anthropic.com/engineering/effective-context-engineering-for-ai-agents |
| `docs/资料/2026-09-27_Anthropic-Multi-Agent-Research-System.md` | anthropic.com/engineering/multi-agent-research-system |
| `docs/资料/2026-09-27_12-Factor-Agents.md` | github.com/humanlayer/12-factor-agents |
| OpenAI《A Practical Guide to Building Agents》官方 PDF | cdn.openai.com |
| `docs/资料/2026-09-16_Anthropic-Building-Effective-Agents.md` | anthropic.com/engineering/building-effective-agents（9/16 抓的） |

> 抓取说明：`platform.openai.com` 的文档页有 Cloudflare 拦截（403），所以 OpenAI 这边只留下官方 PDF 原文；
> 文字抽取需要 `pypdf`，当前 venv 里没装——要看内容直接打开 PDF。
> **这份 7MB 的 PDF 没有进代码仓库**（仓库只放代码与文本资料），存在工作区：
> `D:\workbuddy\项目管理agent\docs\资料\2026-09-27_OpenAI-A-Practical-Guide-To-Building-Agents.pdf`。
