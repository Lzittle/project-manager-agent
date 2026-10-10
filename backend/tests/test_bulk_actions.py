"""阶段 3（D-028）：批量写「先方案后落库」+ 一句话撤销。全部离线，不调模型。

测的是三条硬约束：
1. 批量方案阶段**一个字都不写库**（任务状态/存在性都不变）；
2. 确认落库后，撤销能把任务恢复成原样（状态、负责人，乃至被删任务本身）；
3. 同一轮直接写只准碰一个任务，第二个不同任务必须走方案（dispatch 守卫）。
"""
from core.agent import _ToolExecutor, resolve_bound_action
from models.database import SessionLocal


def _project(client, name):
    r = client.post("/api/projects?user_id=1", json={"name": name, "description": "pytest"})
    assert r.status_code == 201, r.text
    return r.json()


def _task(client, pid, title, status="todo"):
    r = client.post("/api/tasks?user_id=1",
                    json={"project_id": pid, "title": title, "status": status})
    assert r.status_code == 201, r.text
    return r.json()


def _member(client, name):
    r = client.post("/api/members", json={"name": name})
    assert r.status_code in (201, 409), r.text
    return r.json()


def _status(client, task_id):
    return client.get(f"/api/tasks/{task_id}").json()["status"]


def test_bulk_status_plan_writes_nothing_then_apply_and_undo(client):
    """批量改状态：方案阶段零写入 → 确认落库 → 撤销回到原状态。"""
    pid = _project(client, "批量改状态测试")["id"]
    t1 = _task(client, pid, "批量状态任务甲")
    t2 = _task(client, pid, "批量状态任务乙", status="doing")
    ex = _ToolExecutor(user_id=1, project_id=pid)

    plan = ex.plan_bulk_status(task_ids=[t1["id"], t2["id"]], status="done")
    assert plan["ok"] is True, plan
    assert len(plan["data"]) == 2 and "还没落库" in plan["markdown"]
    assert _status(client, t1["id"]) == "todo"      # 方案阶段一个字都没写
    assert _status(client, t2["id"]) == "doing"

    applied = ex.apply_bulk_action()
    assert applied["ok"] is True and applied["kind"] == "bulk_status", applied
    assert _status(client, t1["id"]) == "done" and _status(client, t2["id"]) == "done"

    undone = ex.undo_last_action()
    assert undone["ok"] is True, undone
    assert _status(client, t1["id"]) == "todo"      # 撤销回到原样
    assert _status(client, t2["id"]) == "doing"
    assert len(undone["data"]["restored_fields"]) == 2
    # 已经撤销过的台账不能再撤一次
    assert ex.undo_last_action(run_id=undone["run_id"])["ok"] is False


def test_bulk_delete_plan_then_apply_and_undo_restores_task(client):
    """批量删除：先列清单不删 → 确认才删 → 撤销按快照把任务（含依赖边）放回来。"""
    pid = _project(client, "批量删除测试")["id"]
    t1 = _task(client, pid, "批量删除任务甲")
    t2 = _task(client, pid, "批量删除任务乙")
    client.post(f"/api/tasks/{t1['id']}/dependencies",
                json={"task_id": t1["id"], "depends_on_id": t2["id"]}).raise_for_status()
    ex = _ToolExecutor(user_id=1, project_id=pid)

    plan = ex.plan_bulk_delete(task_ids=[t1["id"], t2["id"]])
    assert plan["ok"] is True and "一个字都还没删" in plan["markdown"], plan
    assert client.get(f"/api/tasks/{t1['id']}").status_code == 200   # 还没删
    assert plan["data"][0]["deps"] == 1                              # 依赖边也让人看见

    applied = ex.apply_bulk_action()
    assert applied["ok"] is True and applied["kind"] == "bulk_delete", applied
    assert client.get(f"/api/tasks/{t1['id']}").status_code == 404

    undone = ex.undo_last_action()
    assert undone["ok"] is True, undone
    back = client.get(f"/api/tasks/{t1['id']}").json()
    assert back["title"] == "批量删除任务甲" and back["status"] == "todo"
    deps = client.get(f"/api/tasks/{t1['id']}/dependencies").json()
    assert deps == [{"task_id": t1["id"], "depends_on_id": t2["id"]}]   # 依赖边也回来了


