"""对话接口 /api/chat

- POST /send      自然语言 -> Agent 工具循环 -> 回复；user/assistant 消息落库 chat_messages
- GET  /history   该用户的对话历史（支持 ?project_id= 按项目隔离，供多项目场景下互不串扰）

/send 响应附 trace：本次回复背后 Agent 实际执行的工具步骤（含受影响实体），
供前端渲染「执行轨迹 + 可点击跳转的实体引用」。
"""
import json
import time

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from core.agent import Agent, resolve_bound_action, is_ask_detail_intent
from models.database import get_db, ChatMessage
from models.schemas import ChatRequest, ChatMessageOut
from services import project_service

router = APIRouter()

HISTORY_LIMIT = 20  # 作为上下文带入 Agent 的最近消息条数


def _format_plan_reply(res: dict, project_name: str | None) -> str:
    """把 plan_tasks 的返回结果拼成给用户的文字回复（不依赖模型二次生成）。"""
    if not res.get("ok"):
        return f"任务规划失败：{res.get('error', '未知错误')}。可重试，或直接说明任务明细，我逐个创建。"
    tasks = res.get("data") or []
    name = project_name or "该项目"
    lines = "\n".join(f"{i}. {t['title']}" for i, t in enumerate(tasks, 1))
    note = res.get("note", "")
    return f"已为「{name}」自动规划 {len(tasks)} 个任务：\n{lines}\n{note}"


def _format_snapshot_note(snap: dict) -> str:
    """把项目状态快照压成给模型的 system 上下文（真实数据，禁止编造）。"""
    d = snap.get("data", {})
    p = d.get("project", {})
    by = d.get("by_status", {})
    lines = [
        f"【项目「{p.get('name','')}」当前真实状态（已从数据库读取，回答务必基于以下数据，不得编造）】",
        f"- 任务总数 {d.get('task_count',0)}：待办 {by.get('todo',0)} / "
        f"进行中 {by.get('doing',0)} / 已完成 {by.get('done',0)}",
    ]
    high = d.get("high_open") or []
    if high:
        lines.append(f"- 未完成的高优先级任务：{'、'.join(high)}")
    blocked = d.get("blocked") or []
    if blocked:
        lines.append("- 依赖未就绪（可能阻塞）的任务：")
        for b in blocked[:5]:
            lines.append(f"  · 「{b['task']}」需等「{b['waiting_on']}」（当前 {b['pre_status']}）")
    if not (high or blocked) and d.get("task_count", 0) == 0:
        lines.append("- 项目暂无任务，可建议用户先「帮我规划任务」。")
    return "\n".join(lines)


def _load_history(db: Session, user_id: int, project_id: int | None,
                  exclude_last_user_content: str | None = None) -> list[dict]:
    """取最近上下文：绑定项目时只取该项目下的消息，未绑定时取该用户全部消息。

    这是防止「跨项目串扰」的关键：不同项目的对话互不进入彼此的上下文。
    刚落库的当前用户消息会由 Agent.run 再次追加，故默认剔除避免重复。
    """
    q = db.query(ChatMessage).filter_by(user_id=user_id)
    if project_id is not None:
        q = q.filter_by(project_id=project_id)
    rows = q.order_by(ChatMessage.id.desc()).limit(HISTORY_LIMIT).all()
    rows.reverse()  # 时间正序
    msgs = [{"role": m.role, "content": m.content} for m in rows
            if m.role in ("user", "assistant")]
    if (exclude_last_user_content is not None and msgs
            and msgs[-1]["role"] == "user"
            and msgs[-1]["content"] == exclude_last_user_content):
        msgs = msgs[:-1]  # 该条由 Agent.run 追加，去掉避免上下文重复
    return msgs


