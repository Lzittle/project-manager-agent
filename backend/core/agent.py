"""Agent 核心：手写工具循环（openai function calling，不依赖 LangChain）。

流程：组装 messages(system + history + user) → 请求模型(带 tools)
     → 若返回 tool_calls 则逐个执行工具、结果以 role="tool" 消息追加 → 再次请求
     → 直到模型不再调用工具、给出最终文本回复。

意图分支由「模型决策 + 工具执行」完成：
  闲聊/问候            → 直接回答（不调工具）
  查询项目信息/知识     → search_knowledge（RAG 检索项目知识库）
  创建/查询项目         → create_project / list_projects
  创建任务/改状态       → create_task / update_task_status / list_tasks

数据访问统一走 services 层（与 REST API 共用），见 services/。
"""
import json
import re
import time
from datetime import datetime
from typing import Any, Optional

from core import llm
from core.rag import search as rag_search
from models.database import (SessionLocal, Project, Task, PlanRun, AssignmentRun,
                             KnowledgeDocument, Member)
from services import knowledge_service, member_service, project_service, task_service

MAX_ITER = 8  # 单轮最多工具迭代次数，防死循环

# 优先级中文（拼提示词与轨迹文案用）
_PRI_CN = {"high": "高", "medium": "中", "low": "低"}


def _clip(v: Any, limit: int = 120) -> str:
    """把任意值压成适合展示的短字符串（截断超长文本/参数）。"""
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
    return s if len(s) <= limit else s[:limit] + "…"


def _brief_error(exc: Exception, hint: str = "") -> str:
    """把异常压成「类型 + 一句关键信息 +（可选）建议」。

    12-Factor Agents ⑨：错误要压缩后再回填上下文。原样把堆栈喂回去既烧 token，
    又会把模型带偏——它会开始分析堆栈，而不是换个办法把事办成。
    """
    raw = str(exc).strip()
    first = raw.splitlines()[0] if raw else ""
    text = f"{type(exc).__name__}：{_clip(first, 140)}" if first else type(exc).__name__
    return f"{text}｜建议：{hint}" if hint else text

def build_system_prompt(project_id: Optional[int] = None,
                        project_name: Optional[str] = None) -> str:
    # 提示词是「每次调用都要付」的固定成本：只留判断用得到的规则，例子尽量压到一行。
    prompt = """你是「项目管理 Agent」：用自然语言帮用户管理项目和任务，也能基于项目知识库回答问题。

铁律：
1. 只依据工具返回的真实数据作答，不编造；用简体中文，回答简洁。
2. 要删/改的对象不明确时，先用 list_tasks / list_projects 查真实 id；仍不确定就问一句，绝不猜。
3. 只做用户要的那件事，不顺手多做（例：指派只改负责人，不改状态）。
4. 说法千变万化也要映射到工具，禁止回答「做不到」：
   - 删任务→delete_task；删项目→delete_project；改任务标题/描述/状态/优先级→update_task_fields；
     改项目名/项目描述→update_project_fields；把结论存成纪要→save_meeting（仅用户明确要求记录时）。
   - 「任务清单/列表/看板/进度」是只读：基于已有数据回答，禁止 plan_tasks。
   - 「加 N 个任务」却没给内容 → 先问内容，绝不自动规划一整套；要按主题拆一整套才用 plan_tasks。
5. 问项目资料（需求/方案/验收/纪要）→ search_knowledge 检索后再答。
6. 指派：「把 X 派给张三」→ list_members 认人（名册没有就先 create_member 建占位成员并把邀请码告诉用户）
   → assign_task；认不出人或有重名先问一句。
7. 「按名单/人员说明分配」→ plan_assignment_from_doc（不写库）→ 把方案原样呈现并说明「还没落库」→
   仅当用户确认（「就按这个来」）后才 apply_assignment；微调用它自己的 overrides 参数。
8. 纯闲聊直接回答，不调工具。"""
    if project_id is not None:
        name = f"「{project_name}」" if project_name else ""
        prompt += (f"\n\n已绑定项目 {name}(id={project_id})：只围绕它工作，工具会自动落到该项目，"
                   "不要反问「哪个项目」，也不要提及或编造其他项目；要新建项目请让用户在页面上方操作。")
    return prompt


# ---------- 确定性路由辅助（绑定项目时先于 LLM 决策，杜绝跨项目串扰） ----------
_PLAN_HINT_WORDS = ("拆解", "分解", "帮我规划", "规划任务", "任务规划",
                    "规划一下", "规划几个", "生成几个任务", "安排几个任务",
                    "帮我生成任务", "帮我安排任务")
# 出现在话术里多为「查询/检索知识库」而非「自动规划」，命中则不强制路由
_PLAN_NOISE = ("文档", "资料", "知识库", "检索", "搜索", "找一下",
               "查一下", "有什么", "有哪些", "怎么", "如何")
# 「任务」后面紧跟这些词 → 是「看清单/看列表」这类只读请求，不是写或规划
_TASK_READONLY_AFTER = r"(?!清单|列表|表格)"


def is_plan_intent(text: str) -> bool:
    """判断是否「自动规划任务」意图（用户未给任务明细）。

    仅用于绑定项目后的确定性路由：命中则直接对绑定项目执行 plan_tasks，
    不再把「给哪个项目规划」交给 LLM 决策 —— 模型反问/编造由此在源头被掐断。
    判定故意偏保守：普通问答、知识库检索类话术不会被误判成规划。
    """
    t = text.strip()
    if any(w in t for w in _PLAN_NOISE):
        return False
    if any(w in t for w in _PLAN_HINT_WORDS):
        return True
    return bool(re.search(rf"(?:生成|规划|安排)\S{{0,6}}任务{_TASK_READONLY_AFTER}", t))


def find_project_mention(db, user_id: int, bound_project_id: int, text: str):
    """若用户话术点到了绑定项目以外的项目 → 返回该项目（路由层拦截用）。

    项目名可能被泛化使用（如项目叫「测试」而用户在闲聊「测试一下」），
    因此这里只做「拦截提示、绝不写数据」，最坏情况是让用户先切换项目，安全。
    """
    for p in project_service.list_projects(db, user_id):
        if p.id == bound_project_id:
            continue
        if p.name and len(p.name) >= 2 and p.name in text:
            return p
    return None


# ---------- 绑定项目时的确定性路由（代码判定，先于 LLM 决策） ----------
_TASK_ADD_HINT = re.compile(r"(?:加|建|创建|新增|添加|安排|补)\S{0,4}任务|任务[:：]")
# 删除类写意图：覆盖「删掉XX任务/删除XX项目的任务/把XX任务删掉/清掉XX」
_TASK_DEL_HINT = re.compile(
    r"(?:删|删除|移除|清理|划掉|去掉)\S{0,12}(?:任务|项目)|(?:任务|项目)\S{0,8}(?:删|删除|划掉|移除)")
# 进度/状态查询（只读，不写数据）：命中则由代码层先注入真实任务数据再让模型作答
_PROGRESS_HINT = re.compile(
    r"进度|进展|怎么样了|怎么样|什么情况|什么状态|还剩|还有哪些|任务列表|任务清单|"
    r"看看任务|查看任务|任务情况|完成情况|完成多少|多少任务|多少个任务|"
    r"进行到|当前状态|目前状态|做到哪|状态如何|状态分布|任务状态|"
    r"有几条|有几个|有哪几|有哪些任务|列出来|列出|doing|todo")
# 出现写动作（加/删/改/规划/状态流转）时不算纯查询，交给对应写工具/写路由
_WRITE_ACTION = re.compile(
    r"(?:加|建|创建|新增|添加|安排|补|删|删除|移除|清理|划掉|去掉|"
    r"改|编辑|更新|标记|设为|调|规划|拆解|分解|生成|安排|推进|开始|完成)\S{0,6}"
    r"(?:任务|项目|状态|优先级|描述|标题)" + _TASK_READONLY_AFTER)
# 出现「数量 + 个任务」（如：加两个任务 / 增加 3 个任务 / 加几个任务）
_COUNT_TASK = re.compile(r"(?:[0-9]+|[一二两三四五六七八九十]|两|几|多)\s*个\s*任务")
# 已给出任务明细的特征（引号包裹 或 「任务：」冒号后跟内容）
_DETAIL_MARK = re.compile(r"[「『【]|任务\s*[:：]")


