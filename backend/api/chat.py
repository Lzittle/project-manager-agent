"""对话接口 /api/chat

- POST /send      自然语言 -> Agent 工具循环 -> 回复；user/assistant 消息落库 chat_messages
- GET  /history   该用户的对话历史（支持 ?project_id= 按项目隔离，供多项目场景下互不串扰）

/send 响应附 trace：本次回复背后 Agent 实际执行的工具步骤（含受影响实体），
供前端渲染「执行轨迹 + 可点击跳转的实体引用」。
"""
import json
import re
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from core import llm
from core.agent import Agent, resolve_bound_action, is_ask_detail_intent
from core.rag import search as rag_search
from models.database import get_db, ChatMessage
from models.schemas import (ChatRequest, ChatMessageOut, MeetingSummaryRequest)
from services import knowledge_service, project_service

router = APIRouter()

HISTORY_LIMIT = 20    # 会议纪要等场景取多少条历史
HISTORY_VERBATIM = 8  # 进上下文时「原样保留」的最近条数
HISTORY_FETCH = 60    # 最多回看多少条（超出的早期部分压成一段摘要）
HISTORY_MODEL_MIN = 16  # 要折叠的早期消息超过这个数才值得花一次模型调用；否则用免费摘要

# 快照注入用的中文标签（状态/优先级对模型和用户都更直观）
_STATUS_CN = {"todo": "待办", "doing": "进行中", "done": "已完成"}
_PRIORITY_CN = {"high": "高", "medium": "中", "low": "低"}

# 资料/记忆类意图：绑定项目时由代码层自动 RAG 检索注入（项目长期记忆），
# 无需模型自觉调用 search_knowledge —— 否则模型经常「不查就答」。
_MATERIAL_HINT = re.compile(
    r"需求|方案|设计|文档|纪要|会议|规则|验收|标准|规范|做法|背景|目标|"
    r"怎么|如何|为什么|哪些资料|记不记得|之前说过|上回|上次|参考|根据|文档里")


def _format_plan_reply(res: dict, project_name: str | None) -> str:
    """把 plan_tasks 的返回结果拼成给用户的文字回复（不依赖模型二次生成）。"""
    if not res.get("ok"):
        return f"任务规划失败：{res.get('error', '未知错误')}。可重试，或直接说明任务明细，我逐个创建。"
    tasks = res.get("data") or []
    name = project_name or "该项目"
    lines = "\n".join(f"{i}. {t['title']}" for i, t in enumerate(tasks, 1))
    note = res.get("note", "")
    if res.get("reused"):  # 幂等命中：复用上一批，不重复创建
        return (f"「{name}」刚刚已经规划过一批任务（共 {len(tasks)} 个），本次没有重复创建：\n"
                f"{lines}\n{note}")
    return f"已为「{name}」自动规划 {len(tasks)} 个任务：\n{lines}\n{note}"


def _format_apply_reply(res: dict, project_name: str | None) -> str:
    """把「方案落库」的结果拼成给用户的文字回复（不依赖模型二次生成）。"""
    if not res.get("ok"):
        return f"落库失败：{res.get('error', '未知错误')}"
    rows = res.get("data") or []
    name = project_name or "该项目"
    lines = "\n".join(
        f"{i}. {t['title']} → {t['assignee_name']}"
        f"（状态仍为{_STATUS_CN.get(t['status'], t['status'])}）"
        for i, t in enumerate(rows, 1))
    out = f"已把「{name}」的 {len(rows)} 条指派落库：\n{lines}"
    created = res.get("created_members") or []
    if created:
        who = "、".join(f"{c['name']}（邀请码 {c['invite_code']}）" for c in created)
        out += f"\n顺手建了 {len(created)} 个占位成员：{who} —— 把邀请码发给对方，注册后即可认领。"
    skipped = res.get("skipped") or []
    if skipped:
        out += f"\n{len(skipped)} 条没动：{'；'.join(skipped)}"
    out += "\n只改了负责人，任务状态没有变化。"
    return out


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
    tasks = d.get("tasks") or []
    if tasks:
        lines.append("- 任务明细（#id｜标题｜状态｜优先级；"
                     "待办=todo、进行中=doing、已完成=done；高=high、中=medium、低=low）：")
        for t in tasks:
            lines.append(f"  · #{t['id']}｜{t['title']}｜{_STATUS_CN.get(t['status'], t['status'])}"
                         f"｜{_PRIORITY_CN.get(t['priority'], t['priority'])}")
        if d.get("tasks_truncated"):
            lines.append(f"  · …另有 {d['tasks_truncated']} 个任务未列出，可用 list_tasks 查全量")
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


