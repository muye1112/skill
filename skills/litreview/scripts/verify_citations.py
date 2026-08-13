#!/usr/bin/env python3
"""引用真实性校验 —— 引用防御第 5 层的可执行部分。

做四件事：
1. 从 Markdown 里提取所有 DOI 和引用标记
2. 逐个查 Crossref 确认 DOI 真实存在
3. 比对标题是否匹配（抓「DOI 真实但配错文献」）
4. 检查是否已撤稿（比不存在的 DOI 危害更大）

用法：
    python verify_citations.py review.md
    python verify_citations.py review.md --email you@example.com --json report.json

只用标准库，不需要 pip install。
"""

from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CTX = ssl.create_default_context()
CROSSREF = "https://api.crossref.org/works"

# DOI 的实际格式比规范宽松，这个模式覆盖绝大多数真实情况
DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:a-z0-9A-Z]+", re.I)
# 结尾的标点不属于 DOI
DOI_TRAIL = re.compile(r"[.,;:)\]}>'\"]+$")


def clean_doi(doi: str) -> str:
    return DOI_TRAIL.sub("", doi.strip()).lower()


def norm_title(t: str) -> str:
    t = re.sub(r"<[^>]+>", " ", t or "")
    t = re.sub(r"[^a-z0-9]+", " ", t.lower())
    return " ".join(t.split())


def similar(a: str, b: str) -> float:
    """标题匹配度 0~1。

    不能直接用 SequenceMatcher —— 文档里常只写标题前半段（期刊要求缩写、
    或作者手动截断），实测「Probiotic Supplementation Improves Cognitive
    Function and Mood」对完整的 195 字标题只得 0.49，会误报成配错文献。

    改用「词覆盖率 + 前缀」双判据：
      截断标题：覆盖率 1.00、是前缀  → 判为匹配
      配错文献：覆盖率 0.30、非前缀  → 判为不匹配
    这两种情况用覆盖率能干净分开。
    """
    na, nb = norm_title(a), norm_title(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    # 一方是另一方的前缀 —— 典型的标题截断，视为匹配
    if nb.startswith(na) or na.startswith(nb):
        return 1.0
    wa, wb = set(na.split()), set(nb.split())
    if not wa:
        return 0.0
    coverage = len(wa & wb) / len(wa)
    # 覆盖率为主，序列相似度作为辅助（防止词序完全打乱的情况）
    return max(coverage, SequenceMatcher(None, na, nb).ratio())


def fetch(doi: str, email: str = "", retries: int = 3) -> dict | None:
    """查 Crossref。返回 None 表示 DOI 不存在（或查不到）。"""
    url = f"{CROSSREF}/{urllib.parse.quote(doi, safe='/')}"
    if email:
        url += f"?mailto={urllib.parse.quote(email)}"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": f"verify-citations/1.0 (mailto:{email})" if email
                              else "verify-citations/1.0",
            })
            with urllib.request.urlopen(req, timeout=30, context=CTX) as r:
                return json.load(r).get("message")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None          # DOI 确实不存在 —— 这是我们要抓的
            if e.code in (429, 500, 502, 503) and attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            return None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            return None
    return None


def extract(text: str) -> list[dict]:
    """提取每个 DOI 及其所在行。

    按行切分而不是按字符窗口 —— 参考文献条目基本都是一行一条，
    用字符窗口会把上一条的内容也吃进来，导致标题比对误报。
    同一个 DOI 出现在不同行要分别记录：这正是「张冠李戴」的典型形态
    （一个真实 DOI 被复制到另一篇文献的条目上）。
    """
    out: list[dict] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for m in DOI_RE.finditer(line):
            doi = clean_doi(m.group())
            out.append({
                "doi": doi,
                # 上下文只取本行 —— 干净得多
                "context": line.strip(),
                "line": lineno,
            })
    return out


def guess_title(context: str) -> str:
    """从一行参考文献里猜标题。

    典型格式：作者. 标题. 期刊. 年. doi:10.xxx
    标题通常是最长的那个句子片段（比作者名和期刊名长）。
    """
    c = DOI_RE.sub(" ", context)
    c = re.sub(r"(?i)\b(doi|https?://doi\.org/)\s*:?\s*", " ", c)
    # 中文引导句常在最前面，去掉纯中文片段
    parts = [p.strip(" .*_[]()、，") for p in re.split(r"[.。]\s*", c)]
    cand = []
    for p in parts:
        if len(p) < 20:
            continue
        # 跳过纯中文段（那是我们自己写的引导语，不是文献标题）
        latin = sum(1 for ch in p if ch.isascii() and ch.isalpha())
        if latin < len(p) * 0.5:
            continue
        # 跳过看起来像期刊+年份的短尾巴
        if re.match(r"^\d{4}\b", p):
            continue
        cand.append(p)
    return max(cand, key=len) if cand else ""


