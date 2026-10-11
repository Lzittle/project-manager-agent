"""可见性与「我」的聚合（轮 4，D-031）

PLAN §8 的验收标准「组员登录后只看得到自己的任务」的服务端实现，覆盖：

- 不带令牌（老路径 `?user_id=`）→ **不过滤**（评测 / 探针 / Agent 走这条，必须零影响）
- 队长（项目创建者）→ 看本项目全部任务
- 组员 → 只看 `assignee_id == 自己的名册成员` 的任务
- `GET /api/tasks/mine` → 跨项目聚合、带项目名；未登录 401；未认领名册 → 空
- 看不见 ≠ 能改：写了不属于自己的任务仍能改（§7 不做细粒度权限），这里明确记录当前边界

自带隔离（用到 `isolate_db`），不污染共享测试库。
"""
import pytest

from models.database import User
from services import auth_service

PW = "pw123456"


@pytest.fixture(autouse=True)
def _isolate_shared_db(isolate_db):
    yield


def _register(client, username):
    r = client.post("/api/auth/register", json={
        "username": username, "email": f"{username}@example.com", "password": PW})
    assert r.status_code == 201, r.text
    body = r.json()
    return body["user"], {"Authorization": f"Bearer {body['token']}"}


def _project(client, owner_id, name):
    r = client.post(f"/api/projects?user_id={owner_id}", json={"name": name, "description": "pytest"})
    assert r.status_code == 201, r.text
    return r.json()


def _task(client, owner_id, project_id, title, assignee_id=None):
    t = client.post(f"/api/tasks?user_id={owner_id}", json={
        "project_id": project_id, "title": title}).json()
    if assignee_id is not None:
        t = client.patch(f"/api/tasks/{t['id']}", json={"assignee_id": assignee_id}).json()
    return t


def _visible_ids(client, project_id, headers=None):
    r = client.get(f"/api/tasks?project_id={project_id}", headers=headers or {})
    assert r.status_code == 200, r.text
    return {t["id"] for t in r.json()}


def test_legacy_path_without_token_is_not_filtered(client):
    """老路径不过滤：不带令牌时看得见全部 —— 评测 / 探针 / Agent 零影响。"""
    captain, _ = _register(client, "老路径队长")
    member, mh = _register(client, "老路径组员")
    pid = _project(client, captain["id"], "老路径项目")["id"]
    t_a = _task(client, captain["id"], pid, "队长的活")
    t_b = _task(client, captain["id"], pid, "组员的活", assignee_id=member["member_id"])

    assert _visible_ids(client, pid) == {t_a["id"], t_b["id"]}          # 无令牌：全看
    assert _visible_ids(client, pid, mh) == {t_b["id"]}                  # 带组员令牌：只看自己的


def test_captain_sees_all_member_sees_only_own(client, db_session):
    from models.database import Task

    captain, ch = _register(client, "队长甲")
    mate, mh = _register(client, "组员乙")
    pid = _project(client, captain["id"], "可见性项目")["id"]

    t_captain = _task(client, captain["id"], pid, "队长自己的活")        # 默认负责人=创建者
    t_mate = _task(client, captain["id"], pid, "派给组员乙的活", assignee_id=mate["member_id"])
    t_none = _task(client, captain["id"], pid, "还没派人的活")
    # 造一个真正「无人负责」的任务：PATCH 的 assignee_id=None 表示「不改」，所以要绕过接口
    db_session.query(Task).filter(Task.id == t_none["id"]).update({"assignee_id": None})
    db_session.commit()

    all_ids = {t_captain["id"], t_mate["id"], t_none["id"]}
    assert _visible_ids(client, pid, ch) == all_ids          # 队长：全看
    assert _visible_ids(client, pid, mh) == {t_mate["id"]}   # 组员：只看派给自己的（无人的也不算）


def test_mine_aggregates_across_projects_with_project_name(client):
    """「我」= 跨项目聚合，且带项目名（替代前端逐项目拉取再过滤的 N+1）。"""
    captain, _ = _register(client, "聚合队长")
    mate, mh = _register(client, "聚合组员")
    p1 = _project(client, captain["id"], "聚合项目一")["id"]
    p2 = _project(client, captain["id"], "聚合项目二")["id"]

    t1 = _task(client, captain["id"], p1, "项目一的活", assignee_id=mate["member_id"])
    t2 = _task(client, captain["id"], p2, "项目二的活", assignee_id=mate["member_id"])
    _task(client, captain["id"], p2, "不是他的活")

    r = client.get("/api/tasks/mine", headers=mh)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert {x["id"] for x in rows} == {t1["id"], t2["id"]}
    names = {x["id"]: x["project_name"] for x in rows}
    assert names[t1["id"]] == "聚合项目一"
    assert names[t2["id"]] == "聚合项目二"
    assert all(x["assignee_name"] == "聚合组员" for x in rows)


def test_mine_requires_login_and_is_empty_without_roster_identity(client, db_session):
    """未登录 401；登录了但没认领名册 → 空列表（你还没有「我」）。"""
    assert client.get("/api/tasks/mine").status_code == 401
    assert client.get("/api/tasks/mine", headers={"Authorization": "Bearer bad.token"}).status_code == 401

    u = User(username="无身份的人", email="noroster@example.com",
             password_hash=auth_service.hash_password(PW))
    db_session.add(u)
    db_session.commit()
    token = auth_service.make_token(u.id)
    r = client.get("/api/tasks/mine", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and r.json() == []


def test_visibility_is_read_only_not_write_permission(client):
    """边界声明：本轮只做「看得见什么」，不做「能改什么」（§7 不做细粒度权限）。"""
    captain, ch = _register(client, "写权限队长")
    mate, mh = _register(client, "写权限组员")
    pid = _project(client, captain["id"], "写权限项目")["id"]
    t = _task(client, captain["id"], pid, "队长的活")

    assert t["id"] not in _visible_ids(client, pid, mh)      # 组员看不见
    r = client.patch(f"/api/tasks/{t['id']}", json={"status": "doing"}, headers=mh)
    assert r.status_code == 200                              # 但改得动 —— 当前有意如此
    assert r.json()["status"] == "doing"
