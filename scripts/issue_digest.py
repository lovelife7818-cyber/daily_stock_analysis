#!/usr/bin/env python3
"""把 daily_stock_analysis 生成的报告压成一份「一眼看完」的 Issue 正文。

用法:
    python scripts/issue_digest.py <report.md> <out.md> [run_number]

环境变量:
    MARKET_REVIEW_FILE  大盘复盘 md 路径（可选，存在则折叠附在末尾）

设计目标：把 40KB / 上千行的原始报告变成
    1. 一张速览表（标的 / 决策 / 评分 / 情绪）
    2. 每只票的操作要点（一句话决策 + 空仓者/持仓者建议）
    3. 完整原文折叠在 <details> 里，需要时再点开
"""
import os
import re
import sys

FRONT = re.compile(
    r"^(?P<icon>\S+)\s+\*\*(?P<label>.+?)\*\*\s*[:：]\s*"
    r"(?P<decision>[^|]+?)\s*\|\s*评分\s*(?P<score>\d+)\s*\|\s*(?P<mood>.+?)\s*$"
)
CODE_IN_LABEL = re.compile(r"\(([A-Z0-9][A-Z0-9.\-]{0,9})\)\s*$")
SECTION_TITLE = re.compile(r"^##\s+(?P<icon>\S+)?\s*(?P<title>.+?)\s*$")
CONCLUSION_LINE = re.compile(r"^\*\*\s*(?P<decision>[^*]+?)\s*\*\*\s*\|\s*(?P<mood>.+?)\s*$")
ONE_LINER = re.compile(r"^\s*>\s*\*\*一句话决策\*\*\s*[:：]\s*(?P<text>.+?)\s*$")
ADVICE_ROW = re.compile(r"^\|\s*(?P<icon>[^\s|]+)\s*\*\*(?P<who>[^*|]+?)\*\*\s*\|\s*(?P<advice>.+?)\s*\|\s*$")

SKIP_TITLES = ("分析结果摘要",)


def split_sections(text):
    """按 '## ' 切成 (标题行, 正文行列表)，丢掉顶部一级标题和摘要块。"""
    sections, cur, buf = [], None, []
    for line in text.splitlines():
        if line.startswith("## "):
            if cur is not None:
                sections.append((cur, buf))
            cur, buf = line, []
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        sections.append((cur, buf))
    return sections


def parse_report(text):
    """返回 (摘要行列表, 个股区块列表)。"""
    summary = []
    for line in text.splitlines():
        m = FRONT.match(line.strip())
        if m:
            label = m.group("label")
            cm = CODE_IN_LABEL.search(label)
            code = cm.group(1) if cm else None
            name = CODE_IN_LABEL.sub("", label).strip().rstrip(",").strip()
            summary.append({
                "icon": m.group("icon"),
                "name": name,
                "code": code,
                "decision": m.group("decision").strip(),
                "score": int(m.group("score")),
                "mood": m.group("mood").strip(),
            })

    blocks = []
    for title, lines in split_sections(text):
        tm = SECTION_TITLE.match(title)
        if not tm:
            continue
        raw_title = tm.group("title").strip()
        if any(s in raw_title for s in SKIP_TITLES):
            continue
        cm = CODE_IN_LABEL.search(raw_title)
        code = cm.group(1) if cm else None
        name = CODE_IN_LABEL.sub("", raw_title).strip().rstrip(",").strip()

        decision, mood, one_liner, advice = None, None, None, []
        for line in lines:
            if decision is None:
                dm = CONCLUSION_LINE.match(line.strip())
                if dm and not dm.group("decision").strip().startswith("⚠"):
                    decision = dm.group("decision").strip()
                    mood = dm.group("mood").strip()
                    continue
            om = ONE_LINER.match(line)
            if om and one_liner is None:
                one_liner = om.group("text").strip()
                continue
            am = ADVICE_ROW.match(line)
            if am:
                advice.append((am.group("icon"), am.group("who").strip(), am.group("advice").strip()))
        blocks.append({
            "code": code, "name": name, "decision": decision,
            "mood": mood, "one_liner": one_liner, "advice": advice,
        })
    return summary, blocks


def pick(blocks, row, index):
    if row.get("code"):
        for b in blocks:
            if b["code"] == row["code"]:
                return b
    return blocks[index] if index < len(blocks) else {}


def build_digest(report_path, market_path=None, run_number=None):
    text = open(report_path, encoding="utf-8", errors="replace").read()
    summary, blocks = parse_report(text)

    # 头部统计（沿用报告自己的口径）
    head_stat = ""
    for line in text.splitlines()[:12]:
        if "只股票" in line:
            head_stat = line.lstrip("> ").strip()
            break

    out = []
    out.append("## 📊 今日速览")
    out.append("")
    if head_stat:
        out.append(f"> {head_stat}")
    out.append(f"> 数据源: daily_stock_analysis · 标的: {len(summary)} 只")
    out.append("")
    out.append("| 标的 | 决策 | 评分 | 情绪 |")
    out.append("|:--|:--|--:|:--|")
    for row in summary:
        code = row["code"] or row["name"]
        out.append(f"| **{code}** | {row['icon']} {row['decision']} | {row['score']} | {row['mood']} |")
    out.append("")
    out.append("---")
    out.append("")
    out.append("## 🎯 操作要点")
    out.append("")

    for i, row in enumerate(summary):
        b = pick(blocks, row, i)
        code = row["code"] or row["name"]
        out.append(f"### {row['icon']} {code} · {row['decision']} · {row['score']} 分")
        if b.get("one_liner"):
            out.append("")
            out.append(f"> {b['one_liner']}")
        if b.get("advice"):
            out.append("")
            for icon, who, advice in b["advice"]:
                out.append(f"- {icon} **{who}**：{advice}")
        out.append("")

    # 没有进摘要表的区块也提示一下，避免漏掉
    listed = {r["code"] for r in summary if r["code"]}
    extras = [b for b in blocks if b["code"] and b["code"] not in listed]
    if extras:
        out.append(f"> 另有 {len(extras)} 个未进入摘要的区块: " + "、".join(b["code"] for b in extras))
        out.append("")

    out.append("---")
    out.append("")

    # 原文折叠
    kb = max(1, len(text.encode("utf-8")) // 1024)
    out.append("<details>")
    out.append(f"<summary><b>📄 展开完整报告（{kb} KB，含行情 / 均线 / 作战计划）</b></summary>")
    out.append("")
    out.append(text)
    out.append("")
    out.append("</details>")
    out.append("")

    if market_path and os.path.exists(market_path):
        mk = open(market_path, encoding="utf-8", errors="replace").read()
        out.append("<details>")
        out.append("<summary><b>🌏 展开大盘复盘</b></summary>")
        out.append("")
        out.append(mk)
        out.append("")
        out.append("</details>")
        out.append("")

    if run_number:
        out.append(f"> _运行 #{run_number} · 由 GitHub Actions 自动生成_")
        out.append("")

    return "\n".join(out)


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    report_path, out_path = sys.argv[1], sys.argv[2]
    run_number = sys.argv[3] if len(sys.argv) > 3 else None
    body = build_digest(report_path, os.environ.get("MARKET_REVIEW_FILE"), run_number)

    # GitHub Issue 正文上限 65536 字符，超了就把折叠原文截掉
    LIMIT = 60000
    if len(body) > LIMIT:
        cut = body[:LIMIT]
        body = cut + "\n\n> ⚠️ 正文超长已截断，完整报告见本次运行的 Artifacts。\n"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(body)
    print(f"已生成 Issue 正文: {out_path} ({len(body)} 字符)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
