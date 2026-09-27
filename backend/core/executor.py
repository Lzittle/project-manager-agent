"""工具执行器：把按职责拆开的 mixin 组装成一个类，并负责调度（D-025）。

各块分别在同目录：executor_core.py（项目/任务/知识）、executor_trace.py（执行轨迹）、
executor_plan.py（任务规划）、executor_team.py（小队成员与指派）。
为什么要这样拆：这个类原本 880 行、20 个方法，任何一次改动都要在长文件里翻找；
按职责分文件后，改指派只需打开 executor_team.py。
"""
import time

from core.executor_core import _CoreToolMixin
from core.executor_plan import _PlanToolMixin
from core.executor_team import _TeamToolMixin
from core.executor_trace import _TraceToolMixin
from core.tools import build_tools
from core.utils import brief_error


class _ToolExecutor(_CoreToolMixin, _PlanToolMixin, _TeamToolMixin, _TraceToolMixin):
    # 同一项目重复规划的复用窗口（秒）：窗口内重复触达 → 复用上一批，不再新建
    PLAN_DEDUP_WINDOW_SEC = 300
    # 任务列表瘦身：一次默认回多少条、上限多少（模型可带 limit/offset 翻页）
    TASK_LIST_LIMIT = 40
    TASK_LIST_MAX = 200

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
        t0 = time.time()
        try:
            result = fn(**args)
        except Exception as e:
            result = {"ok": False,
                      "error": brief_error(e, "换个说法重试；要真实 id 可先 list_tasks / list_members")}
        ms = int((time.time() - t0) * 1000)
        self.last_trace.append(self.summarize_tool(name, args, result, ms))
        return result
