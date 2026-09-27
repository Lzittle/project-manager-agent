"""任务规划：读项目现状 + 记忆 → 让模型产出带依赖的任务批次 → 落库（D-025）。"""
import json
import re
from datetime import datetime
from typing import Optional

from core import llm
from core.rag import search as rag_search
from core.utils import PRI_CN
from models.database import SessionLocal, Project, Task, PlanRun
from services import task_service


class _PlanToolMixin:
    # ---------- 任务自动规划（plan_tasks 工具） ----------
    @staticmethod
    def _parse_tasks(raw) -> list[dict]:
        """从模型输出中提取任务 JSON 数组。

        输入 raw 可以是字符串（由 chat_json 兜底解析失败时的兼容路径）或
        已经解析好的 list（chat_json 正常路径）。每个任务：
        {"title":..., "description":..., "priority":..., "depends_on":[前置任务下标]}
        规划期任务尚无数据库 id，依赖用「数组下标」逻辑引用，落库时映射回真实 id。
        """
        if isinstance(raw, list):
            data = raw
        elif isinstance(raw, str):
            text = raw.strip()
            m = re.search(r"\[[\s\S]*\]", text)
            if not m:
                return []
            try:
                data = json.loads(m.group(0))
            except json.JSONDecodeError:
                return []
        else:
            return []
        if not isinstance(data, list):
            return []
        out = []
        for item in data:
            if isinstance(item, dict) and item.get("title"):
                deps = item.get("depends_on")
                dep_idx = []
                if isinstance(deps, list):
                    for d in deps:
                        if isinstance(d, (int, float)) and not isinstance(d, bool):
                            dep_idx.append(int(d))
                        elif isinstance(d, str) and d.isdigit():
                            dep_idx.append(int(d))
                out.append({
                    "title": str(item["title"]).strip()[:200],
                    "description": str(item.get("description", "")).strip()[:500],
                    "priority": item.get("priority", "medium") if item.get("priority") in ("high", "medium", "low") else "medium",
                    "depends_on": sorted(set(i for i in dep_idx if i >= 0)),
                })
        return out

    def _recent_plan(self, pid: int) -> Optional[dict]:
        """窗口内该项目刚规划过 → 返回上一批复用结果；否则 None（走正常规划）。

        幂等护栏：用户以为卡住重发、连点两次「一键规划」时，第二次直接复用上一批
        任务，而不是再生成一批。上一批任务若已被删除/重置，本护栏自动失效。
        """
        db = SessionLocal()
        try:
            run = (db.query(PlanRun)
                   .filter(PlanRun.project_id == pid, PlanRun.user_id == self.user_id)
                   .order_by(PlanRun.id.desc()).first())
            if run is None or run.created_at is None:
                return None
            age = (datetime.now() - run.created_at).total_seconds()
            if age < 0 or age > self.PLAN_DEDUP_WINDOW_SEC:
                return None
            ids = json.loads(run.task_ids or "[]")
            if not ids:
                return None
            rows = {t.id: t for t in db.query(Task).filter(Task.id.in_(ids)).all()}
            ordered = [rows[i] for i in ids if i in rows]
            if not ordered:
                return None  # 上一批已被删除 → 正常规划
            minutes = max(1, int(age // 60))
            return {
                "ok": True,
                "reused": True,
                "data": [{"id": t.id, "title": t.title, "status": t.status} for t in ordered],
                "note": (f"该项目 {minutes} 分钟前刚规划过 {len(ordered)} 个任务，本次直接复用上一批、"
                         "未重复创建；如需再规划一批新任务，请说「重新规划任务」。"),
            }
        finally:
            db.close()

    def plan_tasks(self, project_id: Optional[int] = None, goal: str = "",
                   force: bool = False) -> dict:
        """上下文感知的任务规划（AI 全流程）：
        1) 读项目已有任务清单 → 已有任务则「增量补缺」，防重复生成；
        2) RAG 检索项目记忆（会议纪要/需求文档）→ 任务贴合历史决策；
        3) 数量按项目复杂度 3~8 条自适应，不再写死 5 条；
        4) 落库带 depends_on 真实依赖边。
        5) 幂等：窗口内重复触达 → 复用上一批（见 _recent_plan），force=True 可跳过。
        主题一律取项目自身名称与描述，不接受模型传入的 goal，
        避免模型受历史话术误导、给别的主题生成任务。
        """
        # project_id 未提供时回落到当前绑定项目
        pid = project_id or self.project_id
        if pid is None:
            return {"ok": False, "error": "未指定项目：请先绑定项目或在话术中说明项目名称"}

        # 0) 幂等护栏：刚规划过就直接复用上一批（force=True 跳过）
        if not force:
            reused = self._recent_plan(pid)
            if reused is not None:
                return reused

        # 1) 项目信息 + 已有任务清单 + RAG 项目记忆（一次性读取）
        db = SessionLocal()
        try:
            p = db.get(Project, pid)
            if p is None:
                return {"ok": False, "error": f"项目 {pid} 不存在"}
            project_desc = {"name": p.name, "description": p.description or "", "status": p.status}
            existing = task_service.list_tasks(db, pid)
            existing_titles = [t.title for t in existing]
            existing_count = len(existing)
        finally:
            db.close()

        # 2) RAG 检索项目记忆（会议纪要/需求文档）；失败静默降级，不影响规划
        memory_snippets = []
        try:
            hits = rag_search(project_desc["name"], project_id=pid, top_k=3)
            memory_snippets = [{"title": h["title"], "text": h["text"][:300],
                                "doc_type": h.get("doc_type", "doc")} for h in hits]
        except Exception:
            memory_snippets = []

        # 3) 组装上下文：项目描述 + 已有任务（增量防重复）+ 记忆片段
        ctx_lines = [f"项目名称：{project_desc['name']}",
                     f"项目描述：{project_desc['description'] or '（无）'}"]
        if existing_count:
            ctx_lines.append(
                "项目已有任务（规划时请勿与下列标题重复，只补充缺失/后续阶段的任务）：")
            ctx_lines += [f"  {i}. {t}" for i, t in enumerate(existing_titles, 1)]
        else:
            ctx_lines.append("项目当前没有任务：请从零规划第一批落地任务。")
        if memory_snippets:
            ctx_lines.append("项目记忆（会议纪要/文档检索命中，任务应贴合其中的决策）：")
            for m in memory_snippets:
                tag = "会议纪要" if m["doc_type"] == "meeting" else "文档"
                ctx_lines.append(f"  ·《{m['title']}》[{tag}] {m['text']}")
        else:
            ctx_lines.append("（知识库暂无相关记忆，按项目描述合理规划即可）")
        ctx = "\n".join(ctx_lines)

        # 4) 调用 LLM 生成任务规划（chat_json：JSON 结构化输出 + 解析失败自动重试）
        try:
            parsed, jerr = llm.chat_json([
                {"role": "system", "content":
                 "你是敏捷项目管理专家。基于项目上下文规划一组具体可执行的落地任务，并给出任务间的先后依赖。"
                 "任务数量不设固定值：按项目复杂度自适应（简单项目 3~4 条，中等 5~6 条，复杂 7~8 条），"
                 "项目已有任务时应增量补缺、聚焦后续阶段，禁止重复已有标题。"
                 "输出 JSON 数组，格式："
                 '[{"title":"任务标题(不超过14字)","description":"一句话描述含验收要点",'
                 '"priority":"high|medium|low","depends_on":[前置任务下标数组]}]。'
                 "依赖规则：前置任务必须已先完成，本任务才能开始；"
                 "depends_on 里填本任务依赖的前置任务在数组中的下标（从 0 开始），"
                 "无依赖则填 []；只允许依赖下标更小的任务（保持数组近似拓扑序），不允许成环。"},
                {"role": "user", "content": ctx},
            ], temperature=0.4, max_tokens=1500)
        except Exception as e:
            return {"ok": False, "error": f"任务规划生成失败: {e}"}

        # 成功时 parsed 是已解析的 list；失败时 parsed 为 None，走统一空结果分支
        tasks = self._parse_tasks(parsed if jerr is None else [])
        if not tasks:
            return {"ok": False, "error":
                    f"任务规划生成失败（模型输出无法解析：{jerr or '空结果'}），请重试或直接说明任务明细"}

        # 5) 批量落库（统一默认待办）+ 按 depends_on 下标映射建真实依赖边
        db = SessionLocal()
        try:
            created = []
            for t in tasks[:10]:  # 上限 10 条防失控，实际由模型按复杂度 3~8
                tk = task_service.create_task(
                    db, pid, self.user_id, t["title"],
                    description=t["description"], priority=t["priority"], status="todo")
                if tk:
                    created.append(tk)

            dep_created = 0
            for i, t in enumerate(tasks[:10]):
                if i >= len(created):
                    break  # 有任务创建失败则跳过其依赖（下标可能错位，安全起见不建）
                for dep_idx in t.get("depends_on", []):
                    if 0 <= dep_idx < i and dep_idx < len(created):  # 只允许依赖更小下标
                        d, ok = task_service.add_dependency(
                            db, created[i].id, created[dep_idx].id)
                        if ok:
                            dep_created += 1
            mode = "增量补充" if existing_count else "从零规划"
            db.add(PlanRun(project_id=pid, user_id=self.user_id,
                           task_ids=json.dumps([tk.id for tk in created]),
                           task_count=len(created)))
            db.commit()
            return {
                "ok": True,
                "data": [{"id": tk.id, "title": tk.title, "status": tk.status} for tk in created],
                "note": (f"{mode} {len(created)} 个任务、{dep_created} 条依赖（默认均为待办），"
                         "可在看板查看并拖拽流转状态"),
            }
        finally:
            db.close()

