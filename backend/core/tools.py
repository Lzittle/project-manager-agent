"""工具定义（给模型看的 schema）与按会话状态裁剪。

工具描述是「每次调用都要付」的固定成本，所以刻意写得短（见 D-024）。
从 core/agent.py 拆出（D-025）。
"""
from typing import Optional


# ---------- 工具定义 ----------
def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


TOOLS: list[dict] = [
    _fn(
        "list_projects",
        "列出用户的全部项目（含任务数）。用于「有哪些项目」",
        {},
        [],
    ),
    _fn(
        "create_project",
        "新建项目。用于「帮我建一个 XX 项目」",
        {"name": {"type": "string", "description": "项目名称"},
         "description": {"type": "string", "description": "项目描述（可空）"}},
        ["name"],
    ),
    _fn(
        "list_tasks",
        "列任务：默认回 40 条，每条含 id/标题/状态/优先级/负责人（不含描述）；"
        "翻页用 offset，只看某状态用 status。用于「任务清单/有哪些任务」",
        {"project_id": {"type": "integer", "description": "项目 id（可省略，默认当前绑定项目）"},
         "status": {"type": "string", "enum": ["todo", "doing", "done"],
                    "description": "只看某种状态（可省略）"},
         "limit": {"type": "integer", "description": "本次最多回多少条（默认 40，上限 200）"},
         "offset": {"type": "integer", "description": "从第几条开始（默认 0，用于翻页）"}},
        [],
    ),
    _fn(
        "create_task",
        "建单个任务（用户已给明确内容时用；要按主题拆一整套用 plan_tasks）",
        {"project_id": {"type": "integer", "description": "所属项目 id（可省略，默认当前绑定项目）"},
         "title": {"type": "string", "description": "任务标题"},
         "description": {"type": "string", "description": "任务描述（可空）"},
         "status": {"type": "string", "enum": ["todo", "doing", "done"], "description": "状态，默认 todo"},
         "priority": {"type": "string", "enum": ["high", "medium", "low"], "description": "优先级，默认 medium"}},
        ["title"],
    ),
    _fn(
        "update_task_status",
        "改任务状态（todo/doing/done）。用于「标记完成/开始做这个」",
        {"task_id": {"type": "integer", "description": "任务 id"},
         "status": {"type": "string", "enum": ["todo", "doing", "done"], "description": "目标状态"}},
        ["task_id", "status"],
    ),
    _fn(
        "delete_task",
        "删除任务（连带评论）。先用 list_tasks 查到真实 task_id",
        {"task_id": {"type": "integer", "description": "要删除的任务 id"}},
        ["task_id"],
    ),
    _fn(
        "update_task_fields",
        "改任务的标题/描述/状态/优先级（只传要改的字段）",
        {"task_id": {"type": "integer", "description": "任务 id"},
         "title": {"type": "string", "description": "新标题（可选）"},
         "description": {"type": "string", "description": "新描述（可选）"},
         "status": {"type": "string", "enum": ["todo", "doing", "done"], "description": "新状态（可选）"},
         "priority": {"type": "string", "enum": ["high", "medium", "low"], "description": "新优先级（可选）"}},
        ["task_id"],
    ),
    _fn(
        "delete_project",
        "删除项目（连带任务/评论/文档/向量，不可恢复）。先 list_projects 查 id",
        {"project_id": {"type": "integer", "description": "要删除的项目 id"}},
        ["project_id"],
    ),
    _fn(
        "update_project_fields",
        "改项目名或项目描述（改任务字段请用 update_task_fields）",
        {"project_id": {"type": "integer", "description": "项目 id"},
         "name": {"type": "string", "description": "新项目名（可选）"},
         "description": {"type": "string", "description": "新描述（可选）"}},
        ["project_id"],
    ),
    _fn(
        "search_knowledge",
        "在项目知识库（资料/会议纪要）里检索片段，回答「资料里怎么写的」",
        {"query": {"type": "string", "description": "检索问题"},
         "project_id": {"type": "integer", "description": "限定项目（可空）"}},
        ["query"],
    ),
    _fn(
        "save_meeting",
        "把本次对话已确认的结论/决策/待办整理成会议纪要存入知识库（之后可被检索到）。"
        "仅在用户明确要求记录/归档时用（「记下来/存成纪要/归档」）；内容必须忠于对话，不得编造",
        {"project_id": {"type": "integer", "description": "要归档纪要的项目 id（可省略，默认当前绑定项目）"},
         "title": {"type": "string", "description": "纪要主题（建议含日期）"},
         "content": {"type": "string", "description": "纪要正文：结论/决策/待办的结构化要点"}},
        ["title", "content"],
    ),
    _fn(
        "plan_tasks",
        "按项目主题拆解并创建一批任务（默认待办）。只用于用户没给明细、要「帮我规划任务」时；"
        "只读请求（任务清单/进度）禁用；用户已给明细就用 create_task 逐个建。force=true 才重新规划一批",
        {"project_id": {"type": "integer", "description": "要规划任务的项目 id（可省略，默认当前绑定项目）"},
         "force": {"type": "boolean",
                   "description": "true=用户明确要求重新规划一批新任务；默认 false 时，该项目刚规划过会直接复用上一批，不重复创建"}},
        [],
    ),
    _fn(
        "list_members",
        "查小队成员名册（id/名字/状态）。指派前先用它把人匹配成 member_id",
        {},
        [],
    ),
    _fn(
        "create_member",
        "把一个人加进名册（占位成员，带邀请码，等对方注册认领）。"
        "同名会失败——那就问用户是不是同一个人",
        {"name": {"type": "string", "description": "成员名字（如「陈工」）"}},
        ["name"],
    ),
    _fn(
        "assign_task",
        "把任务指派给成员：**只改负责人、不改状态**。"
        "先 list_tasks 拿 task_id、list_members 拿 member_id（名册没有就先 create_member）",
        {"task_id": {"type": "integer", "description": "任务 id"},
         "member_id": {"type": "integer", "description": "成员 id（来自 list_members）"}},
        ["task_id", "member_id"],
    ),
    _fn(
        "plan_assignment_from_doc",
        "读资产库资料（默认最新一篇，通常是「相关人员说明/名单」）+ 名册 + 未完成任务，"
        "拟一份「任务 → 负责人」方案。**不写库**：先给用户过一眼，确认后再 apply_assignment",
        {"doc_id": {"type": "integer", "description": "指定资料 id（可省略：默认取该项目最近上传的一篇）"},
         "project_id": {"type": "integer", "description": "项目 id（可省略，默认当前绑定项目）"}},
        [],
    ),
    _fn(
        "apply_assignment",
        "把方案真正落库（写负责人）。**仅在用户明确确认后**调用；"
        "名单外的人会建成占位成员，重名的条目跳过并报告",
        {"plan_id": {"type": "integer", "description": "方案 id（可省略：默认最近一份待确认的方案）"},
         "overrides": {"type": "array",
                       "description": "微调：只覆盖指定任务的负责人，"
                                      "形如 [{\"task_id\": 39, \"member_name\": \"李工\"}]",
                       "items": {"type": "object",
                                 "properties": {"task_id": {"type": "integer"},
                                                "member_name": {"type": "string"}}}}},
        [],
    ),
]


