---
name: deep-read-zotero
description: 批判性精读文献并批量归档到 Zotero（v2.0）。基于 Sartorius & Thornicroft (2025) 批判性阅读方法论生成「5 问批判清单 + 全文精翻 + 术语速查」的 HTML 精读笔记，再通过 Zotero MCP HTTP 直连（127.0.0.1:23120）批量写入 Zotero 条目笔记——全程零重启 Zotero、不依赖 Claude Code 客户端 MCP 工具的可用性。当用户说"精读这篇/这些文献""做批判性精读笔记""把笔记导入 Zotero""给 Zotero 里的论文做 v2.0 精读"等时使用。
---

# 批判性精读 + Zotero 批量归档（deep-read-zotero v2.0）

把一批 PDF 文献处理成「批判性精读笔记 HTML → Zotero 条目子笔记」，供研究生建立系统的文献精读库。

## v2.0 相比 v1 的三个关键升级

| 升级点 | v1（lit-organize） | v2.0（本 skill） |
|---|---|---|
| **阅读方法** | 接受式精翻（"作者说了什么"） | **批判性 5 问法**（"可信吗？为什么这样做？与别人一致吗？"） |
| **Zotero 写入** | 依赖 `mcp__zotero-mcp__*` 客户端工具，标记不可用即失败 | **MCP HTTP 直连**（Python 直接 POST 到 `127.0.0.1:23120/mcp`），客户端工具挂了照样工作 |
| **验证** | 写完不知道是否真成功 | noteKey 回读 + 双通道验证 |

> **核心洞察**：Claude Code 客户端有时把 `mcp__zotero-mcp__*` 工具标记为不可用，但 **Zotero MCP 服务器本身一直在 `127.0.0.1:23120` 正常运行**。绕开客户端、直接用 HTTP 调 MCP 协议，24 个工具全部可用。这就是 `scripts/mcp_client.py` 存在的意义。

## 环境依赖

- Python 3.8+（仅标准库，无需 pip 安装任何东西）
- Zotero 7+ 桌面端**正在运行**，且已装 zotero-mcp 插件（端口 `127.0.0.1:23120` 监听）
- 验证：`netstat -an | grep 23120`（Windows）或访问 `http://127.0.0.1:23120/mcp` 应返回 JSON 描述

## 完整工作流（5 步）

### Step 1 · 复制 PDF 到工作目录

```bash
cp "D:/zotero/storage/<KEY>/paper.pdf" "D:/project/wenxian/"
```

### Step 2 · 解析 PDF 全文

```bash
pdftotext -layout paper.pdf paper.txt
```

注意 Windows Git Bash 下 pdftotext 自带（poppler）；连字已自动展开（`ﬁ`→fi）。

### Step 3 · 按 v2.0 模板写批判性精读笔记（HTML 格式）

**这是本 skill 的灵魂环节**。模板见 `references/note-template.md`，方法论见 `references/critical-reading.md`。核心结构：

```html
<h1>精读笔记：<论文标题>（v2.0）</h1>
<blockquote>原题 / 期刊 / DOI / 通讯作者 / 研究类型 / 报告规范</blockquote>

<h2>一、3 句话结论</h2>          ← 背景+空白 / 方法 / 发现+意义，各 1 句

<h2>二、5 问批判清单</h2>        ← 本 skill 区别于普通精读的核心
  2.1 作者与利益          → 资助来源？COI？谁受益？
  2.2 背景与目的          → 目的是不是可回答的"问题"形式？
  2.3 方法学可信度        → 样本量计算？盲法？伦理批准号？报告规范？
  2.4 结果可信度          → 效应大小？CI？选择性呈现？
  2.5 讨论与定位          → 局限性是否充分承认？与前人一致/矛盾？

<h2>三、核心发现速览（表格）</h2> ← 发现 / 数据证据 / 强度三列

<h2>四、精翻：摘要</h2>
<h2>五、章节精翻要点</h2>        ← 按论文原始章节，"翻译"而非"概括"

<h2>六、给"我"的启发</h2>       ← 与自己课题的嫁接点、创新空白
<h2>七、文献元信息</h2>
<h2>八、术语速查</h2>           ← 术语 / 解释 / 出现位置三列表格
```

**写作纪律**：
- 每篇笔记 6000-10000 字符（太短=概括不是精读；太长=Zotero 渲染卡顿）
- 批判性问题要有**具体证据**（如"⚠️ 未提 PROSPERO 注册号"而非"方法不够严谨"）
- 5 问清单每项必须给 `[OK]` / `[注意]` / `[红旗]` 三档标记
- 全文精翻是主体，术语首次出现保留英文

**文件命名规范**（导入工具靠这个自动匹配 Zotero 条目）：

```
{ZOTERO_ITEM_KEY}_{标题关键词}_v2.0.html
例：LKNAGJ4N_RNA甲基化修饰_金属毒性_v2.0.html
```

