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

抓下来的原文都在**工作区**的 `docs/资料/`（只去网页导航，正文未改）。
> 按项目规范（`docs/WORKFLOW.md` §4）**仓库只放代码 + 开发文档**，外部参考资料留在工作区，不进仓库、不推远端。
> 工作区路径前缀：`D:\workbuddy\项目管理agent\docs\资料\`

| 原文 | 核心主张 | 我们现在的状态 |
| --- | --- | --- |
| [Anthropic · Writing effective tools for agents](D:/workbuddy/项目管理agent/docs/资料/2026-09-27_Anthropic-Writing-Tools-For-Agents.md)（2025-09-11） | 工具要**少而准**、命名有边界、**返回有意义的上下文而不是一堆 id**、为 token 效率做分页/裁剪、用评测量工具（记录耗时/调用次数/token/工具错误），并留 held-out 测试集 | 工具边界清楚 ✓；但 `list_tasks` 返回全字段、`plan_assignment` 一次吐 16 行，**没做裁剪与分页**；评测里也只有耗时，没有逐次工具错误统计 |
| [Anthropic · Effective context engineering](D:/workbuddy/项目管理agent/docs/资料/2026-09-27_Anthropic-Effective-Context-Engineering.md)（2025-09-29） | 上下文是**有限资源**：压缩（compaction）、结构化笔记、子代理、按需检索 | 只带了最近 20 条历史，**没有压缩/摘要**；没有"结构化笔记"（结论沉淀）；按需检索 ✓（RAG） |
| [Anthropic · Multi-agent research system](D:/workbuddy/项目管理agent/docs/资料/2026-09-27_Anthropic-Multi-Agent-Research-System.md) | 评测要**立刻开始、小样本**；能自动判的自动判，主观的用 **LLM-as-judge**；**人评**补漏；非确定性要有 tracing；**会改状态的 agent 要评"终态"** | 前三条基本做到了（真模型评测 + 人工复核档案）；**终态评测没有**（多轮改状态后的结果对不对，没人系统评过） |
| [12-Factor Agents](D:/workbuddy/项目管理agent/docs/资料/2026-09-27_12-Factor-Agents.md) | 把自然语言→工具调用（①）、自己掌控提示与上下文（②③）、工具就是结构化输出（④）、执行状态与业务状态合一（⑤）、**需要人时用工具去问人**（⑦）、自己掌控控制流（⑧）、**压缩错误再回填上下文**（⑨）、小而专注的 agent（⑩） | ①④⑧ ✓（确定性路由 + 结构化工具返回）；**⑨ 没做**（工具异常原样回填，长堆栈会污染上下文）；⑦ 部分（方案确认），删除/批量写还缺"先给方案"；⑩ 工具数已到 17，**该考虑分组/分层** |

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

### 阶段 0 · 先把尺子立起来 —— ✅ 已完成 2026-09-27

- 评测集 **42 → 65 条**：新增「成员指派」6 条、「按名单分配」4 条、「只读负例」11 条（「把任务列表发我看看」「生成一份任务清单」「确认一下这个任务是不是被卡住了」等最容易诱发误写的说法），并补了批量删除与项目级编辑。
- 评测器新增：**写库判定支持指派与加成员**（`assign` / `member` / `assign_or_member`）、**每次工具错误数**、**每用例 token**、**工具选择正确率**；报告新增「工具错误」列。
- 用例前置（`setup`）：`plan_assignment`（先出方案 → 再测"确认落库"）、`prior_conversation`（先塞前置对话 → 再测"把刚才的结论存成纪要"）。
- **基线结果（真模型 65 条）**：65/65 通过 · 误写率 0/45 · 越权 0 · 工具选择 65/65 · 工具报错 0 · 108 次调用 / 335.7k in + 10.5k out / 平均 1.9s。档案：工作区 `docs/Agent_Audit_Logs/2026-09-27_agent-eval-baseline/`。
- **这一轮最值钱的产出**：第一遍跑出 2 条失败，查下来**都是尺子不准而不是 Agent 变笨**（夹具清空了历史导致"刚才的结论"没有指代；绑定模式本来就不暴露项目级编辑工具）。两条已修，修完 65/65。

### 阶段 1 · 按文章原则修工具与上下文 —— ✅ 已完成 2026-09-27（见 D-023）

- **工具返回瘦身**：`list_tasks` 默认只回必要字段 + 支持 `limit/分页`；`plan_assignment` 的返回按"给人看的表格 / 给模型看的条目"分开（模型不用读表格）。
- **错误压缩**（12-Factor ⑨）：工具异常只回填"类型 + 关键一句 + 建议动作"，不再把整段堆栈喂给模型。
- **上下文压缩**：对话超过 N 轮时，把早期历史压成一段摘要再进上下文（现在硬截 20 条）。
- **验收**：~~token 与平均耗时下降~~ → **口径已修正**：评测夹具的任务没有描述，token 收益在那里量不出来；改为"通过率不降 + 用有描述的真实数据单独量瘦身收益"（本轮实测 payload **-24%**），长对话能记住开头的决定（单测覆盖）。
- ~~① 固定成本才是大头~~ → **已完成 2026-09-27（D-024）**：工具描述与提示词瘦身、只读工具子集、工具白名单；固定成本 -22%、只读轮次工具定义 -81%、评测输入 token **-28%**，通过率保持 65/65。
- **遗留（下一轮）**：① 夹具任务描述为空，让 token 对比失真，给夹具补上真实描述再重新基线。② `list_tasks` 不再回描述，目前没有"取单个任务详情"的工具，模型真需要描述时无路可走。③ 代码文件偏长：`core/agent.py` 1201 行（47 个定义）混着工具表/意图路由/执行器/主循环，下一轮拆成 `tools.py` / `intents.py` / `executor.py`；`frontend/src/views/Workspace.vue` 959 行同理由组件拆开。

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

指标口径（沿用行业做法，见工作区 `docs/资料/2026-09-27_Anthropic-Writing-Tools-For-Agents.md`）：
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

| 文件（都在工作区 `docs/资料/`，不进仓库） | 来源 |
| --- | --- |
| `2026-09-27_Anthropic-Writing-Tools-For-Agents.md` | anthropic.com/engineering/writing-tools-for-agents |
| `2026-09-27_Anthropic-Effective-Context-Engineering.md` | anthropic.com/engineering/effective-context-engineering-for-ai-agents |
| `2026-09-27_Anthropic-Multi-Agent-Research-System.md` | anthropic.com/engineering/multi-agent-research-system |
| `2026-09-27_Anthropic-Agent-Skills.md` | anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills |
| `2026-09-27_12-Factor-Agents.md` | github.com/humanlayer/12-factor-agents |
| `2026-09-27_OpenAI-A-Practical-Guide-To-Building-Agents.pdf` | cdn.openai.com（官方指南 PDF，7MB，文字未抽取） |
| `2026-09-16_Anthropic-Building-Effective-Agents.md` | anthropic.com/engineering/building-effective-agents（9/16 抓的） |

> 抓取说明：`platform.openai.com` 的文档页有 Cloudflare 拦截（403），所以 OpenAI 这边只留下官方 PDF 原文；
> 文字抽取需要 `pypdf`，当前 venv 里没装——要看内容直接打开 PDF。
> 抓取脚本：`.workbuddy/tmp/fetch_agent_articles_20260927.py`（要重抓或补文章直接改这个列表）。