# 只读场景（进度/清单这类问题）只给查询类工具：
# 既省固定成本，也从根上杜绝"只想看进度，却顺手写了库"（评测里最危险的错误类别）。
READONLY_TOOL_NAMES = {"list_projects", "list_tasks", "search_knowledge", "list_members"}


def build_tools(project_id: Optional[int] = None, readonly: bool = False) -> list[dict]:
    """按会话状态裁剪工具列表。

    - 未绑定项目：暴露全部 7 个工具（模型可自由创建/查询项目）；
    - 已绑定项目：摘掉 list_projects / create_project，并移除项目类工具里的
      project_id 参数 —— 模型既看不到「还有别的项目」、也无法传错项目，
      所有落点由执行器固定为绑定项目。反问「要给哪个项目」从此无从发生。
    - readonly=True：只留查询类工具（用于进度/清单类只读问题）。
    """
    if readonly and project_id is None:
        return [t for t in TOOLS if t["function"]["name"] in READONLY_TOOL_NAMES]
    if project_id is None:
        return TOOLS
    # 绑定模式：禁止项目级新建/删除/改名，避免模型跨项目动数据；任务级删除/编辑按 id 操作可保留
    HIDDEN = {"list_projects", "create_project", "delete_project", "update_project_fields"}
    trimmed = []
    for t in TOOLS:
        name = t["function"]["name"]
        if name in HIDDEN or (readonly and name not in READONLY_TOOL_NAMES):
            continue
        # 浅拷贝参数结构，避免污染全局 TOOLS
        props = dict(t["function"]["parameters"]["properties"])
        required = [r for r in t["function"]["parameters"].get("required", [])
                    if r != "project_id"]
        props.pop("project_id", None)
        trimmed.append({
            "type": "function",
            "function": {
                "name": name,
                "description": t["function"]["description"],
                "parameters": {"type": "object", "properties": props,
                               "required": required},
            },
        })
    return trimmed
