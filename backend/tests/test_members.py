"""成员名册与指派（D-018）：手填占位成员 → 指派 → 任务带上负责人名字。

离线可跑（不碰 LLM、不碰网络）；用的是 conftest 里的独立测试库。
"""


def _new_project(client, name="成员名册测试项目"):
    r = client.post("/api/projects?user_id=1", json={"name": name, "description": "pytest"})
    assert r.status_code == 201, r.text
    return r.json()


def test_member_roster_placeholder_and_duplicate_name(client):
    """手填的成员是占位身份（没有账号、带邀请码）；同名不自动合并。"""
    r = client.post("/api/members", json={"name": "张三"})
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["status"] == "placeholder"
    assert m["user_id"] is None
    assert len(m["invite_code"]) == 6

    names = [x["name"] for x in client.get("/api/members").json()]
    assert "张三" in names

    # 同名再来一次 → 409（交给上层问人，PLAN §5）
    assert client.post("/api/members", json={"name": "张三"}).status_code == 409


def test_task_shows_assignee_name_without_changing_status(client):
    """指派：写成员 id，界面能读到名字；状态不变（D-005）。"""
    m = client.post("/api/members", json={"name": "李四"}).json()
    p = _new_project(client, "指派测试项目")
    t = client.post("/api/tasks?user_id=1", json={
        "project_id": p["id"], "title": "被指派的任务", "status": "todo"}).json()

    r = client.patch(f"/api/tasks/{t['id']}", json={"assignee_id": m["id"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["assignee_id"] == m["id"]
    assert body["assignee_name"] == "李四"
    assert body["assignee_status"] == "placeholder"
    assert body["status"] == "todo"

    # 列表接口也带名字（批量取名册，不走 N+1）
    lst = client.get(f"/api/tasks?project_id={p['id']}").json()
    row = next(x for x in lst if x["id"] == t["id"])
    assert row["assignee_name"] == "李四"

    # 指派给不在名册里的 id → 404（不悄悄写脏数据）
    assert client.patch(f"/api/tasks/{t['id']}", json={"assignee_id": 99999}).status_code == 404
