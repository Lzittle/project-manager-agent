#!/usr/bin/env python
"""终态评测（L4）：多轮真实对话之后，断言**数据库的最终状态**对不对。

为什么单开一层（roadmap 阶段 3）：前面两层看的是「这句话路由对不对 / 工具选对没有」，
但会改状态的 agent 真正的失分点是**最终结果**——连说几句之后，任务到底是不是那个状态。
本轮新增的批量写与撤销，验收标准本身就是终态（撤销后回到原样），所以这把尺子必须有。

  ../venv/Scripts/python.exe eval/run_terminal_eval.py                 # 全量（真模型，消耗 token）
  ../venv/Scripts/python.exe eval/run_terminal_eval.py --only 批量写终态
  ../venv/Scripts/python.exe eval/run_terminal_eval.py --keep          # 保留评测库便于排查

与 run_agent_eval.py 共用同一套夹具（两项目 / 6 任务 / 3 文档 / 2 成员），
每条用例先把夹具复位到基线，再按 turns 说话，最后一轮跑完读库断言。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_WORKDIR = Path(__import__("tempfile").gettempdir()) / "squad_terminal_eval"

sys.path.insert(0, str(EVAL_DIR))  # 复用 run_agent_eval 的夹具与 bootstrap


def _read_state(client, main_id: int, other_id: int) -> dict:
    """读两个项目的真实任务状态（终态断言的唯一依据）。"""
    def tasks_of(pid):
        return client.get("/api/tasks", params={"project_id": pid}).json()

    main, other = tasks_of(main_id), tasks_of(other_id)
    return {
        "main": {t["title"]: t for t in main},
        "other": {t["title"]: t for t in other},
        "main_count": len(main),
        "other_count": len(other),
    }


def check_case(case: dict, state: dict, turns_changed: list[bool]) -> list[str]:
    """按用例里的断言逐项核对终态；返回失败原因（空 = 通过）。"""
    exp = case.get("expect_final") or {}
    reasons: list[str] = []
    for title, want in (exp.get("tasks") or {}).items():
        got = state["main"].get(title)
        if got is None:
            reasons.append(f"任务「{title}」不存在")
            continue
        for field, value in want.items():
            actual = got.get(field)
            # 没负责人时接口回 null、用例里写 ""——两种都表示"没人"，别让尺子自己判错
            same = (not actual if (field == "assignee_name" and value == "") else actual == value)
            if not same:
                reasons.append(f"「{title}」的 {field} = {actual!r}／期望 {value!r}")
    for title in exp.get("absent") or []:
        if title in state["main"]:
            reasons.append(f"「{title}」本该被删掉，却还在")
    for title in exp.get("present") or []:
        if title not in state["main"] and title not in state["other"]:
            reasons.append(f"「{title}」本该还在，却被删掉了")
    if "task_count" in exp and state["main_count"] != exp["task_count"]:
        reasons.append(f"主项目任务数 {state['main_count']}／期望 {exp['task_count']}")
    if "other_task_count" in exp and state["other_count"] != exp["other_task_count"]:
        reasons.append(f"邻项目任务数 {state['other_count']}／期望 {exp['other_task_count']}")
    for turn, want in (case.get("expect_after_turn") or {}).items():
        idx = int(turn) - 1
        if idx >= len(turns_changed):
            continue
        if turns_changed[idx] is not want.get("changed", True):
            reasons.append(f"第 {turn} 轮{'有' if turns_changed[idx] else '没有'}写库／"
                           f"期望{'有' if want.get('changed') else '没有'}")
    return reasons


def render(report: dict, rows: list[dict]) -> str:
    lines = [
        f"# 终态评测报告（live）", "",
        f"- 生成时间：{report['generated_at']}",
        f"- 用例：{report['total']}　通过：{report['passed']}　平均耗时：{report['avg_ms']} ms",
        f"- 模型调用：{report['llm_calls']} 次　token：{report['prompt_tokens']} in / "
        f"{report['completion_tokens']} out",
        "", "| 用例 | 分类 | 轮数 | 结果 | 失败原因 |", "|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['id']} | {r['category']} | {r['turns']} | "
                     f"{'PASS' if not r['reasons'] else 'FAIL'} | "
                     f"{'；'.join(r['reasons']) or '-'} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Agent 终态评测（L4，真模型）")
    parser.add_argument("--only", default=None, help="只跑某分类或 id（子串匹配）")
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 条")
    parser.add_argument("--workdir", default=str(DEFAULT_WORKDIR))
    parser.add_argument("--keep", action="store_true", help="保留评测库便于排查")
    args = parser.parse_args()

    import run_agent_eval as base  # noqa: E402  （先设好环境变量再导入应用）

    workdir = Path(args.workdir).resolve()
    base.bootstrap(workdir, fresh=not args.keep)

    from fastapi.testclient import TestClient  # noqa: E402

    from core import llm  # noqa: E402
    from core.config import settings  # noqa: E402
    from main import app  # noqa: E402

    cases = json.loads((EVAL_DIR / "terminal_eval_cases.json").read_text(encoding="utf-8"))["cases"]
    if args.only:
        cases = [c for c in cases if args.only in c["category"] or args.only in c["id"]]
    if args.limit:
        cases = cases[:args.limit]
    if not cases:
        print("没有匹配的用例", file=sys.stderr)
        return 2

    print(f"终态评测　模型：{settings.LLM_MODEL}　用例：{len(cases)} 条")
    rows: list[dict] = []
    t_start = time.time()

    with TestClient(app) as client:
        base.install_llm_counter()
        try:  # 提前探活：key/网络不通就别把每条都跑成错误
            llm.chat([{"role": "user", "content": "ping"}], max_tokens=1)
        except Exception as exc:
            print(f"模型不可用（{type(exc).__name__}: {exc}）\n"
                  f"请检查 backend/.env 的 OPENAI_API_KEY / OPENAI_BASE_URL 与网络后重试。",
                  file=sys.stderr)
            return 2
        base.LLM_STATS.update(calls=0, prompt_tokens=0, completion_tokens=0)
        fixture = base.Fixture(client)
        fixture.build()

        for case in cases:
            fixture.reset()
            turns_changed: list[bool] = []
            before = fixture.snapshot()
            error = None
            t0 = time.time()
            for message in case["turns"]:
                try:
                    r = client.post("/api/chat/send", json={
                        "message": message, "user_id": base.USER_ID,
                        "project_id": fixture.main_id})
                    r.raise_for_status()
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                    break
                after = fixture.snapshot()
                turns_changed.append(base.diff_snapshots(before, after) != base.EMPTY_DIFF)
                before = after
            state = _read_state(client, fixture.main_id, fixture.other_id)
            reasons = [f"调用异常：{error}"] if error else check_case(case, state, turns_changed)
            ms = int((time.time() - t0) * 1000)
            row = {"id": case["id"], "category": case["category"],
                   "turns": len(case["turns"]), "reasons": reasons, "ms": ms,
                   "changed": turns_changed, "state": {
                       "main": {k: (v["status"], v.get("assignee_name") or "")
                                for k, v in state["main"].items()},
                       "counts": [state["main_count"], state["other_count"]]}}
            rows.append(row)
            flag = "PASS" if not reasons else "FAIL"
            print(f"  {flag}  {case['id']:<40} 轮数={len(case['turns'])} "
                  f"写库={turns_changed}"
                  + ("  ← " + "；".join(reasons) if reasons else ""), flush=True)

    passed = sum(1 for r in rows if not r["reasons"])
    summary = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(rows), "passed": passed,
        "avg_ms": int(sum(r["ms"] for r in rows) / len(rows)) if rows else 0,
        "llm_calls": base.LLM_STATS["calls"],
        "prompt_tokens": base.LLM_STATS["prompt_tokens"],
        "completion_tokens": base.LLM_STATS["completion_tokens"],
        "elapsed_s": round(time.time() - t_start, 1),
    }
    out_dir = workdir / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    (out_dir / f"terminal_eval_{stamp}.json").write_text(
        json.dumps({"summary": summary, "cases": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    md = out_dir / f"terminal_eval_{stamp}.md"
    md.write_text(render(summary, rows), encoding="utf-8")
    print(f"\n===== 汇总 =====\n通过 {passed}/{len(rows)}"
          f"　平均耗时 {summary['avg_ms']} ms　模型调用 {summary['llm_calls']} 次"
          f"　token {summary['prompt_tokens']} in / {summary['completion_tokens']} out")
    print(f"报告：{md}")
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