def _format_rag_note(hits: list[dict]) -> str:
    """把 RAG 命中的记忆片段压成给模型的 system 上下文（标注来源，防止模型当自己的知识）。"""
    lines = ["【项目记忆检索结果（来自知识库/会议纪要，回答务必基于以下原文，不得编造）】"]
    for i, h in enumerate(hits[:3], 1):
        src = h.get("doc_type") or ""
        src_label = "会议纪要" if src == "meeting" else "知识库"
        lines.append(f"{i}. 《{h.get('title','')}》〔{src_label}〕：{h.get('text','')[:300]}")
    return "\n".join(lines)


def _maybe_inject_memory(db: Session, message: str, project_id: int | None) -> str | None:
    """资料/记忆类问题 + 已绑定项目 → 自动 RAG 检索注入上下文；失败静默降级。

    这是「项目长期记忆」的落点：会议纪要/需求文档向量化后，用户在对话中问
    「上次怎么定的/文档里怎么说」时，代码层自动把相关片段捞回来注入思考，
    模型不必（也常不会）自觉调用 search_knowledge。检索无命中或异常时不打扰对话。
    """
    if project_id is None:
        return None
    if not _MATERIAL_HINT.search(message):
        return None
    try:
        hits = rag_search(message, project_id=project_id, top_k=3)
    except Exception:
        return None  # embedding 未就绪/向量库异常 → 静默降级，不让检索拖垮对话
    if not hits:
        return None
    return _format_rag_note(hits)


def _load_history(db: Session, user_id: int, project_id: int | None,
                  exclude_last_user_content: str | None = None,
                  limit: int = HISTORY_LIMIT) -> list[dict]:
    """取最近上下文：绑定项目时只取该项目下的消息，未绑定时取该用户全部消息。

    这是防止「跨项目串扰」的关键：不同项目的对话互不进入彼此的上下文。
    刚落库的当前用户消息会由 Agent.run 再次追加，故默认剔除避免重复。
    """
    q = db.query(ChatMessage).filter_by(user_id=user_id)
    if project_id is not None:
        q = q.filter_by(project_id=project_id)
    rows = q.order_by(ChatMessage.id.desc()).limit(limit).all()
    rows.reverse()  # 时间正序
    msgs = [{"role": m.role, "content": m.content} for m in rows
            if m.role in ("user", "assistant")]
    if (exclude_last_user_content is not None and msgs
            and msgs[-1]["role"] == "user"
            and msgs[-1]["content"] == exclude_last_user_content):
        msgs = msgs[:-1]  # 该条由 Agent.run 追加，去掉避免上下文重复
    return msgs


def _fallback_digest(older: list[dict]) -> str:
    """确定性兜底摘要（不调模型）：把用户说过的话各截一小段。"""
    said = [m["content"].replace("\n", " ").strip()[:24]
            for m in older if m["role"] == "user"]
    return "；".join(said[-6:]) if said else "（更早的对话都是简短问答）"


