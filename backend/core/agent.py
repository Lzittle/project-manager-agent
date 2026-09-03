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
from typing import Any, Optional

from core import llm
from core.rag import search as rag_search
from models.database import SessionLocal, Project
from services import project_service, task_service

MAX_ITER = 8  # 单轮最多工具迭代次数，防死循环


def _clip(v: Any, limit: int = 120) -> str:
    """把任意值压成适合展示的短字符串（截断超长文本/参数）。"""
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
    return s if len(s) <= limit else s[:limit] + "…"

def build_system_prompt(project_id: Optional[int] = None,
                        project_name: Optional[str] = None) -> str:
    prompt = """你是「项目管理 Agent」，帮用户用自然语言管理项目和任务，也能基于项目知识库文档回答问题。

工具使用规则：
1. 用户要「创建项目、创建任务、查任务列表、推进任务状态、看有哪些项目」时调用对应工具；
2. 用户要求「规划任务/拆解任务/自动生成几个任务/包含 N 个任务」但**未给出任务明细**时：若项目还不存在先 create_project，然后调用 plan_tasks 自动规划；若用户已列出任务明细，则逐个 create_task，不要用 plan_tasks；
3. 用户问题涉及项目资料（需求、方案、验收标准、模块功能等）时调用 search_knowledge 检索相关文档后再回答；
4. 纯闲聊、问候、与项目无关的内容直接回答，不要调用工具；
5. 只能依据工具返回的真实数据回答，不要编造项目或任务信息；
6. 使用简体中文，回答简洁清晰。"""
    if project_id is not None:
        name_desc = f"，名称「{project_name}」" if project_name else ""
        prompt += (
            f"\n\n当前对话已绑定项目（project_id={project_id}{name_desc}）。"
            f"你只能围绕这一个项目工作：加任务、查任务、改状态、检索资料、自动规划任务都会自动落到该项目，"
            f"无需、也禁止向用户反问「要给哪个项目做」。"
            f"本模式下工具列表已移除「列出项目 / 创建项目」入口——不要提及、罗列、猜测或编造其他任何项目，"
            f"更不得使用其他项目的名字或任务内容作答。"
            f"若用户明确要求新建项目，请提示「先在页面上方创建项目并切换过去」，不要假装已创建。"
        )
    return prompt


# ---------- 确定性路由辅助（绑定项目时先于 LLM 决策，杜绝跨项目串扰） ----------
_PLAN_HINT_WORDS = ("拆解", "分解", "帮我规划", "规划任务", "任务规划",
                    "规划一下", "规划几个", "生成几个任务", "安排几个任务",
                    "帮我生成任务", "帮我安排任务")
# 出现在话术里多为「查询/检索知识库」而非「自动规划」，命中则不强制路由
_PLAN_NOISE = ("文档", "资料", "知识库", "检索", "搜索", "找一下",
               "查一下", "有什么", "有哪些", "怎么", "如何")


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
    return bool(re.search(r"(?:生成|规划|安排)\S{0,6}任务", t))


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


def _is_task_write_intent(text: str) -> bool:
    """是否「要往某个项目写任务」：规划意图 或 显式「加/建任务」指令。"""
    return is_plan_intent(text) or bool(_TASK_ADD_HINT.search(text))


