"""后端 API 冒烟测试（离线可跑：LLM 调用用 monkeypatch mock，不消耗 token/不依赖网络）。"""
import json

import pytest

# ---------- 工具函数 ----------

def _new_project(client, name="测试项目"):
    r = client.post(f"/api/projects?user_id=1", json={"name": name, "description": "pytest"})
    assert r.status_code == 201, r.text
    return r.json()


def _new_task(client, project_id, title="测试任务", status="todo"):
    r = client.post("/api/tasks?user_id=1", json={
        "project_id": project_id, "title": title, "status": status, "priority": "medium"})
    assert r.status_code == 201, r.text
    return r.json()


# ---------- 健康检查 ----------

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ---------- 项目 CRUD ----------

def test_project_crud(client):
    p = _new_project(client, "电商系统测试")
    pid = p["id"]
    assert p["status"] == "active"
    assert p["creator_id"] == 1

    # 列表
    lst = client.get("/api/projects?user_id=1").json()
    assert any(x["id"] == pid for x in lst)

    # 详情
    got = client.get(f"/api/projects/{pid}")
    assert got.status_code == 200 and got.json()["name"] == "电商系统测试"

    # 更新（部分更新）
    upd = client.patch(f"/api/projects/{pid}", json={"status": "archived"})
    assert upd.status_code == 200 and upd.json()["status"] == "archived"

    # 404
    assert client.get("/api/projects/999999").status_code == 404

    # 删除
    assert client.delete(f"/api/projects/{pid}").status_code == 200
    assert client.get(f"/api/projects/{pid}").status_code == 404


# ---------- 任务 CRUD + 状态流转 + 评论 ----------

def test_task_crud_and_status_flow(client):
    p = _new_project(client)
    t = _new_task(client, p["id"], "开发首页")

    # 状态流转（模拟看板拖拽）
    r = client.patch(f"/api/tasks/{t['id']}", json={"status": "doing"})
    assert r.status_code == 200 and r.json()["status"] == "doing"
    r = client.patch(f"/api/tasks/{t['id']}", json={"status": "done", "priority": "high"})
    assert r.json()["status"] == "done" and r.json()["priority"] == "high"

    # 列表按项目过滤
    tasks = client.get(f"/api/tasks?project_id={p['id']}").json()
    assert len(tasks) == 1

    # 非法优先级被拒（422）
    bad = client.patch(f"/api/tasks/{t['id']}", json={"priority": "urgent"})
    assert bad.status_code == 422

    # 评论
    c = client.post(f"/api/tasks/{t['id']}/comments?user_id=1",
                    json={"content": "测试评论", "task_id": t["id"], "user_id": 1})
    assert c.status_code == 201
    comments = client.get(f"/api/tasks/{t['id']}/comments").json()
    assert len(comments) == 1 and comments[0]["content"] == "测试评论"

    # 删除任务（级联评论）
    assert client.delete(f"/api/tasks/{t['id']}").status_code == 200
    assert client.get(f"/api/tasks/{t['id']}").status_code == 404


# ---------- 项目删除级联（任务+文档+向量） ----------

def test_delete_project_cascades(client):
    p = _new_project(client, "级联删除测试")
    _new_task(client, p["id"])
    content = "级联删除验证文档：库存预警阈值、支付回调验收标准。"
    up = client.post(f"/api/projects/{p['id']}/documents",
                     files={"file": ("说明.md", content.encode(), "text/markdown")})
    assert up.status_code == 201, up.text

    assert client.delete(f"/api/projects/{p['id']}").status_code == 200
    # 文档已被级联删除
    docs = client.get(f"/api/projects/{p['id']}/documents")
    assert docs.status_code == 404  # 项目本身已不存在


# ---------- 知识库上传（自动向量化） + RAG 检索 ----------