@router.post("/send")
def chat_send(body: ChatRequest, db: Session = Depends(get_db)):
    # 1) 用户消息落库（记录所属项目，供历史隔离）
    user_msg = ChatMessage(role="user", content=body.message,
                           user_id=body.user_id, project_id=body.project_id)
    db.add(user_msg)
    db.commit()

    # 2) 确定性路由：先看有没有「代码层面就能拍板」的情况
    #    —— 例如绑定 A 却说给 B 规划（conflict）、绑定后直接要规划任务（plan）。
    #    这些不再交给 LLM 决策，从根上消除反问「给哪个项目」和跨项目串扰。
    agent = Agent(user_id=body.user_id, project_id=body.project_id)
    reply = None
    trace: list[dict] = []

    # 兜底 0：未绑定 + 只给任务数量不给明细（如「加两个任务」）且没点名项目
    # → 代码层追问，避免模型猜项目/猜内容，更不会自动规划出一整批任务
    if body.project_id is None and is_ask_detail_intent(body.message):
        names = [p.name for p in project_service.list_projects(db, body.user_id)
                 if p.name and p.name in body.message]
        if not names:
            reply = ("请补充两件事，我会马上执行：\n"
                     "1) 给哪个项目加任务（项目名或先在右上角绑定）；\n"
                     "2) 任务的具体内容，例如：\n"
                     "   「加两个任务：① 优化登录页加载速度 ② 修复支付回调超时」\n\n"
                     "如果你是想按项目主题自动拆解任务，请直接说「帮我规划任务」。")
            trace = [{"tool": "ask", "label": "补充任务内容",
                      "detail": "话术只说了任务数量、未给项目与明细，已追问（未写入任何任务）",
                      "ok": True, "ms": 0}]

    # 2) 确定性路由：先看有没有「代码层面就能拍板」的情况
    #    —— 例如绑定 A 却说给 B 规划（conflict）、绑定后直接要规划任务（plan）。
    #    这些不再交给 LLM 决策，从根上消除反问「给哪个项目」和跨项目串扰。
    if reply is None and body.project_id is not None:
        action, payload = resolve_bound_action(
            db, body.user_id, body.project_id,
            agent.executor.project_name, body.message)
        if action == "conflict":
            bound_name = agent.executor.project_name or f"项目{body.project_id}"
            reply = (f"当前对话已绑定「{bound_name}」，而你提到的是另一个项目「{payload}」。"
                     f"为避免任务建到错误项目，请先在页面上方切换到「{payload}」，"
                     f"或先取消绑定再对我说要规划哪个项目。")
            trace = [{"tool": "guard", "label": "安全拦截",
                      "detail": f"话术点名绑定项目之外的「{payload}」，已拦截并提示先切换（未写入任何数据）",
                      "ok": True, "ms": 0}]
        elif action == "ask":
            reply = ("收到，不过你只说了任务数量、还没给任务内容。"
                     "请把要添加的任务发给我（我只会逐个创建、不会自动规划一整套），例如：\n"
                     "「加两个任务：① 优化登录页加载速度 ② 修复支付回调超时」\n\n"
                     "如果确实想按项目主题自动拆解一整套任务，请直接说「帮我规划任务」。")
            trace = [{"tool": "ask", "label": "补充任务内容",
                      "detail": "话术只给了任务数量、未给明细，已追问（未写入任何任务）",
                      "ok": True, "ms": 0}]
        elif action == "plan":
            _t0 = time.time()
            res = agent.executor.plan_tasks()  # project_id 省略 → 落到绑定项目
            _ms = int((time.time() - _t0) * 1000)
            trace = [agent.executor.summarize_tool("plan_tasks", {}, res, _ms)]
            reply = _format_plan_reply(res, agent.executor.project_name)
        elif action == "query":
            # 只读进度查询：代码层先读真实项目状态注入上下文，
            # 模型只能基于数据作答——杜绝「不查库直接泛泛而谈/编造进度」。
            _t0 = time.time()
            snap = agent.executor.project_snapshot()
            _ms = int((time.time() - _t0) * 1000)
            if snap.get("ok"):
                trace = [agent.executor.summarize_tool("project_snapshot", {}, snap, _ms)]
                _note = _format_snapshot_note(snap)
            else:
                _note = None
            history = _load_history(db, body.user_id, body.project_id,
                                    exclude_last_user_content=body.message)
            reply = agent.run(body.message, history=history, context_note=_note)
            # project_snapshot 非 LLM 工具，不会进 executor.last_trace，这里手动合并
            trace = trace + agent.executor.last_trace

    # 3) 其余请求照旧走 Agent 工具循环（dispatch 内部已记录执行轨迹）
    history = _load_history(db, body.user_id, body.project_id,
                            exclude_last_user_content=body.message)
    if reply is None:
        reply = agent.run(body.message, history=history)
        trace = agent.executor.last_trace

    # 4) 助手回复落库（附执行轨迹 JSON，供历史页回放）
    assistant_msg = ChatMessage(role="assistant", content=reply,
                                user_id=body.user_id, project_id=body.project_id,
                                trace=json.dumps(trace, ensure_ascii=False) if trace else None)
    db.add(assistant_msg)
    db.commit()

    return {
        "reply": reply,
        "message_id": assistant_msg.id,
        "project_id": body.project_id,
        "trace": trace,
    }


@router.get("/history", response_model=list[ChatMessageOut])
def chat_history(user_id: int = Query(...),
                 project_id: int | None = Query(None, description="按项目过滤，缺省返回全部"),
                 db: Session = Depends(get_db)):
    q = db.query(ChatMessage).filter_by(user_id=user_id)
    if project_id is not None:
        q = q.filter_by(project_id=project_id)
    rows = q.order_by(ChatMessage.id.asc()).limit(100).all()
    out = []
    for m in rows:
        trace = None
        if m.trace:
            try:
                trace = json.loads(m.trace)
            except json.JSONDecodeError:
                trace = None
        out.append(ChatMessageOut(id=m.id, role=m.role, content=m.content,
                                  created_at=m.created_at, trace=trace))
    return out