存放到统一目录，如 `D:/project/wenxian/精读笔记/`。

### Step 4 · 批量导入 Zotero

```bash
cd <skill 目录>/scripts
python zotero_import.py --html-dir "D:/project/wenxian/精读笔记"
```

常用参数：

| 参数 | 作用 |
|---|---|
| `--html-dir <目录>` | 自动扫描目录，按文件名规则匹配 itemKey |
| `--config notes.json` | 从配置文件加载（适合文件名不规则的情况） |
| `--verify <ITEMKEY>` | 验证某条目的笔记状态 |
| `--init` | 仅初始化 MCP 连接（诊断用） |
| `--replace` | 先删除旧笔记再导入 |
| `--action update` | 更新而非新建 |

单篇笔记 1-2 秒，24 篇 < 1 分钟。

### Step 5 · 验证

```bash
python zotero_import.py --verify LKNAGJ4N
```

⚠️ **注意**：MCP 的 `get_annotations` 工具只查 PDF 高亮注释，**不查 notes**。验证笔记要用 `search_annotations(type=note)` 或直接到 Zotero 客户端看条目的"笔记"标签页。`zotero_import.py` 的 verify 已内置正确通道。

## MCP HTTP 直连原理（为什么这能绕开客户端故障）

MCP（Model Context Protocol）2024-11-05 版的 Streamable HTTP 传输就是普通的 HTTP POST：

```python
# 1. initialize 建会话，响应头里拿 mcp-session-id
# 2. notifications/initialized 完成握手
# 3. tools/list 列工具；tools/call 调工具
# 响应是 SSE 格式：event: message\ndata: {...JSON...}\n\n
```

Zotero MCP 服务器（zotero-integrated-mcp v1.1.0）提供 24 个工具，常用的：

| 工具 | 用途 |
|---|---|
| `write_note` | 创建条目子笔记（返回 noteKey） |
| `write_tag` / `write_metadata` / `write_item` | 改 tag / 补元数据 / 导入附件 |
| `get_item_details` / `get_collection_items` | 读条目 / 遍历分类 |
| `search_fulltext` | 全文搜索 |
| `create_collection` / `add_items_to_collection` | 管理分类 |

完整清单和调用细节见 `scripts/mcp_client.py` 顶部注释。

## 与其他 skill 的分工

| 场景 | 用哪个 skill |
|---|---|
| 批量 PDF → Zotero 归档（本 skill） | deep-read-zotero |
| 单篇论文 → Obsidian 深度笔记 | deeppapernote |
| 检索 + PRISMA 筛选 + 综述草稿 | litreview |
| 一批 PDF → Word 精翻文档 | lit-organize |

## 故障排查

| 症状 | 原因 | 处理 |
|---|---|---|
| `Connection refused` | Zotero 没开或插件没装 | 启动 Zotero，确认插件端口 23120 |
| MCP 工具列表为空 | 会话握手不完整 | 重跑 `python zotero_import.py --init` |
| `write_note` 成功但笔记不挂在条目下（成为"独立笔记"） | **参数名写错：应为 `parentKey`，不是 `itemKey`** | 脚本已内置正确参数；历史脏数据在 Zotero 客户端手动删除或拖到条目下 |
| `write_note` 成功但验证不到 | 用了 `get_annotations`（只查 PDF 高亮） | 用 `--verify`（走 search_annotations）或看 Zotero 客户端 |
| `search_annotations` 报 "q is required" | 该工具强制要求 q/colors/tags 至少一个过滤条件 | 工具已内置 `q='精读笔记'` 检索；验证字段用 `parentKey`（笔记自身的 key 叫 `itemKey`，易混淆） |
| MCP 无删除笔记工具 | write_note 仅支持 create/update/append | 重复笔记需在 Zotero 客户端手动删（条目可挂多条子笔记，追加不破坏数据） |
| 笔记内容超长报错 | 超 200KB 保护 | 拆成多条笔记或精简章节 |
| 中文 tag 报 Parse error | Zotero MCP 对部分中文 UTF-8 载荷有 bug | tag 用英文/拼音；笔记正文中文正常 |

## ⚠ write_note 参数契约（实测 zotero-integrated-mcp v1.1.0）

```
action      : create | update | append   （必填）
content     : HTML 或 Markdown 笔记正文   （必填；MD 自动转 HTML）
parentKey   : 挂载的目标条目 key          （create 时用；缺省 = 独立笔记）
noteKey     : 已有笔记 key               （update/append 时必填）
tags        : 字符串数组                  （可选）
libraryID   : 数字                       （可选，默认个人库）
```

注意区分两个 key：**条目的 key**（如 LKNAGJ4N）传给 `parentKey`；
**笔记自身的 key**（服务器返回，如 SHG2LIQ5）在 search_annotations 结果里叫 `itemKey`。
