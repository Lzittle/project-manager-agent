"""小队成员与指派：名册、指派、按名单拟方案与落库（D-017 / D-018 / D-019 / D-025）。"""
import json
from typing import Optional

from core import llm
from core.utils import PRI_CN
from models.database import (SessionLocal, Task, KnowledgeDocument, AssignmentRun)
from services import member_service, task_service


class _TeamToolMixin:
    # ---------- 小队成员与指派（D-017 / D-018 / D-019） ----------
    def list_members(self) -> dict:
        """名册（已注册在前、待认领在后）。指派前用它把人匹配到 member_id。"""
        db = SessionLocal()
        try:
            rows = member_service.list_members(db)
            return {"ok": True, "data": [
                {"id": m.id, "name": m.name, "status": m.status,
                 "user_id": m.user_id, "invite_code": m.invite_code} for m in rows]}
        finally:
            db.close()

    def create_member(self, name: str) -> dict:
        """把一个名字加进名册（占位成员 + 邀请码）。同名不合并，让上层问人。"""
        n = (name or "").strip()
        if not n:
            return {"ok": False, "error": "成员名字不能为空"}
        db = SessionLocal()
        try:
            same = member_service.find_by_name(db, n)
            if same:
                return {"ok": False,
                        "error": f"名册里已有同名成员（id: {', '.join(str(m.id) for m in same)}）："
                                 "请先确认是不是同一个人，不要重复添加"}
            m = member_service.create_member(db, n)
            return {"ok": True,
                    "data": {"id": m.id, "name": m.name, "status": m.status,
                             "invite_code": m.invite_code},
                    "note": f"「{m.name}」已进名册（待认领），邀请码 {m.invite_code}；"
                            "把邀请码发给 TA，注册后即可认领这条身份"}
        finally:
            db.close()

    def assign_task(self, task_id: int, member_id: int) -> dict:
        """把任务指派给成员：只改负责人，不改状态（D-005）。"""
        db = SessionLocal()
        try:
            t = task_service.get_task(db, task_id)
            if t is None:
                return {"ok": False, "error": f"任务 {task_id} 不存在"}
            m = member_service.get_member(db, member_id)
            if m is None:
                return {"ok": False,
                        "error": f"成员 {member_id} 不在名册里（先用 list_members 查，或用 create_member 建人）"}
            if self.project_id is not None and t.project_id != self.project_id:
                return {"ok": False, "error": "该任务不在当前绑定的项目里，已拒绝跨项目指派"}
            t = task_service.update_task(db, task_id, assignee_id=m.id)
            return {"ok": True,
                    "data": {"id": t.id, "title": t.title, "status": t.status,
                             "project_id": t.project_id, "assignee_id": m.id,
                             "assignee_name": m.name, "assignee_status": m.status},
                    "note": f"负责人已改为「{m.name}」"
                            + ("（占位成员，等 TA 注册后认领）" if m.status != "active" else "")
                            + "；任务状态保持不变"}
        finally:
            db.close()

    # ---------- 读名单 → 认人 → 分配方案（轮 2，D-017） ----------
    ROSTER_CHARS = 6000  # 名单一般不长；截断防止把整篇长文塞进提示词

    @classmethod
    def _roster_text(cls, doc) -> str:
        return (doc.content or "").strip()[:cls.ROSTER_CHARS]

    @staticmethod
    def _normalize_assign_items(raw, tasks, members) -> list[dict]:
        """把模型输出规范成可核对、可落库的条目。

        认人规则（D-017「不许猜」）：
          - task_id 必须命中本次给出的任务清单；
          - 名字在名册里唯一命中 → 记 member_id；
          - 一条都没命中 → needs_create=True（确认后建占位成员）；
          - 命中多条 → ambiguous=True（落库时跳过，请人来定）。
        """
        by_name: dict[str, list] = {}
        for m in members:
            by_name.setdefault(m.name, []).append(m)
        valid_ids = {t.id for t in tasks}
        raw_items = raw if isinstance(raw, list) else (raw.get("items") if isinstance(raw, dict) else [])
        out, seen = [], set()
        for item in raw_items or []:
            if not isinstance(item, dict):
                continue
            try:
                tid = int(item.get("task_id"))
            except (TypeError, ValueError):
                continue
            name = str(item.get("member_name") or "").strip()
            if tid not in valid_ids or tid in seen or not name:
                continue
            seen.add(tid)
            hits = by_name.get(name, [])
            out.append({"task_id": tid, "member_name": name,
                        "reason": str(item.get("reason") or "").strip()[:40],
                        "member_id": hits[0].id if len(hits) == 1 else None,
                        "needs_create": len(hits) == 0,
                        "ambiguous": len(hits) > 1})
        return out

    @staticmethod
    def _assign_markdown(plan_id: int, doc_title: str, items: list[dict]) -> str:
        """把方案拼成给用户看的表格（不依赖模型二次生成，避免它改数）。"""
        lines = ["| 任务 | 负责人 | 依据 |", "| --- | --- | --- |"]
        for it in items:
            who = it["member_name"]
            if it.get("ambiguous"):
                who += "（名册里有重名，待你定）"
            elif it.get("needs_create"):
                who += "（名册没有，确认后建占位成员）"
            lines.append(f"| #{it['task_id']} {it['title']} | {who} | {it.get('reason', '')} |")
        return (f"我按《{doc_title}》拟了一份分配方案（方案 #{plan_id}，**还没落库**）：\n\n"
                + "\n".join(lines)
                + "\n\n确认就说「就按这个来」；要改就说「第 #39 条改成李工」。")

    def plan_assignment_from_doc(self, doc_id: Optional[int] = None,
                                 project_id: Optional[int] = None) -> dict:
        """读名单资料 → 认人 → 拟「任务 → 负责人」方案（**不写库**，D-017）。"""
        pid = project_id or self.project_id
        if pid is None:
            return {"ok": False, "error": "未指定项目：请先绑定项目或在话术中说明项目名称"}
        db = SessionLocal()
        try:
            if doc_id is not None:
                doc = db.get(KnowledgeDocument, doc_id)
                if doc is None or doc.project_id != pid:
                    return {"ok": False, "error": f"资料 {doc_id} 不在项目 {pid} 里"}
            else:
                doc = (db.query(KnowledgeDocument)
                       .filter(KnowledgeDocument.project_id == pid)
                       .order_by(KnowledgeDocument.id.desc()).first())
            if doc is None:
                return {"ok": False,
                        "error": "这个项目还没有上传任何资料：先把「相关人员说明/名单」传到资产库，我再来读"}
            tasks = (db.query(Task)
                     .filter(Task.project_id == pid, Task.status != "done")
                     .order_by(Task.id).limit(40).all())
            if not tasks:
                return {"ok": False,
                        "error": "这个项目还没有未完成的任务：先规划或创建任务，再来分配"}
            members = member_service.list_members(db)
            roster_line = "、".join(
                f"{m.name}（{'已注册' if m.status == 'active' else '待认领'}）"
                for m in members) or "（名册还是空的）"
            task_lines = "\n".join(
                f"#{t.id} {t.title}（优先级 {PRI_CN.get(t.priority, t.priority)}）" for t in tasks)

            try:
                parsed, jerr = llm.chat_json([
                    {"role": "system", "content":
                     "你是小队的分工助手：根据【人员说明】把【未完成任务】分配给最合适的人。\n"
                     "规则：\n"
                     "1) 只能从【人员说明】里出现过的人里选，不要凭空造人；\n"
                     "2) 负责人的职责/角色要跟任务匹配；实在匹配不上就别分配（宁缺毋滥）；\n"
                     "3) 只输出 JSON 数组，每项形如 "
                     "{\"task_id\": 数字, \"member_name\": \"人员说明里的名字\", \"reason\": \"不超过 20 字\"}；\n"
                     "4) 同一个任务最多出现一次。"},
                    {"role": "user", "content":
                     f"【人员说明（来自资产库《{doc.title}》）】\n{self._roster_text(doc)}\n\n"
                     f"【已在小队名册里的人】{roster_line}\n\n"
                     f"【未完成任务】\n{task_lines}"},
                ], temperature=0.2, max_tokens=1500)
            except Exception as e:
                return {"ok": False,
                        "error": "读名单失败：" + brief_error(e, "确认资料已上传、模型可用，再试一次")}
            if jerr is not None:
                return {"ok": False, "error": f"方案生成失败（模型输出无法解析：{jerr}）"}

            items = self._normalize_assign_items(parsed, tasks, members)
            if not items:
                return {"ok": False,
                        "error": "没能从这份资料里配出可用的分配（人名和任务对不上）：可以把名单写得更明确些，"
                                 "或者直接说「把 #39 派给陈工」"}
            titles = {t.id: t.title for t in tasks}
            for it in items:
                it["title"] = titles.get(it["task_id"], "")
            run = AssignmentRun(project_id=pid, user_id=self.user_id, doc_id=doc.id,
                                items=json.dumps(items, ensure_ascii=False), status="pending")
            db.add(run)
            db.commit()
            db.refresh(run)
            return {"ok": True, "data": items, "plan_id": run.id,
                    "markdown": self._assign_markdown(run.id, doc.title, items),
                    "note": "这是**待确认**的方案，还没写库；用户确认后再调 apply_assignment"}
        finally:
            db.close()

    def apply_assignment(self, plan_id: Optional[int] = None,
                         overrides: Optional[list] = None) -> dict:
        """把待确认的方案落库：缺的人建占位成员，逐条写 assignee_id（D-017）。"""
        db = SessionLocal()
        try:
            if plan_id:
                run = db.get(AssignmentRun, plan_id)
            else:
                q = db.query(AssignmentRun).filter_by(user_id=self.user_id, status="pending")
                if self.project_id is not None:
                    q = q.filter(AssignmentRun.project_id == self.project_id)
                run = q.order_by(AssignmentRun.id.desc()).first()
            if run is None:
                return {"ok": False, "error": "没有待确认的分配方案：先让我「按名单分配」一次"}
            if run.status != "pending":
                return {"ok": False, "error": f"方案 #{run.id} 已经落过库了"}
            if self.project_id is not None and run.project_id != self.project_id:
                return {"ok": False, "error": "这份方案不属于当前绑定的项目，已拒绝"}

            items = json.loads(run.items or "[]")
            fixed: dict[int, str] = {}
            for ov in overrides or []:
                if isinstance(ov, dict) and ov.get("task_id") is not None and ov.get("member_name"):
                    try:
                        fixed[int(ov["task_id"])] = str(ov["member_name"]).strip()
                    except (TypeError, ValueError):
                        continue

            applied, skipped, created = [], [], []
            for it in items:
                task = db.get(Task, it.get("task_id"))
                if task is None:
                    skipped.append(f"#{it.get('task_id')}（任务已不存在）")
                    continue
                name = fixed.get(it["task_id"], it["member_name"])
                hits = member_service.find_by_name(db, name)
                if len(hits) > 1:
                    skipped.append(f"「{task.title}」（「{name}」在名册里有 {len(hits)} 个人，重名没敢猜）")
                    continue
                if not hits:
                    m = member_service.create_member(db, name)  # 占位成员（带邀请码）
                    created.append({"name": m.name, "invite_code": m.invite_code})
                else:
                    m = hits[0]
                task_service.update_task(db, task.id, assignee_id=m.id)
                applied.append({"id": task.id, "title": task.title, "status": task.status,
                                "assignee_id": m.id, "assignee_name": m.name})

            run.status = "applied"
            run.applied_count = len(applied)
            db.commit()
            return {"ok": True, "data": applied, "plan_id": run.id, "created_members": created,
                    "skipped": skipped,
                    "note": (f"已落库 {len(applied)} 条指派"
                             + (f"，顺手建了 {len(created)} 个占位成员（带邀请码）" if created else "")
                             + (f"；跳过 {len(skipped)} 条：{'；'.join(skipped)}" if skipped else "")
                             + "；只改了负责人，任务状态没动")}
        finally:
            db.close()

