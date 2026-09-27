"""意图识别与确定性路由：把话交给模型之前，代码先拍板高确定性的情况。

这些规则是行为承诺（跨项目写拦截 / 只给数量先追问 / 纯规划直行 / 名单分配 /
确认落库 / 只读查询），值得单独放，而不是埋在 1300 行文件中间（D-025）。
"""
import re
from typing import Optional

from models.database import AssignmentRun, NoteDraft
from services import project_service


# ---------- 确定性路由辅助（绑定项目时先于 LLM 决策，杜绝跨项目串扰） ----------
_PLAN_HINT_WORDS = ("拆解", "分解", "帮我规划", "规划任务", "任务规划",
                    "规划一下", "规划几个", "生成几个任务", "安排几个任务",
                    "帮我生成任务", "帮我安排任务")
# 出现在话术里多为「查询/检索知识库」而非「自动规划」，命中则不强制路由
_PLAN_NOISE = ("文档", "资料", "知识库", "检索", "搜索", "找一下",
               "查一下", "有什么", "有哪些", "怎么", "如何")
# 「任务」后面紧跟这些词 → 是「看清单/看列表」这类只读请求，不是写或规划
_TASK_READONLY_AFTER = r"(?!清单|列表|表格)"


def is_plan_intent(text: str) -> bool:
    """判断是否「自动规划任务」意图（用户未给任务明细）。

    仅用于绑定项目后的确定性路由：命中则直接对绑定项目执行 plan_tasks，
    不再把「给哪个项目规划」交给 LLM 决策 —— 模型反问/编造由此在源头被掐断。
    判定故意偏保守：普通问答、知识库检索类话术不会被误判成规划。
    """
    t = text.strip()
    if any(w in t for w in _PLAN_NOISE):
        return False
    if any(w in t for w in _PLAN_HINT_WORDS):
        return True
    return bool(re.search(rf"(?:生成|规划|安排)\S{{0,6}}任务{_TASK_READONLY_AFTER}", t))


def find_project_mention(db, user_id: int, bound_project_id: int, text: str):
    """若用户话术点到了绑定项目以外的项目 → 返回该项目（路由层拦截用）。

    项目名可能被泛化使用（如项目叫「测试」而用户在闲聊「测试一下」），
    因此这里只做「拦截提示、绝不写数据」，最坏情况是让用户先切换项目，安全。
    """
    for p in project_service.list_projects(db, user_id):
        if p.id == bound_project_id:
            continue
        if p.name and len(p.name) >= 2 and p.name in text:
            return p
    return None


# ---------- 绑定项目时的确定性路由（代码判定，先于 LLM 决策） ----------
_TASK_ADD_HINT = re.compile(r"(?:加|建|创建|新增|添加|安排|补)\S{0,4}任务|任务[:：]")
# 删除类写意图：覆盖「删掉XX任务/删除XX项目的任务/把XX任务删掉/清掉XX」
_TASK_DEL_HINT = re.compile(
    r"(?:删|删除|移除|清理|划掉|去掉)\S{0,12}(?:任务|项目)|(?:任务|项目)\S{0,8}(?:删|删除|划掉|移除)")
# 进度/状态查询（只读，不写数据）：命中则由代码层先注入真实任务数据再让模型作答
_PROGRESS_HINT = re.compile(
    r"进度|进展|怎么样了|怎么样|什么情况|什么状态|还剩|还有哪些|任务列表|任务清单|"
    r"看看任务|查看任务|任务情况|完成情况|完成多少|多少任务|多少个任务|"
    r"进行到|当前状态|目前状态|做到哪|状态如何|状态分布|任务状态|"
    r"有几条|有几个|有哪几|有哪些任务|列出来|列出|doing|todo")
# 出现写动作（加/删/改/规划/状态流转）时不算纯查询，交给对应写工具/写路由
_WRITE_ACTION = re.compile(
    r"(?:加|建|创建|新增|添加|安排|补|删|删除|移除|清理|划掉|去掉|"
    r"改|编辑|更新|标记|设为|调|规划|拆解|分解|生成|安排|推进|开始|完成)\S{0,6}"
    r"(?:任务|项目|状态|优先级|描述|标题)" + _TASK_READONLY_AFTER)
