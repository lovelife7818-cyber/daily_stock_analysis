#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
今日经济数据段落生成器
==========================================================
在日报工作流里，于个股分析之后、发布 Issue 之前运行。

产出 /tmp/econ.md：一段「先结论、再数据、来源折叠」的当日美国经济数据解读。

为什么需要它
------------
上游项目本身没有宏观/经济数据模块（代码里搜「经济数据」「宏观」命中 0）。
日报因此只能从个股技术面出发，看不到当天 8:30 发布的经济数据。
本脚本用 Tavily 检索 + Gemini 撰文补上这一层。

硬约束
------
- 只允许使用检索结果里出现过的数字；检索不到就写「未获取」，**绝不编造**
- 零依赖（纯标准库）
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122 Safari/537.36")
BJ = timezone(timedelta(hours=8))
ET = timezone(timedelta(hours=-4))     # 美东夏令时；脚本只用于生成查询词与展示

GEMINI_MODELS = ["gemini-2.5-flash", "gemini-3-flash-preview", "gemini-flash-latest"]


def tavily(query: str, max_results: int = 5) -> list[dict]:
    key = os.environ.get("TAVILY_API_KEY") or os.environ.get("TAVILY_API_KEYS")
    if not key:
        return []
    key = key.split(",")[0].strip()
    try:
        body = json.dumps({"query": query, "max_results": max_results,
                           "search_depth": "advanced", "topic": "news", "days": 2}).encode()
        req = urllib.request.Request(
            "https://api.tavily.com/search", data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {key}", "User-Agent": UA})
        with urllib.request.urlopen(req, timeout=40) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        return [{"title": (x.get("title") or "").strip(), "url": x.get("url") or "",
                 "content": re.sub(r"\s+", " ", x.get("content") or "")[:600]}
                for x in d.get("results", [])]
    except Exception as e:                                     # noqa: BLE001
        print(f"[WARN] tavily 失败: {e}", file=sys.stderr)
        return []


def gemini(prompt: str) -> tuple[str | None, str]:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None, "未配置 GEMINI_API_KEY"
    models = ([os.environ["GEMINI_MODEL"]] if os.environ.get("GEMINI_MODEL")
              else []) + GEMINI_MODELS
    last = ""
    for m in models:
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/{m}"
               f":generateContent?key={key}")
        for gi, gen in enumerate([
                {"temperature": 0.2, "maxOutputTokens": 4096,
                 "thinkingConfig": {"thinkingBudget": 0}},
                {"temperature": 0.2, "maxOutputTokens": 4096}]):
            payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": gen}
            req = urllib.request.Request(
                url, data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json", "User-Agent": UA})
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    d = json.loads(r.read().decode("utf-8", "replace"))
                cand = d["candidates"][0]
                txt = "".join(p.get("text", "") for p in
                              cand.get("content", {}).get("parts", [])
                              if not p.get("thought")).strip()
                if txt and cand.get("finishReason") != "MAX_TOKENS":
                    print(f"[INFO] econ: gemini={m} 输出 {len(txt)} 字符")
                    return txt, m
                last = f"{m}: 截断/空"
            except urllib.error.HTTPError as e:
                last = f"{m}: HTTP {e.code}"
                if gi == 0 and e.code == 400:
                    continue
                print(f"[WARN] econ gemini {last}", file=sys.stderr)
                break
            except Exception as e:                             # noqa: BLE001
                last = f"{m}: {e}"
                print(f"[WARN] econ gemini {last}", file=sys.stderr)
                break
    return None, last


def main() -> int:
    now_bj = datetime.now(BJ)
    day = now_bj.strftime("%Y-%m-%d")
    # 美东当天日期（检索英文新闻时用）
    day_et = datetime.now(ET).strftime("%B %d, %Y")

    queries = [
        f"US economic data released today {day_et} actual vs forecast CPI PPI jobless claims",
        f"economic calendar today United States key releases {day_et}",
        f"US market reaction to economic data {day_et} Treasury yields dollar",
    ]
    items, seen = [], set()
    for q in queries:
        for r in tavily(q):
            if r["url"] and r["url"] not in seen:
                seen.add(r["url"]); items.append(r)

    if not items:
        print("[WARN] 经济数据检索无结果，跳过该段落", file=sys.stderr)
        return 0

    src = "\n".join(f"- {r['title']}\n  {r['content']}\n  ({r['url']})" for r in items[:15])

    prompt = f"""你是卖方宏观策略师。今天是北京时间 {day}，美股盘前。
下面是最近 48 小时的英文新闻检索结果，请据此写一份「今日经济数据」段落。

【检索结果】
{src}

严格按下面格式输出，每行一个字段，不要额外标题、不要代码块：

VERDICT: 一句话（40-70 字）—— 今天公布的数据整体偏强/偏弱/中性，把市场往哪个方向推
HOLDING: 一句话（30-55 字）—— 对「美股科技成长股 + 加密概念股」意味着什么
DATA:
- 数据名｜实际值｜预期值｜一句话影响（最多 4 条）
PENDING:
- 待公布数据名｜北京时间几点｜为什么值得看（最多 3 条；没有就写「无」）

硬性约束：
1. 【最重要】**只允许使用上面检索结果里出现过的数字**。材料里没有的数字一律不许出现。
   只找到名字没找到数值的，实际值写「未获取」。
2. 完全没有当天数据 → VERDICT 写「今日未检索到明确的经济数据发布」，DATA 写「- 无」。
3. 不要写免责声明，不要写「综上所述」。
4. VERDICT 和 HOLDING 必须各占一行，不能省略。数据名用中文。"""

    txt, note = gemini(prompt)
    if not txt:
        print(f"[WARN] 经济数据段落生成失败：{note}", file=sys.stderr)
        return 0

    lines = txt.splitlines()
    l1 = l2 = ""
    data, pending = [], []
    mode = None
    for ln in lines:
        s = ln.strip()
        if s.startswith("VERDICT:"):
            l1 = s[8:].strip()
        elif s.startswith("HOLDING:"):
            l2 = s[8:].strip()
        elif s.startswith("DATA:"):
            mode = "data"
        elif s.startswith("PENDING:"):
            mode = "pending"
        elif s.startswith(("-", "•", "*")):
            (data if mode == "data" else pending if mode == "pending" else []).append(
                s.lstrip("-•* ").strip())

    out = ["## 📅 今日经济数据", ""]
    if l1:
        out += [f"**{l1}**", ""]
    if l2:
        out += [f"对持仓：{l2}", ""]
    if data and data != ["无"]:
        out += ["| 数据 | 实际 | 预期 | 影响 |", "|:--|--:|--:|:--|"]
        for row in data[:4]:
            p = [x.strip() for x in row.split("｜")] + [""] * 4
            if not p[0] or p[0] == "无":
                continue
            out.append(f"| {p[0]} | {p[1] or '—'} | {p[2] or '—'} | {p[3][:60]} |")
        out.append("")
    if pending and pending != ["无"]:
        out += ["**待公布**", ""]
        for row in pending[:3]:
            p = [x.strip() for x in row.split("｜")]
            if p and p[0] and p[0] != "无":
                out.append(f"- {p[0]}｜{p[1] if len(p) > 1 else ''}｜"
                           f"{p[2] if len(p) > 2 else ''}")
        out.append("")
    out += ["<details><summary>数据来源</summary>", ""]
    for r in items[:10]:
        out.append(f"- [{r['title'][:90]}]({r['url']})")
    out += ["", "</details>", ""]

    body = "\n".join(out)
    path = os.environ.get("ECON_OUT", "/tmp/econ.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    print(f"[OK] 经济数据段落已生成 {path} ({len(body)} 字符)")
    print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