def main() -> int:
    ap = argparse.ArgumentParser(description="校验文档里的引用是否真实存在")
    ap.add_argument("file", help="要检查的 Markdown 或文本文件")
    ap.add_argument("--email", default="", help="Crossref polite pool 邮箱（推荐，更快）")
    ap.add_argument("--json", default="", help="把报告写成 JSON")
    ap.add_argument("--title-threshold", type=float, default=0.55,
                    help="标题相似度低于此值时告警（默认 0.55）")
    args = ap.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"找不到文件：{path}", file=sys.stderr)
        return 2

    text = path.read_text(encoding="utf-8", errors="replace")
    cites = extract(text)

    if not cites:
        print("没有在文档里找到任何 DOI。")
        print("如果综述里的引用没带 DOI，无法做真实性校验 —— "
              "这本身就是个问题，建议要求每条引用都带 DOI。")
        return 1

    print(f"找到 {len(cites)} 个不重复 DOI，开始逐个校验…\n")

    results = []
    fabricated = mismatched = retracted = ok = 0
    cache: dict[str, dict | None] = {}   # 同一 DOI 只查一次

    for i, c in enumerate(cites, 1):
        if c["doi"] in cache:
            meta = cache[c["doi"]]
        else:
            meta = fetch(c["doi"], args.email)
            cache[c["doi"]] = meta
        row = {"doi": c["doi"], "line": c["line"]}

        if meta is None:
            row["status"] = "FABRICATED"
            row["note"] = "Crossref 查不到这个 DOI —— 极可能是编造的"
            fabricated += 1
            print(f"  [{i}/{len(cites)}] 编造  {c['doi']}  (第 {c['line']} 行)")
        else:
            real_title = (meta.get("title") or [""])[0]
            row["real_title"] = real_title
            row["journal"] = (meta.get("container-title") or [""])[0]
            parts = (meta.get("issued", {}).get("date-parts") or [[None]])[0]
            row["year"] = parts[0] if parts else None

            is_retracted = any(
                (u.get("type") or "").lower() == "retraction"
                for u in (meta.get("update-to") or [])
            )
            row["retracted"] = is_retracted

            guessed = guess_title(c["context"])
            sim = similar(guessed, real_title) if guessed else None
            row["title_similarity"] = round(sim, 3) if sim is not None else None

            if is_retracted:
                row["status"] = "RETRACTED"
                row["note"] = "这篇论文已被撤稿 —— 引用它比引用不存在的文献危害更大"
                retracted += 1
                print(f"  [{i}/{len(cites)}] 撤稿  {c['doi']}")
                print(f"                {real_title[:66]}")
            elif sim is not None and sim < args.title_threshold:
                row["status"] = "TITLE_MISMATCH"
                row["guessed_title"] = guessed[:120]
                row["note"] = ("文档里写的标题和这个 DOI 的实际标题差异很大 —— "
                               "可能是张冠李戴（两篇都真实存在但配错了）")
                mismatched += 1
                print(f"  [{i}/{len(cites)}] 不匹配 {c['doi']}  相似度 {sim:.2f}")
                print(f"                文档写: {guessed[:60]}")
                print(f"                实际是: {real_title[:60]}")
            else:
                row["status"] = "OK"
                ok += 1
                print(f"  [{i}/{len(cites)}] 通过  {c['doi']}  {real_title[:52]}")

        results.append(row)

    print(f"\n{'=' * 62}")
    print(f"  通过        {ok}")
    print(f"  编造        {fabricated}   <- 必须删除或换成真实文献")
    print(f"  标题不匹配   {mismatched}   <- 检查是否配错文献")
    print(f"  已撤稿      {retracted}   <- 必须删除")
    print(f"{'=' * 62}")

    if args.json:
        Path(args.json).write_text(
            json.dumps({
                "file": str(path),
                "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "summary": {"ok": ok, "fabricated": fabricated,
                            "title_mismatch": mismatched, "retracted": retracted},
                "results": results,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n报告已写入 {args.json}")

    if fabricated or retracted:
        print("\n有编造或已撤稿的引用 —— 这些必须处理后才能投稿。")
        return 1
    if mismatched:
        print("\n有标题不匹配的引用 —— 请人工确认是否配错。")
        return 1
    print("\n全部引用通过校验。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
