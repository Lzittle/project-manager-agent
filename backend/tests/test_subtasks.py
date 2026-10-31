"""任务小块 API：父任务汇总、组员推进与删除级联。"""
import pytest


PW = "pw123456"


@pytest.fixture(autouse=True)
def _isolate_shared_db(isolate_db):
    yield


def _register(client, username):
    r = client.post("/api/auth/register", json={
        "username": username,
        "email": f"{username}@subtasks.example",
        "password": PW,
    })
    assert r.status_code == 201, r.text
    body = r.json()
    return body["user"], {"Authorization": f"Bearer {body['token']}"}


def _project(client, owner_id):
    r = client.post(f"/api/projects?user_id={owner_id}",
                     json={"name": "小块验收项目", "description": "pytest"})
    assert r.status_code == 201, r.text
    return r.json()


def _task(client, owner_id, project_id, title="父任务"):
    r = client.post(f"/api/tasks?user_id={owner_id}", json={
        "project_id": project_id, "title": title})
    assert r.status_code == 201, r.text
    return r.json()


def test_subtask_create_update_and_parent_summary(client):
    captain, ch = _register(client, "subtask_captain")
    member, mh = _register(client, "subtask_member")
    project = _project(client, captain["id"])
    parent = _task(client, captain["id"], project["id"])

    # 队长把父任务指派给组员，组员才可以拆自己的小块
    assigned = client.patch(f"/api/tasks/{parent['id']}",
                            json={"assignee_id": member["member_id"]})
    assert assigned.status_code == 200

    created = client.post(f"/api/tasks/{parent['id']}/subtasks", headers=mh,
                          json={"title": "拆出接口", "description": "先做 API"})
    assert created.status_code == 201, created.text
    first = created.json()
    assert first["assignee_id"] == member["member_id"]

    second = client.post(f"/api/tasks/{parent['id']}/subtasks", headers=ch,
                         json={"title": "补验收", "assignee_id": member["member_id"]})
    assert second.status_code == 201, second.text

    progressed = client.patch(f"/api/tasks/subtasks/{first['id']}", headers=mh,
                              json={"status": "done"})
    assert progressed.status_code == 200
    assert progressed.json()["status"] == "done"

    summary = client.get(f"/api/tasks/{parent['id']}", headers=ch)
    assert summary.status_code == 200
    assert summary.json()["subtask_count"] == 2
    assert summary.json()["subtask_done_count"] == 1

    rows = client.get(f"/api/tasks/{parent['id']}/subtasks", headers=mh)
    assert rows.status_code == 200
    assert {row["title"] for row in rows.json()} == {"拆出接口", "补验收"}


def test_subtask_visibility_and_delete_cascade(client):
    captain, ch = _register(client, "subtask_owner")
    member, mh = _register(client, "subtask_other")
    project = _project(client, captain["id"])
    parent = _task(client, captain["id"], project["id"])

    created = client.post(f"/api/tasks/{parent['id']}/subtasks?user_id={captain['id']}",
                          json={"title": "仅队长父任务的小块"})
    assert created.status_code == 201, created.text

    # 登录组员不能读取或修改不属于自己的父任务小块
    assert client.get(f"/api/tasks/{parent['id']}/subtasks", headers=mh).status_code == 403
    assert client.patch(f"/api/tasks/subtasks/{created.json()['id']}", headers=mh,
                        json={"status": "done"}).status_code == 403

    assert client.delete(f"/api/tasks/{parent['id']}").status_code == 200
    assert client.get(f"/api/tasks/{parent['id']}/subtasks").status_code == 404