def test_knowledge_upload_and_rag(client):
    from core import rag
    p = _new_project(client, "知识库项目")
    content = ("智慧校园系统需求：\n1) 课表与选课模块；\n2) 一卡通消费流水；\n"
               "3) 宿舍门禁联动；\n验收：刷卡识别延迟低于 200 毫秒。")
    up = client.post(f"/api/projects/{p['id']}/documents",
                     files={"file": ("智慧校园.md", content.encode(), "text/markdown")})
    assert up.status_code == 201, up.text
    doc = up.json()
    assert doc["file_type"] == "md"

    # 检索应命中该校项目文档
    hits = rag.search("门禁识别延迟要求", project_id=p["id"], top_k=2)
    assert hits, "向量检索应命中文档"
    assert any("200 毫秒" in h["text"] for h in hits)

    # 删除文档后向量同步清理
    assert client.delete(f"/api/documents/{doc['id']}").status_code == 200
    assert rag.search("门禁识别延迟要求", project_id=p["id"], top_k=2) == []

    # 非 UTF-8 文件被拒
    bad = client.post(f"/api/projects/{p['id']}/documents",
                      files={"file": ("乱码.txt", b"\xff\xfe\x00\x01", "text/plain")})
    assert bad.status_code == 400


# ---------- 对话（LLM 打桩，验证链路与落库） ----------

def test_chat_send_and_history(client, monkeypatch):
    from types import SimpleNamespace

    def fake_chat(messages, tools=None, **kwargs):
        # 模拟模型直接给出文本回复（不调用工具）
        assert any(m["role"] == "user" for m in messages)  # 用户消息确实传入
        return SimpleNamespace(choices=[
            SimpleNamespace(message=SimpleNamespace(content="（模拟）好的，已收到！", tool_calls=None))
        ])

    monkeypatch.setattr("core.llm.chat", fake_chat)

    r = client.post("/api/chat/send",
                    json={"message": "你好", "user_id": 1, "project_id": None})
    assert r.status_code == 200
    assert r.json()["reply"] == "（模拟）好的，已收到！"

    # user + assistant 两条均已落库
    history = client.get("/api/chat/history?user_id=1").json()
    roles = [m["role"] for m in history]
    assert roles[-2:] == ["user", "assistant"]


def test_chat_history_project_isolation(client, monkeypatch):
    """回归：绑定不同项目对话，历史必须按项目隔离，不得互相串扰。"""
    from types import SimpleNamespace

    def fake_chat(messages, tools=None, **kwargs):
        return SimpleNamespace(choices=[
            SimpleNamespace(message=SimpleNamespace(content="模拟回复", tool_calls=None))
        ])

    monkeypatch.setattr("core.llm.chat", fake_chat)

    pa = _new_project(client, "隔离项目A")
    pb = _new_project(client, "隔离项目B")

    for pid, msg in [(pa["id"], "A 项目的问题"), (pb["id"], "B 项目的问题")]:
        r = client.post("/api/chat/send", json={"message": msg, "user_id": 1, "project_id": pid})
        assert r.status_code == 200

    # A 项目历史只含 A 的消息（user+assistant 各一条）
    ha = client.get(f"/api/chat/history?user_id=1&project_id={pa['id']}").json()
    assert [m["content"] for m in ha] == ["A 项目的问题", "模拟回复"]

    # B 项目历史只含 B 的消息
    hb = client.get(f"/api/chat/history?user_id=1&project_id={pb['id']}").json()
    assert [m["content"] for m in hb] == ["B 项目的问题", "模拟回复"]

    # 未绑定（全部）应同时含两者
    hall = client.get("/api/chat/history?user_id=1").json()
    contents = [m["content"] for m in hall]
    assert "A 项目的问题" in contents and "B 项目的问题" in contents


# ---------- 绑定项目下的确定性路由（规划直行 / 跨项目拦截） ----------