def resolve_bound_action(db, user_id: int, bound_project_id: Optional[int],
                         bound_project_name: Optional[str], message: str):
    """绑定项目场景下，把「高确定性」的情况在进入 LLM 前先用代码判定：

    返回 (action, payload)：
      ("conflict", other_name)  消息要写任务却点名绑定项目之外的项目
                                → 提示先切换，绝不跨项目写数据；
      ("plan",      None)       纯规划意图 → 直接对绑定项目执行 plan_tasks；
      ("agent",     None)       其余 → 交给 Agent 工具循环（工具已按绑定项目裁剪）。

    说明：仅「提及别的项目」（如“参照A项目的做法”）不拦截，交给裁剪后的
    Agent —— 工具里已无 project_id，它也无法把数据写到别的项目。
    """
    if bound_project_id is None:
        return ("agent", None)
    other = find_project_mention(db, user_id, bound_project_id, message)
    if other is not None and _is_task_write_intent(message):
        return ("conflict", other.name)
    if is_plan_intent(message):
        return ("plan", None)
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
        "列出当前用户的所有项目（含任务数），用于用户问「有哪些项目/我的项目」",
        {},
        [],
    ),
    _fn(
        "create_project",
        "创建一个新项目，参数 name 为项目名、description 为项目描述。用于「帮我创建/新建一个 XX 项目」",
        {"name": {"type": "string", "description": "项目名称"},
         "description": {"type": "string", "description": "项目描述（可空）"}},
        ["name"],
    ),
    _fn(
        "list_tasks",
        "列出指定项目下的任务。用于用户问「XX 项目的任务有哪些/任务列表」。"
        "project_id 可省略：省略时默认当前绑定的项目（若未绑定则必须提供）",
        {"project_id": {"type": "integer", "description": "项目 id（可省略，默认当前绑定项目）"}},
        [],
    ),
    _fn(
        "create_task",
        "在指定项目下创建一个任务。用于「在 XX 项目加一个任务/任务：YY」。"
        "project_id 可省略：省略时默认创建到当前绑定的项目（若未绑定则必须提供）",
        {"project_id": {"type": "integer", "description": "所属项目 id（可省略，默认当前绑定项目）"},
         "title": {"type": "string", "description": "任务标题"},
         "description": {"type": "string", "description": "任务描述（可空）"},
         "status": {"type": "string", "enum": ["todo", "doing", "done"], "description": "状态，默认 todo"},
         "priority": {"type": "string", "enum": ["high", "medium", "low"], "description": "优先级，默认 medium"}},
        ["title"],
    ),
    _fn(
        "update_task_status",
        "更新任务状态（todo/doing/done）。用于「把 XX 任务标记为进行中/完成」",
        {"task_id": {"type": "integer", "description": "任务 id"},
         "status": {"type": "string", "enum": ["todo", "doing", "done"], "description": "目标状态"}},
        ["task_id", "status"],
    ),
    _fn(
        "search_knowledge",
        "在项目知识库中检索文档片段（RAG），回答与项目资料相关的问题。如果用户问的与某个项目绑定就传 project_id",
        {"query": {"type": "string", "description": "检索问题"},
         "project_id": {"type": "integer", "description": "限定项目（可空）"}},
        ["query"],
    ),
    _fn(
        "plan_tasks",
        "为指定项目自动规划一组任务：根据项目主题调用大模型生成约 5 条落地任务并创建入库（首个任务置为进行中）。"
        "用于用户说「规划任务/拆解任务/自动生成 N 个任务/包含几个任务」但未给出具体任务清单时；若用户已列出任务明细，直接用 create_task 逐个创建。"
        "project_id 可省略：省略时默认当前绑定的项目（若未绑定则必须提供）",
        {"project_id": {"type": "integer", "description": "要规划任务的项目 id（可省略，默认当前绑定项目）"}},
        [],
    ),
]


