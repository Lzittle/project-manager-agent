"""对话回复文案：把执行结果拼成给用户看的中文回复（D-025 / D-028）。

为什么单独一个文件：这些函数**不依赖模型二次生成** —— 工具返回什么就说什么，
数字与状态都来自数据库，是「不许编造」这条铁律的落点。它们和路由/落库逻辑无关，
拆出去也让 `api/chat.py` 回到 400 行以内（AGENTS.md 的单文件软上限）。
"""

# 状态/优先级中文标签（对模型和用户都更直观）
STATUS_CN = {"todo": "待办", "doing": "进行中", "done": "已完成"}
PRIORITY_CN = {"high": "高", "medium": "中", "low": "低"}


def format_plan_reply(res: dict, project_name: str | None) -> str:
    """把 plan_tasks 的返回结果拼成给用户的文字回复。"""
    if not res.get("ok"):
        return f"任务规划失败：{res.get('error', '未知错误')}。可重试，或直接说明任务明细，我逐个创建。"
    tasks = res.get("data") or []
    name = project_name or "该项目"
    lines = "\n".join(f"{i}. {t['title']}" for i, t in enumerate(tasks, 1))
    note = res.get("note", "")
    if res.get("reused"):  # 幂等命中：复用上一批，不重复创建
        return (f"「{name}」刚刚已经规划过一批任务（共 {len(tasks)} 个），本次没有重复创建：\n"
                f"{lines}\n{note}")
    return f"已为「{name}」自动规划 {len(tasks)} 个任务：\n{lines}\n{note}"


def format_apply_reply(res: dict, project_name: str | None) -> str:
    """把「按名单分配方案落库」的结果拼成给用户的文字回复。"""
    if not res.get("ok"):
        return f"落库失败：{res.get('error', '未知错误')}"
    rows = res.get("data") or []
    name = project_name or "该项目"
    lines = "\n".join(
        f"{i}. {t['title']} → {t['assignee_name']}"
        f"（状态仍为{STATUS_CN.get(t['status'], t['status'])}）"
        for i, t in enumerate(rows, 1))
    out = f"已把「{name}」的 {len(rows)} 条指派落库：\n{lines}"
    created = res.get("created_members") or []
    if created:
        who = "、".join(f"{c['name']}（邀请码 {c['invite_code']}）" for c in created)
        out += f"\n顺手建了 {len(created)} 个占位成员：{who} —— 把邀请码发给对方，注册后即可认领。"
    skipped = res.get("skipped") or []
    if skipped:
        out += f"\n{len(skipped)} 条没动：{'；'.join(skipped)}"
    out += "\n只改了负责人，任务状态没有变化。要反悔就说一句「撤销」，我按台账回滚。"
    return out


def format_bulk_applied(res: dict, project_name: str | None) -> str:
    """批量方案落库后的回复：改了什么、删了什么，都摆明白，并告诉用户能撤销。"""
    if not res.get("ok"):
        return f"落库失败：{res.get('error', '未知错误')}"
    name = project_name or "该项目"
    rows = res.get("data") or []
    if res.get("kind") == "bulk_delete":
        lines = "\n".join(f"{i}. {t['title']}（#{t['id']}）" for i, t in enumerate(rows, 1))
        out = f"已删掉「{name}」的 {len(rows)} 个任务：\n{lines}\n（依赖边与评论一并清掉了。）"
    else:
        lines = "\n".join(
            f"{i}. {t['title']}：{STATUS_CN.get(t.get('from'), t.get('from', ''))} → "
            f"{STATUS_CN.get(t['status'], t['status'])}"
            for i, t in enumerate(rows, 1))
        out = f"已按方案把「{name}」的 {len(rows)} 条任务改完：\n{lines}"
    skipped = res.get("skipped") or []
    if skipped:
        out += f"\n{len(skipped)} 条没动：{'；'.join(skipped)}"
    out += "\n要反悔就说一句「撤销」，我按台账回滚。"
    return out