def test_chat_bound_plan_goes_to_bound_project(client, monkeypatch):
    """回归：绑定项目时说「帮我规划几个任务」，任务必须 100% 落在绑定项目，
    不再反问/串扰（plan_tasks 内部的 LLM 只负责生成任务清单，落点由代码锁定）。"""
    from types import SimpleNamespace

    def fake_chat_text(messages, **kwargs):
        assert any(m["role"] == "user" for m in messages)
        return ('[{"title":"规划任务甲","description":"desc","priority":"high"},'
                '{"title":"规划任务乙","description":"desc","priority":"medium"}]')

    monkeypatch.setattr("core.llm.chat_text", fake_chat_text)

    pa = _new_project(client, "路由A项目")
    pb = _new_project(client, "路由B项目")

    r = client.post("/api/chat/send",
                    json={"message": "帮我规划几个任务", "user_id": 1, "project_id": pb["id"]})
    assert r.status_code == 200
    reply = r.json()["reply"]
    assert "路由B项目" in reply and "规划任务甲" in reply

    # 任务落在绑定项目 B，A 不受影响
    tb = client.get(f"/api/tasks?project_id={pb['id']}").json()
    ta = client.get(f"/api/tasks?project_id={pa['id']}").json()
    assert {t["title"] for t in tb} == {"规划任务甲", "规划任务乙"}
    assert tb and all(t["status"] == "todo" for t in tb)  # 规划任务统一默认待办
    assert ta == []


def test_chat_bound_blocks_other_project_plan(client, monkeypatch):
    """回归：绑定 A 却说「给 B 规划任务」→ 必须拦截并提示先切换，绝不在 A 下建任务。"""
    pa = _new_project(client, "绑定A项目")
    pb = _new_project(client, "绑定B项目")

    r = client.post("/api/chat/send",
                    json={"message": f"帮「{pb['name']}」规划几个任务", "user_id": 1,
                          "project_id": pa["id"]})
    assert r.status_code == 200
    reply = r.json()["reply"]
    assert "切换" in reply and pb["name"] in reply
    assert "已为" not in reply  # 未触发规划
    # 拦截路径也应返回 guard 轨迹，让用户看到"Agent 做了什么"
    assert r.json()["trace"][0]["tool"] == "guard"

    # 两个项目都不应有新任务
    assert client.get(f"/api/tasks?project_id={pa['id']}").json() == []
    assert client.get(f"/api/tasks?project_id={pb['id']}").json() == []


# ---------- 看板「一键规划」接口（POST /api/projects/{id}/plan） ----------

def test_project_plan_endpoint(client, monkeypatch):
    """新建项目勾选「AI 自动规划」→ 规划接口把任务建到该项目，统一默认待办。"""
    def fake_chat_text(messages, **kwargs):
        assert any(m["role"] == "user" for m in messages)
        return ('[{"title":"一键规划任务甲","description":"d","priority":"high"},'
                '{"title":"一键规划任务乙","description":"d","priority":"low"}]')

    monkeypatch.setattr("core.llm.chat_text", fake_chat_text)

    p = _new_project(client, "一键规划项目")
    r = client.post(f"/api/projects/{p['id']}/plan", params={"user_id": 1})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["planned"] == 2
    assert data["note"] and "待办" in data["note"]

    tasks = client.get(f"/api/tasks?project_id={p['id']}").json()
    assert {t["title"] for t in tasks} == {"一键规划任务甲", "一键规划任务乙"}
    assert tasks and all(t["status"] == "todo" for t in tasks)

    # 项目不存在 → 404
    r404 = client.post("/api/projects/999999/plan", params={"user_id": 1})
    assert r404.status_code == 404


# ---------- Agent 执行轨迹（trace） ----------

