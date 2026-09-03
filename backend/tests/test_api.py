"""后端 API 冒烟测试（离线可跑：LLM 调用用 monkeypatch mock，不消耗 token/不依赖网络）。"""
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
