"""Agent 核心：手写工具循环（openai function calling，不依赖 LangChain）。

流程：组装 messages(system + history + user) → 请求模型(带 tools)
     → 若返回 tool_calls 则逐个执行工具、结果以 role="tool" 消息追加 → 再次请求
     → 直到模型不再调用工具、给出最终文本回复。

意图分支由「模型决策 + 工具执行」完成：
  闲聊/问候            → 直接回答（不调工具）
  查询项目信息/知识     → search_knowledge（RAG 检索项目知识库）
  创建/查询项目         → create_project / list_projects
  创建任务/改状态       → create_task / update_task_status / list_tasks
"""
import json
from typing import Any, Optional

from core import llm
from core.rag import search as rag_search
from models.database import SessionLocal, Project, Task

MAX_ITER = 8  # 单轮最多工具迭代次数，防死循环

SYSTEM_PROMPT = """你是「项目管理 Agent」，帮用户用自然语言管理项目和任务，也能基于项目知识库文档回答问题。

工具使用规则：
1. 用户要「创建项目、创建任务、查任务列表、推进任务状态、看有哪些项目」时调用对应工具；
2. 用户问题涉及项目资料（需求、方案、验收标准、模块功能等）时调用 search_knowledge 检索相关文档后再回答；
3. 纯闲聊、问候、与项目无关的内容直接回答，不要调用工具；
4. 创建任务时，若用户一次性给出多个任务，请逐个调用 create_task；
5. 只能依据工具返回的真实数据回答，不要编造项目或任务信息；
6. 使用简体中文，回答简洁清晰。"""


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
]


# ---------- 工具执行（业务逻辑，直接操作数据库） ----------
class _ToolExecutor:
    """把工具调用分发到具体函数；user_id 由会话上下文注入，不暴露给模型。"""

    def __init__(self, user_id: int, project_id: Optional[int] = None):
        self.user_id = user_id
        self.project_id = project_id

    def _db(self):
        return SessionLocal()

    def list_projects(self) -> dict:
        db = self._db()
        try:
            projects = db.query(Project).filter_by(creator_id=self.user_id)\
                .order_by(Project.id.desc()).all()
            return {"ok": True, "data": [
                {"id": p.id, "name": p.name, "description": p.description,
                 "status": p.status, "task_count": len(p.tasks)} for p in projects]}
        finally:
            db.close()

    def create_project(self, name: str, description: str = "") -> dict:
        db = self._db()
        try:
            p = Project(name=name, description=description or "",
                        status="active", creator_id=self.user_id)
            db.add(p)
            db.commit()
            return {"ok": True, "data": {"id": p.id, "name": p.name, "status": p.status}}
        finally:
            db.close()

    def list_tasks(self, project_id: int) -> dict:
        db = self._db()
        try:
            tasks = db.query(Task).filter_by(project_id=project_id)\
                .order_by(Task.id.desc()).all()
            return {"ok": True, "data": [
                {"id": t.id, "title": t.title, "status": t.status,
                 "priority": t.priority, "description": t.description} for t in tasks]}
        finally:
            db.close()

    def create_task(self, project_id: int, title: str, description: str = "",
                    status: str = "todo", priority: str = "medium") -> dict:
        db = self._db()
        try:
            proj = db.get(Project, project_id)
            if proj is None:
                return {"ok": False, "error": f"项目 {project_id} 不存在"}
            t = Task(title=title, description=description or "", status=status,
                     priority=priority, project_id=project_id, assignee_id=self.user_id)
            db.add(t)
            db.commit()
            return {"ok": True, "data": {"id": t.id, "title": t.title,
                                         "project_id": project_id, "status": t.status}}
        finally:
            db.close()

    def update_task_status(self, task_id: int, status: str) -> dict:
        db = self._db()
        try:
            t = db.get(Task, task_id)
            if t is None:
                return {"ok": False, "error": f"任务 {task_id} 不存在"}
            t.status = status
            db.commit()
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
        except Exception as e:  # 模型未就绪等场景
            return {"ok": False, "error": f"知识库检索失败: {e}"}

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
        messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
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