def test_chat_plan_returns_trace_and_persists(client, monkeypatch):
    """绑定项目规划：/send 返回 plan_tasks 轨迹步骤，且历史消息可回放同一 trace。"""
    def fake_chat_text(messages, **kwargs):
        return '[{"title":"轨迹任务甲","description":"d","priority":"medium"}]'

    monkeypatch.setattr("core.llm.chat_text", fake_chat_text)
    p = _new_project(client, "轨迹项目A")

    r = client.post("/api/chat/send",
                    json={"message": "帮我规划几个任务", "user_id": 1, "project_id": p["id"]})
    assert r.status_code == 200
    data = r.json()
    assert data["trace"] and data["trace"][0]["tool"] == "plan_tasks"
    step = data["trace"][0]
    assert step["ok"] is True and len(step.get("refs", [])) == 1
    assert step["refs"][0]["kind"] == "task"

    # 历史接口中该条 assistant 消息的 trace 同样可解析回放
    hist = client.get(f"/api/chat/history?user_id=1&project_id={p['id']}").json()
    asst = [m for m in hist if m["role"] == "assistant"][-1]
    assert asst["trace"] and asst["trace"][0]["tool"] == "plan_tasks"


def test_chat_agent_tool_loop_records_trace(client, monkeypatch):
    """未绑定走 Agent 工具循环：dispatch 自动记录工具步骤与受影响实体引用。"""
    from types import SimpleNamespace

    calls = {"n": 0}

    def fake_chat(messages, tools=None, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            tc = SimpleNamespace(
                id="call_1", type="function",
                function=SimpleNamespace(
                    name="create_project",
                    arguments='{"name": "轨迹工具项目", "description": "trace"}'))
            return SimpleNamespace(choices=[
                SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[tc]))])
        return SimpleNamespace(choices=[
            SimpleNamespace(message=SimpleNamespace(content="已创建项目", tool_calls=None))])

    monkeypatch.setattr("core.llm.chat", fake_chat)

    r = client.post("/api/chat/send", json={"message": "帮我创建一个项目", "user_id": 1})
    assert r.status_code == 200
    steps = r.json()["trace"]
    assert any(s["tool"] == "create_project" and s["ok"] for s in steps)
    refs = [rf for s in steps for rf in s.get("refs", [])]
    assert any(rf["kind"] == "project" for rf in refs)


# ---------- 「加 N 个任务没给明细」→ 追问，绝不自动规划 ----------

def test_chat_bound_ask_details_when_no_content(client):
    """绑定项目时说「帮我加两个任务」但没给内容 → 追问，且不创建任何任务（不误触发规划）。"""
    pa = _new_project(client, "追问项目A")

    r = client.post("/api/chat/send",
                    json={"message": "帮我加两个任务", "user_id": 1, "project_id": pa["id"]})
    assert r.status_code == 200
    reply = r.json()["reply"]
    assert "没给任务内容" in reply or "请把要添加的任务" in reply
    assert "规划" not in reply or "不会自动规划" in reply
    assert r.json()["trace"][0]["tool"] == "ask"
    # 项目里不应多出任务
    assert client.get(f"/api/tasks?project_id={pa['id']}").json() == []


def test_chat_unbound_ask_details_and_project(client):
    """未绑定 + 「加两个任务」且没点名项目 → 追问项目与内容，两个维度都不让模型猜。"""
    r = client.post("/api/chat/send", json={"message": "加两个任务", "user_id": 1})
    assert r.status_code == 200
    reply = r.json()["reply"]
    assert "哪个项目" in reply and "①" in reply
    assert r.json()["trace"][0]["tool"] == "ask"


def test_chat_task_add_with_details_still_creates(client, monkeypatch):
    """给了明细（「任务：」+ 内容）不被拦截，照常走工具逐个创建（防误伤回归）。"""
    from types import SimpleNamespace

    calls = {"n": 0}

    def fake_chat(messages, tools=None, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            tc = SimpleNamespace(
                id="call_1", type="function",
                function=SimpleNamespace(
                    name="create_task",
                    arguments='{"title": "登录页性能优化", "priority": "high"}'))
            return SimpleNamespace(choices=[
                SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[tc]))])
        return SimpleNamespace(choices=[
            SimpleNamespace(message=SimpleNamespace(content="已创建任务", tool_calls=None))])

    monkeypatch.setattr("core.llm.chat", fake_chat)

    pa = _new_project(client, "明细项目A")
    r = client.post("/api/chat/send",
                    json={"message": "加两个任务：① 登录页优化 ② 支付修复",
                          "user_id": 1, "project_id": pa["id"]})
    assert r.status_code == 200
    tasks = client.get(f"/api/tasks?project_id={pa['id']}").json()
    assert len(tasks) == 1  # mock 只建 1 条（明细路径未被 ask 拦截）