def _compact_history(older: list[dict]) -> str | None:
    """把更早的历史压成一小段摘要（≤300 字）；失败退回确定性摘要。

    压缩本身绝不能把对话搞挂 —— 所以这里是 try/except 包住的，异常一律降级。
    """
    if len(older) <= 4:
        return None
    head = f"【更早的对话摘要（{len(older)} 条已折叠）】"
    if len(older) < HISTORY_MODEL_MIN:
        # 不太长就别花一次模型调用：确定性摘要已经够用（省 token 也省一次往返）
        return head + _fallback_digest(older)
    try:
        resp = llm.chat([
            {"role": "system", "content":
             "你是会话压缩器。把下面的历史对话压成不超过 3 条要点（每条不超过 30 字），"
             "只保留三样东西：用户的核心诉求、已经定下的决定、还没解决的悬而未决项。"
             "不要复述寒暄，不要编造。直接输出要点，不要 JSON。"},
            {"role": "user", "content": "\n".join(
                f"{'用户' if m['role'] == 'user' else '助手'}：{m['content'][:200]}"
                for m in older)},
        ], temperature=0.2, max_tokens=220)
        text = (resp.choices[0].message.content or "").strip()
        if text:
            return head + (text if len(text) <= 300 else text[:300] + "…")
    except Exception:
        pass  # 压缩失败不打扰对话，走确定性兜底
    return head + _fallback_digest(older)


def _load_context(db: Session, user_id: int, project_id: int | None,
                  exclude_last_user_content: str | None = None):
    """返回 (原样历史, 更早历史的摘要)。

    为什么不全量带：上下文是有限资源（Anthropic《Effective context engineering》）；
    为什么不全丢：硬截最近 20 条会把"开头定下的事"丢掉，聊到后面就开始答非所问。
    折中：最近 8 条原样保留，更早的（最多回看 60 条）压成一段摘要。
    """
    rows = _load_history(db, user_id, project_id, exclude_last_user_content,
                         limit=HISTORY_FETCH)
    if len(rows) <= HISTORY_VERBATIM:
        return rows, None
    older, latest = rows[:-HISTORY_VERBATIM], rows[-HISTORY_VERBATIM:]
    return latest, _compact_history(older)


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
        elif action == "assign_plan":
            # 按上传的名单/人员说明拟分配方案（不写库，D-017）
            _t0 = time.time()
            res = agent.executor.plan_assignment_from_doc()
            _ms = int((time.time() - _t0) * 1000)
            trace = [agent.executor.summarize_tool("plan_assignment_from_doc", {}, res, _ms)]
            reply = res.get("markdown") or f"没能拟出分配方案：{res.get('error', '未知错误')}"
        elif action == "apply":
            # 用户确认后才落库（只在存在待确认方案时才会走到这里）
            _t0 = time.time()
            res = agent.executor.apply_assignment()
            _ms = int((time.time() - _t0) * 1000)
            trace = [agent.executor.summarize_tool("apply_assignment", {}, res, _ms)]
            reply = _format_apply_reply(res, agent.executor.project_name)
        elif action == "query":
            # 只读进度查询：代码层先读真实项目状态注入上下文，
            # 模型只能基于数据作答——杜绝「不查库直接泛泛而谈/编造进度」。
            # 另外这一轮只给它只读工具（readonly=True）：既省固定成本，也杜绝"看进度却写了库"。
            ro = Agent(user_id=body.user_id, project_id=body.project_id, readonly=True)
            _t0 = time.time()
            snap = ro.executor.project_snapshot()
            _ms = int((time.time() - _t0) * 1000)
            if snap.get("ok"):
                trace = [ro.executor.summarize_tool("project_snapshot", {}, snap, _ms)]
                _note = _format_snapshot_note(snap)
            else:
                _note = None
            history, compact_note = _load_context(db, body.user_id, body.project_id,
                                                 exclude_last_user_content=body.message)
            _note = "\n\n".join(x for x in (_note, compact_note) if x) or None
            reply = ro.run(body.message, history=history, context_note=_note)
            # project_snapshot 非 LLM 工具，不会进 executor.last_trace，这里手动合并
            trace = trace + ro.executor.last_trace

    # 3) 其余请求照旧走 Agent 工具循环（dispatch 内部已记录执行轨迹）
    if reply is None:
        # 长期记忆注入：绑定项目 + 资料/记忆类问题 → 代码层自动 RAG 检索
        # （失败静默降级，不影响对话；命中则作为 system 上下文交给模型）
        memory_note = _maybe_inject_memory(db, body.message, body.project_id)
        history, compact_note = _load_context(db, body.user_id, body.project_id,
                                             exclude_last_user_content=body.message)
        context_note = "\n\n".join(x for x in (compact_note, memory_note) if x) or None
        reply = agent.run(body.message, history=history, context_note=context_note)
        trace = agent.executor.last_trace
        # 折叠更早的对话也记一笔，让"为什么它还记着开头的事"对用户可见
        if compact_note:
            trace = [{"tool": "compact_history", "label": "折叠更早的对话",
                      "detail": compact_note.split("】")[0].lstrip("【"),
                      "ok": True, "ms": 0}] + trace
        # 检索动作本身记入轨迹，让「Agent 查了项目记忆」对用户可见
        if memory_note:
            trace = [{"tool": "search_knowledge", "label": "检索项目记忆",
                      "detail": f"自动检索知识库/会议纪要，命中 {memory_note.count('《')} 篇相关片段",
                      "ok": True, "ms": 0}] + trace

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


