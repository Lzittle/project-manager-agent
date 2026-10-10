"""批量动作与撤销：先方案后落库 + 一句话回滚（阶段 3，D-028）。

为什么单独一块：批量改状态、批量删除是影响面最大的一类写操作。roadmap 阶段 3 定的
规矩是「先给方案、人拍板、再落库」，落库之后还要能一句话撤销。它和「按名单分配」
是同一套节奏，但读的不是名单资料、而是任务清单，所以单独一个 mixin。

两条硬约束：
1. 方案落在 action_runs（pending），**不碰 tasks**；只有用户确认后走 apply_bulk_action。
2. 每次落库都留 undo 快照（_record_action / mark_applied），「撤销」按它回滚。
"""
import json
from datetime import datetime
from typing import Optional

from models.database import AssignmentRun, SessionLocal, Task, TaskDependency
from services import action_service, task_service

STATUS_CN = {"todo": "待办", "doing": "进行中", "done": "已完成"}
TASK_STATUS = ("todo", "doing", "done")


class _ActionToolMixin:
    # 一份方案最多列多少条：超过就让人缩小范围，避免变成「一键清库」
    BULK_MAX = 50

    # ---------- 落库台账（撤销用） ----------
    def _record_action(self, kind: str, items: list[dict], undo: list[dict],
                       project_id: Optional[int] = None) -> Optional[int]:
        """把一次已落库的写动作记进台账。失败不影响主流程（宁可不能撤销，也不能写不进去）。"""
        pid = project_id or self.project_id
        if pid is None:
            return None
        db = SessionLocal()
        try:
            run = action_service.record_applied(db, pid, self.user_id, kind, items, undo)
            return run.id
        except Exception:
            return None
        finally:
            db.close()

    @staticmethod
    def _resolve_tasks(db, pid: int, task_ids) -> tuple[list, list]:
        """把 task_id 列表解析成本项目内的任务行；返回 (命中, 不存在或不属于本项目的 id)。"""
        seen, wanted = set(), []
        for raw in task_ids or []:
            try:
                tid = int(raw)
            except (TypeError, ValueError):
                continue
            if tid not in seen:
                seen.add(tid)
                wanted.append(tid)
        rows, missing = [], []
        for tid in wanted:
            t = db.get(Task, tid)
            if t is None or t.project_id != pid:
                missing.append(tid)
            else:
                rows.append(t)
        return rows, missing

    @staticmethod
    def _dep_edges(db, task_id: int) -> int:
        """这个任务身上挂着几条依赖边（删除会一并清掉，得先让人看见）。"""
        return (db.query(TaskDependency)
                .filter((TaskDependency.task_id == task_id)
                        | (TaskDependency.depends_on_id == task_id)).count())

    @staticmethod
    def _footer(run_id: int) -> str:
        return (f"\n\n确认就说「就按这个来」（方案 #{run_id}）；要改就说「第 #39 条别动」。"
                "落库之后说一句「撤销」，我能按台账回滚。")

    @classmethod
    def _status_markdown(cls, run_id: int, items: list[dict], status: str,
                         unchanged: int, missing: list) -> str:
        lines = ["| 任务 | 现在是 | 改成 |", "| --- | --- | --- |"]
        for it in items:
            lines.append(f"| #{it['task_id']} {it['title']} | "
                         f"{STATUS_CN.get(it['from'], it['from'])} | "
                         f"{STATUS_CN.get(status, status)} |")
        extra = []
        if unchanged:
            extra.append(f"另有 {unchanged} 条本来就是这个状态，不用动")
        if missing:
            extra.append(f"{len(missing)} 个 id 不在这个项目里，已跳过（{', '.join('#' + str(i) for i in missing[:5])}）")
        head = (f"这 {len(items)} 条我打算统一改成{STATUS_CN.get(status, status)}"
                f"（方案 #{run_id}，**还没落库**）：")
        body = "\n".join(lines)
        return head + "\n\n" + body + ("\n\n" + "；".join(extra) if extra else "") + cls._footer(run_id)

    @classmethod
    def _delete_markdown(cls, run_id: int, items: list[dict], missing: list) -> str:
        lines = ["| 任务 | 当前状态 | 会一起清掉的依赖边 |", "| --- | --- | --- |"]
        for it in items:
            lines.append(f"| #{it['task_id']} {it['title']} | "
                         f"{STATUS_CN.get(it['status'], it['status'])} | {it.get('deps', 0)} 条 |")
        head = (f"这 {len(items)} 个任务我打算删掉（方案 #{run_id}，**一个字都还没删**）；"
                "删除会连带清掉它们的依赖边与评论，落库后仍可撤销：")
        extra = ""
        if missing:
            extra = (f"\n\n{len(missing)} 个 id 不在这个项目里，已跳过"
                     f"（{', '.join('#' + str(i) for i in missing[:5])}）")
        return head + "\n\n" + "\n".join(lines) + extra + cls._footer(run_id)

    # ---------- 批量改状态 ----------
    def plan_bulk_status(self, task_ids: Optional[list] = None, status: str = "",
                         project_id: Optional[int] = None) -> dict:
        """批量改状态：只拟方案、不写库（阶段 3）。"""
        pid = project_id or self.project_id
        if pid is None:
            return {"ok": False, "error": "未指定项目：请先绑定项目或在话术中说明项目名称"}
        if status not in TASK_STATUS:
            return {"ok": False, "error": f"非法状态 {status}（todo/doing/done）"}
        if not task_ids:
            return {"ok": False, "error": "要改哪些任务？先用 list_tasks 查到 id，再把 id 列表给我"}
        db = SessionLocal()
        try:
            rows, missing = self._resolve_tasks(db, pid, task_ids)
            if not rows:
                return {"ok": False, "error": "这些任务在当前项目里都没找到：先用 list_tasks 确认 id"}
            if len(rows) > self.BULK_MAX:
                return {"ok": False,
                        "error": f"一次最多拟 {self.BULK_MAX} 条：请缩小范围（比如按状态或关键任务挑）"}
            items = [{"task_id": t.id, "title": t.title, "from": t.status, "to": status}
                     for t in rows if t.status != status]
            unchanged = len(rows) - len(items)
            if not items:
                return {"ok": True, "data": [],
                        "note": f"这些任务本来就都是{STATUS_CN.get(status, status)}，没有要改的"}
            run = action_service.create_plan(db, pid, self.user_id, "bulk_status", items)
            return {"ok": True, "data": items, "plan_id": run.id,
                    "markdown": self._status_markdown(run.id, items, status, unchanged, missing),
                    "note": "这是**待确认**的批量方案，还没落库；用户确认后再调 apply_bulk_action"}
        finally:
            db.close()

    # ---------- 批量删除 ----------
    def plan_bulk_delete(self, task_ids: Optional[list] = None,
                         project_id: Optional[int] = None) -> dict:
        """批量删除：只列清单、不删任何东西（阶段 3）。"""
        pid = project_id or self.project_id
        if pid is None:
            return {"ok": False, "error": "未指定项目：请先绑定项目或在话术中说明项目名称"}
        if not task_ids:
            return {"ok": False, "error": "要删哪些任务？先用 list_tasks 查到 id，再把 id 列表给我"}
        db = SessionLocal()
        try:
            rows, missing = self._resolve_tasks(db, pid, task_ids)
            if not rows:
                return {"ok": False, "error": "这些任务在当前项目里都没找到：先用 list_tasks 确认 id"}
            if len(rows) > self.BULK_MAX:
                return {"ok": False,
                        "error": f"一次最多拟 {self.BULK_MAX} 条：请缩小范围，别一次清一库"}
            items = [{"task_id": t.id, "title": t.title, "status": t.status,
                      "deps": self._dep_edges(db, t.id)} for t in rows]
            run = action_service.create_plan(db, pid, self.user_id, "bulk_delete", items)
            return {"ok": True, "data": items, "plan_id": run.id,
                    "markdown": self._delete_markdown(run.id, items, missing),
                    "note": "这是**待确认**的删除清单，一个字都还没删；用户确认后再调 apply_bulk_action"}
        finally:
            db.close()

    # ---------- 落库 ----------
    def apply_bulk_action(self, plan_id: Optional[int] = None) -> dict:
        """把待确认的批量方案真正落库（仅在用户明确确认后调用）。"""
        db = SessionLocal()
        try:
            run = (action_service.get_run(db, plan_id) if plan_id
                   else action_service.get_pending(db, self.user_id, self.project_id))
            if run is None:
                return {"ok": False,
                        "error": "没有待确认的批量方案：先说要改哪些任务，我拟一份给你过目"}
            if run.status != "pending":
                return {"ok": False, "error": f"方案 #{run.id} 已经处理过了（{run.status}）"}
            if self.project_id is not None and run.project_id != self.project_id:
                return {"ok": False, "error": "这份方案不属于当前绑定的项目，已拒绝"}

            items = json.loads(run.items or "[]")
            undo: list[dict] = []
            applied: list[dict] = []
            skipped: list[str] = []
            if run.kind == "bulk_status":
                for it in items:
                    t = db.get(Task, it.get("task_id"))
                    if t is None or t.project_id != run.project_id:
                        skipped.append(f"#{it.get('task_id')}（任务已不存在）")
                        continue
                    before = t.status
                    if before == it.get("to"):
                        skipped.append(f"「{t.title}」已经是{STATUS_CN.get(before, before)}")
                        continue
                    t.status = it["to"]
                    db.flush()
                    undo.append(action_service.field_undo(t.id, status=before))
                    applied.append({"id": t.id, "title": t.title,
                                    "status": t.status, "from": before})
            elif run.kind == "bulk_delete":
                for it in items:
                    payload = action_service.task_restore_payload(db, it.get("task_id"))
                    if payload is None:
                        skipped.append(f"#{it.get('task_id')}（任务已不存在）")
                        continue
                    snap = task_service.delete_task(db, it["task_id"])
                    if snap is None:
                        skipped.append(f"#{it.get('task_id')}（删除失败）")
                        continue
                    undo.append(action_service.restore_undo(payload))
                    applied.append({"id": snap["id"], "title": snap["title"]})
            else:
                return {"ok": False, "error": f"方案 #{run.id} 的类型 {run.kind} 不支持批量落库"}

            action_service.mark_applied(db, run, undo, len(applied))
            note = f"已落库 {len(applied)} 条"
            if skipped:
                note += f"；跳过 {len(skipped)} 条：{'；'.join(skipped)}"
            note += "。说一句「撤销」可以回滚。"
            return {"ok": True, "kind": run.kind, "data": applied, "plan_id": run.id,
                    "applied_count": len(applied), "skipped": skipped, "note": note}
        finally:
            db.close()

    def apply_pending_action(self) -> dict:
        """确认落库的统一入口（确定性路由用）：按项目里真正待确认的那一份方案走。

        可能待确认的有两种：按名单分配的方案（AssignmentRun）和批量动作方案（ActionRun）。
        取更新的那一份 —— 用户刚看到哪份，确认的就是哪份。
        """
        db = SessionLocal()
        try:
            candidates: list[tuple] = []
            q = db.query(AssignmentRun).filter_by(user_id=self.user_id, status="pending")
            if self.project_id is not None:
                q = q.filter(AssignmentRun.project_id == self.project_id)
            a = q.order_by(AssignmentRun.id.desc()).first()
            if a is not None:
                candidates.append((a.created_at or datetime.min, "assign"))
            b = action_service.get_pending(db, self.user_id, self.project_id)
            if b is not None:
                candidates.append((b.created_at or datetime.min, "bulk"))
        finally:
            db.close()
        if not candidates:
            return {"ok": False,
                    "error": "没有待确认的方案：先让我拟一份（按名单分配，或批量改状态/删除）"}
        candidates.sort(key=lambda kv: kv[0], reverse=True)
        return self.apply_assignment() if candidates[0][1] == "assign" else self.apply_bulk_action()

    # ---------- 撤销 ----------
    def undo_last_action(self, run_id: Optional[int] = None) -> dict:
        """撤销最近一次落库的动作（指派 / 批量改状态 / 批量删除 / 单任务编辑）。"""
        db = SessionLocal()
        try:
            run = (action_service.get_run(db, run_id) if run_id
                   else action_service.latest_undoable(db, self.user_id, self.project_id))
            if run is None:
                # 没得撤不是「失败」，是如实回答：按 no-op 返回，别污染工具报错指标
                return {"ok": True, "data": {"nothing_to_undo": True},
                        "note": "没有可撤销的操作：我只记得最近一次落库的动作"}
            if self.project_id is not None and run.project_id != self.project_id:
                return {"ok": False, "error": "这条台账不属于当前绑定的项目，已拒绝"}
            if run.status != "applied":
                return {"ok": False, "error": f"这条动作（{action_service.KIND_CN.get(run.kind, run.kind)}）已经撤销过了"}
            label = action_service.KIND_CN.get(run.kind, run.kind)
            result = action_service.undo(db, run)
            action_service.mark_undone(db, run)
            return {"ok": True, "kind": run.kind, "data": result, "run_id": run.id,
                    "note": f"已撤销上一次{label}（台账 #{run.id}）"}
        finally:
            db.close()
