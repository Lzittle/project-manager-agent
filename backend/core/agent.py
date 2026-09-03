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
from typing import Any, Optional

from core import llm
from core.rag import search as rag_search
from models.database import SessionLocal, Project
from services import project_service, task_service

MAX_ITER = 8  # 单轮最多工具迭代次数，防死循环

def build_system_prompt(project_id: Optional[int] = None) -> str:
    prompt = """你是「项目管理 Agent」，帮用户用自然语言管理项目和任务，也能基于项目知识库文档回答问题。

工具使用规则：
1. 用户要「创建项目、创建任务、查任务列表、推进任务状态、看有哪些项目」时调用对应工具；
2. 用户要求「规划任务/拆解任务/自动生成几个任务/包含 N 个任务」但**未给出任务明细**时：若项目还不存在先 create_project，然后调用 plan_tasks 自动规划；若用户已列出任务明细，则逐个 create_task，不要用 plan_tasks；
3. 用户问题涉及项目资料（需求、方案、验收标准、模块功能等）时调用 search_knowledge 检索相关文档后再回答；
4. 纯闲聊、问候、与项目无关的内容直接回答，不要调用工具；
5. 只能依据工具返回的真实数据回答，不要编造项目或任务信息；
6. 使用简体中文，回答简洁清晰。"""
    if project_id is not None:
        prompt += (
            f"\n\n当前对话已绑定项目（project_id={project_id}）。"
            f"除非用户明确说「创建/新建」一个新项目，否则禁止调用 create_project；"
            f"谈及该项目的内容一律用 list_tasks / search_knowledge 查询，绝不重复创建同名项目。"
        )
    return prompt


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
        "列出指定项目下的任务。用于用户问「XX 项目的任务有哪些/任务列表」",
        {"project_id": {"type": "integer", "description": "项目 id"}},
        ["project_id"],
    ),
    _fn(
        "create_task",
        "在指定项目下创建一个任务。用于「在 XX 项目加一个任务/任务：YY」",
        {"project_id": {"type": "integer", "description": "所属项目 id"},
         "title": {"type": "string", "description": "任务标题"},
         "description": {"type": "string", "description": "任务描述（可空）"},
         "status": {"type": "string", "enum": ["todo", "doing", "done"], "description": "状态，默认 todo"},
         "priority": {"type": "string", "enum": ["high", "medium", "low"], "description": "优先级，默认 medium"}},
        ["project_id", "title"],
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
        "用于用户说「规划任务/拆解任务/自动生成 N 个任务/包含几个任务」但未给出具体任务清单时；若用户已列出任务明细，直接用 create_task 逐个创建",
        {"project_id": {"type": "integer", "description": "要规划任务的项目 id"},
         "goal": {"type": "string", "description": "规划目标/主题（可空，缺省用项目名）"}},
        ["project_id"],
    ),
]


# ---------- 工具执行（业务逻辑经 services 层，user_id 由会话注入不暴露给模型） ----------
class _ToolExecutor:
    def __init__(self, user_id: int, project_id: Optional[int] = None):
        self.user_id = user_id
        self.project_id = project_id

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

    def list_tasks(self, project_id: int) -> dict:
        db = SessionLocal()
        try:
            data = [self._task_brief(t) for t in task_service.list_tasks(db, project_id)]
            return {"ok": True, "data": data}
        finally:
            db.close()

    def create_task(self, project_id: int, title: str, description: str = "",
                    status: str = "todo", priority: str = "medium") -> dict:
        db = SessionLocal()
        try:
            t = task_service.create_task(
                db, project_id, self.user_id, title,
                description=description, status=status, priority=priority)
            if t is None:
                return {"ok": False, "error": f"项目 {project_id} 不存在"}
            return {"ok": True, "data": {"id": t.id, "title": t.title,
                                         "project_id": project_id, "status": t.status}}
        finally:
            db.close()

    def update_task_status(self, task_id: int, status: str) -> dict:
        db = SessionLocal()
        try:
            t = task_service.update_task(db, task_id, status=status)
            if t is None:
                return {"ok": False, "error": f"任务 {task_id} 不存在"}
            return {"ok": True, "data": {"id": t.id, "title": t.title, "status": t.status}}
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

    def plan_tasks(self, project_id: int, goal: str = "") -> dict:
        # 1) 项目校验 + 确定主题
        db = SessionLocal()
        try:
            p = db.get(Project, project_id)
            if p is None:
                return {"ok": False, "error": f"项目 {project_id} 不存在"}
            topic = (goal or f"{p.name} 项目").strip()
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

        # 3) 批量落库，首个任务置为进行中
        db = SessionLocal()
        try:
            created = []
            for t in tasks[:6]:
                tk = task_service.create_task(
                    db, project_id, self.user_id, t["title"],
                    description=t["description"], priority=t["priority"], status="todo")
                if tk:
                    created.append(tk)
            if created:
                task_service.update_task(db, created[0].id, status="doing")
            return {
                "ok": True,
                "data": [{"id": tk.id, "title": tk.title, "status": tk.status} for tk in created],
                "note": f"已规划 {len(created)} 个任务，首个任务已置为进行中，可在看板查看并拖拽流转",
            }
        finally:
            db.close()

    def dispatch(self, name: str, args: dict) -> dict:
        fn = getattr(self, name, None)
        if fn is None:
            return {"ok": False, "error": f"未知工具 {name}"}
        try:
            return fn(**args)
        except Exception as e:
            return {"ok": False, "error": f"工具执行异常: {e}"}


# ---------- Agent 主循环 ----------
class Agent:
    def __init__(self, user_id: int, project_id: Optional[int] = None):
        self.executor = _ToolExecutor(user_id, project_id)

    def run(self, message: str, history: Optional[list[dict]] = None) -> str:
        """执行一轮对话。history: 此前 {role: user/assistant, content} 列表（不含工具消息）。"""
        messages: list[dict[str, Any]] = [{"role": "system", "content": build_system_prompt(self.executor.project_id)}]
        for h in history or []:
            messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": message})

        for _ in range(MAX_ITER):
            resp = llm.chat(messages, tools=TOOLS)
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
