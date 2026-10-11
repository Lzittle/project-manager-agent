"""认证与邀请码认领（轮 3，D-030）

覆盖：注册即入队、登录、令牌校验、错误密码/重复注册、认领成功与各种冲突。
认领的关键断言：**认领后已指派的任务自动归位**（任务指向 member.id，认领不改 id）。
离线可跑（不碰 LLM、不碰网络）。

**为什么要自带隔离**：本仓库的测试共用一个文件库（conftest 只在会话开始清一次），
而 `create_task` 会把「创建者的成员身份」默认设成负责人。本模块注册的账号会占到
`user_id=1`，从而改变后续用例里 `user_id=1` 的含义（既有用例 `test_bulk_actions` 的
「撤销后负责人为空」就因此被带偏）。所以这里每个用例跑完都把新增行按 id 清掉，
把库还原到进来时的样子 —— 不动既有用例，也不用改它们的假设。
"""
import pytest
from sqlalchemy import func

from models.database import (ActionRun, AssignmentRun, ChatMessage,
                             KnowledgeDocument, Member, NoteDraft, PlanRun,
                             Project, Task, TaskComment, TaskDependency, User)
from services import auth_service

PW = "pw123456"

# 清理顺序：先子表后主表（SQLite 默认不强制外键，但按依赖顺序更稳）
_TABLES_CHILD_FIRST = [
    TaskDependency, TaskComment, ChatMessage, ActionRun, AssignmentRun,
    PlanRun, NoteDraft, KnowledgeDocument, Task, Project, Member, User,
]


@pytest.fixture(autouse=True)
def _isolate_shared_db(db_session):
    """记录进来时各表的 max(id)，用例结束后删掉新增行（本模块自带隔离）。"""
    baseline = {m: db_session.query(func.max(m.id)).scalar() or 0
                for m in _TABLES_CHILD_FIRST}
    yield
    for model in _TABLES_CHILD_FIRST:
        db_session.query(model).filter(model.id > baseline[model]).delete(synchronize_session=False)
    db_session.commit()


def _register(client, username, email=None, password=PW):
    return client.post("/api/auth/register", json={
        "username": username, "email": email or f"{username}@example.com", "password": password})


def _login_token(client, username, password=PW):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def _new_project(client, name):
    r = client.post("/api/projects?user_id=1", json={"name": name, "description": "pytest"})
    assert r.status_code == 201, r.text
    return r.json()


def test_register_creates_account_and_active_member(client):
    """注册即入队：账号建好的同时，名册上多一条 active 成员。"""
    r = _register(client, "小明")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["token"]
    user = body["user"]
    assert user["username"] == "小明"
    assert user["member_id"] is not None      # 注册即挂上了名册成员
    assert user["member_status"] == "active"

    names = [m["name"] for m in client.get("/api/members").json()]
    assert "小明" in names

    # 密码相关字段永不回传
    assert "password" not in user and "password_hash" not in user


def test_register_rejects_duplicate_username_and_email(client):
    assert _register(client, "dup_user").status_code == 201
    assert _register(client, "dup_user", "other@example.com").status_code == 409
    assert _register(client, "dup_user2", "dup_user@example.com").status_code == 409
    # 密码太短 → 422（Pydantic 层拦下）
    assert client.post("/api/auth/register", json={
        "username": "shortpw", "email": "s@example.com", "password": "123"}).status_code == 422


def test_login_and_me(client):
    _register(client, "登录用户")
    # 错密码 / 不存在的用户 → 都是 401，不区分（防账号枚举）
    assert client.post("/api/auth/login", json={
        "username": "登录用户", "password": "wrong_pw"}).status_code == 401
    assert client.post("/api/auth/login", json={
        "username": "不存在的人", "password": PW}).status_code == 401

    token = _login_token(client, "登录用户")
    r = client.get("/api/auth/me", headers=_bearer(token))
    assert r.status_code == 200, r.text
    assert r.json()["username"] == "登录用户"

    # 无令牌 / 篡改令牌 → 401
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers=_bearer("bad.token.here")).status_code == 401


def test_claim_takes_over_assignments(client, db_session):
    """核心闭环：占位成员先被派了活 → 本人认领后，活自动归位到本人。"""
    # 0) 造一个「还没入队」的账号（模拟通过邀请进入小队的人），绕过注册即入队
    user = User(username="受邀者", email="invitee@example.com",
                password_hash=auth_service.hash_password(PW))
    db_session.add(user)
    db_session.commit()
    token = auth_service.make_token(user.id)

    # 1) 队长手填占位成员（带邀请码），并给它派活
    placeholder = client.post("/api/members", json={"name": "待认领的人"}).json()
    assert placeholder["status"] == "placeholder"
    code = placeholder["invite_code"]

    project = _new_project(client, "认领测试项目")
    # 建任务不接 assignee_id（创建时按创建人默认），指派走 PATCH
    task = client.post("/api/tasks?user_id=1", json={
        "project_id": project["id"], "title": "给占位成员的活"}).json()
    task = client.patch(f"/api/tasks/{task['id']}",
                        json={"assignee_id": placeholder["id"]}).json()
    assert task["assignee_name"] == "待认领的人"

    # 2) 认领
    r = client.post("/api/members/claim", json={"invite_code": code}, headers=_bearer(token))
    assert r.status_code == 200, r.text
    claimed = r.json()
    assert claimed["id"] == placeholder["id"]   # 认领不换 id
    assert claimed["user_id"] == user.id
    assert claimed["status"] == "active"
    assert claimed["invite_code"] is None       # 邀请码用完作废

    # 3) **任务自动归位**：任务仍指向同一个 member.id，负责人名字不变
    rows = client.get(f"/api/tasks?project_id={project['id']}").json()
    mine = next(x for x in rows if x["id"] == task["id"])
    assert mine["assignee_id"] == placeholder["id"]
    assert mine["assignee_name"] == "待认领的人"
    assert mine["assignee_status"] == "active"  # 状态跟着成员一起转为 active

    # 4) 邀请码不可重复使用 / 无效码 / 未登录
    assert client.post("/api/members/claim", json={"invite_code": code},
                       headers=_bearer(token)).status_code == 404
    assert client.post("/api/members/claim", json={"invite_code": "ZZZZZZ"},
                       headers=_bearer(token)).status_code == 404
    assert client.post("/api/members/claim", json={"invite_code": "ZZZZZZ"}).status_code == 401


def test_claim_rejected_when_already_member(client):
    """注册即入队的人再认领别人的邀请码 → 409（一人只占名册一个位置）。"""
    reg = _register(client, "已有身份的人")
    token = reg.json()["token"]
    placeholder = client.post("/api/members", json={"name": "另一个占位"}).json()

    r = client.post("/api/members/claim", json={"invite_code": placeholder["invite_code"]},
                    headers=_bearer(token))
    assert r.status_code == 409, r.text
