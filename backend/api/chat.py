"""对话接口 /api/chat

- POST /send      自然语言 -> Agent 工具循环 -> 回复；user/assistant 消息落库 chat_messages
- GET  /history   该用户的对话历史（支持 ?project_id= 按项目隔离，供多项目场景下互不串扰）
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from core.agent import Agent, resolve_bound_action
from models.database import get_db, ChatMessage
from models.schemas import ChatRequest, ChatMessageOut

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
    if body.project_id is not None:
        action, payload = resolve_bound_action(
            db, body.user_id, body.project_id,
            agent.executor.project_name, body.message)
        if action == "conflict":
            bound_name = agent.executor.project_name or f"项目{body.project_id}"
            reply = (f"当前对话已绑定「{bound_name}」，而你提到的是另一个项目「{payload}」。"
                     f"为避免任务建到错误项目，请先在页面上方切换到「{payload}」，"
                     f"或先取消绑定再对我说要规划哪个项目。")
        elif action == "plan":
            res = agent.executor.plan_tasks()  # project_id 省略 → 落到绑定项目
            reply = _format_plan_reply(res, agent.executor.project_name)

    # 3) 其余请求照旧走 Agent 工具循环
    history = _load_history(db, body.user_id, body.project_id,
                            exclude_last_user_content=body.message)
    if reply is None:
        reply = agent.run(body.message, history=history)

    # 4) 助手回复落库
    assistant_msg = ChatMessage(role="assistant", content=reply,
                                user_id=body.user_id, project_id=body.project_id)
    db.add(assistant_msg)
    db.commit()

    return {
        "reply": reply,
        "message_id": assistant_msg.id,
        "project_id": body.project_id,
    }


@router.get("/history", response_model=list[ChatMessageOut])
def chat_history(user_id: int = Query(...),
                 project_id: int | None = Query(None, description="按项目过滤，缺省返回全部"),
                 db: Session = Depends(get_db)):
    q = db.query(ChatMessage).filter_by(user_id=user_id)
    if project_id is not None:
        q = q.filter_by(project_id=project_id)
    return q.order_by(ChatMessage.id.asc()).limit(100).all()
