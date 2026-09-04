"""LLM 统一封装（openai 兼容接口，对接 .env 的 OPENAI_API_KEY / BASE_URL / LLM_MODEL）。

对外暴露 chat() / chat_text() / chat_json()：
- chat()      原始响应（带 tools 的 Agent 工具循环用）；
- chat_text() 仅取文本回复；
- chat_json() JSON 结构化输出：格式约束 + 解析容错 + 失败重试（工程化）。
模型选择：.env 中 LLM_MODEL（当前为 deepseek-chat，DeepSeek 兼容 OpenAI 语法）。
"""
import json
import re
from typing import Optional

from openai import OpenAI

from core.config import settings

_client: Optional[OpenAI] = None


def get_client() -> OpenAI:
    """懒加载单例 client。"""
    global _client
    if _client is None:
        if not settings.has_api_key:
            raise RuntimeError(
                "未配置可用的 OPENAI_API_KEY（缺失或为占位 sk-xxx），请先在 backend/.env 填写真实 key"
            )
        _client = OpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            timeout=120,
            max_retries=2,
        )
    return _client


def chat(
    messages: list[dict],
    model: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 2048,
    tools: Optional[list] = None,
) -> object:
    """调用大模型。

    messages: [{"role": "system"|"user"|"assistant"|"tool", "content": str}, ...]
    tools:    openai function calling 工具列表（agent 使用）
    返回原始响应对象（choices[0]），由调用方决定取文本或 tool_calls。
    """
    kwargs = dict(
        model=model or settings.LLM_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if tools:
        kwargs["tools"] = tools
    return get_client().chat.completions.create(**kwargs)


def chat_text(messages: list[dict], **kwargs) -> str:
    """便捷方法：只取文本回复。"""
    resp = chat(messages, **kwargs)
    return (resp.choices[0].message.content or "").strip()


# ---------- JSON 结构化输出（工程化：格式约束 + 解析容错 + 重试） ----------

def _extract_json(text: str):
    """从模型输出中稳健提取 JSON 对象/数组。

    容错手段（对应面试「LLM 输出 JSON 不稳定」）：
      1. 剥离 ```json ... ``` 围栏；
      2. 若整体解析失败，截取首个 { / [ 起的最长合法片段（容忍模型前后夹带解释文字）；
      3. 返回 (parsed, error)：parsed 为 dict/list 或 None，error 为 None 表示成功。
    """
    if not text:
        return None, "空输出"
    t = text.strip()
    # 1) 剥离 markdown 围栏
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t).strip()
    try:
        return json.loads(t), None
    except json.JSONDecodeError:
        pass
    # 2) 前后夹带文字：从首个 { 或 [ 截取最长合法片段
    for opener, closer in (("{", "}"), ("[", "]")):
        start = t.find(opener)
        if start == -1:
            continue
        end = t.rfind(closer)
        if end <= start:
            continue
        try:
            return json.loads(t[start:end + 1]), None
        except json.JSONDecodeError:
            continue
    return None, "无法从模型输出中解析出 JSON"


def chat_json(messages: list[dict], *, attempts: int = 2,
              temperature: float = 0.2, **kwargs):
    """请求模型输出 JSON 并解析，失败自动带错误信息重试一次。

    典型用途：plan_tasks / 结构化抽取等「模型必须给可解析结构」的场景。
    - 首次请求在 user/system 消息后追加「只输出 JSON」约束（不污染调用方 messages）；
    - 解析失败把原始输出 + 错误原因回传，让模型自纠错重试；
    - 重试仍失败返回 (None, error)，由调用方决定降级策略，绝不抛异常。
    返回 (parsed, error)，parsed 为 dict/list 或 None。
    """
    prompt_tail = ("\n\n严格约束：只输出一个合法的 JSON（对象或数组），"
                   "不要任何解释、前后缀或 ```json 代码块标记。")
    msgs = [dict(m) for m in messages]
    if msgs and msgs[-1]["role"] == "user":
        msgs[-1] = {**msgs[-1], "content": msgs[-1]["content"] + prompt_tail}
    else:
        msgs.append({"role": "user", "content": prompt_tail.strip()})

    last_error = None
    for i in range(max(1, attempts)):
        try:
            resp = chat(msgs, temperature=temperature, **kwargs)
            raw = (resp.choices[0].message.content or "").strip()
        except Exception as e:  # 网络/限流等
            last_error = f"LLM 调用失败: {e}"
            continue
        parsed, err = _extract_json(raw)
        if err is None:
            return parsed, None
        last_error = err
        # 重试：把上次失败输出与错误原因回传，引导模型自纠错
        msgs.append({"role": "user", "content":
                     f"你上次的输出无法解析为 JSON（错误：{err}）。\n"
                     f"上次输出：\n{raw[:500]}\n\n请重新只输出一个合法 JSON。"})
    return None, last_error or "解析失败"
