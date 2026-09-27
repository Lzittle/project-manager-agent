"""Agent 主循环：组装 messages → 请求模型（带 tools）→ 执行工具 → 直到给出回复。

拆分后的门面（D-025）：行为逻辑拆到同目录的 core/tools.py（工具 schema）、
core/intents.py（意图与路由）、core/executor.py（工具执行）、core/prompts.py（提示词）、
core/utils.py（小工具）。为不让调用方（api/chat.py、eval/、tests/）改写法，
这里把上面这些名字转出去 —— 老的 `from core.agent import ...` 继续有效。
"""
import json
from typing import Any, Optional

from core import llm
from core.executor import _ToolExecutor
from core.intents import (find_project_mention, has_pending_assignment,
                          is_apply_assignment_intent, is_ask_detail_intent,
                          is_assign_plan_intent, is_plan_intent, is_progress_query,
                          resolve_bound_action)
from core.prompts import build_system_prompt
from core.tools import READONLY_TOOL_NAMES, TOOLS, build_tools
from core.utils import brief_error, clip

__all__ = [
    "Agent", "MAX_ITER", "TOOLS", "READONLY_TOOL_NAMES", "build_tools",
    "build_system_prompt", "resolve_bound_action", "is_plan_intent",
    "is_progress_query", "is_ask_detail_intent", "is_assign_plan_intent",
    "is_apply_assignment_intent", "has_pending_assignment", "find_project_mention",
    "clip", "brief_error",
]

MAX_ITER = 8  # 单轮最多工具迭代次数，防死循环


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
