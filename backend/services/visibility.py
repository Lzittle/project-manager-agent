"""范围与可见性策略（轮 4，D-031）：谁能看到哪些任务。

PLAN §2 定了两种视角：**队长**看全队、**组员**只看到派给自己的任务（跨项目）。
§8 的验收标准里也有一条「组员登录后只看得到自己的任务」—— 本模块就是这条的服务端实现。

判定口径（刻意简单，配 §7「不做细粒度权限，只做队长 / 组员两级」）：

- **队长** = 项目的创建者（`projects.creator_id == 账号 id`）→ 本项目任务全看；
- **组员** = 其余人 → 只看 `assignee_id == 自己的名册成员 id` 的任务；
- **没有身份**（未登录 / 老路径 `?user_id=`）→ **不过滤**。

最后一条是关键取舍：项目此前「无登录体系」，所有接口靠 `?user_id=` 传当前用户，
演示脚本、79 条评测、只读探针、Agent 工具循环走的都是这条老路径。
把过滤挂在「有没有令牌」上，就能做到**只对真正登录的人生效**，老路径一行不用改
（这与轮 3「只新增不替换」是同一个原则）。

**这里只管「看」，不管「改」**：写操作的授权是另一件事，§7 明确不做细粒度权限。
"""
from typing import Optional

from sqlalchemy.orm import Session

from models.database import Project, Task


class Viewer:
    """当前请求的「谁」：账号 + 它在名册上的成员身份（未登录时为 None）。

    用轻量对象而不是 ORM 例子，避免把 Session 生命周期带进策略里。
    """

    __slots__ = ("user_id", "member_id", "member_name")

    def __init__(self, user_id: int, member_id: Optional[int] = None,
                 member_name: Optional[str] = None):
        self.user_id = user_id
        self.member_id = member_id
        self.member_name = member_name

    def __repr__(self) -> str:  # 便于测试与日志
        return f"Viewer(user_id={self.user_id}, member_id={self.member_id})"


def is_captain(db: Session, viewer: Viewer, project_id: int) -> bool:
    """队长 = 项目的创建者。项目不存在时按「不是队长」处理（保守）。"""
    project = db.get(Project, project_id)
    return bool(project) and project.creator_id == viewer.user_id


def filter_tasks(db: Session, tasks: list[Task], viewer: Optional[Viewer]) -> list[Task]:
    """按视角裁剪任务列表；`viewer is None` 表示没有身份 → 原样返回（老路径）。"""
    if viewer is None or not tasks:
        return tasks
    # 只要列表里还混着别的项目，就无法用单个项目判队长 —— 调用方应逐项目传
    project_ids = {t.project_id for t in tasks}
    if len(project_ids) == 1:
        project_id = next(iter(project_ids))
        if is_captain(db, viewer, project_id):
            return tasks
        return [t for t in tasks if t.assignee_id == viewer.member_id]
    # 多项目混合（本项目当前没有这种调用）：逐条按各自项目判定
    out = []
    for t in tasks:
        if is_captain(db, viewer, t.project_id) or t.assignee_id == viewer.member_id:
            out.append(t)
    return out


def visible_tasks(db: Session, project_id: int, tasks: list[Task],
                  viewer: Optional[Viewer]) -> list[Task]:
    """项目内任务的可视子集（`list_tasks` 之后调一次）。"""
    return filter_tasks(db, tasks, viewer)


def mine_tasks(db: Session, viewer: Viewer) -> list[Task]:
    """跨项目：名册上属于我的全部任务（组员的「我」投影）。

    没有名册身份时返回空 —— 你还没有「我」，自然没有派给你的活。
    这与「未登录不过滤」不冲突：那条说的是**没有身份**，这条说的是
    「有账号但没认领名册」这一个人情况。
    """
    if viewer.member_id is None:
        return []
    return (db.query(Task)
            .filter(Task.assignee_id == viewer.member_id)
            .order_by(Task.id.desc())
            .all())