# 出现「数量 + 个任务」（如：加两个任务 / 增加 3 个任务 / 加几个任务）
_COUNT_TASK = re.compile(r"(?:[0-9]+|[一二两三四五六七八九十]|两|几|多)\s*个\s*任务")
# 已给出任务明细的特征（引号包裹 或 「任务：」冒号后跟内容）
_DETAIL_MARK = re.compile(r"[「『【]|任务\s*[:：]")


def _is_task_write_intent(text: str) -> bool:
    """是否「要往某个项目写任务」：规划意图 / 显式「加/建任务」/ 删除任务指令。"""
    return (is_plan_intent(text)
            or bool(_TASK_ADD_HINT.search(text))
            or bool(_TASK_DEL_HINT.search(text)))


def is_progress_query(text: str) -> bool:
    """是否「查询项目进度/任务状态」类只读意图。

    命中且已绑定项目时，路由层先强制读取真实任务数据注入上下文，
    再让模型作答 —— 防止模型「不查库直接泛泛而谈/编造进度」。
    与写意图互斥：出现加/删/改/推进类动作词时不算查询（走写工具）。
    """
    t = text.strip()
    if not t:
        return False
    if _WRITE_ACTION.search(t):
        return False
    if _is_task_write_intent(t):
        return False
    return bool(_PROGRESS_HINT.search(t))


def is_ask_detail_intent(text: str) -> bool:
    """写任务意图但用户只给了「数量/泛泛几个任务」、没有任何任务明细 →
    代码层直接追问内容，防止模型把「加 2 个任务」误当成主题规划一次生成 5 条。

    例如命中：
      「帮我加两个任务」「增加3个任务」「加几个任务吧」
    不命中（已有明细，交给 Agent 逐个创建）：
      「加两个任务：① 登录页优化 ② 支付修复」
      「给 XX 加一个任务：上线前回归测试」
    """
    if not _is_task_write_intent(text):
        return False
    if is_plan_intent(text):  # 「帮我规划几个任务」→ 仍是按主题规划，不拦
        return False
    return bool(_COUNT_TASK.search(text)) and not _DETAIL_MARK.search(text)


# 「按名单分配」与「确认落库」的确定性识别（代码拍板，避免模型漏调工具）
_ROSTER_DOC_HINT = re.compile(
    r"名单|人员说明|人员介绍|人员资料|分工说明|团队介绍|团队成员|上传的(?:说明|资料|文档)")
_ASSIGN_PLAN_HINT = re.compile(r"分配|分工|安排|分下去|分给|认人|落到人")
# 确认语：短句、明确的「按这个方案来」；只在真的有待确认方案时才生效（见 resolve_bound_action）
_APPLY_ASSIGN_HINT = re.compile(
    r"(?:就)?(?:按|照|依)(?:这个|这份|上述|上面的|你(?:说|给)的)(?:方案|分配|安排|名单)?(?:来|办|执行|落库)?"
    r"|^(?:确认|确认吧|确认分配|同意|没问题|就这样|照这个来|落库|执行吧|开始分配|开始吧)[，,。!！\s]*$")


def is_assign_plan_intent(text: str) -> bool:
    """是否「按上传的名单/人员说明做分配」：既要提到名单类资料，也要有分配动作。"""
    t = (text or "").strip()
    return bool(_ROSTER_DOC_HINT.search(t)) and bool(_ASSIGN_PLAN_HINT.search(t))


def is_apply_assignment_intent(text: str) -> bool:
    """是否「确认把分配方案落库」。只在存在待确认方案时路由（见 resolve_bound_action），
    所以这里可以宽松一点，也不用担心闲聊里的「确认」被误判。"""
    t = (text or "").strip()
    if not t or len(t) > 40:
        return False
    return bool(_APPLY_ASSIGN_HINT.search(t))


def has_pending_assignment(db, user_id: int, project_id: int) -> bool:
    """该项目是否有一份还没落库的分配方案（决定「确认」这句话要不要走落库路由）。"""
    return (db.query(AssignmentRun)
            .filter_by(user_id=user_id, project_id=project_id, status="pending")
            .order_by(AssignmentRun.id.desc()).first()) is not None


# ---------- 记忆闭环：认「这是个决定」，先拟稿、确认后入库（D-027） ----------
# 用户自己把话"定下来"的说法。注意与「记下来/存成纪要」区分：后者是显式归档，
# 由模型直接调 save_meeting 写库，不需要再走草稿确认。
_CONCLUSION_HINT = re.compile(
    r"就这么定|就这么办|说定了|定下来|确定为|统一为|统一用|约定|结论是|"
    r"我们决定|决定采用|拍板|以后都|从今往后|规矩定|这个方案定")
