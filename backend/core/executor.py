"""工具执行器：把按职责拆开的 mixin 组装成一个类，并负责调度（D-025 / D-028）。

各块分别在同目录：executor_core.py（项目/任务/知识）、executor_trace.py（执行轨迹）、
executor_plan.py（任务规划）、executor_team.py（小队成员与指派）、
executor_action.py（批量动作方案与撤销）。
为什么要这样拆：这个类原本 880 行、20 个方法，任何一次改动都要在长文件里翻找；
按职责分文件后，改指派只需打开 executor_team.py。
"""
import time

from core.executor_action import _ActionToolMixin
from core.executor_core import _CoreToolMixin
from core.executor_plan import _PlanToolMixin
from core.executor_team import _TeamToolMixin
from core.executor_trace import _TraceToolMixin
from core.tools import build_tools
from core.utils import brief_error


class _ToolExecutor(_CoreToolMixin, _PlanToolMixin, _TeamToolMixin, _ActionToolMixin,
                    _TraceToolMixin):
    # 同一项目重复规划的复用窗口（秒）：窗口内重复触达 → 复用上一批，不再新建
    PLAN_DEDUP_WINDOW_SEC = 300
    # 任务列表瘦身：一次默认回多少条、上限多少（模型可带 limit/offset 翻页）
    TASK_LIST_LIMIT = 40
    TASK_LIST_MAX = 200
    # 单轮「直接写任务」的上限（D-028）：同一个任务重复写没关系，但同一轮碰第二个
    # 不同任务就是批量写 —— 必须走 plan_bulk_*（先方案后落库），不许模型闷头写一串。
    # assign_task 暂不在内：批量指派还没有方案路径（记在 D-028 的代价里）。
    DIRECT_TASK_WRITES = {"delete_task", "update_task_status", "update_task_fields"}

    @staticmethod
    def _task_id_of(args: dict):
        try:
            return int(args.get("task_id"))
        except (TypeError, ValueError):
            return None

    def dispatch(self, name: str, args: dict) -> dict:
        # 只认"本轮真正开放"的工具：光靠不给列表还不够 ——
        # 模型猜对名字（如绑定模式下猜 update_project_fields）时，这里必须挡住，
        # 否则"工具列表已裁剪"就只是心理安慰（2026-09-27 评测里真发生过）。
        allowed = {t["function"]["name"] for t in build_tools(self.project_id, self.readonly)}
        if name not in allowed:
            return {"ok": False,
                    "error": f"工具 {name} 在本轮不可用；本轮可用的是：{'、'.join(sorted(allowed))}"}
        fn = getattr(self, name, None)
        if fn is None:
            return {"ok": False, "error": f"未知工具 {name}"}
        # 批量写守卫：一轮里第 2 个不同任务必须先出方案（D-028）。
        # 这是代码层硬约束 —— 光在提示词里说「批量要先方案」，模型照样会逐个写。
        if name in self.DIRECT_TASK_WRITES:
            tid = self._task_id_of(args)
            if tid is not None:
                written = getattr(self, "_turn_written", None)
                if written is None:
                    written = self._turn_written = set()
                if written and tid not in written:
                    return {
                        "ok": False,
                        "error": (f"本轮已经直接改过任务 {sorted(written)}；一次要动多个任务时"
                                  "必须先出方案给人过目：改状态用 plan_bulk_status、"
                                  "删除用 plan_bulk_delete，用户确认后再 apply_bulk_action"),
                    }
                written.add(tid)
        t0 = time.time()
        try:
            result = fn(**args)
        except Exception as e:
            result = {"ok": False,
                      "error": brief_error(e, "换个说法重试；要真实 id 可先 list_tasks / list_members")}
        ms = int((time.time() - t0) * 1000)
        self.last_trace.append(self.summarize_tool(name, args, result, ms))
        return result
