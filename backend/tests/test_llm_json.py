"""LLM 层 JSON 结构化输出容错测试（chat_json）：解析失败重试 / 围栏剥离 / 夹带文字提取。

离线可跑：mock core.llm.chat，不消耗 token。
"""
import pytest

from core import llm
from types import SimpleNamespace


def _resp(content: str):
    return SimpleNamespace(choices=[
        SimpleNamespace(message=SimpleNamespace(content=content))])


def test_chat_json_clean_output(monkeypatch):
    """正常输出：直接解析成功。"""
    monkeypatch.setattr("core.llm.chat", lambda *a, **kw: _resp('{"a": 1}'))
    parsed, err = llm.chat_json([{"role": "user", "content": "hi"}])
    assert err is None and parsed == {"a": 1}


def test_chat_json_fence_stripped(monkeypatch):
    """模型带 ```json 围栏 → 剥离后解析。"""
    monkeypatch.setattr("core.llm.chat",
                        lambda *a, **kw: _resp('```json\n[{"t": "x"}]\n```'))
    parsed, err = llm.chat_json([{"role": "user", "content": "hi"}])
    assert err is None and parsed == [{"t": "x"}]


def test_chat_json_wrapped_text_extracted(monkeypatch):
    """模型前后夹带解释文字 → 截取首个 {…} 片段解析。"""
    monkeypatch.setattr("core.llm.chat",
                        lambda *a, **kw: _resp('好的，这是结果：{"name": "测试"} 希望对你有帮助'))
    parsed, err = llm.chat_json([{"role": "user", "content": "hi"}])
    assert err is None and parsed == {"name": "测试"}


def test_chat_json_retry_then_success(monkeypatch):
    """首次输出非法 JSON → 自动带错误回传重试，二次成功。"""
    calls = {"n": 0}

    def fake_chat(messages, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return _resp("我不是JSON")
        # 第二次：应能看到重试指令（引导自纠错）
        assert any("无法解析" in (m.get("content") or "") for m in messages)
        return _resp('{"ok": true}')

    monkeypatch.setattr("core.llm.chat", fake_chat)
    parsed, err = llm.chat_json([{"role": "user", "content": "hi"}])
    assert err is None and parsed == {"ok": True}
    assert calls["n"] == 2  # 确实重试了一次


def test_chat_json_retry_exhausted_returns_error(monkeypatch):
    """两次都非法 → 返回 (None, error) 不抛异常，由调用方降级。"""
    monkeypatch.setattr("core.llm.chat", lambda *a, **kw: _resp("全是废话"))
    parsed, err = llm.chat_json([{"role": "user", "content": "hi"}], attempts=2)
    assert parsed is None
    assert err  # 有错误说明


def test_chat_json_appends_json_constraint(monkeypatch):
    """首次请求会在 user 消息后追加「只输出 JSON」约束（不污染调用方 messages）。"""
    seen = {}

    def fake_chat(messages, **kw):
        seen["last"] = messages[-1]["content"]
        return _resp("[]")

    monkeypatch.setattr("core.llm.chat", fake_chat)
    original = [{"role": "user", "content": "原始提问"}]
    llm.chat_json(original, attempts=1)
    assert "只输出一个合法的 JSON" in seen["last"]
    # 调用方 messages 未被原地修改
    assert original[0]["content"] == "原始提问"
    assert "只输出一个合法的 JSON" not in original[0]["content"]
