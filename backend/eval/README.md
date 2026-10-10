# Agent 行为评测（backend/eval）

把「真实话术 → 期望行为」跑成可比较的数字。`tests/` 里 59 个用例全部把模型 mock 掉，
只验了路由分支与数据流；模型到底选没选对工具、有没有乱写库，这个目录负责回答。

**当前基线（2026-10-01，真模型 79 条）**：通过 **78/79**（剔除已知短板 **100%**）· 路由 79/79 ·
工具 79/79 · 写库 79/79 · 回复 79/79 · 误写率 **0/54** · 越权写库 0 · 118 次调用 · 平均 1.4s。
唯一失败的是已知短板 `r02`（`create_task` 没幂等护栏，同一句话连发会再建一条；`d02`、`r02`
都是波动型短板，见 `DECISIONS.md` D-028/D-029）。另有 L4 终态评测 **5/5**（多轮 + 断言最终状态）。
档案在工作区 `docs/Agent_Audit_Logs/2026-10-01_stage3/`。

## 跑法

```bash
cd backend

# 1) 离线：只跑代码层判定（路由/正则），零 token，秒级
../venv/Scripts/python.exe eval/run_agent_eval.py

# 2) 在线：真实模型走完整链路（消耗 token）
../venv/Scripts/python.exe eval/run_agent_eval.py --mode live

# 常用过滤
../venv/Scripts/python.exe eval/run_agent_eval.py --mode live --only 安全护栏
../venv/Scripts/python.exe eval/run_agent_eval.py --mode live --limit 5
../venv/Scripts/python.exe eval/run_agent_eval.py --mode live --keep
```

报告（Markdown + JSON）默认写到系统临时目录 `squad_agent_eval/reports/`，不进仓库。
重跑只会重建评测库与向量库，**历史报告会保留**，可直接做修复前后对照；用 `--workdir` 可另开一份环境。

## 判什么

每条用例四个维度，任一不过 = 用例不过：

| 维度 | 判据 | 想拦住的问题 |
|---|---|---|
| 路由 | 代码层 route 是否等于期望（query / ask / plan / conflict / agent） | 正则漏判、误判 |
| 工具 | `must_call_any` 至少命中一个；`must_not_call` 一个都不能调 | 该查不查、该改不改、乱调工具 |
| 写库 | 只读请求必须零写入（含"改负责人/加成员"也算写）；写请求数量要落在区间 | 幻觉写库、重复写库 |
| 回复 | 回复里必须出现真实数据（任务数、任务名、纪要里的结论） | 不查库直接泛泛而谈 |

写库的判定口径（`expect.write.mode`）：`none`／`create`／`update`／`delete`／`doc`／
`assign`（改负责人，且**不允许连带改状态**——D-005）／`member`（加成员）／`assign_or_member`。

额外几项全局指标：

- 误写率：只读类请求里实际发生写库的比例（最危险的错误）。
- 越权写库：写到了非绑定项目的次数（绑定模式下必须为 0）。
- 工具选择正确率、**工具报错数**、每用例 token、平均耗时（用来观察工具与提示词改动的收益）。

`known_gap: true` 的用例是已知短板，单独统计，用来观察「改了之后有没有变好」，
不掩盖回归信号。`repeat: 2` 的用例会把同一句话连发两次，检查第二次是否又建一批（幂等）。

## 数据集

`agent_eval_cases.json`，分类：查询 12 / 写入 14 / 安全护栏 8 / 知识记忆 5 /
闲聊 3 / 幂等 2 / 成员指派 6 / 按名单分配 4 / 只读负例 11 / 记忆闭环 5 / **批量写 5** / **撤销 4**（共 **79 条**）。
话术尽量照抄真实用户说法（口语、省略主语、歧义说法都有）。
夹具固定为两个项目 + 6 个任务 + 3 篇文档（需求说明书、会议纪要、**相关人员说明**）+ **2 个成员**（张三、李四），
每条用例前复位到基线，用例之间不共享会话历史。
新增用例：往 `cases` 里加一条即可，字段说明见文件头的 `fields`。

用例前置 `setup`（可选）：

- `plan_assignment`：先让 Agent 按名单拟一份**待确认**方案，用来测「就按这个来」会不会落库。
  offline 模式下不调模型，直接塞一条 pending 记录（保持零 token）。
- `plan_bulk_status` / `plan_bulk_delete`：先生成一份待确认的**批量方案**（改状态 / 删除），
  用来测「确认」会不会落库、以及方案阶段零写入。
- `applied_bulk_status` / `applied_assignment` / `deleted_task`：先落库一次（真的改了库），
  给「撤销」用例准备台账。
- `prior_conversation`：先塞两轮前置对话，让「把刚才的结论存成会议纪要」里的"刚才"有指代
  ——夹具默认清历史，没有它这条用例会变成"让模型凭空编纪要"（实测过，见审计档案）。
- `note_draft` / `note_saved`：给记忆闭环用例准备状态（先拟一条结论草稿；`note_saved` 在 live 模式下再存进项目记忆并向量化）。

## L4 · 终态评测（多轮改状态后，最终状态对不对）

三层评测有个共同盲区：**只看单轮的「这句话处理得对不对」**。可是会改状态的 agent 真正
会翻车的地方是**最终结果**——连说几句之后，任务到底停在什么状态。所以单开一层：

```bash
cd backend
../venv/Scripts/python.exe eval/run_terminal_eval.py                 # 全量（真模型）
../venv/Scripts/python.exe eval/run_terminal_eval.py --only 批量写终态
../venv/Scripts/python.exe eval/run_terminal_eval.py --keep          # 保留评测库排查
```

用例在 `terminal_eval_cases.json`：每条给一串 `turns`（真实话术按顺序发），跑完读库断言
`expect_final`（任务状态 / 负责人 / 任务数 / 该不该存在），还可以用 `expect_after_turn`
断言**时序**——比如「第 1 轮必须零写入、第 2 轮才落库」，这正是「先方案后落库」的关键证据。
当前 5 条覆盖：多轮改状态终态、批量改状态 + 撤销、批量删除 + 撤销、指派 + 撤销、跨项目拦截后的终态。

## 隔离性

- 评测库（SQLite）与向量库（Chroma）落在独立临时目录，不碰 `project_manager.db` 演示数据；
- 走真实 FastAPI 路由（TestClient），与线上同一条代码路径；
- 只从 `backend/eval/` 读用例、向临时目录写报告，对仓库本身只读。

## 怎么读结果

- 离线看两件事：代码层直接裁决了多少（其余走 agent 兜底），以及路由误判在哪。
- 在线看四个维度分数与误写率。改提示词 / 换模型 / 调工具描述之后重跑，
  通过率变化就是这次改动的收益，不用再凭感觉说「好像聪明了一点」。