def build_tools(project_id: Optional[int] = None) -> list[dict]:
    """按会话状态裁剪工具列表。

    - 未绑定项目：暴露全部 7 个工具（模型可自由创建/查询项目）；
    - 已绑定项目：摘掉 list_projects / create_project，并移除项目类工具里的
      project_id 参数 —— 模型既看不到「还有别的项目」、也无法传错项目，
      所有落点由执行器固定为绑定项目。反问「要给哪个项目」从此无从发生。
    """
    if project_id is None:
        return TOOLS
    HIDDEN = {"list_projects", "create_project"}
    trimmed = []
    for t in TOOLS:
        name = t["function"]["name"]
        if name in HIDDEN:
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
    def __init__(self, user_id: int, project_id: Optional[int] = None):
        self.user_id = user_id
        self.project_id = project_id
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

    def _task_brief(self, t) -> dict:
        return {"id": t.id, "title": t.title, "description": t.description,
                "status": t.status, "priority": t.priority}

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

    def list_tasks(self, project_id: Optional[int] = None) -> dict:
        pid = project_id or self.project_id
        if pid is None:
            return {"ok": False, "error": "未指定项目：请先绑定项目或在话术中说明项目名称"}
        db = SessionLocal()
        try:
            data = [self._task_brief(t) for t in task_service.list_tasks(db, pid)]
            return {"ok": True, "data": data}
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
            return {"ok": False, "error": f"知识库检索失败: {e}"}

    # ---------- 执行轨迹（让每一步工具调用对用户可见、可跳转） ----------
    _LABELS = {
        "create_project": "创建项目", "list_projects": "查看项目列表",
        "list_tasks": "查看任务", "create_task": "创建任务",
        "update_task_status": "更新任务状态", "search_knowledge": "检索知识库",
        "plan_tasks": "自动规划任务",
    }

    def _refs_from(self, name: str, args: dict, result: dict) -> list[dict]:
        """提取受影响的实体（任务/项目），供前端渲染可点击跳转的引用。"""
        data = result.get("data") if result.get("ok") else None
        refs = []
        if name == "create_project" and isinstance(data, dict):
            refs.append({"kind": "project", "id": data["id"], "title": data.get("name", "")})
        elif name in ("create_task", "update_task_status") and isinstance(data, dict):
            refs.append({"kind": "task", "id": data["id"], "title": data.get("title", ""),
                         "project_id": data.get("project_id")})
        elif name == "plan_tasks" and isinstance(data, list):
            pid = args.get("project_id") or self.project_id
            for t in data:
                refs.append({"kind": "task", "id": t["id"], "title": t["title"],
                             "project_id": pid})
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
        elif name == "create_task" and isinstance(data, dict):
            detail = f"创建任务「{data.get('title','')}」（#{data['id']}）"
        elif name == "update_task_status" and isinstance(data, dict):
            detail = f"任务「{data.get('title','')}」状态 → {data.get('status','')}"
        elif name == "plan_tasks" and isinstance(data, list):
            detail = f"生成 {len(data)} 条任务并入库（默认待办）"
        elif name == "list_projects" and isinstance(data, list):
            detail = f"共 {len(data)} 个项目"
        elif name == "list_tasks" and isinstance(data, list):
            detail = f"共 {len(data)} 个任务"
        elif name == "search_knowledge" and isinstance(data, list):
            detail = f"检索到 {len(data)} 条相关片段" if data else "知识库暂无相关内容"
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
    def _parse_tasks(raw: str) -> list[dict]:
        """从模型输出中提取任务 JSON 数组（容忍 ```json 围栏与多余文字）。"""
        text = raw.strip()
        m = re.search(r"\[[\s\S]*\]", text)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []
        if not isinstance(data, list):
            return []
        out = []
        for item in data:
            if isinstance(item, dict) and item.get("title"):
                out.append({
                    "title": str(item["title"]).strip()[:200],
                    "description": str(item.get("description", "")).strip()[:500],
                    "priority": item.get("priority", "medium") if item.get("priority") in ("high", "medium", "low") else "medium",
                })
        return out

    def plan_tasks(self, project_id: Optional[int] = None, goal: str = "") -> dict:
        """自动规划任务。主题一律取项目自身名称，不接受模型传入的 goal，
        避免模型受历史话术误导、给别的主题生成任务。"""
        # project_id 未提供时回落到当前绑定项目
        pid = project_id or self.project_id
        if pid is None:
            return {"ok": False, "error": "未指定项目：请先绑定项目或在话术中说明项目名称"}

        # 1) 项目校验 + 确定主题（以项目名称为准）
        db = SessionLocal()
        try:
            p = db.get(Project, pid)
            if p is None:
                return {"ok": False, "error": f"项目 {pid} 不存在"}
            topic = f"{p.name} 项目"
        finally:
            db.close()

        # 2) 调用 LLM 生成任务规划
        try:
            raw = llm.chat_text([
                {"role": "system", "content":
                 "你是敏捷项目管理专家。基于项目主题规划 5 条具体可执行的落地任务。"
                 "只输出 JSON 数组，不要任何多余文字或代码块标记。格式："
                 '[{"title":"任务标题(不超过14字)","description":"一句话描述含验收要点","priority":"high|medium|low"}]'},
                {"role": "user", "content": f"项目主题：{topic}"},
            ], temperature=0.4, max_tokens=900)
        except Exception as e:
            return {"ok": False, "error": f"任务规划生成失败: {e}"}

        tasks = self._parse_tasks(raw)
        if not tasks:
            return {"ok": False, "error": "任务规划生成失败（模型输出无法解析），请重试或直接说明任务明细"}

        # 3) 批量落库（统一默认待办：规划≠开工，是否开始做由用户在看板拖拽决定）
        db = SessionLocal()
        try:
            created = []
            for t in tasks[:6]:
                tk = task_service.create_task(
                    db, pid, self.user_id, t["title"],
                    description=t["description"], priority=t["priority"], status="todo")
                if tk:
                    created.append(tk)
            return {
                "ok": True,
                "data": [{"id": tk.id, "title": tk.title, "status": tk.status} for tk in created],
                "note": f"已规划 {len(created)} 个任务（默认均为待办），可在看板查看并拖拽流转状态",
            }
        finally:
            db.close()

    def dispatch(self, name: str, args: dict) -> dict:
        fn = getattr(self, name, None)
        if fn is None:
            return {"ok": False, "error": f"未知工具 {name}"}
        t0 = time.time()
        try:
            result = fn(**args)
        except Exception as e:
            result = {"ok": False, "error": f"工具执行异常: {e}"}
        ms = int((time.time() - t0) * 1000)
        self.last_trace.append(self.summarize_tool(name, args, result, ms))
        return result


# ---------- Agent 主循环 ----------
class Agent:
    def __init__(self, user_id: int, project_id: Optional[int] = None):
        self.executor = _ToolExecutor(user_id, project_id)

    def run(self, message: str, history: Optional[list[dict]] = None) -> str:
        """执行一轮对话。history: 此前 {role: user/assistant, content} 列表（不含工具消息）。"""
        messages: list[dict[str, Any]] = [{
            "role": "system",
            "content": build_system_prompt(self.executor.project_id, self.executor.project_name),
        }]
        for h in history or []:
            messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": message})

        for _ in range(MAX_ITER):
            resp = llm.chat(messages, tools=build_tools(self.executor.project_id))
            msg = resp.choices[0].message
            tool_calls = getattr(msg, "tool_calls", None)
            if not tool_calls:
                return (msg.content or "").strip()

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
