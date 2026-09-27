"""成员指派与「按名单分配」（D-017 / D-019）：工具层离线测试（LLM 用 mock，不联网）。

- assign_task：只改负责人、不改状态；名册外的人直接失败；
- plan_assignment_from_doc：读资料 + 名册 + 未完成任务 → 出方案但**不写库**；
- apply_assignment：确认后落库，名册里没有的人建成占位成员（带邀请码）；支持 overrides 微调。

注意：测试库是 session 级的，成员名字统一加前缀，避免和 test_members.py 的同名用例撞车。
"""
import json
from types import SimpleNamespace

from core.agent import _ToolExecutor
from models.database import SessionLocal, KnowledgeDocument


def _resp(content: str):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def _project(client, name):
    r = client.post("/api/projects?user_id=1", json={"name": name, "description": "pytest"})
    assert r.status_code == 201, r.text
    return r.json()


def _task(client, pid, title):
    r = client.post("/api/tasks?user_id=1", json={"project_id": pid, "title": title, "status": "todo"})
    assert r.status_code == 201, r.text
    return r.json()


def _member(client, name):
    r = client.post("/api/members", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


def _roster_doc(pid, title="相关人员说明", content="张三负责后端；李四负责前端。"):
    """直接插一条资料记录：绕过向量化，测试保持离线可跑。"""
    db = SessionLocal()
    try:
        doc = KnowledgeDocument(title=title, content=content, file_type="txt",
                                doc_type="doc", project_id=pid)
        db.add(doc)
        db.commit()
        db.refresh(doc)
        return doc.id
    finally:
        db.close()


def test_assign_task_tool_keeps_status(client):
    """assign_task：写负责人、状态不动（D-005）；名册外的成员 id 直接失败。"""
    m = _member(client, "指派工具张三")
    pid = _project(client, "指派工具测试项目")["id"]
    t = _task(client, pid, "指派工具用任务")

    ex = _ToolExecutor(user_id=1, project_id=pid)
    res = ex.assign_task(t["id"], m["id"])
    assert res["ok"] is True, res
    assert res["data"]["assignee_name"] == "指派工具张三"
    assert res["data"]["status"] == "todo"

    again = client.get(f"/api/tasks/{t['id']}").json()
    assert again["assignee_id"] == m["id"] and again["status"] == "todo"
    assert again["assignee_status"] == "placeholder"

    bad = ex.assign_task(t["id"], 999999)
    assert bad["ok"] is False and "名册" in bad["error"]


def test_plan_then_apply_assignment(client, monkeypatch):
    """读名单 → 出方案（不落库）→ 确认 → 落库（名册没有的人建占位成员）。"""
    pid = _project(client, "按名单分配测试")["id"]
    t1 = _task(client, pid, "后端接口开发")
    t2 = _task(client, pid, "前端页面开发")
    _roster_doc(pid)
    _member(client, "名单张三")

    canned = json.dumps([
        {"task_id": t1["id"], "member_name": "名单张三", "reason": "后端由他负责"},
        {"task_id": t2["id"], "member_name": "名单李四", "reason": "前端由他负责"},
        {"task_id": 999999, "member_name": "名单张三", "reason": "不存在的任务，应被丢掉"},
    ], ensure_ascii=False)
    monkeypatch.setattr("core.llm.chat", lambda *a, **kw: _resp(canned))

    ex = _ToolExecutor(user_id=1, project_id=pid)
    plan = ex.plan_assignment_from_doc()
    assert plan["ok"] is True, plan
    assert len(plan["data"]) == 2                      # 不存在的任务被过滤掉
    assert "还没落库" in plan["markdown"]
    by_task = {it["task_id"]: it for it in plan["data"]}
    assert by_task[t1["id"]]["member_id"] is not None   # 名册里唯一命中 → 直接认人
    assert by_task[t2["id"]]["needs_create"] is True    # 名册没有 → 确认后建占位成员

    # 关键：方案还没碰任务
    assert client.get(f"/api/tasks/{t1['id']}").json()["assignee_id"] is None
    assert client.get(f"/api/tasks/{t2['id']}").json()["assignee_id"] is None

    applied = ex.apply_assignment()
    assert applied["ok"] is True, applied
    assert len(applied["data"]) == 2
    assert {c["name"] for c in applied["created_members"]} == {"名单李四"}

    a1 = client.get(f"/api/tasks/{t1['id']}").json()
    a2 = client.get(f"/api/tasks/{t2['id']}").json()
    assert a1["assignee_name"] == "名单张三" and a1["status"] == "todo"
    assert a2["assignee_name"] == "名单李四" and a2["assignee_status"] == "placeholder"

    # 同一份方案不能落两次
    assert ex.apply_assignment(plan_id=plan["plan_id"])["ok"] is False


def test_apply_assignment_with_override(client, monkeypatch):
    """微调：overrides 覆盖某条任务的负责人（用户说「第 3 条改成李工」）。"""
    pid = _project(client, "分配微调测试")["id"]
    t = _task(client, pid, "谁来做这件事")
    _roster_doc(pid)
    _member(client, "微调张三")
    _member(client, "微调李四")
    canned = json.dumps([{"task_id": t["id"], "member_name": "微调张三", "reason": "初版"}],
                        ensure_ascii=False)
    monkeypatch.setattr("core.llm.chat", lambda *a, **kw: _resp(canned))

    ex = _ToolExecutor(user_id=1, project_id=pid)
    assert ex.plan_assignment_from_doc()["ok"] is True
    res = ex.apply_assignment(overrides=[{"task_id": t["id"], "member_name": "微调李四"}])
    assert res["ok"] is True, res
    assert client.get(f"/api/tasks/{t['id']}").json()["assignee_name"] == "微调李四"
