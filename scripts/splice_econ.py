#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把经济数据段落插进 Issue 正文（插在「操作要点」之前）。

用法: python scripts/splice_econ.py <issue_body> <econ_section>
环境变量 MARKER 可覆盖插入锚点，默认 "## 🎯 操作要点"
"""
import os
import sys


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    body_path, econ_path = sys.argv[1], sys.argv[2]
    if not (os.path.exists(body_path) and os.path.exists(econ_path)):
        print("[WARN] 文件缺失，跳过拼接")
        return 0

    body = open(body_path, encoding="utf-8").read()
    econ = open(econ_path, encoding="utf-8").read().strip()
    if not econ:
        print("[WARN] 经济数据段落为空，跳过")
        return 0

    marker = os.environ.get("MARKER", "## 🎯 操作要点")
    block = econ + "\n\n---\n\n"
    if marker and marker in body:
        body = body.replace(marker, block + marker, 1)
    else:
        body = block + body

    with open(body_path, "w", encoding="utf-8") as f:
        f.write(body)
    print(f"[OK] 已插入经济数据段落（{len(econ)} 字符），正文现 {len(body)} 字符")
    return 0


if __name__ == "__main__":
    sys.exit(main())
