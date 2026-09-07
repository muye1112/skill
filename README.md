# 个人科研 skill 集

一套覆盖科研全流程的 skill，同时支持 **Claude Code** 和 **Codex**。

| 能力 | 说明 |
|---|---|
| **文献检索** | 中文研究问题 → 含 MeSH 主题词的英文检索式，跨 5 个免费数据库 |
| **批判性精读** | PDF → 「5 问批判清单 + 全文精翻」v2.0 笔记，批量归档 Zotero（MCP HTTP 直连，零重启） |
| **精读单篇** | PDF / DOI → 结构化笔记，含图表处理 |
| **PRISMA 筛选** | 两阶段筛选、排除原因记录、流程图导出 |
| **主题综合** | 按主题组织而非逐篇罗列 |
| **引用校验** | 查 Crossref 确认真实存在 + 撤稿检查 |
| **创新评估** | 多轮检索 + 严苛批评者视角 |
| **投稿自查** | 自我审阅 + 同行评审模板 |

---

## 为什么需要它

三个反复出现的失败，任何一个都会让综述作废：

**中文检索不到文献。** PubMed、OpenAlex、Crossref 都不索引中文。实测「肠道菌群 AND 抑郁症」返回 **0 篇**，而 `gut microbiota AND depression` 返回 **3877 篇**。多数人以为工具坏了，其实是语言问题 —— 需要的是概念到英文主题词的映射，不是字面翻译。

**AI 编造或错配引用。** 投稿综述唯一致命的失效模式。引用**已撤稿**论文更糟 —— 不存在的 DOI 审稿人一眼看出，已撤稿的会跟着进正式发表。

**罗列文献而非综合文献。** 「张三等研究了……李四等研究了……」是研究生最常被退稿的问题。

---

## 安装

### Claude Code

放在项目内（推荐，跟项目一起走）：

```bash
cd 你的项目目录
git clone git@github.com:muye1112/skill.git .claude/_tmp
cp -r .claude/_tmp/skills .claude/
rm -rf .claude/_tmp
```

或装到全局：

```bash
git clone git@github.com:muye1112/skill.git
cp -r skill/skills/* ~/.claude/skills/
```

### Codex

Codex 通过 `.codex-plugin/plugin.json` 加载：

1. 克隆本仓库到本地
2. Codex 命令面板运行 **Install Plugin from Folder**（或插件设置里选「从本地文件夹安装」）
3. 选择本仓库根目录（含 `.codex-plugin/` 的那一层）

装好后直接说「精读这篇 PDF」「帮我做这个方向的文献综述」即可触发。

**Codex 的优势是能读图。** 论文的核心结果常在图表里，只读文字会漏。精读单篇优先用 Codex。

---

## 给 Codex 接大模型

Codex 需要一个 LLM 后端。三条路，按国内可行性排序。

### 方式一 · 任意 OpenAI 兼容后端（国内直连可用，推荐）

Codex 支持指向自定义 base URL，所以国内模型也能接。编辑 `~/.codex/config.toml`：

```toml
[model_providers.deepseek]
name = "DeepSeek"
base_url = "https://api.deepseek.com/v1"
env_key = "DEEPSEEK_API_KEY"

[profiles.deepseek]
model = "deepseek-chat"
model_provider = "deepseek"
```

然后设 key 并启动：

```powershell
setx DEEPSEEK_API_KEY "sk-你的key"
# 关掉窗口重开（setx 只对新窗口生效）
codex --profile deepseek
```

同样写法适用于通义千问、Kimi、智谱或任何中转服务 —— 改 `base_url`、`env_key`、`model` 三处即可。

**读图注意**：DeepSeek 目前不支持读图。要用 Codex 的读图能力，得选支持视觉的模型，例如通义千问：

```toml
[model_providers.qwen]
name = "Qwen"
base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
env_key = "DASHSCOPE_API_KEY"

[profiles.qwen-vl]
model = "qwen-vl-max"
model_provider = "qwen"
```

### 方式二 · ChatGPT 账号登录

需要 ChatGPT Plus / Pro / Business 订阅，用订阅额度不额外花钱。

```bash
codex login
```

选 **Sign in with ChatGPT**，浏览器授权。

### 方式三 · OpenAI API Key