@router.post("/meeting-summary")
def meeting_summary(body: MeetingSummaryRequest, db: Session = Depends(get_db)):
    """前端「把本次对话存为纪要」按钮：将该项目最近的对话整理成会议纪要入库。

    与 Agent 的 save_meeting 工具区别：本接口由页面按钮直接触发、不经过对话轮次，
    对最近对话历史做一次 LLM 结构化摘要后落 doc_type=meeting（自动向量化进长期记忆）。
    """
    if project_service.get_project(db, body.project_id) is None:
        raise HTTPException(404, f"项目 {body.project_id} 不存在")
    history = _load_history(db, body.user_id, body.project_id)
    exchanges = [
        f"{'用户' if h['role'] == 'user' else '助手'}: {h['content']}"
        for h in history if h["content"] and h["content"].strip()
    ]
    if len(exchanges) < 2:
        raise HTTPException(400, "当前对话内容太少，暂无可沉淀的结论")
    transcript = "\n".join(exchanges[-20:])

    try:
        parsed, jerr = llm.chat_json([
            {"role": "system", "content":
             "你是团队记录助手。把下面的对话记录整理成一份结构化会议纪要，"
             "提取其中真正有保存价值的结论、决策、待办、风险与共识；"
             "不要收录寒暄与无关闲谈。"
             "输出 JSON：{\"title\":\"纪要主题（建议含日期，形如「2026-09-08 XX 讨论」，不超过 30 字）\","
             "\"content\":\"纪要正文\"}。"
             "正文用分节要点列出（【结论】【决策】【待办】【风险】等），"
             "只能依据对话中真实出现的内容，不得编造。"},
            {"role": "user", "content": f"对话记录：\n{transcript}"},
        ], temperature=0.3, max_tokens=1200)
    except Exception as e:
        raise HTTPException(502, f"纪要生成失败: {e}")
    if jerr is not None or not isinstance(parsed, dict) or not str(parsed.get("title") or "").strip():
        raise HTTPException(502, f"纪要生成失败（模型输出无法解析：{jerr or '空结果'}），请重试")

    title = str(parsed["title"]).strip()[:200]
    content = str(parsed.get("content") or "").strip()
    doc = knowledge_service.create_document(db, body.project_id, title,
                                            content or transcript,
                                            file_type="txt", doc_type="meeting")
    return {"ok": True, "doc_id": doc.id, "title": doc.title,
            "created_at": doc.created_at.isoformat() if doc.created_at else None}