# ---------- 删除/编辑能力（delete_task / update_task_fields / delete_project） ----------

def _mock_tool_chat(monkeypatch, first_tool, first_args, final_text="完成"):
    """打桩 LLM：第一次返回指定工具调用，第二次返回收尾文本。"""
    from types import SimpleNamespace

    calls = {"n": 0}

    def fake_chat(messages, tools=None, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            tc = SimpleNamespace(
                id="call_1", type="function",
                function=SimpleNamespace(name=first_tool,
                                         arguments=json.dumps(first_args, ensure_ascii=False)))
            return SimpleNamespace(choices=[
                SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[tc]))])
        return SimpleNamespace(choices=[
            SimpleNamespace(message=SimpleNamespace(content=final_text, tool_calls=None))])

    monkeypatch.setattr("core.llm.chat", fake_chat)
    return calls


def test_chat_delete_task_tool(client, monkeypatch):
    """说「删掉任务」→ 模型调 delete_task，任务真正删除且轨迹/引用正常。"""
    import json
    p = _new_project(client, "删除工具项目")
    t = _new_task(client, p["id"], "待删除任务")
    _mock_tool_chat(monkeypatch, "delete_task", {"task_id": t["id"]}, "已删除")

    r = client.post("/api/chat/send", json={"message": "删掉那个任务", "user_id": 1})
    assert r.status_code == 200
    steps = r.json()["trace"]
    assert any(s["tool"] == "delete_task" and s["ok"] for s in steps)
    # 任务确实已删除
    assert client.get(f"/api/tasks/{t['id']}").status_code == 404


def test_chat_update_task_fields_tool(client, monkeypatch):
    """说「把任务调成高优先级」→ update_task_fields 只更新目标字段。"""
    import json
    p = _new_project(client, "编辑工具项目")
    t = _new_task(client, p["id"], "待调级任务")
    _mock_tool_chat(monkeypatch, "update_task_fields",
                    {"task_id": t["id"], "priority": "high"}, "已调为高优先级")

    r = client.post("/api/chat/send", json={"message": "把这个任务调成高优先级", "user_id": 1})
    assert r.status_code == 200
    steps = r.json()["trace"]
    assert any(s["tool"] == "update_task_fields" and s["ok"] for s in steps)
    got = client.get(f"/api/tasks/{t['id']}").json()
    assert got["priority"] == "high"


def test_chat_delete_project_tool(client, monkeypatch):
    """说「删除 XX 项目」→ delete_project 级联删除。"""
    import json
    p = _new_project(client, "待删项目")
    _mock_tool_chat(monkeypatch, "delete_project", {"project_id": p["id"]}, "已删除")

    r = client.post("/api/chat/send", json={"message": "删除该项目", "user_id": 1})
    assert r.status_code == 200
    steps = r.json()["trace"]
    assert any(s["tool"] == "delete_project" and s["ok"] for s in steps)
    assert client.get(f"/api/projects/{p['id']}").status_code == 404


def test_chat_bound_conflict_on_delete_other_project(client):
    """绑定 A 却说「删 B 的任务」→ 拦截，两个项目都不动。"""
    pa = _new_project(client, "删除拦截A")
    pb = _new_project(client, "删除拦截B")
    tb = _new_task(client, pb["id"], "B项目任务")

    r = client.post("/api/chat/send",
                    json={"message": f"把「{pb['name']}」的项目任务删掉", "user_id": 1,
                          "project_id": pa["id"]})
    assert r.status_code == 200
    assert "切换" in r.json()["reply"]
    assert r.json()["trace"][0]["tool"] == "guard"
    # B 的任务还在
    assert client.get(f"/api/tasks/{tb['id']}").status_code == 200
