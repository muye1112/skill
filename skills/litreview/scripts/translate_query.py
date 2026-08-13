#!/usr/bin/env python3
"""检索式跨库转换 + 中文兜底翻译。

解决的核心问题：PubMed / OpenAlex / Crossref 都不索引中文。
实测「肠道菌群 AND 抑郁症」→ 0 篇，「gut microbiota AND depression」→ 3877 篇。

另一个坑：各库语法不同。把 PubMed 的 [tiab]/[MeSH Terms] 直接发给 Crossref
会被当普通词，返回垃圾结果。

用法：
    python translate_query.py "肠道菌群 抑郁症"                  # 中文兜底翻译
    python translate_query.py --to crossref "(x[tiab] OR y) AND z"  # 跨库转换
    python translate_query.py --list-terms                       # 看词表

只用标准库。
"""

from __future__ import annotations

import argparse
import json
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------- 中文词表
# 无 AI 时的兜底。不求全 —— 覆盖高频概念即可，其余靠 AI 生成 MeSH 主题词。
ZH_EN: dict[str, str] = {
    # 微生物 / 消化
    "肠道菌群": "gut microbiota", "肠道微生物": "gut microbiome",
    "菌群失调": "dysbiosis", "益生菌": "probiotics", "益生元": "prebiotics",
    "粪菌移植": "fecal microbiota transplantation",
    "短链脂肪酸": "short-chain fatty acids", "肠脑轴": "gut-brain axis",
    "炎症性肠病": "inflammatory bowel disease",
    "肠易激综合征": "irritable bowel syndrome", "克罗恩病": "Crohn disease",
    "肠黏膜屏障": "intestinal barrier",
    # 精神 / 神经
    "抑郁症": "depression", "抑郁": "depression",
    "重度抑郁": "major depressive disorder",
    "焦虑": "anxiety", "焦虑症": "anxiety disorders", "双相": "bipolar disorder",
    "精神分裂症": "schizophrenia", "失眠": "insomnia",
    "认知障碍": "cognitive dysfunction", "阿尔茨海默病": "Alzheimer disease",
    "帕金森病": "Parkinson disease", "自闭症": "autism spectrum disorder",
    "孤独症": "autism spectrum disorder", "神经炎症": "neuroinflammation",
    "应激": "stress", "慢性应激": "chronic stress",
    # 代谢 / 心血管
    "糖尿病": "diabetes mellitus", "2型糖尿病": "type 2 diabetes",
    "肥胖": "obesity", "代谢综合征": "metabolic syndrome",
    "高血压": "hypertension", "血脂异常": "dyslipidemia",
    "冠心病": "coronary artery disease", "心力衰竭": "heart failure",
    "动脉粥样硬化": "atherosclerosis", "卒中": "stroke",
    "脂肪肝": "fatty liver", "胰岛素抵抗": "insulin resistance",
    # 肿瘤
    "肿瘤": "neoplasms", "癌症": "cancer", "肺癌": "lung neoplasms",
    "乳腺癌": "breast neoplasms", "胃癌": "stomach neoplasms",
    "结直肠癌": "colorectal neoplasms", "肝癌": "liver neoplasms",
    "免疫治疗": "immunotherapy", "化疗": "chemotherapy",
    "靶向治疗": "molecular targeted therapy", "放疗": "radiotherapy",
    "预后": "prognosis", "转移": "neoplasm metastasis",
    # 免疫 / 感染
    "炎症": "inflammation", "免疫": "immunity", "自身免疫": "autoimmunity",
    "新冠": "COVID-19", "疫苗": "vaccines",
    "抗生素": "anti-bacterial agents", "耐药": "drug resistance",
    "脓毒症": "sepsis",
    # 研究类型
    "随机对照试验": "randomized controlled trial", "队列研究": "cohort studies",
    "病例对照": "case-control studies", "横断面": "cross-sectional studies",
    "meta分析": "meta-analysis", "荟萃分析": "meta-analysis",
    "系统综述": "systematic review", "临床试验": "clinical trial",
    "动物实验": "animal experimentation", "小鼠": "mice", "大鼠": "rats",
    "细胞实验": "in vitro techniques", "问卷": "surveys and questionnaires",
    # 其他常用
    "危险因素": "risk factors", "发病机制": "pathogenesis",
    "生物标志物": "biomarkers", "疗效": "treatment outcome",
    "安全性": "safety", "不良反应": "adverse effects",
    "生活质量": "quality of life", "死亡率": "mortality",
    "流行病学": "epidemiology", "基因": "genes",
    "氧化应激": "oxidative stress", "老年": "aged", "儿童": "child",
    "孕妇": "pregnant women", "运动": "exercise", "饮食": "diet",
    "地中海饮食": "mediterranean diet", "睡眠": "sleep",
    "维生素D": "vitamin D", "omega3": "fatty acids, omega-3",
}