_ARCHIVE_HINT = re.compile(r"纪要|归档|存进资料库|记进资料库|记下来|存档|沉淀一下")
# 确认/放弃都只认短句：长篇大论里的"存"字不算（和 apply 的判法一致）
_NOTE_CONFIRM_HINT = re.compile(
    r"^(?:存|存吧|存入|记吧|记下来|好|好的|行|可以|嗯|对|确认|就这样|同意)[，,。!！\s]*$")
_NOTE_DISCARD_HINT = re.compile(
    r"^(?:不用|不用了|算了|别记|别记了|不存|不要|取消|撤回|删掉这条笔记)[，,。!！\s]*$")


def is_conclusion_intent(text: str) -> bool:
    """用户把一件事"定下来"了 → 值得沉淀成一条笔记（先拟稿，确认后入库）。

    故意窄：既要命中"定下来"的说法，又要排除显式归档语（那条走 save_meeting）、
    排除疑问句（"定了吗？"）。宁可不记，也不要刷一库噪音。
    """
    t = (text or "").strip()
    if not t or len(t) > 120:
        return False
    if _ARCHIVE_HINT.search(t):
        return False
    if t.endswith(("？", "?")):
        return False
    return bool(_CONCLUSION_HINT.search(t))


def is_note_confirm_intent(text: str) -> bool:
    """「存 / 记下来 / 好」这种一句话确认（只在真有草稿时才生效）。"""
    t = (text or "").strip()
    return bool(t) and len(t) <= 12 and bool(_NOTE_CONFIRM_HINT.match(t))


def is_note_discard_intent(text: str) -> bool:
    """「不用了 / 算了 / 别记」这种一句话放弃。"""
    t = (text or "").strip()
    return bool(t) and len(t) <= 12 and bool(_NOTE_DISCARD_HINT.match(t))


def has_pending_note(db, user_id: int, project_id: int) -> bool:
    """该项目有没有一份还没确认的结论笔记草稿。"""
    return (db.query(NoteDraft)
            .filter_by(user_id=user_id, project_id=project_id, status="pending")
            .order_by(NoteDraft.id.desc()).first()) is not None


def resolve_bound_action(db, user_id: int, bound_project_id: Optional[int],
                         bound_project_name: Optional[str], message: str):
    """绑定项目场景下，把「高确定性」的情况在进入 LLM 前先用代码判定：

    返回 (action, payload)：
      ("conflict", other_name)  消息要写任务却点名绑定项目之外的项目
                                → 提示先切换，绝不跨项目写数据；
      ("ask",      None)        要加任务但只给数量/没给明细（如「加两个任务」）
                                → 先追问内容，绝不自动规划一整批；
      ("plan",      None)       纯规划意图 → 直接对绑定项目执行 plan_tasks；
      ("query",     None)       只读进度/状态查询 → 先注入真实任务数据再让模型作答；
      ("agent",     None)       其余 → 交给 Agent 工具循环（工具已按绑定项目裁剪）。

    说明：仅「提及别的项目」（如“参照A项目的做法”）不拦截，交给裁剪后的
    Agent —— 工具里已无 project_id，它也无法把数据写到别的项目。
    """
    if bound_project_id is None:
        return ("agent", None)
    other = find_project_mention(db, user_id, bound_project_id, message)
    if other is not None and _is_task_write_intent(message):
        return ("conflict", other.name)
    # 名单分配 / 确认落库：都要求「绑定项目」，且判在 plan 之前 ——
    # 「按名单安排任务」不该被当成「按项目主题自动规划一批任务」。
    if is_assign_plan_intent(message):
        return ("assign_plan", None)
    if has_pending_assignment(db, user_id, bound_project_id) and is_apply_assignment_intent(message):
        return ("apply", None)
    # 记忆闭环：先看有没有草稿等着"存/不用"，再看这句话本身是不是个结论
    if has_pending_note(db, user_id, bound_project_id):
        if is_note_discard_intent(message):
            return ("note_discard", None)
        if is_note_confirm_intent(message):
            return ("note_confirm", None)
    if is_conclusion_intent(message):
        return ("note_draft", None)
    if is_plan_intent(message):
        return ("plan", None)
    if is_ask_detail_intent(message):
        return ("ask", None)
    if is_progress_query(message):
        return ("query", None)
    return ("agent", None)