需要国际信用卡。

1. `platform.openai.com` → Billing 充值（最低 5 美元）
2. API keys → Create new secret key
3. `setx OPENAI_API_KEY "sk-你的key"`
4. 关窗口重开，运行 `codex`

### 国内网络的现实

`api.openai.com` 和 `auth.openai.com` 在国内**基本不通** —— 方式二和方式三都需要代理，没有代理的话即使买了 key 也连不上。

没有代理就走**方式一**接国内模型。

---

## 结构

```
skills/
├── litreview/                  ← 主 skill，编排全流程
│   ├── SKILL.md                七阶段 + 引用防御六层
│   ├── references/
│   │   └── citation-defense.md 引用防幻觉（必读）
│   ├── scripts/
│   │   ├── verify_citations.py 引用真实性 + 撤稿校验
│   │   └── translate_query.py  跨库检索式转换 + 中文兜底
│   └── agents/openai.yaml      Codex 适配层
│
├── deeppapernote/              单篇精读 → Obsidian 笔记
├── deep-read-zotero/           批判性精读 v2.0 → Zotero 批量归档
│   ├── SKILL.md                5 问批判法 + MCP HTTP 直连原理
│   ├── codex/SKILL.md          Codex 适配版（串行流程 + 读图优势）
│   ├── references/
│   │   ├── critical-reading.md 批判性 5 问方法论（Sartorius & Thornicroft 2025）
│   │   └── note-template.md    v2.0 笔记 HTML 模板 + 写作检查清单
│   └── scripts/
│       ├── mcp_client.py       Zotero MCP HTTP 直连客户端（绕开客户端工具故障）
│       └── zotero_import.py    精读笔记批量导入 + 验证工具
├── paper-glossary/             术语表构建
├── liteparse/                  PDF 解析
│
├── literature-review/          系统综述七阶段
├── literature-review-agent/    综述方法论
├── survey-generation/          综述文章生成
├── related-work-writing/       相关工作章节
│
├── idea-generation/            研究想法生成
├── novelty-assessment/         创新性评估
├── atomic-decomposition/       原子命题分解
├── backward-traceability/      论断反向溯源
│
├── peer-review/                同行评审
├── self-review/                投稿前自查
├── scholar-evaluation/         学术评估
├── scientific-writing/         写作规范
│
├── citation-management/        引用管理 / BibTeX
├── paper-lookup/               文献查找
├── research-lookup/            跨源检索
├── pyzotero/                   Zotero 读写
│
└── skill-creator/              提炼新 skill（Anthropic 官方）
```

---

## 两个脚本可以单独用

不装 skill 也能直接跑，只用 Python 标准库，无需 `pip install`。

**校验引用真实性**：

```bash
python skills/litreview/scripts/verify_citations.py 我的综述.md --email you@example.com
```

实测输出：

```
  [1/5] 通过  10.1016/j.ebiom.2023.104527  Gut microbiota and its metabolites in depression
  [4/5] 编造  10.1038/s41586-024-99999-x  (第 9 行)
  [5/5] 不匹配 10.1016/j.ebiom.2023.104527  相似度 0.51
                文档写: Fecal microbiota transplantation for treatment-resistant dep
                实际是: Gut microbiota and its metabolites in depression: from patho
```

抓三类问题：编造的 DOI、张冠李戴（DOI 真实但配错文献）、已撤稿论文。

**转换检索式**：

```bash
# 中文兜底翻译
python skills/litreview/scripts/translate_query.py "肠道菌群 抑郁症 随机对照试验"

# 跨库转换
python skills/litreview/scripts/translate_query.py '("gut microbiota"[tiab]) AND depression[tiab]'

# 零结果诊断
python skills/litreview/scripts/translate_query.py "肠道菌群 AND 抑郁症" --diagnose
```

---

## 一句必须说清的话

AI 产出的是**草稿**，不是能直接投稿的成品。

STORM（斯坦福，30k★）官方明确声明产物达不到可发表水准。目前没有任何工具能端到端产出可投稿的综述。

定位是：**引用可溯源的高质量初稿 + 人工精修**。核查这一步无法省略。

---

## 许可

自研部分（`skills/litreview/`）采用 MIT。其余 skill 保留各自原许可，来源见各目录内文件。
