"""对话接口 /api/chat

- POST /send      自然语言 -> Agent 工具循环 -> 回复；user/assistant 消息落库 chat_messages
- GET  /history   该用户的对话历史（供前端多轮展示，最多取最近 50 条）
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from core.agent import Agent
from models.database import get_db, ChatMessage
from models.schemas import ChatRequest, ChatMessageOut

router = APIRouter()

HISTORY_LIMIT = 20  # 作为上下文带入 Agent 的最近消息条数


def _load_history(db: Session, user_id: int) -> list[dict]:
    rows = (db.query(ChatMessage)
            .filter_by(user_id=user_id)
            .order_by(ChatMessage.id.desc())
            .limit(HISTORY_LIMIT)
            .all())
    rows.reverse()  # 时间正序
    return [{"role": m.role, "content": m.content} for m in rows if m.role in ("user", "assistant")]


@router.post("/send")
def chat_send(body: ChatRequest, db: Session = Depends(get_db)):
    # 1) 用户消息落库
    user_msg = ChatMessage(role="user", content=body.message, user_id=body.user_id)
    db.add(user_msg)
    db.commit()

    # 2) 携带最近上下文调用 Agent
    history = _load_history(db, body.user_id)
    agent = Agent(user_id=body.user_id, project_id=body.project_id)
    reply = agent.run(body.message, history=history)

    # 3) 助手回复落库
    assistant_msg = ChatMessage(role="assistant", content=reply, user_id=body.user_id)
    db.add(assistant_msg)
    db.commit()

    return {
        "reply": reply,
        "message_id": assistant_msg.id,
        "project_id": body.project_id,
    }


@router.get("/history", response_model=list[ChatMessageOut])
def chat_history(user_id: int = Query(...), db: Session = Depends(get_db)):
    return (db.query(ChatMessage)
            .filter_by(user_id=user_id)
            .order_by(ChatMessage.id.asc())
            .limit(100)
            .all())
