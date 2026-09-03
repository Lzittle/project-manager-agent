"""LLM 统一封装（openai 兼容接口，对接 .env 的 OPENAI_API_KEY / BASE_URL / LLM_MODEL）。

对外只暴露 chat()：传入 messages 列表，返回模型文本回复。
模型选择：.env 中 LLM_MODEL（当前为 deepseek-chat，DeepSeek 兼容 OpenAI 语法）。
"""
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