# PubMed 字段限定标记 —— 转给别的库时要剥掉
_FIELD_TAG = re.compile(
    r"\[(?:tiab|ti|ab|title|title/abstract|mesh(?:\s+terms)?|mh|majr|"
    r"publication\s+type|pt|dp|la|language|au|so|journal|all\s+fields)\]",
    re.I,
)
_DATE_RANGE = re.compile(r"\b\d{4}\s*:\s*\d{4}\s*\[dp\]", re.I)


def has_chinese(text: str) -> bool:
    return bool(re.search(r"[一-鿿]", text))


def looks_like_query(text: str) -> bool:
    """已经是检索式（含布尔算符或字段限定）就别乱改用户写的东西。"""
    return bool(re.search(
        r"\b(AND|OR|NOT)\b|\[(tiab|ti|ab|MeSH|mh|pt|dp|la|Title)|\"", text))


def naive_translate(text: str) -> tuple[str, list[tuple[str, str]]]:
    """词表兜底翻译。返回 (英文检索式, 命中的映射对)。

    长词优先，避免「抑郁症」被「抑郁」抢先匹配。
    """
    hits: list[tuple[str, str]] = []
    out = text
    for zh in sorted(ZH_EN, key=len, reverse=True):
        if zh in out:
            out = out.replace(zh, f" {ZH_EN[zh]} ")
            hits.append((zh, ZH_EN[zh]))
    # 命中了就用 AND 连起来（比空格更精确）
    if hits:
        return " AND ".join(f'"{en}"' for _, en in hits), hits
    return " ".join(out.split()), hits


def to_plain(query: str) -> str:
    """剥掉字段限定，保留布尔结构和引号短语。

    用于 OpenAlex / Europe PMC —— 它们支持布尔但不认 PubMed 字段。
    """
    q = _DATE_RANGE.sub(" ", query)
    q = _FIELD_TAG.sub("", q)
    q = re.sub(r"\s+", " ", q).strip()
    # 剥空后会留下悬空算符和空括号，要清干净。
    # 例：剥掉 2020:2026[dp] 后变成 "... AND " —— 末尾那个 AND 会让部分库报语法错
    for _ in range(3):      # 多跑几轮，处理嵌套残留
        before = q
        q = re.sub(r"\(\s*(?:OR|AND|NOT)\s+", "(", q, flags=re.I)
        q = re.sub(r"\s+(?:OR|AND|NOT)\s*\)", ")", q, flags=re.I)
        q = re.sub(r"\(\s*\)", " ", q)
        q = re.sub(r"\b(AND|OR|NOT)\s+(AND|OR|NOT)\b", r"\1", q, flags=re.I)
        q = re.sub(r"\s+", " ", q).strip()
        # 去掉首尾悬空的布尔算符
        q = re.sub(r"^\s*(?:AND|OR|NOT)\s+", "", q, flags=re.I)
        q = re.sub(r"\s+(?:AND|OR|NOT)\s*$", "", q, flags=re.I)
        if q == before:
            break
    return q.strip()


def to_bag(query: str, max_terms: int = 8) -> str:
    """空格分隔的关键词串，用于 Crossref / Semantic Scholar。

    按 AND 切成概念块，每块只取第一个同义词 ——
    把所有同义词都塞进去会让这些库的相关度排序失效。
    """
    q = to_plain(query)
    blocks = re.split(r"\bAND\b", q, flags=re.I)
    picked: list[str] = []
    for b in blocks:
        m = re.search(r'"([^"]{2,60})"', b)
        if m:
            picked.append(m.group(1))
            continue
        words = [w for w in re.sub(r"[()\[\]]", " ", b).split()
                 if len(w) > 2 and w.upper() not in ("AND", "OR", "NOT")]
        if words:
            picked.append(words[0])
    return " ".join(picked[:max_terms])


