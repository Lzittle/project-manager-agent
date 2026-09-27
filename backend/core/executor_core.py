"""核心工具：项目 / 任务 / 知识库（一个职责一块，见 D-025）。"""
import json
from datetime import datetime
from typing import Any, Optional

from core import llm
from core.rag import search as rag_search
from core.utils import PRI_CN, brief_error, clip
from models.database import (SessionLocal, Project, Task, PlanRun, AssignmentRun,
                             KnowledgeDocument, Member)
from services import knowledge_service, member_service, project_service, task_service


class _CoreToolMixin:
    def __init__(self, user_id: int, project_id: Optional[int] = None,
                 readonly: bool = False):
        self.user_id = user_id
        self.project_id = project_id
        self.readonly = readonly
        # 本轮会话的执行轨迹（Agent 感可见化）：每执行一个工具记一条
        self.last_trace: list[dict] = []
        # 缓存绑定项目名：注入 system prompt，防止模型引用错项目名
        self.project_name: Optional[str] = None
        if project_id is not None:
            db = SessionLocal()
            try:
                p = db.get(Project, project_id)
                self.project_name = p.name if p else None
            finally:
                db.close()

    def _project_brief(self, p) -> dict:
        return {"id": p.id, "name": p.name, "description": p.description,
                "status": p.status, "task_count": len(p.tasks)}

    def _task_brief(self, t, assignee_name: Optional[str] = None) -> dict:
        """任务瘦身版（给模型看的）：只留"找 id / 看状态 / 认人"要用的字段。

        刻意不带 description —— 一条描述动辄上百字，模型在选任务、报进度时用不上，
        却会成倍推高每一轮 token（Anthropic《Writing effective tools for agents》的原则：
        工具返回要有意义、要对 token 友好）。
        """
        d = {"id": t.id, "title": t.title, "status": t.status, "priority": t.priority}
        if assignee_name:
            d["assignee"] = assignee_name
        return d

    def list_projects(self) -> dict:
        db = SessionLocal()
        try:
            data = [self._project_brief(p)
                    for p in project_service.list_projects(db, self.user_id)]
            return {"ok": True, "data": data}
        finally:
            db.close()

    def create_project(self, name: str, description: str = "") -> dict:
        db = SessionLocal()
        try:
            p = project_service.create_project(db, self.user_id, name, description)
            return {"ok": True, "data": {"id": p.id, "name": p.name, "status": p.status}}
        finally:
            db.close()

    def list_tasks(self, project_id: Optional[int] = None, status: Optional[str] = None,
                   limit: Optional[int] = None, offset: int = 0) -> dict:
        """列任务：默认最多 40 条，可按状态过滤、可翻页。

        返回里带 total / shown：模型据此知道"还有没有没看到的"，需要时自己带 offset 再查，
        而不是一次把几百条任务灌进上下文。
        """
        pid = project_id or self.project_id
        if pid is None:
            return {"ok": False, "error": "未指定项目：请先绑定项目或在话术中说明项目名称"}
        db = SessionLocal()
        try:
            rows = task_service.list_tasks(db, pid)  # 已按 id 倒序（新的在前）
            if status in ("todo", "doing", "done"):
                rows = [t for t in rows if t.status == status]
            total = len(rows)
            cap = max(1, min(int(limit or self.TASK_LIST_LIMIT), self.TASK_LIST_MAX))
            off = max(0, int(offset or 0))
            page = rows[off:off + cap]
            ids = {t.assignee_id for t in page if t.assignee_id}
            names = {}
            if ids:
                names = {m.id: m.name
                         for m in db.query(Member).filter(Member.id.in_(ids)).all()}
            data = [self._task_brief(t, names.get(t.assignee_id)) for t in page]
            res = {"ok": True, "data": data, "total": total, "shown": len(data)}
            if off + len(data) < total:
                res["note"] = (f"共 {total} 条，本次回了 {len(data)} 条（offset={off}）；"
                               "需要更多请带 offset 再查，或按 status 过滤")
            return res
        finally:
            db.close()

    def project_snapshot(self, project_id: Optional[int] = None) -> dict:
        """读取项目当前真实状态快照（含依赖与风险），供注入上下文让模型基于数据作答。

        区别于 list_tasks 的平铺列表：这里给模型的是「一句话能看懂」的汇总——
        各状态数量、未完成高优任务、被阻塞/依赖未就绪的任务。全部来自数据库，模型不可编造。
        """
        pid = project_id or self.project_id
        if pid is None:
            return {"ok": False, "error": "未指定项目"}
        db = SessionLocal()
        try:
            p = db.get(Project, pid)
            if p is None:
                return {"ok": False, "error": f"项目 {pid} 不存在"}
            tasks = task_service.list_tasks(db, pid)
            dep_rows = task_service.list_project_dependencies(db, pid)
            by_status: dict[str, list[dict]] = {"todo": [], "doing": [], "done": []}
            high_open = []  # 未完成的高优任务
            for t in tasks:
                b = self._task_brief(t)
                by_status.setdefault(t.status, []).append(b)
                if t.status != "done" and t.priority == "high":
                    high_open.append(b["title"])
            # 被依赖阻塞：前置任务未 done 的任务（自己也没 done）
            dep_by_task: dict[int, list[dict]] = {}
            for d in dep_rows:
                dep_by_task.setdefault(d["task_id"], []).append(d)
            blocked = []
            for d in dep_rows:
                if d["depends_on_status"] != "done":
                    blocked.append({
                        "task": d["task_title"],
                        "waiting_on": d["depends_on_title"],
                        "pre_status": d["depends_on_status"],
                    })
            return {
                "ok": True,
                "data": {
                    "project": {"id": p.id, "name": p.name,
                                "status": p.status, "description": p.description},
                    "task_count": len(tasks),
                    "by_status": {k: len(v) for k, v in by_status.items()},
                    # 任务明细（供只读问答直接点名作答，不必再让模型自己查一遍）
                    "tasks": [self._task_brief(t) for t in tasks[:30]],
                    "tasks_truncated": max(0, len(tasks) - 30),
                    "done_ratio": round(len(by_status["done"]) / len(tasks), 2) if tasks else 0.0,
                    "high_open": high_open[:10],
                    "blocked": blocked[:10],
                    "dependencies": len(dep_rows),
                },
            }
        finally:
            db.close()

    def create_task(self, project_id: Optional[int] = None, title: str = "",
                    description: str = "", status: str = "todo",
                    priority: str = "medium") -> dict:
        # project_id 未提供时回落到当前绑定项目
        pid = project_id or self.project_id
        if pid is None:
            return {"ok": False, "error": "未指定项目：请先绑定项目或在话术中说明项目名称"}
        db = SessionLocal()
        try:
            t = task_service.create_task(
                db, pid, self.user_id, title,
                description=description, status=status, priority=priority)
            if t is None:
                return {"ok": False, "error": f"项目 {pid} 不存在"}
            return {"ok": True, "data": {"id": t.id, "title": t.title,
                                         "project_id": pid, "status": t.status}}
        finally:
            db.close()

    def update_task_status(self, task_id: int, status: str) -> dict:
        db = SessionLocal()
        try:
            t = task_service.update_task(db, task_id, status=status)
            if t is None:
                return {"ok": False, "error": f"任务 {task_id} 不存在"}
            return {"ok": True, "data": {"id": t.id, "title": t.title, "status": t.status,
                                         "project_id": t.project_id}}
        finally:
            db.close()

    def delete_task(self, task_id: int) -> dict:
        """删除任务（级联删除评论）。"""
        db = SessionLocal()
        try:
            snap = task_service.delete_task(db, task_id)
            if snap is None:
                return {"ok": False, "error": f"任务 {task_id} 不存在"}
            return {"ok": True, "data": {"id": snap["id"], "title": snap["title"],
                                         "project_id": snap["project_id"]}}
        finally:
            db.close()

    def delete_project(self, project_id: int) -> dict:
        """删除项目（级联任务/评论/文档与向量）。"""
        db = SessionLocal()
        try:
            snap = project_service.delete_project(db, project_id)
            if snap is None:
                return {"ok": False, "error": f"项目 {project_id} 不存在"}
            return {"ok": True, "data": {"id": snap["id"], "name": snap["name"],
                                         "status": snap["status"]}}
        finally:
            db.close()

    def update_task_fields(self, task_id: int, title: Optional[str] = None,
                           description: Optional[str] = None,
                           status: Optional[str] = None,
                           priority: Optional[str] = None) -> dict:
        """更新任务的标题/描述/状态/优先级（只更新调用方提供的字段）。"""
        fields: dict[str, str] = {}
        if title is not None:
            if not str(title).strip():
                return {"ok": False, "error": "任务标题不能为空"}
            fields["title"] = str(title).strip()[:200]
        if description is not None:
            fields["description"] = str(description).strip()[:500]
        if status is not None:
            if status not in ("todo", "doing", "done"):
                return {"ok": False, "error": f"非法状态 {status}（todo/doing/done）"}
            fields["status"] = status
        if priority is not None:
            if priority not in ("high", "medium", "low"):
                return {"ok": False, "error": f"非法优先级 {priority}（high/medium/low）"}
            fields["priority"] = priority
        if not fields:
            return {"ok": False, "error": "未提供任何要更新的字段（title/description/status/priority）"}
        db = SessionLocal()
        try:
            t = task_service.update_task(db, task_id, **fields)
            if t is None:
                return {"ok": False, "error": f"任务 {task_id} 不存在"}
            return {"ok": True, "data": {"id": t.id, "title": t.title, "status": t.status,
                                         "priority": t.priority, "project_id": t.project_id}}
        finally:
            db.close()

    def update_project_fields(self, project_id: int, name: Optional[str] = None,
                              description: Optional[str] = None) -> dict:
        """更新项目的名称/描述。"""
        fields: dict[str, str] = {}
        if name is not None:
            if not str(name).strip():
                return {"ok": False, "error": "项目名称不能为空"}
            fields["name"] = str(name).strip()[:100]
        if description is not None:
            fields["description"] = str(description).strip()[:500]
        if not fields:
            return {"ok": False, "error": "未提供任何要更新的字段（name/description）"}
        db = SessionLocal()
        try:
            p = project_service.update_project(db, project_id, **fields)
            if p is None:
                return {"ok": False, "error": f"项目 {project_id} 不存在"}
            return {"ok": True, "data": {"id": p.id, "name": p.name,
                                         "description": p.description, "status": p.status}}
        finally:
            db.close()

    def search_knowledge(self, query: str, project_id: Optional[int] = None) -> dict:
        pid = project_id or self.project_id
        try:
            hits = rag_search(query, project_id=pid, top_k=3)
            if not hits:
                return {"ok": True, "data": [],
                        "note": "未检索到相关文档片段，可如实告知用户知识库暂无相关内容"}
            return {"ok": True, "data": [
                {"title": h["title"], "text": h["text"][:500]} for h in hits]}
        except Exception as e:  # embedding 模型未就绪等场景
            return {"ok": False,
                    "error": "知识库检索失败：" + brief_error(e, "稍后重试；也可以直接说任务明细")}

    def save_meeting(self, title: str, content: str,
                     project_id: Optional[int] = None) -> dict:
        """把对话结论整理成会议纪要入库（doc_type=meeting，自动向量化进项目长期记忆）。"""
        pid = project_id or self.project_id
        if pid is None:
            return {"ok": False, "error": "未指定项目：请先绑定项目或在话术中说明项目名称"}
        t = (title or "").strip()
        if not t:
            return {"ok": False, "error": "纪要标题不能为空"}
        db = SessionLocal()
        try:
            doc = knowledge_service.create_document(
                db, pid, t[:200], (content or "").strip(), file_type="txt", doc_type="meeting")
            if doc is None:
                return {"ok": False, "error": f"项目 {pid} 不存在"}
            return {"ok": True,
                    "data": {"id": doc.id, "title": doc.title,
                             "doc_type": doc.doc_type, "project_id": pid},
                    "note": "已作为会议纪要存入项目知识库（自动向量化），"
                            "之后问「上次怎么定的」即可自动检索到"}
        finally:
            db.close()