def _is_task_write_intent(text: str) -> bool:
    """是否「要往某个项目写任务」：规划意图 / 显式「加/建任务」/ 删除任务指令。"""
    return (is_plan_intent(text)
            or bool(_TASK_ADD_HINT.search(text))
            or bool(_TASK_DEL_HINT.search(text)))


def is_progress_query(text: str) -> bool:
    """是否「查询项目进度/任务状态」类只读意图。

    命中且已绑定项目时，路由层先强制读取真实任务数据注入上下文，
    再让模型作答 —— 防止模型「不查库直接泛泛而谈/编造进度」。
    与写意图互斥：出现加/删/改/推进类动作词时不算查询（走写工具）。
    """
    t = text.strip()
    if not t:
        return False
    if _WRITE_ACTION.search(t):
        return False
    if _is_task_write_intent(t):
        return False
    return bool(_PROGRESS_HINT.search(t))


def is_ask_detail_intent(text: str) -> bool:
    """写任务意图但用户只给了「数量/泛泛几个任务」、没有任何任务明细 →
    代码层直接追问内容，防止模型把「加 2 个任务」误当成主题规划一次生成 5 条。

    例如命中：
      「帮我加两个任务」「增加3个任务」「加几个任务吧」
    不命中（已有明细，交给 Agent 逐个创建）：
      「加两个任务：① 登录页优化 ② 支付修复」
      「给 XX 加一个任务：上线前回归测试」
    """
    if not _is_task_write_intent(text):
        return False
    if is_plan_intent(text):  # 「帮我规划几个任务」→ 仍是按主题规划，不拦
        return False
    return bool(_COUNT_TASK.search(text)) and not _DETAIL_MARK.search(text)


# 「按名单分配」与「确认落库」的确定性识别（代码拍板，避免模型漏调工具）
_ROSTER_DOC_HINT = re.compile(
    r"名单|人员说明|人员介绍|人员资料|分工说明|团队介绍|团队成员|上传的(?:说明|资料|文档)")
_ASSIGN_PLAN_HINT = re.compile(r"分配|分工|安排|分下去|分给|认人|落到人")
# 确认语：短句、明确的「按这个方案来」；只在真的有待确认方案时才生效（见 resolve_bound_action）
_APPLY_ASSIGN_HINT = re.compile(
    r"(?:就)?(?:按|照|依)(?:这个|这份|上述|上面的|你(?:说|给)的)(?:方案|分配|安排|名单)?(?:来|办|执行|落库)?"
    r"|^(?:确认|确认吧|确认分配|同意|没问题|就这样|照这个来|落库|执行吧|开始分配|开始吧)[，,。!！\s]*$")


def is_assign_plan_intent(text: str) -> bool:
    """是否「按上传的名单/人员说明做分配」：既要提到名单类资料，也要有分配动作。"""
    t = (text or "").strip()
    return bool(_ROSTER_DOC_HINT.search(t)) and bool(_ASSIGN_PLAN_HINT.search(t))


def is_apply_assignment_intent(text: str) -> bool:
    """是否「确认把分配方案落库」。只在存在待确认方案时路由（见 resolve_bound_action），
    所以这里可以宽松一点，也不用担心闲聊里的「确认」被误判。"""
    t = (text or "").strip()
    if not t or len(t) > 40:
        return False
    return bool(_APPLY_ASSIGN_HINT.search(t))


def has_pending_assignment(db, user_id: int, project_id: int) -> bool:
    """该项目是否有一份还没落库的分配方案（决定「确认」这句话要不要走落库路由）。"""
    return (db.query(AssignmentRun)
            .filter_by(user_id=user_id, project_id=project_id, status="pending")
            .order_by(AssignmentRun.id.desc()).first()) is not None


def resolve_bound_action(db, user_id: int, bound_project_id: Optional[int],
                         bound_project_name: Optional[str], message: str):
    """绑定项目场景下，把「高确定性」的情况在进入 LLM 前先用代码判定：

    返回 (action, payload)：
      ("conflict", other_name)  消息要写任务却点名绑定项目之外的项目
                                → 提示先切换，绝不跨项目写数据；
      ("ask",      None)        要加任务但只给数量/没给明细（如「加两个任务」）
                                → 先追问内容，绝不自动规划一整批；
      ("plan",      None)       纯规划意图 → 直接对绑定项目执行 plan_tasks；
      ("query",     None)       只读进度/状态查询 → 先注入真实任务数据再让模型作答；
      ("agent",     None)       其余 → 交给 Agent 工具循环（工具已按绑定项目裁剪）。

    说明：仅「提及别的项目」（如“参照A项目的做法”）不拦截，交给裁剪后的
    Agent —— 工具里已无 project_id，它也无法把数据写到别的项目。
    """
    if bound_project_id is None:
        return ("agent", None)
    other = find_project_mention(db, user_id, bound_project_id, message)
    if other is not None and _is_task_write_intent(message):
        return ("conflict", other.name)
    # 名单分配 / 确认落库：都要求「绑定项目」，且判在 plan 之前 ——
    # 「按名单安排任务」不该被当成「按项目主题自动规划一批任务」。
    if is_assign_plan_intent(message):
        return ("assign_plan", None)
    if has_pending_assignment(db, user_id, bound_project_id) and is_apply_assignment_intent(message):
        return ("apply", None)
    if is_plan_intent(message):
        return ("plan", None)
    if is_ask_detail_intent(message):
        return ("ask", None)
    if is_progress_query(message):
        return ("query", None)
    return ("agent", None)


# ---------- 工具定义 ----------
def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


