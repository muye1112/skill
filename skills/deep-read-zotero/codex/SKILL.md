---
name: deep-read-zotero
description: 批判性精读文献并批量归档到 Zotero（v2.0，Codex 适配版）。基于 Sartorius & Thornicroft (2025) 批判性阅读方法论生成「5 问批判清单 + 全文精翻 + 术语速查」的 HTML 精读笔记，再通过 Zotero MCP HTTP 直连（127.0.0.1:23120）批量写入 Zotero 条目子笔记。当用户说"精读这篇/这些文献""做批判性精读笔记""把笔记导入 Zotero""给 Zotero 里的论文做 v2.0 精读"等时使用。
---

# 批判性精读 + Zotero 批量归档（Codex 适配版）

> 本文档是 `skills/deep-read-zotero/SKILL.md` 的 **Codex 专用适配版**。
> 两者方法论、模板、脚本完全一致；差异只在执行模式：

| 差异点 | Claude Code 版 | Codex 版（本文档） |
|---|---|---|
| 子代理并行 | 可用 Agent tool 每篇 PDF 派一个子代理 | **无并行，串行逐篇处理** |
| 触发方式 | Skill 系统 | AGENTS.md 约定 / 直接给本文档路径 |
| 读图能力 | — | **Codex 能读图**：论文图表直接看，精读时优先用 |

## Codex 专属优势：读图

论文的核心结果常在**图 1-6 / 表 1-3** 里，只读 pdftotext 文字会漏掉：
- 机制图（图里的箭头关系）
- Western blot 条带（灰度差异）
- 森林图（Meta 分析的效应量和异质性）

**Codex 工作流**：先 `pdftotext` 拿正文 → 再直接打开 PDF 看关键图表 → 把图表信息写进笔记的「核心发现速览」和「结果精翻」。

## 完整工作流（串行 5 步）

### Step 1 · 准备

确认 Zotero 运行中、MCP 插件端口在监听：

```bash
# Windows
netstat -an | findstr 23120
# 应看到 TCP 127.0.0.1:23120 LISTENING
```

### Step 2 · 逐篇解析 PDF

```bash
pdftotext -layout paper.pdf paper.txt
```

每篇处理完再处理下一篇（Codex 串行）。**先完整读完 txt 再动笔**。

### Step 3 · 按 v2.0 模板写批判性精读笔记

模板在 `../references/note-template.md`，方法论在 `../references/critical-reading.md`。

Codex 串行版的额外纪律（因为没有子代理兜底）：
- 每写完一篇，**立即做「写作检查清单」自检**（见模板末尾），通过后再写下一篇
- 大 PDF 分段读 txt，**严禁跳读**——批判性 5 问需要方法学和讨论部分的细节
- 笔记写完先落盘 HTML，攒批后统一导入（见 Step 4），不要写一篇导一篇

文件命名规范（导入工具靠它匹配 Zotero 条目）：

```
{ZOTERO_ITEM_KEY}_{标题关键词}_v2.0.html
例：LKNAGJ4N_RNA甲基化修饰_金属毒性_v2.0.html
```

### Step 4 · 批量导入 Zotero

```bash
python ../scripts/zotero_import.py --html-dir "D:/project/wenxian/精读笔记"
```

单篇 1-2 秒；导入报告自动存为 `import_report.json`。

### Step 5 · 验证

```bash
python ../scripts/zotero_import.py --verify LKNAGJ4N
```

⚠️ `get_annotations` 只查 PDF 高亮不查 notes——验证走 `search_annotations(type='note')`（工具已内置）。最可靠是打开 Zotero 客户端看条目的"笔记"标签页。

## 笔记结构契约（与 Claude Code 版一致）

```
h1 标题 + blockquote 元信息
一、3 句话结论
二、5 问批判清单          ← 作者与利益 / 背景目的 / 方法学 / 结果 / 讨论定位
三、核心发现速览（表格）
四、精翻：摘要
五、章节精翻要点          ← 引言 / 方法 / 结果 / 讨论
六、给我的启发            ← 空白点 / 方法学借鉴 / 向导师提的问题
七、文献元信息
八、术语速查（表格）
```

每篇 6000-10000 字符；批判性问题必须带具体证据；全文精翻是主体。

## 故障排查（Codex 环境特有）

| 症状 | 处理 |
|---|---|
| `python` 不在 PATH | Codex shell 用绝对路径：`/usr/bin/python3` 或 `py -3` |
| MCP 连接拒绝 | Zotero 没开或插件没装；`netstat` 确认 23120 |
| pdftotext 缺失 | Windows: `winget install poppler`；Linux: `apt install poppler-utils` |
| 中文 tag 报 Parse error | Zotero MCP 的 UTF-8 载荷 bug，tag 用英文/拼音，笔记正文中文正常 |
