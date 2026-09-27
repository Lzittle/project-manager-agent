"""阶段 2 记忆闭环（D-027）：认出「这是个决定」→ 拟稿（不写库）→ 一句话确认 → 入库；说不用就丢弃。

这条链路是**确定性路由**，不经过模型 —— 所以测试不需要 mock LLM，也不联网。
"""
from core.intents import (is_conclusion_intent, is_note_confirm_intent,
                          is_note_discard_intent)


def _project(client, name):
    r = client.post("/api/projects?user_id=1", json={"name": name, "description": "pytest"})
    assert r.status_code == 201, r.text
    return r.json()


def _docs(client, pid):
    return client.get(f"/api/projects/{pid}/documents").json()


def _say(client, pid, message):
    r = client.post("/api/chat/send",
                    json={"message": message, "user_id": 1, "project_id": pid})
    assert r.status_code == 200, r.text
    return r.json()


def test_conclusion_intent_is_narrow():
    """判定要窄：宁可不记，也别刷一库噪音。"""
    assert is_conclusion_intent("就这么定：登录用 JWT + 短信验证码双因子")
    assert is_conclusion_intent("这条约定下来：灰度先覆盖 3 个城市")
    # 显式归档走 save_meeting，不重复走草稿确认
    assert not is_conclusion_intent("把结论记下来存成纪要")
    # 疑问句不是结论
    assert not is_conclusion_intent("登录方案定了吗？")
    # 普通陈述不是结论
    assert not is_conclusion_intent("这个任务还需要再打磨一下")
    assert not is_conclusion_intent("今天先把登录联调跑通")
    # 确认 / 放弃都只认短句
    assert is_note_confirm_intent("存") and is_note_confirm_intent("好的")
    assert is_note_discard_intent("不用了") and is_note_discard_intent("算了")
    assert not is_note_confirm_intent("存一下这个任务的时间安排吧，我想看看")  # 长句不算


def test_draft_then_confirm_writes_note(client):
    """拟稿阶段一个字都不写库；确认后才生成一条 doc_type=note 的项目记忆。"""
    pid = _project(client, "记忆闭环测试")["id"]
    before = len(_docs(client, pid))

    drafted = _say(client, pid, "就这么定：登录方案用 JWT + 短信验证码双因子")
    assert "存" in drafted["reply"] and "不用" in drafted["reply"]
    assert [s["tool"] for s in drafted["trace"]] == ["draft_note"]
    assert len(_docs(client, pid)) == before, "拟稿阶段不许写库"

    saved = _say(client, pid, "存")
    assert "项目记忆" in saved["reply"]
    assert [s["tool"] for s in saved["trace"]] == ["save_note"]
    docs = _docs(client, pid)
    assert len(docs) == before + 1
    note = docs[-1] if docs[-1]["doc_type"] == "note" else [d for d in docs if d["doc_type"] == "note"][0]
    assert note["doc_type"] == "note" and "JWT" in note["content"]

    # 同样的结论再确认一次 → 去重，不重复入库
    _say(client, pid, "就这么定：登录方案用 JWT + 短信验证码双因子")
    again = _say(client, pid, "存")
    assert "重复" in again["reply"] or "刚记过" in again["reply"]
    assert len([d for d in _docs(client, pid) if d["doc_type"] == "note"]) == 1


def test_discard_leaves_no_trace(client):
    """说「不用了」→ 草稿作废，项目记忆里不留东西。"""
    pid = _project(client, "记忆丢弃测试")["id"]
    before = len(_docs(client, pid))
    _say(client, pid, "就这么定：支付超时统一 5 秒，重试 3 次")
    out = _say(client, pid, "不用了")
    assert [s["tool"] for s in out["trace"]] == ["discard_note"]
    assert len(_docs(client, pid)) == before
    # 草稿作废后再"存"，也没有东西可存 —— 直接问执行器，避免这一步跑到模型
    # （实测：草稿没了还说"存"会落到 agent 兜底，模型可能顺手存一份纪要，
    #  这属于已知边界，记在 D-027 的代价里）
    from core.agent import _ToolExecutor
    res = _ToolExecutor(user_id=1, project_id=pid).save_note()
    assert res["ok"] is False and "没有待确认" in res["error"]
    assert len(_docs(client, pid)) == before