def format_undo(res: dict) -> str:
    """撤销结果：把「找回了什么、还原成什么」逐条说清。"""
    if not res.get("ok"):
        return f"没能撤销：{res.get('error', '未知错误')}"
    d = res.get("data") or {}
    if d.get("nothing_to_undo"):
        return res.get("note") or "没有可撤销的操作"
    lines: list[str] = []
    for t in d.get("restored_tasks") or []:
        lines.append(f"· 找回任务「{t['title']}」（#{t['id']}）")
    for f in d.get("restored_fields") or []:
        detail = "、".join(f"{k} → {v}" for k, v in (f.get("restored") or {}).items())
        lines.append(f"· 「{f['title']}」已还原（{detail or '原样'}）")
    out = res.get("note", "已撤销上一次动作") + "：\n" + "\n".join(lines or ["（没有需要还原的内容）"])
    skipped = d.get("skipped") or []
    if skipped:
        out += f"\n{len(skipped)} 条没动：{'；'.join(skipped)}"
    return out


def format_note_draft(res: dict) -> str:
    """拟好草稿 → 问一句要不要记（阶段 2 记忆闭环：写前给一句话确认，避免刷噪音）。"""
    if not res.get("ok"):
        return f"没能拟出笔记：{res.get('error', '未知错误')}"
    d = res.get("data") or {}
    return (f"这句话听着像个决定，我拟成一条笔记：\n\n"
            f"《{d.get('title', '')}》\n{d.get('content', '')}\n\n"
            f"要记进项目记忆就说「存」，不用就说「不用」。")


def format_note_saved(res: dict, project_name: str | None) -> str:
    """结论笔记入库的回复。"""
    if not res.get("ok"):
        return f"没能记下来：{res.get('error', '未知错误')}"
    if res.get("skipped"):
        return res.get("note") or "这条刚才已经记过了，没有重复入库。"
    d = res.get("data") or {}
    return (f"已记进「{project_name or '这个项目'}」的项目记忆：《{d.get('title', '')}》"
            f"——之后问「上次定的…」，我会检索到它。")


def format_snapshot_note(snap: dict) -> str:
    """把项目状态快照压成给模型的 system 上下文（真实数据，禁止编造）。"""
    d = snap.get("data", {})
    p = d.get("project", {})
    by = d.get("by_status", {})
    lines = [
        f"【项目「{p.get('name','')}」当前真实状态（已从数据库读取，回答务必基于以下数据，不得编造）】",
        f"- 任务总数 {d.get('task_count',0)}：待办 {by.get('todo',0)} / "
        f"进行中 {by.get('doing',0)} / 已完成 {by.get('done',0)}",
    ]
    tasks = d.get("tasks") or []
    if tasks:
        lines.append("- 任务明细（#id｜标题｜状态｜优先级；"
                     "待办=todo、进行中=doing、已完成=done；高=high、中=medium、低=low）：")
        for t in tasks:
            lines.append(f"  · #{t['id']}｜{t['title']}｜{STATUS_CN.get(t['status'], t['status'])}"
                         f"｜{PRIORITY_CN.get(t['priority'], t['priority'])}")
        if d.get("tasks_truncated"):
            lines.append(f"  · …另有 {d['tasks_truncated']} 个任务未列出，可用 list_tasks 查全量")
    high = d.get("high_open") or []
    if high:
        lines.append(f"- 未完成的高优先级任务：{'、'.join(high)}")
    blocked = d.get("blocked") or []
    if blocked:
        lines.append("- 依赖未就绪（可能阻塞）的任务：")
        for b in blocked[:5]:
            lines.append(f"  · 「{b['task']}」需等「{b['waiting_on']}」（当前 {b['pre_status']}）")
    if not (high or blocked) and d.get("task_count", 0) == 0:
        lines.append("- 项目暂无任务，可建议用户先「帮我规划任务」。")
    return "\n".join(lines)


def format_rag_note(hits: list[dict]) -> str:
    """把 RAG 命中的记忆片段压成给模型的 system 上下文（标注来源，防止模型当自己的知识）。"""
    lines = ["【项目记忆检索结果（来自知识库/会议纪要，回答务必基于以下原文，不得编造）】"]
    for i, h in enumerate(hits[:3], 1):
        src = h.get("doc_type") or ""
        src_label = "会议纪要" if src == "meeting" else "知识库"
        lines.append(f"{i}. 《{h.get('title','')}》〔{src_label}〕：{h.get('text','')[:300]}")
    return "\n".join(lines)
