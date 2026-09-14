#!/usr/bin/env python
"""Agent 行为评测器：把「真实话术 → 期望行为」跑成可比较的数字。

两种模式：
  offline（默认） 只跑代码层判定（路由/正则），零 token，量「规则覆盖了多少说法」
  live            走真实 FastAPI 链路 + 真实模型，量「工具选择 / 写库 / 作答」到底对不对

用法（在 backend 目录下运行）：
  ../venv/Scripts/python.exe eval/run_agent_eval.py                     # 离线，零 token
  ../venv/Scripts/python.exe eval/run_agent_eval.py --mode live         # 在线，消耗 token
  ../venv/Scripts/python.exe eval/run_agent_eval.py --mode live --only 安全护栏
  ../venv/Scripts/python.exe eval/run_agent_eval.py --mode live --limit 5
  ../venv/Scripts/python.exe eval/run_agent_eval.py --mode live --keep  # 保留评测库便于排查

设计约束：
- 不碰演示数据：评测库 + 向量库都落在独立临时目录（--workdir 可改）；
- 走真实 HTTP 链路（TestClient → FastAPI 路由），与线上同一条代码路径；
- 每条用例前把夹具复位到基线（任务/文档/会话历史），用例后清理新增文档；
- 判定四维：路由 / 工具选择 / 写库行为 / 回复内容，任一不过 = 用例不过；
- known_gap=true 的用例是「已知短板」，单独统计，避免盖住回归信号。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
CASES_FILE = EVAL_DIR / "agent_eval_cases.json"
DEFAULT_WORKDIR = Path(tempfile.gettempdir()) / "squad_agent_eval"

BASE_PROJECT = "评测主项目"
OTHER_PROJECT = "评测邻项目"
USER_ID = 1

# ---------- 夹具：固定基线，保证每条用例从同一状态出发 ----------
BASE_TASKS = [
    {"title": "需求分析文档", "priority": "high", "status": "todo"},
    {"title": "登录联调", "priority": "medium", "status": "doing"},
    {"title": "素材拍摄", "priority": "low", "status": "todo"},
    {"title": "首页设计", "priority": "medium", "status": "todo"},
    {"title": "弱网容错", "priority": "low", "status": "done"},
    {"title": "支付回调修复", "priority": "high", "status": "todo"},
]
OTHER_TASKS = [
    {"title": "竞品调研", "priority": "medium", "status": "todo"},
    {"title": "登录任务", "priority": "high", "status": "todo"},
]
DEPENDENCY = ("支付回调修复", "登录联调")  # 前者依赖后者 → 制造「被阻塞」

DOC_TITLE = "需求说明书 v1"
DOC_TEXT = """需求说明书 v1（评测夹具）

一、功能范围
1. 商户入驻注册、菜品管理、订单接收与状态流转、营业统计看板。
2. 商户评价回复系统（二期）。

二、验收标准
1. 所有支付链路必须在弱网（3G，丢包率 5%）下完成端到端回归，失败率低于 1%。
2. 订单状态流转需覆盖：待接单 → 已接单 → 配送中 → 已完成 / 已取消。
3. 上线前需完成全链路回归，缺陷收敛到零 P0/P1。

三、支付超时约定
支付接口超时时间统一 5 秒；超时后自动重试 3 次，仍失败则进入人工对账流程。

四、里程碑
上线时间：2026-10-15。
"""

MEETING_TITLE = "2026-09-01 迭代评审"
MEETING_TEXT = """2026-09-01 迭代评审（评测夹具）

【结论】
1. 登录方案采用 JWT + 短信验证码双因子。
2. 先做商户入驻，再做菜品管理。

【决策】
1. 灰度发布范围先覆盖 3 个城市。

