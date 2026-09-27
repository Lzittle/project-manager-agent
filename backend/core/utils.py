"""通用小工具：把任意值/异常压成给模型看的短文本（与业务无关）。

从 core/agent.py 拆出（D-025），行为逐字未改。
"""
import json
from typing import Any


def clip(v: Any, limit: int = 120) -> str:
    """把任意值压成适合展示的短字符串（截断超长文本/参数）。"""
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
    return s if len(s) <= limit else s[:limit] + "…"


def brief_error(exc: Exception, hint: str = "") -> str:
    """把异常压成「类型 + 一句关键信息 +（可选）建议」。

    12-Factor Agents ⑨：错误要压缩后再回填上下文。原样把堆栈喂回去既烧 token，
    又会把模型带偏——它会开始分析堆栈，而不是换个办法把事办成。
    """
    raw = str(exc).strip()
    first = raw.splitlines()[0] if raw else ""
    text = f"{type(exc).__name__}：{clip(first, 140)}" if first else type(exc).__name__
    return f"{text}｜建议：{hint}" if hint else text

# 优先级中文（拼提示词与轨迹文案用）
PRI_CN = {"high": "高", "medium": "中", "low": "低"}
