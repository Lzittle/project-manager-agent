"""阶段 1 的三件事（D-023）：任务列表瘦身与分页、工具错误压缩、长对话上下文压缩。

离线可跑：只在需要"模型输出"的地方 monkeypatch core.llm.chat。
"""
from types import SimpleNamespace

from api import chat as chat_api
from core.agent import _ToolExecutor
from models.database import ChatMessage, SessionLocal


def _resp(content: str):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def _project(client, name):
    r = client.post("/api/projects?user_id=1", json={"name": name, "description": "pytest"})
    assert r.status_code == 201, r.text
    return r.json()


def _task(client, pid, title, status="todo"):
    r = client.post("/api/tasks?user_id=1", json={
        "project_id": pid, "title": title, "status": status, "priority": "medium"})
    assert r.status_code == 201, r.text
    return r.json()


# ---------- 1. 任务列表：瘦身 + 分页 ----------

def test_task_list_is_lean_and_paged(client):
    pid = _project(client, "瘦身分页测试")["id"]
    for i in range(7):
        _task(client, pid, f"任务{i + 1}")
    _task(client, pid, "已完成的任务", status="done")

    ex = _ToolExecutor(user_id=1, project_id=pid)
    page = ex.list_tasks(limit=5)
    assert page["ok"] is True
    assert page["total"] == 8 and page["shown"] == 5, page
    assert "需带 offset" in page["note"] or "offset" in page["note"]

    # 瘦身：不带 description（模型用不到，白烧 token）
    item = page["data"][0]
    assert set(item) <= {"id", "title", "status", "priority", "assignee"}, item
    assert "description" not in item

    # 翻页：第二页与第一页不重叠
    page2 = ex.list_tasks(limit=5, offset=5)
    assert page2["shown"] == 3
    assert not ({t["id"] for t in page["data"]} & {t["id"] for t in page2["data"]})

    # 按状态过滤
    done = ex.list_tasks(status="done")
    assert done["total"] == 1 and done["data"][0]["title"] == "已完成的任务"

    # 负责人会带出来（有就带，没有就不占字段）
    m = client.post("/api/members", json={"name": "瘦身测试人"}).json()
    t = client.get(f"/api/tasks?project_id={pid}").json()[0]
    ex.assign_task(t["id"], m["id"])
    listed = ex.list_tasks(limit=200)
    assert any(x.get("assignee") == "瘦身测试人" for x in listed["data"])


# ---------- 2. 工具错误：压缩后再回填 ----------

def test_tool_error_is_compressed(client):
    # 依赖 client fixture：它会触发 lifespan 建表（单独跑这条时也成立）
    ex = _ToolExecutor(user_id=1, project_id=1)
    res = ex.dispatch("list_tasks", {"limit": "不是数字"})
    assert res["ok"] is False
    assert "ValueError" in res["error"]              # 有类型
    assert "｜建议：" in res["error"]                 # 有下一步建议
    assert "Traceback" not in res["error"]            # 没有堆栈
    assert len(res["error"]) <= 220                   # 够短


def test_dispatch_refuses_tools_not_offered(client):
    """绑定模式不给项目级写工具，模型"猜对名字"也必须被挡（2026-09-27 评测中真发生过）。"""
    pid = _project(client, "工具白名单测试")["id"]
    ex = _ToolExecutor(user_id=1, project_id=pid)
    res = ex.dispatch("update_project_fields", {"project_id": pid, "description": "偷偷改"})
    assert res["ok"] is False
    assert "不可用" in res["error"]
    # 项目描述没被改
    got = client.get(f"/api/projects/{pid}").json()
    assert got["description"] == "pytest"

    # 只读轮次里，写工具同样调不动
    ro = _ToolExecutor(user_id=1, project_id=pid, readonly=True)
    res2 = ro.dispatch("create_task", {"title": "偷偷建"})
    assert res2["ok"] is False and "不可用" in res2["error"]


# ---------- 3. 长对话：压缩早期历史 ----------

def test_long_history_is_compacted(client, monkeypatch):
    pid = _project(client, "上下文压缩测试")["id"]
    db = SessionLocal()
    try:
        for i in range(24):  # 12 轮
            db.add(ChatMessage(role="user", user_id=1, project_id=pid,
                               content=f"第{i + 1}轮：请记住这个决定-{i + 1}"))
            db.add(ChatMessage(role="assistant", user_id=1, project_id=pid,
                               content=f"已记下决定-{i + 1}"))
        db.commit()

        # 有模型：用模型给的摘要
        monkeypatch.setattr("core.llm.chat", lambda *a, **kw: _resp("1. 用户要记住每个决定\n2. 无悬空项"))
        msgs, note = chat_api._load_context(db, 1, pid)
        assert len(msgs) == chat_api.HISTORY_VERBATIM == 8
        assert note and "已折叠" in note and "无悬空项" in note
        assert msgs[-1]["content"] == "已记下决定-24"          # 最近的原样保留
        assert "第1轮" not in "".join(m["content"] for m in msgs)  # 早期的不再逐条带入

        # 模型挂了：退化成确定性摘要，不能把对话搞挂
        def boom(*a, **kw):
            raise RuntimeError("模型不可用")

        monkeypatch.setattr("core.llm.chat", boom)
        msgs2, note2 = chat_api._load_context(db, 1, pid)
        assert len(msgs2) == 8 and note2 and "已折叠" in note2
        assert "第20轮" in note2                              # 兜底摘要取了折叠窗口里最后几条用户话
    finally:
        db.query(ChatMessage).filter_by(project_id=pid).delete()
        db.commit()
        db.close()
