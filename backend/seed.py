"""seed.py — 演示数据初始化脚本（幂等：已有用户数据则跳过）

用法: 在 backend/ 目录执行  ../venv/Scripts/python.exe seed.py
"""
import hashlib
from datetime import date

from core import rag
from models.database import (
    SessionLocal, init_db,
    User, Project, Task, KnowledgeDocument, ChatMessage,
)

DEMO_PASSWORD = "demo1234"


def _hash(pwd: str) -> str:
    return hashlib.sha256(pwd.encode()).hexdigest()


def seed() -> None:
    init_db()
    db = SessionLocal()
    try:
        if db.query(User).count() > 0:
            print("[skip] 已有用户数据，seed 幂等跳过")
            return

        # ---- 1 个用户 ----
        alice = User(
            username="alice",
            email="alice@example.com",
            password_hash=_hash(DEMO_PASSWORD),
        )
        db.add(alice)
        db.flush()

        # ---- 项目1：电商系统 + 5 个任务（示例：自然语言一键建项目场景）----
        p1 = Project(
            name="电商系统",
            description="在线商城管理后台，覆盖商品、订单、会员、营销模块",
            status="active",
            creator_id=alice.id,
        )
        db.add(p1)
        db.flush()
        tasks_p1 = [
            ("需求分析文档", "梳理角色、功能模块与验收标准", "done", "high", None),
            ("数据库表结构设计", "商品/订单/会员/优惠券等核心表设计", "done", "high", None),
            ("用户登录与权限模块", "账号登录 + RBAC 角色权限控制", "doing", "high", None),
            ("商品列表与详情页", "商品分页、搜索、SKU 展示", "doing", "medium", date(2026, 9, 15)),
            ("订单支付流程联调", "下单-支付-回调-发货全链路打通", "todo", "high", date(2026, 9, 20)),
        ]
        for title, desc, status, priority, due in tasks_p1:
            db.add(Task(title=title, description=desc, status=status,
                        priority=priority, project_id=p1.id,
                        assignee_id=alice.id, due_date=due))

        # ---- 项目2：官网改版 + 3 个任务 ----
        p2 = Project(
            name="官网改版",
            description="公司品牌官网升级，重做首页与产品介绍",
            status="active",
            creator_id=alice.id,
        )
        db.add(p2)
        db.flush()
        for title, desc, status, priority in [
            ("新版首页视觉稿", "品牌主视觉与首屏 Banner 设计", "doing", "medium"),
            ("产品介绍页文案", "三个产品线的卖点文案撰写", "todo", "low"),
            ("响应式适配验收", "移动端/平板断点走查修复", "done", "medium"),
        ]:
            db.add(Task(title=title, description=desc, status=status,
                        priority=priority, project_id=p2.id, assignee_id=alice.id))

        # ---- 知识库文档 1 篇（RAG 演示用，埋独特关键词便于检索命中验证）----
        # 落库后立即向量化，保证重置后知识库立即可检索
        doc1 = KnowledgeDocument(
            title="电商系统需求说明",
            content=(
                "电商系统面向中小商家提供一站式开店能力，核心模块：\n"
                "1) 商品中心：支持多规格 SKU，库存预警（低于 5 件自动通知运营）；\n"
                "2) 订单中心：下单-支付-发货-售后全流程，支持取消与退款；\n"
                "3) 会员体系：等级积分、满减优惠券、新人礼包；\n"
                "4) 营销工具：限时秒杀、多级分销佣金结算；\n"
                "5) 数据看板：GMV、转化率、复购率实时统计。\n"
                "验收标准：支付回调成功率不低于 99.9%，库存预警通知延迟小于 1 分钟。"
            ),
            file_type="md",
            project_id=p1.id,
        )
        db.add(doc1)
        db.flush()  # 先取 doc.id
        rag.index_document(doc1.id, doc1.project_id, doc1.title, doc1.content)
        db.add(ChatMessage(role="user", content="帮我创建一个电商系统项目", user_id=alice.id))

        db.commit()
        print(f"[ok] seed 完成：用户 1 / 项目 2 / 任务 {len(tasks_p1) + 3} / 文档 1(已向量化) / 对话 1")
        print(f"[ok] 演示账号: alice / {DEMO_PASSWORD} (密码为 sha256 演示哈希)")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