TOOLS: list[dict] = [
    _fn(
        "list_projects",
        "列出用户的全部项目（含任务数）。用于「有哪些项目」",
        {},
        [],
    ),
    _fn(
        "create_project",
        "新建项目。用于「帮我建一个 XX 项目」",
        {"name": {"type": "string", "description": "项目名称"},
         "description": {"type": "string", "description": "项目描述（可空）"}},
        ["name"],
    ),
    _fn(
        "list_tasks",
        "列任务：默认回 40 条，每条含 id/标题/状态/优先级/负责人（不含描述）；"
        "翻页用 offset，只看某状态用 status。用于「任务清单/有哪些任务」",
        {"project_id": {"type": "integer", "description": "项目 id（可省略，默认当前绑定项目）"},
         "status": {"type": "string", "enum": ["todo", "doing", "done"],
                    "description": "只看某种状态（可省略）"},
         "limit": {"type": "integer", "description": "本次最多回多少条（默认 40，上限 200）"},
         "offset": {"type": "integer", "description": "从第几条开始（默认 0，用于翻页）"}},
        [],
    ),
    _fn(
        "create_task",
        "建单个任务（用户已给明确内容时用；要按主题拆一整套用 plan_tasks）",
        {"project_id": {"type": "integer", "description": "所属项目 id（可省略，默认当前绑定项目）"},
         "title": {"type": "string", "description": "任务标题"},
         "description": {"type": "string", "description": "任务描述（可空）"},
         "status": {"type": "string", "enum": ["todo", "doing", "done"], "description": "状态，默认 todo"},
         "priority": {"type": "string", "enum": ["high", "medium", "low"], "description": "优先级，默认 medium"}},
        ["title"],
    ),
    _fn(
        "update_task_status",
        "改任务状态（todo/doing/done）。用于「标记完成/开始做这个」",
        {"task_id": {"type": "integer", "description": "任务 id"},
         "status": {"type": "string", "enum": ["todo", "doing", "done"], "description": "目标状态"}},
        ["task_id", "status"],
    ),
    _fn(
        "delete_task",
        "删除任务（连带评论）。先用 list_tasks 查到真实 task_id",
        {"task_id": {"type": "integer", "description": "要删除的任务 id"}},
        ["task_id"],
    ),
    _fn(
        "update_task_fields",
        "改任务的标题/描述/状态/优先级（只传要改的字段）",
        {"task_id": {"type": "integer", "description": "任务 id"},
         "title": {"type": "string", "description": "新标题（可选）"},
         "description": {"type": "string", "description": "新描述（可选）"},
         "status": {"type": "string", "enum": ["todo", "doing", "done"], "description": "新状态（可选）"},
         "priority": {"type": "string", "enum": ["high", "medium", "low"], "description": "新优先级（可选）"}},
        ["task_id"],
    ),
    _fn(
        "delete_project",
        "删除项目（连带任务/评论/文档/向量，不可恢复）。先 list_projects 查 id",
        {"project_id": {"type": "integer", "description": "要删除的项目 id"}},
        ["project_id"],
    ),
    _fn(
        "update_project_fields",
        "改项目名或项目描述（改任务字段请用 update_task_fields）",
        {"project_id": {"type": "integer", "description": "项目 id"},
         "name": {"type": "string", "description": "新项目名（可选）"},
         "description": {"type": "string", "description": "新描述（可选）"}},
        ["project_id"],
    ),
    _fn(
        "search_knowledge",
        "在项目知识库（资料/会议纪要）里检索片段，回答「资料里怎么写的」",
        {"query": {"type": "string", "description": "检索问题"},
         "project_id": {"type": "integer", "description": "限定项目（可空）"}},
        ["query"],
    ),
    _fn(
        "save_meeting",
        "把本次对话已确认的结论/决策/待办整理成会议纪要存入知识库（之后可被检索到）。"
        "仅在用户明确要求记录/归档时用（「记下来/存成纪要/归档」）；内容必须忠于对话，不得编造",
        {"project_id": {"type": "integer", "description": "要归档纪要的项目 id（可省略，默认当前绑定项目）"},
         "title": {"type": "string", "description": "纪要主题（建议含日期）"},
         "content": {"type": "string", "description": "纪要正文：结论/决策/待办的结构化要点"}},
        ["title", "content"],
    ),
    _fn(
        "plan_tasks",
        "按项目主题拆解并创建一批任务（默认待办）。只用于用户没给明细、要「帮我规划任务」时；"
        "只读请求（任务清单/进度）禁用；用户已给明细就用 create_task 逐个建。force=true 才重新规划一批",
        {"project_id": {"type": "integer", "description": "要规划任务的项目 id（可省略，默认当前绑定项目）"},
         "force": {"type": "boolean",
                   "description": "true=用户明确要求重新规划一批新任务；默认 false 时，该项目刚规划过会直接复用上一批，不重复创建"}},
        [],
    ),
    _fn(
        "list_members",
        "查小队成员名册（id/名字/状态）。指派前先用它把人匹配成 member_id",
        {},
        [],
    ),
    _fn(
        "create_member",
        "把一个人加进名册（占位成员，带邀请码，等对方注册认领）。"
        "同名会失败——那就问用户是不是同一个人",
        {"name": {"type": "string", "description": "成员名字（如「陈工」）"}},
        ["name"],
    ),
    _fn(
        "assign_task",
        "把任务指派给成员：**只改负责人、不改状态**。"
        "先 list_tasks 拿 task_id、list_members 拿 member_id（名册没有就先 create_member）",
        {"task_id": {"type": "integer", "description": "任务 id"},
         "member_id": {"type": "integer", "description": "成员 id（来自 list_members）"}},
        ["task_id", "member_id"],
    ),
    _fn(
        "plan_assignment_from_doc",
        "读资产库资料（默认最新一篇，通常是「相关人员说明/名单」）+ 名册 + 未完成任务，"
        "拟一份「任务 → 负责人」方案。**不写库**：先给用户过一眼，确认后再 apply_assignment",
        {"doc_id": {"type": "integer", "description": "指定资料 id（可省略：默认取该项目最近上传的一篇）"},
         "project_id": {"type": "integer", "description": "项目 id（可省略，默认当前绑定项目）"}},
        [],
    ),
    _fn(
        "apply_assignment",
        "把方案真正落库（写负责人）。**仅在用户明确确认后**调用；"
        "名单外的人会建成占位成员，重名的条目跳过并报告",
        {"plan_id": {"type": "integer", "description": "方案 id（可省略：默认最近一份待确认的方案）"},
         "overrides": {"type": "array",
                       "description": "微调：只覆盖指定任务的负责人，"
                                      "形如 [{\"task_id\": 39, \"member_name\": \"李工\"}]",
                       "items": {"type": "object",
                                 "properties": {"task_id": {"type": "integer"},
                                                "member_name": {"type": "string"}}}}},
        [],
    ),
]


# 只读场景（进度/清单这类问题）只给查询类工具：
# 既省固定成本，也从根上杜绝"只想看进度，却顺手写了库"（评测里最危险的错误类别）。
READONLY_TOOL_NAMES = {"list_projects", "list_tasks", "search_knowledge", "list_members"}


def build_tools(project_id: Optional[int] = None, readonly: bool = False) -> list[dict]:
    """按会话状态裁剪工具列表。

    - 未绑定项目：暴露全部 7 个工具（模型可自由创建/查询项目）；
    - 已绑定项目：摘掉 list_projects / create_project，并移除项目类工具里的
      project_id 参数 —— 模型既看不到「还有别的项目」、也无法传错项目，
      所有落点由执行器固定为绑定项目。反问「要给哪个项目」从此无从发生。
    - readonly=True：只留查询类工具（用于进度/清单类只读问题）。
    """
    if readonly and project_id is None:
        return [t for t in TOOLS if t["function"]["name"] in READONLY_TOOL_NAMES]
    if project_id is None:
        return TOOLS
    # 绑定模式：禁止项目级新建/删除/改名，避免模型跨项目动数据；任务级删除/编辑按 id 操作可保留
    HIDDEN = {"list_projects", "create_project", "delete_project", "update_project_fields"}
    trimmed = []
    for t in TOOLS:
        name = t["function"]["name"]
        if name in HIDDEN or (readonly and name not in READONLY_TOOL_NAMES):
            continue
        # 浅拷贝参数结构，避免污染全局 TOOLS
        props = dict(t["function"]["parameters"]["properties"])
        required = [r for r in t["function"]["parameters"].get("required", [])
                    if r != "project_id"]
        props.pop("project_id", None)
        trimmed.append({
            "type": "function",
            "function": {
                "name": name,
                "description": t["function"]["description"],
                "parameters": {"type": "object", "properties": props,
                               "required": required},
            },
        })
    return trimmed