【风险】
1. 支付渠道资质审批可能延期，影响上线时间。
"""

FIXTURE_DOC_TITLES = {DOC_TITLE, MEETING_TITLE}


# ---------- 启动引导：环境变量必须在导入应用前设好 ----------
def resolve_backend_dir() -> Path:
    """定位 backend 目录：默认本脚本位于 backend/eval/ 下，支持环境变量覆盖。"""
    env = os.environ.get("SQUAD_BACKEND_DIR")
    if env:
        return Path(env).resolve()
    guess = EVAL_DIR.parent
    if (guess / "core" / "agent.py").exists():
        return guess
    raise SystemExit(
        "找不到 backend 目录。本脚本默认放在 backend/eval/ 下运行；"
        "若从别处运行，请设置环境变量 SQUAD_BACKEND_DIR 指向 backend。"
    )


def bootstrap(workdir: Path, fresh: bool) -> Path:
    """准备评测环境。

    fresh=True 时只清「评测库 + 向量库」重建干净数据，**保留 reports/ 里的历史报告** ——
    否则每次跑评测都会把上一轮的报告一起删掉，没法做修复前后对照与人工复核。
    """
    workdir.mkdir(parents=True, exist_ok=True)
    if fresh:
        for stale in (workdir / "eval.db", workdir / "chroma"):
            if stale.is_dir():
                shutil.rmtree(stale, ignore_errors=True)
            elif stale.exists():
                stale.unlink(missing_ok=True)
    os.environ["DATABASE_URL"] = f"sqlite:///{(workdir / 'eval.db').as_posix()}"
    os.environ["CHROMA_PERSIST_DIR"] = str(workdir / "chroma")
    os.environ["CHROMA_COLLECTION"] = "eval_knowledge_docs"
    backend = resolve_backend_dir()
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    return backend


# ---------- 夹具 ----------
class Fixture:
    """评测夹具：两个项目 + 固定任务 + 两篇文档；用例前复位到基线。"""

    def __init__(self, client):
        self.client = client
        self.main_id: int | None = None
        self.other_id: int | None = None
        self.main_name = BASE_PROJECT

    # --- 建 ---
    def build(self) -> None:
        projects = {p["name"]: p for p in self._get("/api/projects", user_id=USER_ID)}
        main = projects.get(BASE_PROJECT) or self._create_project(
            BASE_PROJECT, "面向 2–6 人小队的外卖商户平台")
        other = projects.get(OTHER_PROJECT) or self._create_project(
            OTHER_PROJECT, "用于跨项目拦截评测")
        self.main_id, self.other_id = main["id"], other["id"]
        self._ensure_docs()
        self.reset()

    def _create_project(self, name: str, desc: str) -> dict:
        r = self.client.post(f"/api/projects?user_id={USER_ID}",
                             json={"name": name, "description": desc})
        r.raise_for_status()
        return r.json()

    def _ensure_docs(self) -> None:
        titles = {d["title"] for d in self.docs()}
        if DOC_TITLE not in titles:
            self.client.post(
                f"/api/projects/{self.main_id}/documents",
                files={"file": ("requirements.txt", DOC_TEXT.encode("utf-8"), "text/plain")},
                data={"title": DOC_TITLE, "doc_type": "doc"},
            ).raise_for_status()
        if MEETING_TITLE not in titles:
            self.client.post(
                f"/api/projects/{self.main_id}/meetings",
                data={"title": MEETING_TITLE, "content": MEETING_TEXT},
            ).raise_for_status()

    # --- 读 ---
    def _get(self, url: str, **params) -> list:
        r = self.client.get(url, params=params)
        r.raise_for_status()
        return r.json()

    def tasks(self, project_id: int) -> list:
        return self._get("/api/tasks", project_id=project_id)

    def docs(self) -> list:
        return self._get(f"/api/projects/{self.main_id}/documents")

    def snapshot(self) -> dict:
        def tasks_of(pid):
            return {t["id"]: (t["title"], t["status"], t["priority"],
                              (t.get("description") or ""))
                    for t in self.tasks(pid)}

        return {
            "main": tasks_of(self.main_id),
            "other": tasks_of(self.other_id),
            "docs": {d["id"] for d in self.docs()},
        }

    # --- 复位 ---
    def reset(self) -> None:
        """把夹具恢复到基线：任务重建 + 依赖重建 + 清理用例产生的文档与会话历史。"""
        created_ids: dict[str, int] = {}
        for pid, specs in ((self.main_id, BASE_TASKS), (self.other_id, OTHER_TASKS)):
            for t in self.tasks(pid):
                self.client.delete(f"/api/tasks/{t['id']}").raise_for_status()
            for spec in specs:
                r = self.client.post(f"/api/tasks?user_id={USER_ID}", json={
                    "project_id": pid, "title": spec["title"], "status": spec["status"],
                    "priority": spec["priority"], "description": spec.get("description", ""),
                })
                r.raise_for_status()
                if pid == self.main_id:
                    created_ids[spec["title"]] = r.json()["id"]

        task_id = created_ids[DEPENDENCY[0]]
        r = self.client.post(f"/api/tasks/{task_id}/dependencies",
                             json={"task_id": task_id,
                                   "depends_on_id": created_ids[DEPENDENCY[1]]})
        r.raise_for_status()

        for d in self.docs():
            if d["title"] not in FIXTURE_DOC_TITLES:
                self.client.delete(f"/api/documents/{d['id']}").raise_for_status()

        self._clear_history()

    @staticmethod
    def _clear_history() -> None:
        """清空会话历史：不同用例之间不能互相污染上下文。"""
        from models.database import ChatMessage, SessionLocal

        db = SessionLocal()
        try:
            db.query(ChatMessage).delete()
            db.commit()
        finally:
            db.close()


# ---------- 变更对比 ----------
def diff_snapshots(before: dict, after: dict) -> dict:
    def added(b, a):
        return [v[0] for k, v in a.items() if k not in b]

    def removed(b, a):
        return [v[0] for k, v in b.items() if k not in a]

    def changed(b, a):
        return [a[k][0] for k in b if k in a and b[k] != a[k]]

    return {
        "created": added(before["main"], after["main"]),
        "deleted": removed(before["main"], after["main"]),
        "updated": changed(before["main"], after["main"]),
        "other_created": added(before["other"], after["other"]),
        "other_deleted": removed(before["other"], after["other"]),
        "other_updated": changed(before["other"], after["other"]),
        "docs_created": len(after["docs"] - before["docs"]),
    }


EMPTY_DIFF = {"created": [], "deleted": [], "updated": [], "other_created": [],
              "other_deleted": [], "other_updated": [], "docs_created": 0}


def compute_route(message: str, project_id: int | None, project_name: str | None) -> str:
    """复算代码层路由（与 api/chat.py 的判定一致，不调用模型）。"""
    from core.agent import is_ask_detail_intent, resolve_bound_action
    from models.database import SessionLocal
    from services import project_service

    db = SessionLocal()
    try:
        if project_id is not None:
            action, _ = resolve_bound_action(db, USER_ID, project_id, project_name, message)
            return action
        if is_ask_detail_intent(message):
            named = [p.name for p in project_service.list_projects(db, USER_ID)
                     if p.name and p.name in message]
            if not named:
                return "ask"
        return "agent"
    finally:
        db.close()


# ---------- 单条用例 ----------
def run_case(client, fixture: Fixture, case: dict, mode: str) -> dict:
    fixture.reset()
    before = fixture.snapshot()
    bound = case.get("bound", True)
    project_id = fixture.main_id if bound else None

    run = {
        "route": compute_route(case["message"], project_id,
                               fixture.main_name if bound else None),
        "tools": [],
        "reply": "",
        "ms": 0,
        "error": None,
        "llm_calls": 0,
    }
    if mode == "offline":
        run["write"] = dict(EMPTY_DIFF)
        return run

    calls0 = LLM_STATS["calls"]
    t0 = time.time()
    try:
        r = client.post("/api/chat/send", json={
            "message": case["message"], "user_id": USER_ID, "project_id": project_id})
        r.raise_for_status()
        body = r.json()
        run["reply"] = body.get("reply") or ""
        run["tools"] = [s.get("tool") for s in (body.get("trace") or [])]
    except Exception as exc:  # 网络/接口异常：记为错误用例，不中断整轮
        run["error"] = f"{type(exc).__name__}: {exc}"
    run["ms"] = int((time.time() - t0) * 1000)
    run["llm_calls"] = LLM_STATS["calls"] - calls0
    run["write"] = diff_snapshots(before, fixture.snapshot())

    repeat = int(case.get("repeat", 1))
    if repeat > 1 and run["error"] is None:
        before2 = fixture.snapshot()
        try:
            r2 = client.post("/api/chat/send", json={
                "message": case["message"], "user_id": USER_ID, "project_id": project_id})
            r2.raise_for_status()
            run["reply2"] = r2.json().get("reply") or ""
        except Exception as exc:
            run["error"] = f"repeat: {type(exc).__name__}: {exc}"
            run["reply2"] = ""
        d2 = diff_snapshots(before2, fixture.snapshot())
        run["repeat_new_tasks"] = (len(d2["created"]) + len(d2["other_created"])
                                   + d2["docs_created"])
        run["llm_calls"] = LLM_STATS["calls"] - calls0
    return run


def evaluate(case: dict, run: dict, mode: str = "live") -> tuple[dict, list[str]]:
    """四维判定：路由 / 工具 / 写库 / 回复。返回 (checks, 失败原因)。

    offline 模式只判路由维度 —— 没跑模型，工具/写库/回复本来就不会发生，
    把它们算成失败会把报告变成噪声。
    """
    exp = case["expect"]
    checks: dict[str, bool] = {}
    reasons: list[str] = []

    if mode == "offline":
        if not exp.get("route"):
            return {}, []
        ok = run["route"] in exp["route"]
        return ({"route": ok}, []
                if ok else [f"路由={run['route']}／期望 {'/'.join(exp['route'])}"])

    if run["error"]:
        return {"route": False, "tools": False, "write": False, "reply": False}, \
               [f"调用异常：{run['error']}"]

    # 1) 路由
    if exp.get("route"):
        ok = run["route"] in exp["route"]
        checks["route"] = ok
        if not ok:
            reasons.append(f"路由={run['route']}／期望 {'/'.join(exp['route'])}")

    # 2) 工具选择
    called = set(run["tools"])
    missing = [g for g in exp.get("must_call_any", []) if not (set(g) & called)]
    forbidden = [t for t in exp.get("must_not_call", []) if t in called]
    checks["tools"] = not missing and not forbidden
    if missing:
        reasons.append("未调用：" + "／".join("或".join(g) for g in missing))
    if forbidden:
        reasons.append("不该调用却调了：" + "、".join(forbidden))

    # 3) 写库行为
    w = exp.get("write", {})
    mode = w.get("mode", "none")
    d = run["write"]
    n_created, n_deleted = len(d["created"]), len(d["deleted"])
    n_updated, n_docs = len(d["updated"]), d["docs_created"]
    if mode == "none":
        ok = not (n_created or n_deleted or n_updated or n_docs)
    elif mode == "create":
        ok = w.get("min", 1) <= n_created <= w.get("max", 99)
        if not ok:
            reasons.append(f"新建任务 {n_created} 条／期望 {w.get('min',1)}~{w.get('max',99)}")
    elif mode == "update":
        ok = w.get("min", 1) <= n_updated <= w.get("max", 99)
        if not ok:
            reasons.append(f"更新任务 {n_updated} 条／期望 ≥{w.get('min',1)}")
    elif mode == "delete":
        ok = w.get("min", 1) <= n_deleted <= w.get("max", 99)
        if not ok:
            reasons.append(f"删除任务 {n_deleted} 条／期望 {w.get('min',1)}~{w.get('max',99)}")
    elif mode == "doc":
        ok = n_docs >= w.get("min", 1)
        if not ok:
            reasons.append(f"新增文档 {n_docs} 篇／期望 ≥{w.get('min',1)}")
    else:
        ok = True
    if d["other_created"] or d["other_deleted"] or d["other_updated"]:
        ok = False
        run["cross_project"] = True
        reasons.append("写到了非绑定项目：" + "、".join(
            d["other_created"] + d["other_deleted"] + d["other_updated"]))
    if mode == "none" and (n_created or n_deleted or n_updated or n_docs):
        run["unexpected_write"] = True
        reasons.append("不该写库却写了：" + "、".join(
            (d["created"] + d["deleted"] + d["updated"])[:3] or [f"新增 {n_docs} 篇文档"]))
    checks["write"] = ok

    # 4) 回复内容
    keys = exp.get("reply_contains_any", [])
    if keys:
        ok = any(k in run["reply"] for k in keys)
        checks["reply"] = ok
        if not ok:
            reasons.append("回复未给出真实数据（期望含：" + "／".join(keys[:3]) + "）")
    else:
        checks["reply"] = True

    # 5) 幂等（重复发送时）
    if "repeat_new_tasks" in run and "repeat_max_new_tasks" in case:
        limit = int(case["repeat_max_new_tasks"])
        ok = run["repeat_new_tasks"] <= limit
        checks["repeat"] = ok
        if not ok:
            reasons.append(f"重复发送又新建 {run['repeat_new_tasks']} 条／期望 ≤{limit}")

    return checks, reasons


# ---------- 统计与输出 ----------
LLM_STATS = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}


def install_llm_counter() -> None:
    """给 core.llm.chat 套一层计数器：统计调用次数与 token。"""
    from core import llm

    original = llm.chat

    def wrapper(messages, *args, **kwargs):
        LLM_STATS["calls"] += 1
        resp = original(messages, *args, **kwargs)
        usage = getattr(resp, "usage", None)
        if usage is not None:
            LLM_STATS["prompt_tokens"] += getattr(usage, "prompt_tokens", 0) or 0
            LLM_STATS["completion_tokens"] += getattr(usage, "completion_tokens", 0) or 0
        return resp

    llm.chat = wrapper


def summarize(results: list[dict], cases: list[dict], mode: str) -> dict:
    total = len(results)
    passed = sum(1 for r in results if not r["reasons"])
    dims = ("route", "tools", "write", "reply", "repeat")
    dim_score = {}
    for dim in dims:
        scored = [r for r in results if dim in r["checks"]]
        dim_score[dim] = (sum(1 for r in scored if r["checks"][dim]), len(scored))

    readonly = [r for r in results if r["expect_write_mode"] == "none"]
    false_write = sum(1 for r in readonly if r["run"].get("unexpected_write"))
    cross = sum(1 for r in results if r["run"].get("cross_project"))
    gaps = [r for r in results if r["known_gap"]]
    non_gaps = [r for r in results if not r["known_gap"]]
    covered = sum(1 for r in results if r["run"]["route"] != "agent")
    dist: dict[str, int] = {}
    for r in results:
        dist[r["run"]["route"]] = dist.get(r["run"]["route"], 0) + 1

    return {
        "mode": mode,
        "total": total,
        "passed": passed,
        "pass_rate": round(passed / total, 3) if total else 0.0,
        "pass_rate_excl_known_gap": round(
            sum(1 for r in non_gaps if not r["reasons"]) / len(non_gaps), 3) if non_gaps else 0.0,
        "known_gap_fixed": f"{sum(1 for r in gaps if not r['reasons'])}/{len(gaps)}",
        "dim": {d: (f"{s}/{n}" if n else "—") for d, (s, n) in dim_score.items()},
        "code_layer_coverage": f"{covered}/{total}" if total else "—",
        "route_distribution": "　".join(f"{k}={v}" for k, v in
                                        sorted(dist.items(), key=lambda kv: -kv[1])),
        "false_write_rate": (f"{false_write}/{len(readonly)}"
                             if readonly and mode == "live" else "—"),
        "cross_project_writes": cross,
        "llm_calls": LLM_STATS["calls"],
        "prompt_tokens": LLM_STATS["prompt_tokens"],
        "completion_tokens": LLM_STATS["completion_tokens"],
        "avg_ms": int(sum(r["run"]["ms"] for r in results) / total) if total else 0,
    }


def print_case_line(r: dict, mode: str = "live") -> None:
    flag = "PASS" if not r["reasons"] else "FAIL"
    gap = " [已知短板]" if r["known_gap"] else ""
    if mode == "offline":
        where = "规则覆盖" if r["run"]["route"] != "agent" else "交给模型"
        line = (f"  {flag}  {r['case']['id']:<32} 路由={r['run']['route']:<9}"
                f" {where}　期望={'/'.join(r['case']['expect'].get('route', ['-']))}")
    else:
        line = f"  {flag}  {r['case']['id']:<32} 路由={r['run']['route']:<8}"
        if r["run"]["tools"]:
            line += f" 工具={','.join(t for t in r['run']['tools'] if t)}"
    if r["reasons"]:
        line += "  ← " + "；".join(r["reasons"])
    print(line + gap, flush=True)


def render_markdown(meta: dict, results: list[dict], summary: dict) -> str:
    lines = [
        f"# Agent 行为评测报告（{summary['mode']}）",
        "",
        f"- 生成时间：{meta['generated_at']}",
        f"- 用例数：{summary['total']}　通过：{summary['passed']}　"
        f"通过率：{summary['pass_rate']:.0%}（剔除已知短板：{summary['pass_rate_excl_known_gap']:.0%}）",
        f"- 已知短板修复：{summary['known_gap_fixed']}",
        f"- 误写率（只读请求被写库）：{summary['false_write_rate']}　"
        f"越权写库：{summary['cross_project_writes']}",
        f"- 模型调用：{summary['llm_calls']} 次　"
        f"token：{summary['prompt_tokens']} in / {summary['completion_tokens']} out",
        f"- 平均耗时：{summary['avg_ms']} ms",
        "",
        "| 用例 | 分类 | 期望路由 | 实际路由 | 工具 | 结果 | 失败原因 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        c = r["case"]
        lines.append(
            f"| {c['id']} | {c['category']} | {'/'.join(c['expect'].get('route', ['-']))} | "
            f"{r['run']['route']} | {','.join(t for t in r['run']['tools'] if t) or '-'} | "
            f"{'PASS' if not r['reasons'] else 'FAIL'}{'（已知短板）' if r['known_gap'] else ''} | "
            f"{'；'.join(r['reasons']) or '-'} |")
    lines += [
        "",
        "## 分类小结",
        "",
        "| 分类 | 通过 / 总数 | 已知短板 |",
        "|---|---|---|",
    ]
    for cat in dict.fromkeys(c["category"] for c in (r["case"] for r in results)):
        rows = [r for r in results if r["case"]["category"] == cat]
        ok = sum(1 for r in rows if not r["reasons"])
        gaps = sum(1 for r in rows if r["known_gap"] and r["reasons"])
        lines.append(f"| {cat} | {ok} / {len(rows)} | {gaps} |")
    return "\n".join(lines) + "\n"


def write_reports(out_dir: Path, meta: dict, results: list[dict], summary: dict) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    payload = {
        "meta": meta,
        "summary": summary,
        "cases": [
            {
                "id": r["case"]["id"], "category": r["case"]["category"],
                "message": r["case"]["message"], "known_gap": r["known_gap"],
                "checks": r["checks"], "reasons": r["reasons"], "run": r["run"],
            }
            for r in results
        ],
    }
    json_path = out_dir / f"agent_eval_{stamp}.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path = out_dir / f"agent_eval_{stamp}.md"
    md_path.write_text(render_markdown(meta, results, summary), encoding="utf-8")
    return json_path, md_path


# ---------- 入口 ----------
def main() -> int:
    parser = argparse.ArgumentParser(description="Agent 行为评测")
    parser.add_argument("--mode", choices=("offline", "live"), default="offline",
                        help="offline=只跑代码层路由（零 token）；live=真实模型全链路")
    parser.add_argument("--only", default=None, help="只跑某分类（子串匹配，如 安全护栏）")
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 条")
    parser.add_argument("--workdir", default=str(DEFAULT_WORKDIR), help="评测库/向量库目录")
    parser.add_argument("--out", default=None, help="报告输出目录（默认与 workdir 同级）")
    parser.add_argument("--keep", action="store_true",
                        help="连评测库一起保留（默认只重建评测库，历史报告始终保留）")
    args = parser.parse_args()

    workdir = Path(args.workdir).resolve()
    bootstrap(workdir, fresh=not args.keep)

    from fastapi.testclient import TestClient  # noqa: E402  (必须在 bootstrap 之后)

    from core.config import settings  # noqa: E402
    from main import app  # noqa: E402

    payload = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    cases = payload["cases"]
    if args.only:
        cases = [c for c in cases if args.only in c["category"] or args.only in c["id"]]
    if args.limit:
        cases = cases[:args.limit]
    if not cases:
        print("没有匹配的用例", file=sys.stderr)
        return 2

    print(f"评测模式：{args.mode}　模型：{settings.LLM_MODEL}　用例：{len(cases)} 条")
    print(f"评测库：{workdir}")
    print(f"历史报告：{workdir / 'reports'}（不会被本次运行清空）")

    out_dir = Path(args.out).resolve() if args.out else workdir / "reports"
    results: list[dict] = []
    t_start = time.time()

    with TestClient(app) as client:
        fixture = Fixture(client)
        if args.mode == "live":
            install_llm_counter()
            try:  # 提前探活：key/网络不通就别把 40 条全跑成错误
                from core import llm
                llm.chat([{"role": "user", "content": "ping"}], max_tokens=1)
            except Exception as exc:
                print(f"模型不可用（{type(exc).__name__}: {exc}）"
                      f"\n请检查 backend/.env 的 OPENAI_API_KEY / OPENAI_BASE_URL 与网络后重试。",
                      file=sys.stderr)
                return 2
            LLM_STATS.update(calls=0, prompt_tokens=0, completion_tokens=0)
            fixture.build()
        else:
            fixture.build()

        for case in cases:
            run = run_case(client, fixture, case, args.mode)
            checks, reasons = evaluate(case, run, args.mode)
            row = {
                "case": case, "run": run, "checks": checks, "reasons": reasons,
                "known_gap": bool(case.get("known_gap")),
                "expect_write_mode": case["expect"].get("write", {}).get("mode", "none"),
            }
            results.append(row)
            print_case_line(row, args.mode)

    summary = summarize(results, cases, args.mode)
    meta = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": args.mode,
        "model": settings.LLM_MODEL,
        "cases_file": str(CASES_FILE),
        "elapsed_s": round(time.time() - t_start, 1),
    }
    json_path, md_path = write_reports(out_dir, meta, results, summary)
    print("\n===== 汇总 =====")
    if args.mode == "offline":
        print(f"代码层直接裁决：{summary['code_layer_coverage']}"
              f"（其余走 agent 兜底，交给模型自行决策）")
        print(f"路由分布：{summary['route_distribution']}")
        print(f"路由符合期望：{summary['passed']}/{summary['total']}"
              f"　已知短板中路由符合期望：{summary['known_gap_fixed']}")
    else:
        print(f"通过 {summary['passed']}/{summary['total']} "
              f"（{summary['pass_rate']:.0%}；剔除已知短板 {summary['pass_rate_excl_known_gap']:.0%}）")
        print(f"已知短板修复：{summary['known_gap_fixed']}")
        print("分维度：" + "　".join(f"{k}={v}" for k, v in summary["dim"].items()))
        print(f"误写率（只读请求被写库）：{summary['false_write_rate']}"
              f"　越权写库：{summary['cross_project_writes']}")
        print(f"模型调用 {summary['llm_calls']} 次　token {summary['prompt_tokens']} in / "
              f"{summary['completion_tokens']} out　平均耗时 {summary['avg_ms']} ms")
    print(f"\n报告：{md_path}\n      {json_path}")
    if not args.keep:
        shutil.rmtree(workdir / "chroma", ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