def diagnose_zero(query: str) -> list[str]:
    """零结果诊断。不静默失败 —— 告诉用户可能哪里出了问题。"""
    tips: list[str] = []
    if has_chinese(query):
        tips.append("检索式里含中文。PubMed 等库只索引英文，中文词检索不到任何结果。")
    n_and = len(re.findall(r"\bAND\b", query))
    if n_and >= 4:
        tips.append(f"用了 {n_and} 个 AND，条件可能过窄。试着去掉一两个次要概念。")
    if "[MeSH" in query:
        tips.append("含 MeSH 限定。若某个 MeSH 词拼写不标准，PubMed 会直接返回 0 —— 可关闭 MeSH 再试。")
    if re.search(r"\[Publication Type\]|\[pt\]", query, re.I):
        tips.append("限定了研究类型（如仅 RCT）。这个筛子很紧，可以先放开看总量。")
    if re.search(r"\d{4}:\d{4}\[dp\]", query, re.I):
        tips.append("限定了年份范围。可以先放宽年份确认主题本身有文献。")
    if not tips:
        tips.append("语法正常但无命中。可能主题过新过窄，或关键词与文献用词不一致 —— 试试更常见的同义词。")
    return tips


TARGETS = {
    "pubmed": ("原样保留", lambda q: q),
    "europepmc": ("剥字段，保留布尔", to_plain),
    "openalex": ("剥字段，保留布尔", to_plain),
    "crossref": ("只留关键词", to_bag),
    "s2": ("只留关键词", to_bag),
}


def main() -> int:
    ap = argparse.ArgumentParser(description="检索式转换与中文兜底翻译")
    ap.add_argument("query", nargs="?", default="", help="检索式或中文关键词")
    ap.add_argument("--to", choices=list(TARGETS), help="转换到哪个库（不填则全部）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--diagnose", action="store_true", help="零结果诊断")
    ap.add_argument("--list-terms", action="store_true", help="列出内置词表")
    args = ap.parse_args()

    if args.list_terms:
        print(f"内置 {len(ZH_EN)} 条中英对照：\n")
        for zh, en in sorted(ZH_EN.items()):
            print(f"  {zh:14} {en}")
        return 0

    if not args.query:
        ap.print_help()
        return 2

    q = args.query
    result: dict = {"input": q}

    if has_chinese(q):
        en, hits = naive_translate(q)
        result["chinese_detected"] = True
        result["translated"] = en
        result["term_hits"] = [{"zh": z, "en": e} for z, e in hits]
        if not args.json:
            print("检测到中文输入。PubMed 等库不索引中文，已用内置词表转换：\n")
            for z, e in hits:
                print(f"  {z}  →  {e}")
            print(f"\n英文检索式：\n  {en}")
            if not hits:
                print("\n词表未命中任何词。建议改用英文，或让 AI 生成含 MeSH 主题词的检索式（覆盖更全）。")
            else:
                print("\n注意：词表只做字面映射，没有同义词扩展和 MeSH 主题词。")
                print("      让 AI 生成检索式能显著提高召回率。")
        q = en

    if args.diagnose:
        # 诊断用**原始输入**，不是翻译后的 —— 否则「含中文」这条永远不会触发，
        # 而它恰恰是最常见的零结果原因
        tips = diagnose_zero(args.query)
        result["diagnosis"] = tips
        if not args.json:
            print("\n零结果可能的原因：")
            for t in tips:
                print(f"  · {t}")

    targets = [args.to] if args.to else list(TARGETS)
    conv = {}
    for name in targets:
        desc, fn = TARGETS[name]
        conv[name] = {"note": desc, "query": fn(q)}
    result["converted"] = conv

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif not has_chinese(args.query) or args.to:
        print("\n各库检索式：")
        for name, v in conv.items():
            print(f"\n  {name}  （{v['note']}）")
            print(f"    {v['query']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