# ---------- 工具执行（业务逻辑经 services 层，user_id 由会话注入不暴露给模型） ----------
class _ToolExecutor:
    # 同一项目重复规划的复用窗口（秒）：窗口内重复触达 → 复用上一批，不再新建
    PLAN_DEDUP_WINDOW_SEC = 300
    # 任务列表瘦身：一次默认回多少条、上限多少（模型可带 limit/offset 翻页）
    TASK_LIST_LIMIT = 40
    TASK_LIST_MAX = 200

    def __init__(self, user_id: int, project_id: Optional[int] = None,
                 readonly: bool = False):
        self.user_id = user_id
        self.project_id = project_id
        self.readonly = readonly
        # 本轮会话的执行轨迹（Agent 感可见化）：每执行一个工具记一条
        self.last_trace: list[dict] = []
        # 缓存绑定项目名：注入 system prompt，防止模型引用错项目名
        self.project_name: Optional[str] = None
        if project_id is not None:
            db = SessionLocal()
            try:
                p = db.get(Project, project_id)
                self.project_name = p.name if p else None
            finally:
                db.close()

    def _project_brief(self, p) -> dict:
        return {"id": p.id, "name": p.name, "description": p.description,
                "status": p.status, "task_count": len(p.tasks)}

    def _task_brief(self, t, assignee_name: Optional[str] = None) -> dict:
        """任务瘦身版（给模型看的）：只留"找 id / 看状态 / 认人"要用的字段。

        刻意不带 description —— 一条描述动辄上百字，模型在选任务、报进度时用不上，
        却会成倍推高每一轮 token（Anthropic《Writing effective tools for agents》的原则：
        工具返回要有意义、要对 token 友好）。
        """
        d = {"id": t.id, "title": t.title, "status": t.status, "priority": t.priority}
        if assignee_name:
            d["assignee"] = assignee_name
        return d

    def list_projects(self) -> dict:
        db = SessionLocal()
        try:
            data = [self._project_brief(p)
                    for p in project_service.list_projects(db, self.user_id)]
            return {"ok": True, "data": data}
        finally:
            db.close()

    def create_project(self, name: str, description: str = "") -> dict:
        db = SessionLocal()
        try:
            p = project_service.create_project(db, self.user_id, name, description)
            return {"ok": True, "data": {"id": p.id, "name": p.name, "status": p.status}}
        finally:
            db.close()

    def list_tasks(self, project_id: Optional[int] = None, status: Optional[str] = None,
                   limit: Optional[int] = None, offset: int = 0) -> dict:
        """列任务：默认最多 40 条，可按状态过滤、可翻页。

        返回里带 total / shown：模型据此知道"还有没有没看到的"，需要时自己带 offset 再查，
        而不是一次把几百条任务灌进上下文。
        """
        pid = project_id or self.project_id
        if pid is None:
            return {"ok": False, "error": "未指定项目：请先绑定项目或在话术中说明项目名称"}
        db = SessionLocal()
        try:
            rows = task_service.list_tasks(db, pid)  # 已按 id 倒序（新的在前）
            if status in ("todo", "doing", "done"):
                rows = [t for t in rows if t.status == status]
            total = len(rows)
            cap = max(1, min(int(limit or self.TASK_LIST_LIMIT), self.TASK_LIST_MAX))
            off = max(0, int(offset or 0))
            page = rows[off:off + cap]
            ids = {t.assignee_id for t in page if t.assignee_id}
            names = {}
            if ids:
                names = {m.id: m.name
                         for m in db.query(Member).filter(Member.id.in_(ids)).all()}
            data = [self._task_brief(t, names.get(t.assignee_id)) for t in page]
            res = {"ok": True, "data": data, "total": total, "shown": len(data)}
            if off + len(data) < total:
                res["note"] = (f"共 {total} 条，本次回了 {len(data)} 条（offset={off}）；"
                               "需要更多请带 offset 再查，或按 status 过滤")
            return res
        finally:
            db.close()

    def project_snapshot(self, project_id: Optional[int] = None) -> dict:
        """读取项目当前真实状态快照（含依赖与风险），供注入上下文让模型基于数据作答。

        区别于 list_tasks 的平铺列表：这里给模型的是「一句话能看懂」的汇总——
        各状态数量、未完成高优任务、被阻塞/依赖未就绪的任务。全部来自数据库，模型不可编造。
        """
        pid = project_id or self.project_id
        if pid is None:
            return {"ok": False, "error": "未指定项目"}
        db = SessionLocal()
        try:
            p = db.get(Project, pid)
            if p is None:
                return {"ok": False, "error": f"项目 {pid} 不存在"}
            tasks = task_service.list_tasks(db, pid)
            dep_rows = task_service.list_project_dependencies(db, pid)
            by_status: dict[str, list[dict]] = {"todo": [], "doing": [], "done": []}
            high_open = []  # 未完成的高优任务
            for t in tasks:
                b = self._task_brief(t)
                by_status.setdefault(t.status, []).append(b)
                if t.status != "done" and t.priority == "high":
                    high_open.append(b["title"])
            # 被依赖阻塞：前置任务未 done 的任务（自己也没 done）
            dep_by_task: dict[int, list[dict]] = {}
            for d in dep_rows:
                dep_by_task.setdefault(d["task_id"], []).append(d)
            blocked = []
            for d in dep_rows:
                if d["depends_on_status"] != "done":
                    blocked.append({
                        "task": d["task_title"],
                        "waiting_on": d["depends_on_title"],
                        "pre_status": d["depends_on_status"],
                    })
            return {
                "ok": True,
                "data": {
                    "project": {"id": p.id, "name": p.name,
                                "status": p.status, "description": p.description},
                    "task_count": len(tasks),
                    "by_status": {k: len(v) for k, v in by_status.items()},
                    # 任务明细（供只读问答直接点名作答，不必再让模型自己查一遍）
                    "tasks": [self._task_brief(t) for t in tasks[:30]],
                    "tasks_truncated": max(0, len(tasks) - 30),
                    "done_ratio": round(len(by_status["done"]) / len(tasks), 2) if tasks else 0.0,
                    "high_open": high_open[:10],
                    "blocked": blocked[:10],
                    "dependencies": len(dep_rows),
                },
            }
        finally:
            db.close()

    def create_task(self, project_id: Optional[int] = None, title: str = "",
                    description: str = "", status: str = "todo",
                    priority: str = "medium") -> dict:
        # project_id 未提供时回落到当前绑定项目
        pid = project_id or self.project_id
        if pid is None:
            return {"ok": False, "error": "未指定项目：请先绑定项目或在话术中说明项目名称"}
        db = SessionLocal()
        try:
            t = task_service.create_task(
                db, pid, self.user_id, title,
                description=description, status=status, priority=priority)
            if t is None:
                return {"ok": False, "error": f"项目 {pid} 不存在"}
            return {"ok": True, "data": {"id": t.id, "title": t.title,
                                         "project_id": pid, "status": t.status}}
        finally:
            db.close()

    def update_task_status(self, task_id: int, status: str) -> dict:
        db = SessionLocal()
        try:
            t = task_service.update_task(db, task_id, status=status)
            if t is None:
                return {"ok": False, "error": f"任务 {task_id} 不存在"}
            return {"ok": True, "data": {"id": t.id, "title": t.title, "status": t.status,
                                         "project_id": t.project_id}}
        finally:
            db.close()

    def delete_task(self, task_id: int) -> dict:
        """删除任务（级联删除评论）。"""
        db = SessionLocal()
        try:
            snap = task_service.delete_task(db, task_id)
            if snap is None:
                return {"ok": False, "error": f"任务 {task_id} 不存在"}
            return {"ok": True, "data": {"id": snap["id"], "title": snap["title"],
                                         "project_id": snap["project_id"]}}
        finally:
            db.close()

    def delete_project(self, project_id: int) -> dict:
        """删除项目（级联任务/评论/文档与向量）。"""
        db = SessionLocal()
        try:
            snap = project_service.delete_project(db, project_id)
            if snap is None:
                return {"ok": False, "error": f"项目 {project_id} 不存在"}
            return {"ok": True, "data": {"id": snap["id"], "name": snap["name"],
                                         "status": snap["status"]}}
        finally:
            db.close()

    def update_task_fields(self, task_id: int, title: Optional[str] = None,
                           description: Optional[str] = None,
                           status: Optional[str] = None,
                           priority: Optional[str] = None) -> dict:
        """更新任务的标题/描述/状态/优先级（只更新调用方提供的字段）。"""
        fields: dict[str, str] = {}
        if title is not None:
            if not str(title).strip():
                return {"ok": False, "error": "任务标题不能为空"}
            fields["title"] = str(title).strip()[:200]
        if description is not None:
            fields["description"] = str(description).strip()[:500]
        if status is not None:
            if status not in ("todo", "doing", "done"):
                return {"ok": False, "error": f"非法状态 {status}（todo/doing/done）"}
            fields["status"] = status
        if priority is not None:
            if priority not in ("high", "medium", "low"):
                return {"ok": False, "error": f"非法优先级 {priority}（high/medium/low）"}
            fields["priority"] = priority
        if not fields:
            return {"ok": False, "error": "未提供任何要更新的字段（title/description/status/priority）"}
        db = SessionLocal()
        try:
            t = task_service.update_task(db, task_id, **fields)
            if t is None:
                return {"ok": False, "error": f"任务 {task_id} 不存在"}
            return {"ok": True, "data": {"id": t.id, "title": t.title, "status": t.status,
                                         "priority": t.priority, "project_id": t.project_id}}
        finally:
            db.close()

    def update_project_fields(self, project_id: int, name: Optional[str] = None,
                              description: Optional[str] = None) -> dict:
        """更新项目的名称/描述。"""
        fields: dict[str, str] = {}
        if name is not None:
            if not str(name).strip():
                return {"ok": False, "error": "项目名称不能为空"}
            fields["name"] = str(name).strip()[:100]
        if description is not None:
            fields["description"] = str(description).strip()[:500]
        if not fields:
            return {"ok": False, "error": "未提供任何要更新的字段（name/description）"}
        db = SessionLocal()
        try:
            p = project_service.update_project(db, project_id, **fields)
            if p is None:
                return {"ok": False, "error": f"项目 {project_id} 不存在"}
            return {"ok": True, "data": {"id": p.id, "name": p.name,
                                         "description": p.description, "status": p.status}}
        finally:
            db.close()

    def search_knowledge(self, query: str, project_id: Optional[int] = None) -> dict:
        pid = project_id or self.project_id
        try:
            hits = rag_search(query, project_id=pid, top_k=3)
            if not hits:
                return {"ok": True, "data": [],
                        "note": "未检索到相关文档片段，可如实告知用户知识库暂无相关内容"}
            return {"ok": True, "data": [
                {"title": h["title"], "text": h["text"][:500]} for h in hits]}
        except Exception as e:  # embedding 模型未就绪等场景
            return {"ok": False,
                    "error": "知识库检索失败：" + _brief_error(e, "稍后重试；也可以直接说任务明细")}

    def save_meeting(self, title: str, content: str,
                     project_id: Optional[int] = None) -> dict:
        """把对话结论整理成会议纪要入库（doc_type=meeting，自动向量化进项目长期记忆）。"""
        pid = project_id or self.project_id
        if pid is None:
            return {"ok": False, "error": "未指定项目：请先绑定项目或在话术中说明项目名称"}
        t = (title or "").strip()
        if not t:
            return {"ok": False, "error": "纪要标题不能为空"}
        db = SessionLocal()
        try:
            doc = knowledge_service.create_document(
                db, pid, t[:200], (content or "").strip(), file_type="txt", doc_type="meeting")
            if doc is None:
                return {"ok": False, "error": f"项目 {pid} 不存在"}
            return {"ok": True,
                    "data": {"id": doc.id, "title": doc.title,
                             "doc_type": doc.doc_type, "project_id": pid},
                    "note": "已作为会议纪要存入项目知识库（自动向量化），"
                            "之后问「上次怎么定的」即可自动检索到"}
        finally:
            db.close()

    # ---------- 执行轨迹（让每一步工具调用对用户可见、可跳转） ----------
    _LABELS = {
        "create_project": "创建项目", "list_projects": "查看项目列表",
        "list_tasks": "查看任务", "create_task": "创建任务",
        "update_task_status": "更新任务状态", "search_knowledge": "检索知识库",
        "plan_tasks": "自动规划任务",
        "delete_task": "删除任务", "delete_project": "删除项目",
        "update_task_fields": "编辑任务", "update_project_fields": "编辑项目",
        "project_snapshot": "读取项目状态", "save_meeting": "保存会议纪要",
        "list_members": "查看成员名册", "create_member": "添加成员",
        "assign_task": "指派任务", "plan_assignment_from_doc": "按名单拟分配方案",
        "apply_assignment": "落库分配方案",
    }
    _TASK_TOOLS = {"create_task", "update_task_status", "delete_task", "update_task_fields",
                   "assign_task"}
    _PROJECT_TOOLS = {"create_project", "delete_project", "update_project_fields"}

    def _refs_from(self, name: str, args: dict, result: dict) -> list[dict]:
        """提取受影响的实体（任务/项目），供前端渲染可点击跳转的引用。"""
        data = result.get("data") if result.get("ok") else None
        refs = []
        if name in self._PROJECT_TOOLS and isinstance(data, dict):
            refs.append({"kind": "project", "id": data["id"],
                         "title": data.get("name") or data.get("title", "")})
        elif name in self._TASK_TOOLS and isinstance(data, dict):
            refs.append({"kind": "task", "id": data["id"], "title": data.get("title", ""),
                         "project_id": data.get("project_id")})
        elif name == "plan_tasks" and isinstance(data, list):
            pid = args.get("project_id") or self.project_id
            for t in data:
                refs.append({"kind": "task", "id": t["id"], "title": t["title"],
                             "project_id": pid})
        elif name in ("plan_assignment_from_doc", "apply_assignment") and isinstance(data, list):
            pid = args.get("project_id") or self.project_id
            for it in data:
                refs.append({"kind": "task", "id": it.get("id") or it.get("task_id"),
                             "title": it.get("title", ""), "project_id": pid})
        return refs

    def summarize_tool(self, name: str, args: dict, result: dict, ms: int = 0) -> dict:
        """把一次工具调用压成一条对用户友好的轨迹步骤。"""
        label = self._LABELS.get(name, name)
        if not result.get("ok"):
            return {"tool": name, "label": label,
                    "detail": _clip(result.get("error", "执行失败"), 100),
                    "ok": False, "ms": ms}
        data = result.get("data")
        if name == "create_project" and isinstance(data, dict):
            detail = f"创建项目「{data.get('name','')}」（#{data['id']}）"
        elif name == "delete_project" and isinstance(data, dict):
            detail = f"删除项目「{data.get('name','')}」（#{data['id']}）"
        elif name == "update_project_fields" and isinstance(data, dict):
            changed = [k for k in ("name", "description")
                       if k in args and args[k] not in (None, "")]
            detail = f"项目「{data.get('name','')}」已更新（{'/'.join(changed) or '描述'}）"
        elif name == "create_task" and isinstance(data, dict):
            detail = f"创建任务「{data.get('title','')}」（#{data['id']}）"
        elif name == "delete_task" and isinstance(data, dict):
            detail = f"删除任务「{data.get('title','')}」（#{data['id']}）"
        elif name == "update_task_status" and isinstance(data, dict):
            detail = f"任务「{data.get('title','')}」状态 → {data.get('status','')}"
        elif name == "update_task_fields" and isinstance(data, dict):
            changed = [k for k in ("title", "description", "status", "priority")
                       if k in args and args[k] not in (None, "")]
            detail = f"任务「{data.get('title','')}」已更新（{'/'.join(changed) or '字段'}）"
        elif name == "plan_tasks" and isinstance(data, list):
            detail = (f"复用上一批 {len(data)} 条任务（未重复创建）" if result.get("reused")
                      else f"生成 {len(data)} 条任务并入库（默认待办）")
        elif name == "list_projects" and isinstance(data, list):
            detail = f"共 {len(data)} 个项目"
        elif name == "list_tasks" and isinstance(data, list):
            total = result.get("total", len(data))
            shown = result.get("shown", len(data))
            detail = (f"共 {total} 个任务" if total == shown
                      else f"共 {total} 个任务，本次回 {shown} 条（可翻页）")
        elif name == "project_snapshot" and isinstance(data, dict):
            s = data
            detail = (f"项目「{s.get('project',{}).get('name','')}」："
                      f"共 {s.get('task_count',0)} 个任务，"
                      f"待办 {s.get('by_status',{}).get('todo',0)} / "
                      f"进行中 {s.get('by_status',{}).get('doing',0)} / "
                      f"完成 {s.get('by_status',{}).get('done',0)}")
        elif name == "search_knowledge" and isinstance(data, list):
            detail = f"检索到 {len(data)} 条相关片段" if data else "知识库暂无相关内容"
        elif name == "save_meeting" and isinstance(data, dict):
            detail = f"纪要「{data.get('title','')}」已存入知识库"
        elif name == "list_members" and isinstance(data, list):
            active = sum(1 for m in data if m.get("status") == "active")
            detail = f"名册 {len(data)} 人（已注册 {active} · 待认领 {len(data) - active}）"
        elif name == "create_member" and isinstance(data, dict):
            detail = f"「{data.get('name','')}」已进名册（待认领 · 邀请码 {data.get('invite_code','')}）"
        elif name == "assign_task" and isinstance(data, dict):
            detail = (f"任务「{data.get('title','')}」负责人 → {data.get('assignee_name','')}"
                      f"（状态仍为 {data.get('status','')}）")
        elif name == "plan_assignment_from_doc" and isinstance(data, list):
            detail = f"按名单拟出 {len(data)} 条分配（待确认，未落库）"
        elif name == "apply_assignment" and isinstance(data, list):
            extra = len(result.get("created_members") or [])
            detail = (f"落库 {len(data)} 条指派"
                      + (f"，新建 {extra} 个占位成员" if extra else ""))
        else:
            detail = f"{label}完成"
        step = {"tool": name, "label": label, "detail": _clip(detail, 120),
                "ok": True, "ms": ms}
        refs = self._refs_from(name, args, result)
        if refs:
            step["refs"] = refs
        return step

    # ---------- 任务自动规划（plan_tasks 工具） ----------
    @staticmethod
    def _parse_tasks(raw) -> list[dict]:
        """从模型输出中提取任务 JSON 数组。

        输入 raw 可以是字符串（由 chat_json 兜底解析失败时的兼容路径）或
        已经解析好的 list（chat_json 正常路径）。每个任务：
        {"title":..., "description":..., "priority":..., "depends_on":[前置任务下标]}
        规划期任务尚无数据库 id，依赖用「数组下标」逻辑引用，落库时映射回真实 id。
        """
        if isinstance(raw, list):
            data = raw
        elif isinstance(raw, str):
            text = raw.strip()
            m = re.search(r"\[[\s\S]*\]", text)
            if not m:
                return []
            try:
                data = json.loads(m.group(0))
            except json.JSONDecodeError:
                return []
        else:
            return []
        if not isinstance(data, list):
            return []
        out = []
        for item in data:
            if isinstance(item, dict) and item.get("title"):
                deps = item.get("depends_on")
                dep_idx = []
                if isinstance(deps, list):
                    for d in deps:
                        if isinstance(d, (int, float)) and not isinstance(d, bool):
                            dep_idx.append(int(d))
                        elif isinstance(d, str) and d.isdigit():
                            dep_idx.append(int(d))
                out.append({
                    "title": str(item["title"]).strip()[:200],
                    "description": str(item.get("description", "")).strip()[:500],
                    "priority": item.get("priority", "medium") if item.get("priority") in ("high", "medium", "low") else "medium",
                    "depends_on": sorted(set(i for i in dep_idx if i >= 0)),
                })
        return out

    def _recent_plan(self, pid: int) -> Optional[dict]:
        """窗口内该项目刚规划过 → 返回上一批复用结果；否则 None（走正常规划）。

        幂等护栏：用户以为卡住重发、连点两次「一键规划」时，第二次直接复用上一批
        任务，而不是再生成一批。上一批任务若已被删除/重置，本护栏自动失效。
        """
        db = SessionLocal()
        try:
            run = (db.query(PlanRun)
                   .filter(PlanRun.project_id == pid, PlanRun.user_id == self.user_id)
                   .order_by(PlanRun.id.desc()).first())
            if run is None or run.created_at is None:
                return None
            age = (datetime.now() - run.created_at).total_seconds()
            if age < 0 or age > self.PLAN_DEDUP_WINDOW_SEC:
                return None
            ids = json.loads(run.task_ids or "[]")
            if not ids:
                return None
            rows = {t.id: t for t in db.query(Task).filter(Task.id.in_(ids)).all()}
            ordered = [rows[i] for i in ids if i in rows]
            if not ordered:
                return None  # 上一批已被删除 → 正常规划
            minutes = max(1, int(age // 60))
            return {
                "ok": True,
                "reused": True,
                "data": [{"id": t.id, "title": t.title, "status": t.status} for t in ordered],
                "note": (f"该项目 {minutes} 分钟前刚规划过 {len(ordered)} 个任务，本次直接复用上一批、"
                         "未重复创建；如需再规划一批新任务，请说「重新规划任务」。"),
            }
        finally:
            db.close()

    def plan_tasks(self, project_id: Optional[int] = None, goal: str = "",
                   force: bool = False) -> dict:
        """上下文感知的任务规划（AI 全流程）：
        1) 读项目已有任务清单 → 已有任务则「增量补缺」，防重复生成；
        2) RAG 检索项目记忆（会议纪要/需求文档）→ 任务贴合历史决策；
        3) 数量按项目复杂度 3~8 条自适应，不再写死 5 条；
        4) 落库带 depends_on 真实依赖边。
        5) 幂等：窗口内重复触达 → 复用上一批（见 _recent_plan），force=True 可跳过。
        主题一律取项目自身名称与描述，不接受模型传入的 goal，
        避免模型受历史话术误导、给别的主题生成任务。
        """
        # project_id 未提供时回落到当前绑定项目
        pid = project_id or self.project_id
        if pid is None:
            return {"ok": False, "error": "未指定项目：请先绑定项目或在话术中说明项目名称"}

        # 0) 幂等护栏：刚规划过就直接复用上一批（force=True 跳过）
        if not force:
            reused = self._recent_plan(pid)
            if reused is not None:
                return reused

        # 1) 项目信息 + 已有任务清单 + RAG 项目记忆（一次性读取）
        db = SessionLocal()
        try:
            p = db.get(Project, pid)
            if p is None:
                return {"ok": False, "error": f"项目 {pid} 不存在"}
            project_desc = {"name": p.name, "description": p.description or "", "status": p.status}
            existing = task_service.list_tasks(db, pid)
            existing_titles = [t.title for t in existing]
            existing_count = len(existing)
        finally:
            db.close()

        # 2) RAG 检索项目记忆（会议纪要/需求文档）；失败静默降级，不影响规划
        memory_snippets = []
        try:
            hits = rag_search(project_desc["name"], project_id=pid, top_k=3)
            memory_snippets = [{"title": h["title"], "text": h["text"][:300],
                                "doc_type": h.get("doc_type", "doc")} for h in hits]
        except Exception:
            memory_snippets = []

        # 3) 组装上下文：项目描述 + 已有任务（增量防重复）+ 记忆片段
        ctx_lines = [f"项目名称：{project_desc['name']}",
                     f"项目描述：{project_desc['description'] or '（无）'}"]
        if existing_count:
            ctx_lines.append(
                "项目已有任务（规划时请勿与下列标题重复，只补充缺失/后续阶段的任务）：")
            ctx_lines += [f"  {i}. {t}" for i, t in enumerate(existing_titles, 1)]
        else:
            ctx_lines.append("项目当前没有任务：请从零规划第一批落地任务。")
        if memory_snippets:
            ctx_lines.append("项目记忆（会议纪要/文档检索命中，任务应贴合其中的决策）：")
            for m in memory_snippets:
                tag = "会议纪要" if m["doc_type"] == "meeting" else "文档"
                ctx_lines.append(f"  ·《{m['title']}》[{tag}] {m['text']}")
        else:
            ctx_lines.append("（知识库暂无相关记忆，按项目描述合理规划即可）")
        ctx = "\n".join(ctx_lines)

        # 4) 调用 LLM 生成任务规划（chat_json：JSON 结构化输出 + 解析失败自动重试）
        try:
            parsed, jerr = llm.chat_json([
                {"role": "system", "content":
                 "你是敏捷项目管理专家。基于项目上下文规划一组具体可执行的落地任务，并给出任务间的先后依赖。"
                 "任务数量不设固定值：按项目复杂度自适应（简单项目 3~4 条，中等 5~6 条，复杂 7~8 条），"
                 "项目已有任务时应增量补缺、聚焦后续阶段，禁止重复已有标题。"
                 "输出 JSON 数组，格式："
                 '[{"title":"任务标题(不超过14字)","description":"一句话描述含验收要点",'
                 '"priority":"high|medium|low","depends_on":[前置任务下标数组]}]。'
                 "依赖规则：前置任务必须已先完成，本任务才能开始；"
                 "depends_on 里填本任务依赖的前置任务在数组中的下标（从 0 开始），"
                 "无依赖则填 []；只允许依赖下标更小的任务（保持数组近似拓扑序），不允许成环。"},
                {"role": "user", "content": ctx},
            ], temperature=0.4, max_tokens=1500)
        except Exception as e:
            return {"ok": False, "error": f"任务规划生成失败: {e}"}

        # 成功时 parsed 是已解析的 list；失败时 parsed 为 None，走统一空结果分支
        tasks = self._parse_tasks(parsed if jerr is None else [])
        if not tasks:
            return {"ok": False, "error":
                    f"任务规划生成失败（模型输出无法解析：{jerr or '空结果'}），请重试或直接说明任务明细"}

        # 5) 批量落库（统一默认待办）+ 按 depends_on 下标映射建真实依赖边
        db = SessionLocal()
        try:
            created = []
            for t in tasks[:10]:  # 上限 10 条防失控，实际由模型按复杂度 3~8
                tk = task_service.create_task(
                    db, pid, self.user_id, t["title"],
                    description=t["description"], priority=t["priority"], status="todo")
                if tk:
                    created.append(tk)

            dep_created = 0
            for i, t in enumerate(tasks[:10]):
                if i >= len(created):
                    break  # 有任务创建失败则跳过其依赖（下标可能错位，安全起见不建）
                for dep_idx in t.get("depends_on", []):
                    if 0 <= dep_idx < i and dep_idx < len(created):  # 只允许依赖更小下标
                        d, ok = task_service.add_dependency(
                            db, created[i].id, created[dep_idx].id)
                        if ok:
                            dep_created += 1
            mode = "增量补充" if existing_count else "从零规划"
            db.add(PlanRun(project_id=pid, user_id=self.user_id,
                           task_ids=json.dumps([tk.id for tk in created]),
                           task_count=len(created)))
            db.commit()
            return {
                "ok": True,
                "data": [{"id": tk.id, "title": tk.title, "status": tk.status} for tk in created],
                "note": (f"{mode} {len(created)} 个任务、{dep_created} 条依赖（默认均为待办），"
                         "可在看板查看并拖拽流转状态"),
            }
        finally:
            db.close()

    # ---------- 小队成员与指派（D-017 / D-018 / D-019） ----------
    def list_members(self) -> dict:
        """名册（已注册在前、待认领在后）。指派前用它把人匹配到 member_id。"""
        db = SessionLocal()
        try:
            rows = member_service.list_members(db)
            return {"ok": True, "data": [
                {"id": m.id, "name": m.name, "status": m.status,
                 "user_id": m.user_id, "invite_code": m.invite_code} for m in rows]}
        finally:
            db.close()

    def create_member(self, name: str) -> dict:
        """把一个名字加进名册（占位成员 + 邀请码）。同名不合并，让上层问人。"""
        n = (name or "").strip()
        if not n:
            return {"ok": False, "error": "成员名字不能为空"}
        db = SessionLocal()
        try:
            same = member_service.find_by_name(db, n)
            if same:
                return {"ok": False,
                        "error": f"名册里已有同名成员（id: {', '.join(str(m.id) for m in same)}）："
                                 "请先确认是不是同一个人，不要重复添加"}
            m = member_service.create_member(db, n)
            return {"ok": True,
                    "data": {"id": m.id, "name": m.name, "status": m.status,
                             "invite_code": m.invite_code},
                    "note": f"「{m.name}」已进名册（待认领），邀请码 {m.invite_code}；"
                            "把邀请码发给 TA，注册后即可认领这条身份"}
        finally:
            db.close()

    def assign_task(self, task_id: int, member_id: int) -> dict:
        """把任务指派给成员：只改负责人，不改状态（D-005）。"""
        db = SessionLocal()
        try:
            t = task_service.get_task(db, task_id)
            if t is None:
                return {"ok": False, "error": f"任务 {task_id} 不存在"}
            m = member_service.get_member(db, member_id)
            if m is None:
                return {"ok": False,
                        "error": f"成员 {member_id} 不在名册里（先用 list_members 查，或用 create_member 建人）"}
            if self.project_id is not None and t.project_id != self.project_id:
                return {"ok": False, "error": "该任务不在当前绑定的项目里，已拒绝跨项目指派"}
            t = task_service.update_task(db, task_id, assignee_id=m.id)
            return {"ok": True,
                    "data": {"id": t.id, "title": t.title, "status": t.status,
                             "project_id": t.project_id, "assignee_id": m.id,
                             "assignee_name": m.name, "assignee_status": m.status},
                    "note": f"负责人已改为「{m.name}」"
                            + ("（占位成员，等 TA 注册后认领）" if m.status != "active" else "")
                            + "；任务状态保持不变"}
        finally:
            db.close()

    # ---------- 读名单 → 认人 → 分配方案（轮 2，D-017） ----------
    ROSTER_CHARS = 6000  # 名单一般不长；截断防止把整篇长文塞进提示词

    @classmethod
    def _roster_text(cls, doc) -> str:
        return (doc.content or "").strip()[:cls.ROSTER_CHARS]

    @staticmethod
    def _normalize_assign_items(raw, tasks, members) -> list[dict]:
        """把模型输出规范成可核对、可落库的条目。

        认人规则（D-017「不许猜」）：
          - task_id 必须命中本次给出的任务清单；
          - 名字在名册里唯一命中 → 记 member_id；
          - 一条都没命中 → needs_create=True（确认后建占位成员）；
          - 命中多条 → ambiguous=True（落库时跳过，请人来定）。
        """
        by_name: dict[str, list] = {}
        for m in members:
            by_name.setdefault(m.name, []).append(m)
        valid_ids = {t.id for t in tasks}
        raw_items = raw if isinstance(raw, list) else (raw.get("items") if isinstance(raw, dict) else [])
        out, seen = [], set()
        for item in raw_items or []:
            if not isinstance(item, dict):
                continue
            try:
                tid = int(item.get("task_id"))
            except (TypeError, ValueError):
                continue
            name = str(item.get("member_name") or "").strip()
            if tid not in valid_ids or tid in seen or not name:
                continue
            seen.add(tid)
            hits = by_name.get(name, [])
            out.append({"task_id": tid, "member_name": name,
                        "reason": str(item.get("reason") or "").strip()[:40],
                        "member_id": hits[0].id if len(hits) == 1 else None,
                        "needs_create": len(hits) == 0,
                        "ambiguous": len(hits) > 1})
        return out

    @staticmethod
    def _assign_markdown(plan_id: int, doc_title: str, items: list[dict]) -> str:
        """把方案拼成给用户看的表格（不依赖模型二次生成，避免它改数）。"""
        lines = ["| 任务 | 负责人 | 依据 |", "| --- | --- | --- |"]
        for it in items:
            who = it["member_name"]
            if it.get("ambiguous"):
                who += "（名册里有重名，待你定）"
            elif it.get("needs_create"):
                who += "（名册没有，确认后建占位成员）"
            lines.append(f"| #{it['task_id']} {it['title']} | {who} | {it.get('reason', '')} |")
        return (f"我按《{doc_title}》拟了一份分配方案（方案 #{plan_id}，**还没落库**）：\n\n"
                + "\n".join(lines)
                + "\n\n确认就说「就按这个来」；要改就说「第 #39 条改成李工」。")

    def plan_assignment_from_doc(self, doc_id: Optional[int] = None,
                                 project_id: Optional[int] = None) -> dict:
        """读名单资料 → 认人 → 拟「任务 → 负责人」方案（**不写库**，D-017）。"""
        pid = project_id or self.project_id
        if pid is None:
            return {"ok": False, "error": "未指定项目：请先绑定项目或在话术中说明项目名称"}
        db = SessionLocal()
        try:
            if doc_id is not None:
                doc = db.get(KnowledgeDocument, doc_id)
                if doc is None or doc.project_id != pid:
                    return {"ok": False, "error": f"资料 {doc_id} 不在项目 {pid} 里"}
            else:
                doc = (db.query(KnowledgeDocument)
                       .filter(KnowledgeDocument.project_id == pid)
                       .order_by(KnowledgeDocument.id.desc()).first())
            if doc is None:
                return {"ok": False,
                        "error": "这个项目还没有上传任何资料：先把「相关人员说明/名单」传到资产库，我再来读"}
            tasks = (db.query(Task)
                     .filter(Task.project_id == pid, Task.status != "done")
                     .order_by(Task.id).limit(40).all())
            if not tasks:
                return {"ok": False,
                        "error": "这个项目还没有未完成的任务：先规划或创建任务，再来分配"}
            members = member_service.list_members(db)
            roster_line = "、".join(
                f"{m.name}（{'已注册' if m.status == 'active' else '待认领'}）"
                for m in members) or "（名册还是空的）"
            task_lines = "\n".join(
                f"#{t.id} {t.title}（优先级 {_PRI_CN.get(t.priority, t.priority)}）" for t in tasks)

            try:
                parsed, jerr = llm.chat_json([
                    {"role": "system", "content":
                     "你是小队的分工助手：根据【人员说明】把【未完成任务】分配给最合适的人。\n"
                     "规则：\n"
                     "1) 只能从【人员说明】里出现过的人里选，不要凭空造人；\n"
                     "2) 负责人的职责/角色要跟任务匹配；实在匹配不上就别分配（宁缺毋滥）；\n"
                     "3) 只输出 JSON 数组，每项形如 "
                     "{\"task_id\": 数字, \"member_name\": \"人员说明里的名字\", \"reason\": \"不超过 20 字\"}；\n"
                     "4) 同一个任务最多出现一次。"},
                    {"role": "user", "content":
                     f"【人员说明（来自资产库《{doc.title}》）】\n{self._roster_text(doc)}\n\n"
                     f"【已在小队名册里的人】{roster_line}\n\n"
                     f"【未完成任务】\n{task_lines}"},
                ], temperature=0.2, max_tokens=1500)
            except Exception as e:
                return {"ok": False,
                        "error": "读名单失败：" + _brief_error(e, "确认资料已上传、模型可用，再试一次")}
            if jerr is not None:
                return {"ok": False, "error": f"方案生成失败（模型输出无法解析：{jerr}）"}

            items = self._normalize_assign_items(parsed, tasks, members)
            if not items:
                return {"ok": False,
                        "error": "没能从这份资料里配出可用的分配（人名和任务对不上）：可以把名单写得更明确些，"
                                 "或者直接说「把 #39 派给陈工」"}
            titles = {t.id: t.title for t in tasks}
            for it in items:
                it["title"] = titles.get(it["task_id"], "")
            run = AssignmentRun(project_id=pid, user_id=self.user_id, doc_id=doc.id,
                                items=json.dumps(items, ensure_ascii=False), status="pending")
            db.add(run)
            db.commit()
            db.refresh(run)
            return {"ok": True, "data": items, "plan_id": run.id,
                    "markdown": self._assign_markdown(run.id, doc.title, items),
                    "note": "这是**待确认**的方案，还没写库；用户确认后再调 apply_assignment"}
        finally:
            db.close()

    def apply_assignment(self, plan_id: Optional[int] = None,
                         overrides: Optional[list] = None) -> dict:
        """把待确认的方案落库：缺的人建占位成员，逐条写 assignee_id（D-017）。"""
        db = SessionLocal()
        try:
            if plan_id:
                run = db.get(AssignmentRun, plan_id)
            else:
                q = db.query(AssignmentRun).filter_by(user_id=self.user_id, status="pending")
                if self.project_id is not None:
                    q = q.filter(AssignmentRun.project_id == self.project_id)
                run = q.order_by(AssignmentRun.id.desc()).first()
            if run is None:
                return {"ok": False, "error": "没有待确认的分配方案：先让我「按名单分配」一次"}
            if run.status != "pending":
                return {"ok": False, "error": f"方案 #{run.id} 已经落过库了"}
            if self.project_id is not None and run.project_id != self.project_id:
                return {"ok": False, "error": "这份方案不属于当前绑定的项目，已拒绝"}

            items = json.loads(run.items or "[]")
            fixed: dict[int, str] = {}
            for ov in overrides or []:
                if isinstance(ov, dict) and ov.get("task_id") is not None and ov.get("member_name"):
                    try:
                        fixed[int(ov["task_id"])] = str(ov["member_name"]).strip()
                    except (TypeError, ValueError):
                        continue

            applied, skipped, created = [], [], []
            for it in items:
                task = db.get(Task, it.get("task_id"))
                if task is None:
                    skipped.append(f"#{it.get('task_id')}（任务已不存在）")
                    continue
                name = fixed.get(it["task_id"], it["member_name"])
                hits = member_service.find_by_name(db, name)
                if len(hits) > 1:
                    skipped.append(f"「{task.title}」（「{name}」在名册里有 {len(hits)} 个人，重名没敢猜）")
                    continue
                if not hits:
                    m = member_service.create_member(db, name)  # 占位成员（带邀请码）
                    created.append({"name": m.name, "invite_code": m.invite_code})
                else:
                    m = hits[0]
                task_service.update_task(db, task.id, assignee_id=m.id)
                applied.append({"id": task.id, "title": task.title, "status": task.status,
                                "assignee_id": m.id, "assignee_name": m.name})

            run.status = "applied"
            run.applied_count = len(applied)
            db.commit()
            return {"ok": True, "data": applied, "plan_id": run.id, "created_members": created,
                    "skipped": skipped,
                    "note": (f"已落库 {len(applied)} 条指派"
                             + (f"，顺手建了 {len(created)} 个占位成员（带邀请码）" if created else "")
                             + (f"；跳过 {len(skipped)} 条：{'；'.join(skipped)}" if skipped else "")
                             + "；只改了负责人，任务状态没动")}
        finally:
            db.close()

    def dispatch(self, name: str, args: dict) -> dict:
        # 只认"本轮真正开放"的工具：光靠不给列表还不够 ——
        # 模型猜对名字（如绑定模式下猜 update_project_fields）时，这里必须挡住，
        # 否则"工具列表已裁剪"就只是心理安慰（2026-09-27 评测里真发生过）。
        allowed = {t["function"]["name"] for t in build_tools(self.project_id, self.readonly)}
        if name not in allowed:
            return {"ok": False,
                    "error": f"工具 {name} 在本轮不可用；本轮可用的是：{'、'.join(sorted(allowed))}"}
        fn = getattr(self, name, None)
        if fn is None:
            return {"ok": False, "error": f"未知工具 {name}"}
        t0 = time.time()
        try:
            result = fn(**args)
        except Exception as e:
            result = {"ok": False,
                      "error": _brief_error(e, "换个说法重试；要真实 id 可先 list_tasks / list_members")}
        ms = int((time.time() - t0) * 1000)
        self.last_trace.append(self.summarize_tool(name, args, result, ms))
        return result


# ---------- Agent 主循环 ----------
class Agent:
    def __init__(self, user_id: int, project_id: Optional[int] = None,
                 readonly: bool = False):
        self.executor = _ToolExecutor(user_id, project_id)
        self.executor.readonly = readonly     # 让 dispatch 也知道本轮开放了哪些工具
        # 只读轮次（进度/清单类问题）：不给写工具，防止"看一眼"变成"改一手"
        self.readonly = readonly

    def run(self, message: str, history: Optional[list[dict]] = None,
            context_note: Optional[str] = None) -> str:
        """执行一轮对话。history: 此前 {role: user/assistant, content} 列表（不含工具消息）。

        context_note: 代码层注入的「真实数据说明」（如项目当前任务快照），
        作为 system 级上下文放在 user 消息之前——模型必须基于它作答，不能编造。
        """
        messages: list[dict[str, Any]] = [{
            "role": "system",
            "content": build_system_prompt(self.executor.project_id, self.executor.project_name),
        }]
        if context_note:
            messages.append({"role": "system", "content": context_note})
        for h in history or []:
            messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": message})

        for _ in range(MAX_ITER):
            resp = llm.chat(messages,
                            tools=build_tools(self.executor.project_id, self.readonly))
            msg = resp.choices[0].message
            tool_calls = getattr(msg, "tool_calls", None)
            if not tool_calls:
                text = (msg.content or "").strip()
                # 纯对话/常识类回复（一轮下来没调用任何工具）：
                # 也给一条轨迹说明，避免用户看到空面板误以为功能异常
                if not self.executor.last_trace:
                    self.executor.last_trace.append({
                        "tool": "none", "label": "直接回答",
                        "detail": "本轮无需读写数据（对话/常识类），未调用工具",
                        "ok": True, "ms": 0})
                return text

            # 回传 assistant 的工具调用，随后逐个执行
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in tool_calls
                ],
            })
            for tc in tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = self.executor.dispatch(name, args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })

        return "处理步骤过多已自动停止，请换一种更简洁的说法再试。"