def test_undo_restores_assignee_and_reports_when_nothing_to_undo(client):
    """指派可撤销；没有台账时如实说「没有可撤销的操作」，不乱动数据。"""
    pid = _project(client, "撤销指派测试")["id"]
    t = _task(client, pid, "撤销指派任务")
    m = _member(client, "撤销指派张三")
    ex = _ToolExecutor(user_id=1, project_id=pid)

    nothing = ex.undo_last_action()                      # 什么都没做：如实说没得撤（no-op，不算失败）
    assert nothing["ok"] is True and nothing["data"]["nothing_to_undo"] is True
    assert ex.assign_task(t["id"], m["id"])["ok"] is True
    assert client.get(f"/api/tasks/{t['id']}").json()["assignee_name"] == "撤销指派张三"

    undone = ex.undo_last_action()
    assert undone["ok"] is True and undone["kind"] == "assign", undone
    assert client.get(f"/api/tasks/{t['id']}").json()["assignee_id"] is None


def test_dispatch_blocks_second_direct_task_write(client):
    """同一轮直接写只准碰一个任务：第二个不同任务必须走 plan_bulk_*（否则逐个写一串）。"""
    pid = _project(client, "批量守卫测试")["id"]
    t1 = _task(client, pid, "守卫任务甲")
    t2 = _task(client, pid, "守卫任务乙")
    ex = _ToolExecutor(user_id=1, project_id=pid)

    assert ex.dispatch("update_task_status", {"task_id": t1["id"], "status": "done"})["ok"] is True
    blocked = ex.dispatch("update_task_status", {"task_id": t2["id"], "status": "done"})
    assert blocked["ok"] is False and "plan_bulk_status" in blocked["error"]
    assert _status(client, t2["id"]) == "todo"           # 第二个任务没被写
    # 同一个任务重复写不算批量（幂等场景不受影响）
    assert ex.dispatch("update_task_status", {"task_id": t1["id"], "status": "doing"})["ok"] is True


def test_routes_pick_apply_and_undo_only_when_there_is_something(client):
    """「确认」只在真有方案时走落库；「撤销」只在真有台账时走回滚。"""
    pid = _project(client, "批量路由测试")["id"]
    t = _task(client, pid, "路由任务")
    ex = _ToolExecutor(user_id=1, project_id=pid)
    db = SessionLocal()
    try:
        # 没有待确认方案时说「就按这个来」→ 代码层拦住并让用户重出方案（D-028 探针发现的缺口）
        assert resolve_bound_action(db, 1, pid, "批量路由测试", "就按这个来")[0] == "apply_missing"
        assert resolve_bound_action(db, 1, pid, "批量路由测试", "撤销")[0] == "agent"
    finally:
        db.close()

    assert ex.plan_bulk_status(task_ids=[t["id"]], status="done")["ok"] is True
    db = SessionLocal()
    try:
        assert resolve_bound_action(db, 1, pid, "批量路由测试", "就按这个来")[0] == "apply"
    finally:
        db.close()

    assert ex.apply_bulk_action()["ok"] is True
    db = SessionLocal()
    try:
        assert resolve_bound_action(db, 1, pid, "批量路由测试", "撤销上一次改动")[0] == "undo"
        # 撤销之后没有可撤销台账 → 这句话回到通用处理，不再乱回滚
    finally:
        db.close()
    assert ex.undo_last_action()["ok"] is True
    db = SessionLocal()
    try:
        assert resolve_bound_action(db, 1, pid, "批量路由测试", "撤销")[0] == "agent"
    finally:
        db.close()
