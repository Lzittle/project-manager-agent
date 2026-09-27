"""执行轨迹：把每次工具调用压成对用户友好的步骤 + 可点击实体引用（D-025）。"""
from typing import Any

from core.utils import clip


class _TraceToolMixin:
    # ---------- 执行轨迹（让每一步工具调用对用户可见、可跳转） ----------
    _LABELS = {
        "create_project": "创建项目", "list_projects": "查看项目列表",
        "list_tasks": "查看任务", "create_task": "创建任务",
        "update_task_status": "更新任务状态", "search_knowledge": "检索知识库",
        "plan_tasks": "自动规划任务",
        "delete_task": "删除任务", "delete_project": "删除项目",
        "update_task_fields": "编辑任务", "update_project_fields": "编辑项目",
        "project_snapshot": "读取项目状态", "save_meeting": "保存会议纪要",
        "list_members": "查看成员名册", "create_member": "添加成员",
        "assign_task": "指派任务", "plan_assignment_from_doc": "按名单拟分配方案",
        "apply_assignment": "落库分配方案",
    }
    _TASK_TOOLS = {"create_task", "update_task_status", "delete_task", "update_task_fields",
                   "assign_task"}
    _PROJECT_TOOLS = {"create_project", "delete_project", "update_project_fields"}

    def _refs_from(self, name: str, args: dict, result: dict) -> list[dict]:
        """提取受影响的实体（任务/项目），供前端渲染可点击跳转的引用。"""
        data = result.get("data") if result.get("ok") else None
        refs = []
        if name in self._PROJECT_TOOLS and isinstance(data, dict):
            refs.append({"kind": "project", "id": data["id"],
                         "title": data.get("name") or data.get("title", "")})
        elif name in self._TASK_TOOLS and isinstance(data, dict):
            refs.append({"kind": "task", "id": data["id"], "title": data.get("title", ""),
                         "project_id": data.get("project_id")})
        elif name == "plan_tasks" and isinstance(data, list):
            pid = args.get("project_id") or self.project_id
            for t in data:
                refs.append({"kind": "task", "id": t["id"], "title": t["title"],
                             "project_id": pid})
        elif name in ("plan_assignment_from_doc", "apply_assignment") and isinstance(data, list):
            pid = args.get("project_id") or self.project_id
            for it in data:
                refs.append({"kind": "task", "id": it.get("id") or it.get("task_id"),
                             "title": it.get("title", ""), "project_id": pid})
        return refs

    def summarize_tool(self, name: str, args: dict, result: dict, ms: int = 0) -> dict:
        """把一次工具调用压成一条对用户友好的轨迹步骤。"""
        label = self._LABELS.get(name, name)
        if not result.get("ok"):
            return {"tool": name, "label": label,
                    "detail": clip(result.get("error", "执行失败"), 100),
                    "ok": False, "ms": ms}
        data = result.get("data")
        if name == "create_project" and isinstance(data, dict):
            detail = f"创建项目「{data.get('name','')}」（#{data['id']}）"
        elif name == "delete_project" and isinstance(data, dict):
            detail = f"删除项目「{data.get('name','')}」（#{data['id']}）"
        elif name == "update_project_fields" and isinstance(data, dict):
            changed = [k for k in ("name", "description")
                       if k in args and args[k] not in (None, "")]
            detail = f"项目「{data.get('name','')}」已更新（{'/'.join(changed) or '描述'}）"
        elif name == "create_task" and isinstance(data, dict):
            detail = f"创建任务「{data.get('title','')}」（#{data['id']}）"
        elif name == "delete_task" and isinstance(data, dict):
            detail = f"删除任务「{data.get('title','')}」（#{data['id']}）"
        elif name == "update_task_status" and isinstance(data, dict):
            detail = f"任务「{data.get('title','')}」状态 → {data.get('status','')}"
        elif name == "update_task_fields" and isinstance(data, dict):
            changed = [k for k in ("title", "description", "status", "priority")
                       if k in args and args[k] not in (None, "")]
            detail = f"任务「{data.get('title','')}」已更新（{'/'.join(changed) or '字段'}）"
        elif name == "plan_tasks" and isinstance(data, list):
            detail = (f"复用上一批 {len(data)} 条任务（未重复创建）" if result.get("reused")
                      else f"生成 {len(data)} 条任务并入库（默认待办）")
        elif name == "list_projects" and isinstance(data, list):
            detail = f"共 {len(data)} 个项目"
        elif name == "list_tasks" and isinstance(data, list):
            total = result.get("total", len(data))
            shown = result.get("shown", len(data))
            detail = (f"共 {total} 个任务" if total == shown
                      else f"共 {total} 个任务，本次回 {shown} 条（可翻页）")
        elif name == "project_snapshot" and isinstance(data, dict):
            s = data
            detail = (f"项目「{s.get('project',{}).get('name','')}」："
                      f"共 {s.get('task_count',0)} 个任务，"
                      f"待办 {s.get('by_status',{}).get('todo',0)} / "
                      f"进行中 {s.get('by_status',{}).get('doing',0)} / "
                      f"完成 {s.get('by_status',{}).get('done',0)}")
        elif name == "search_knowledge" and isinstance(data, list):
            detail = f"检索到 {len(data)} 条相关片段" if data else "知识库暂无相关内容"
        elif name == "save_meeting" and isinstance(data, dict):
            detail = f"纪要「{data.get('title','')}」已存入知识库"
        elif name == "list_members" and isinstance(data, list):
            active = sum(1 for m in data if m.get("status") == "active")
            detail = f"名册 {len(data)} 人（已注册 {active} · 待认领 {len(data) - active}）"
        elif name == "create_member" and isinstance(data, dict):
            detail = f"「{data.get('name','')}」已进名册（待认领 · 邀请码 {data.get('invite_code','')}）"
        elif name == "assign_task" and isinstance(data, dict):
            detail = (f"任务「{data.get('title','')}」负责人 → {data.get('assignee_name','')}"
                      f"（状态仍为 {data.get('status','')}）")
        elif name == "plan_assignment_from_doc" and isinstance(data, list):
            detail = f"按名单拟出 {len(data)} 条分配（待确认，未落库）"
        elif name == "apply_assignment" and isinstance(data, list):
            extra = len(result.get("created_members") or [])
            detail = (f"落库 {len(data)} 条指派"
                      + (f"，新建 {extra} 个占位成员" if extra else ""))
        else:
            detail = f"{label}完成"
        step = {"tool": name, "label": label, "detail": clip(detail, 120),
                "ok": True, "ms": ms}
        refs = self._refs_from(name, args, result)
        if refs:
            step["refs"] = refs
        return step

