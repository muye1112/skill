# -*- coding: utf-8 -*-
"""
zotero_import.py — 精读笔记批量导入 Zotero 工具
================================================

v2.0（deep-read-zotero skill）

【功能】
    把 v2.0 批判性精读笔记（HTML 格式）批量写入 Zotero 条目的子笔记。
    走 MCP HTTP 直连（见 mcp_client.py），不依赖 Claude Code 客户端
    的 mcp__zotero-mcp__* 工具是否可用。

【三种加载模式】
    1. --html-dir <目录>   自动扫描目录下的 .html，按文件名规则匹配 itemKey
                          文件名规范：{ITEMKEY}_{标题关键词}_v2.0.html
                          例：LKNAGJ4N_RNA甲基化修饰_金属毒性_v2.0.html
                          → itemKey = LKNAGJ4N（取第一个下划线前的部分）
    2. --config <json>    从配置文件加载（文件名不规则时用）：
                          {"notes": [{"itemKey": "...", "html_path": "...",
                                      "name": "可选显示名"}, ...]}
    3. --verify <KEY>     只验证某条目的笔记状态，不写入
       --init             只建立 MCP 会话，诊断连接用

【常用参数】
    --replace      先删旧笔记再导入（默认追加保留旧笔记）
    --action update  更新已有笔记而非新建（需服务器支持）
    --config / --html-dir 二选一

【典型命令】
    python zotero_import.py --init                     # 诊断连接
    python zotero_import.py --html-dir "D:/精读笔记"    # 批量导入
    python zotero_import.py --verify LKNAGJ4N          # 验证
    python zotero_import.py --config batch.json --replace

【验证笔记的坑】
    Zotero MCP 的 get_annotations 只查 PDF 高亮注释，不查 notes。
    本工具的 verify_note() 改用 search_annotations(type='note')。
    最可靠的验证是打开 Zotero 客户端看条目的"笔记"标签页。

【依赖】
    仅标准库 + 同目录 mcp_client.py（也仅标准库）。
"""
import argparse
import json
import os
import re
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')

from mcp_client import init_mcp, call_tool

# ---------------------------------------------------------------------------
# 常量：Zotero 笔记单条内容的安全上限。
# 超过 200KB 时 Zotero 客户端渲染明显卡顿，超过会有丢内容风险。
# ---------------------------------------------------------------------------
MAX_NOTE_CHARS = 200_000


# ===========================================================================
# HTML 预处理
# ===========================================================================
def html_to_zotero(html_content, strip_body=True):
    """把精读笔记 HTML 清洗成 Zotero 笔记接受的片段。

    Zotero 笔记渲染 HTML 的子集（h1-h4/p/ul/ol/table/blockquote/dl/
    strong/em/i/b/code/pre/br/hr 等都支持），但拒绝：
      - 完整 HTML 文档结构（<!DOCTYPE>/<html>/<head>/<body> 外壳）
      - <style>/<script> 块
      - HTML 注释

    本函数做四件事：
      1. 提取 <body> 内层内容（strip_body=True 时）
      2. 删 <style> 块
      3. 删 <script> 块
      4. 删 HTML 注释 + 压缩连续空行

    参数：
        html_content : 原始 HTML 字符串（可以是完整文档或片段）
        strip_body   : 是否只保留 <body> 内层。模板类笔记建议 True。

    返回：
        清洗后的 HTML 片段字符串。
    """
    content = html_content

    # 1. 提取 <body> 内层（re.DOTALL 让 . 匹配换行）
    if strip_body:
        m = re.search(r'<body[^>]*>(.*?)</body>', content,
                      re.DOTALL | re.IGNORECASE)
        if m:
            content = m.group(1)

    # 2/3. 删 style、script 块
    content = re.sub(r'<style[^>]*>.*?</style>', '',
                     content, flags=re.DOTALL | re.IGNORECASE)
    content = re.sub(r'<script[^>]*>.*?</script>', '',
                     content, flags=re.DOTALL | re.IGNORECASE)

    # 4. 删注释 + 压缩 3 个以上连续换行为 2 个
    content = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)
    content = re.sub(r'\n\s*\n\s*\n+', '\n\n', content)

    return content.strip()


# ===========================================================================
# 文件名 → itemKey 自动匹配
# ===========================================================================
def derive_item_key(filename):
    """从 HTML 文件名提取 Zotero itemKey。

    规范：{ITEMKEY}_{标题关键词}_v2.0.html
    例：  LKNAGJ4N_RNA甲基化修饰_金属毒性_v2.0.html → LKNAGJ4N

    兜底：没有下划线时取去掉扩展名的整个文件名
    （适合直接用 itemKey 命名的简单场景）。
    """
    base = os.path.splitext(os.path.basename(filename))[0]
    if '_' in base:
        return base.split('_')[0]
    return base


def load_notes_from_dir(html_dir):
    """扫描目录，返回符合命名规范的笔记列表。

    返回：[{'itemKey': ..., 'html_path': ..., 'name': ...}, ...]
    """
    notes = []
    for fn in sorted(os.listdir(html_dir)):
        if not fn.lower().endswith('.html'):
            continue
        notes.append({
            'itemKey': derive_item_key(fn),
            'html_path': os.path.join(html_dir, fn),
            'name': fn,
        })
    return notes


def load_notes_from_config(config_path):
    """从 JSON 配置文件加载笔记列表。

    配置格式：
        {"notes": [{"itemKey": "X", "html_path": "D:/a.html",
                    "name": "显示名（可选）"}, ...]}
    """
    with open(config_path, encoding='utf-8') as f:
        config = json.load(f)
    return config.get('notes', [])


# ===========================================================================
# 核心导入逻辑
# ===========================================================================
def import_note(item_key, html_path, action='create', replace=False,
                max_chars=MAX_NOTE_CHARS):
    """导入单份 HTML 精读笔记到 Zotero 条目。

    流程：
        读文件 → html_to_zotero 清洗 → 长度校验
        → （replace 时先查旧笔记）→ write_note 写入 → 解析 noteKey

    参数：
        item_key  : Zotero 条目 key（8 位大写字母数字，如 LKNAGJ4N）
        html_path : 笔记 HTML 路径
        action    : 'create'（新建子笔记）或 'update'
        replace   : True 时先尝试清理该条目旧笔记（依赖服务器支持）
        max_chars : 内容长度上限保护，默认 200KB

    返回：
        dict，固定含 'success'；成功时含 'noteKey' 和 'content_length'；
        失败时含 'error'。
    """
    # --- 读文件 ---
    if not os.path.exists(html_path):
        return {'success': False, 'error': f'文件不存在: {html_path}'}

    with open(html_path, encoding='utf-8') as f:
        html = f.read()

    # --- 清洗 ---
    content = html_to_zotero(html)
    if not content:
        return {'success': False, 'error': 'HTML 清洗后为空（检查模板结构）'}

    # --- 长度保护 ---
    if len(content) > max_chars:
        return {'success': False,
                'error': f'内容超长 ({len(content)} > {max_chars})，请拆分笔记',
                'content_length': len(content)}

    # --- replace 模式 ---
    # ⚠ Zotero MCP（v1.1.0）没有删除笔记的工具（write_note 仅支持
    #   create/update/append）。replace 只能提示用户手动清理。
    #   Zotero 允许一个条目挂多条子笔记，追加不会破坏数据。
    if replace:
        print('    [提示] --replace 需要 Zotero 客户端手动删除旧笔记'
              '（MCP 无删除工具），本次将直接追加新笔记')

    # --- 写入 ---
    # ⚠ write_note 的参数名是 parentKey（不是 itemKey）！
    #   传错参数名会导致服务器忽略它、创建"独立笔记"（不挂任何条目）。
    #   write_note 无删除能力（action 仅 create/update/append），
    #   所以传错参数产生的脏数据只能在 Zotero 客户端手动清理。
    result = call_tool('write_note', {
        'parentKey': item_key,
        'content': content,
        'action': action,
    })
    if not result:
        return {'success': False, 'error': 'MCP 工具调用无响应'}

    # --- 解析结果 ---
    # 服务器返回两种形态：
    #   a) JSON 字符串（含 noteKey / success / error）
    #   b) 纯文本（含 "Note created successfully (key: XXXX)"）
    try:
        parsed = json.loads(result)
    except (json.JSONDecodeError, TypeError):
        parsed = None

    if isinstance(parsed, dict):
        # a) 结构化响应
        data = parsed.get('data', parsed)
        note_key = data.get('noteKey') or parsed.get('noteKey')
        if note_key or parsed.get('success'):
            return {'success': True,
                    'noteKey': note_key or 'created',
                    'content_length': len(content)}
        return {'success': False, 'error': parsed.get('error', str(parsed)[:200])}

    # b) 文本响应：从 "Note created successfully (key: 3FYN2XYG)" 提取 key
    m = re.search(r'key:\s*([A-Z0-9]{6,10})', result)
    if 'success' in result.lower() or 'created' in result.lower() or m:
        return {'success': True,
                'noteKey': m.group(1) if m else 'created',
                'content_length': len(content)}

    return {'success': False, 'error': f'MCP 返回异常: {result[:200]}'}


def batch_import(notes_list, action='create', replace=False, delay=0.5):
    """批量导入多份笔记，打印进度，返回结果列表。

    delay：两次调用间隔秒数，防止高频请求触发服务器限流。
    """
    results = []
    for i, note in enumerate(notes_list, 1):
        key, path = note['itemKey'], note['html_path']
        name = note.get('name', key)
        print(f'\n[{i}/{len(notes_list)}] {name} ({key})')

        result = import_note(key, path, action=action, replace=replace)
        result.update({'name': name, 'itemKey': key, 'html_path': path})
        results.append(result)

        if result['success']:
            print(f"  OK  noteKey={result.get('noteKey', '?')}"
                  f"  {result.get('content_length', '?')} chars")
        else:
            print(f"  FAIL  {result.get('error', '未知错误')}")

        if i < len(notes_list) and delay > 0:
            time.sleep(delay)

    ok = sum(1 for r in results if r['success'])
    print('\n' + '=' * 60)
    print(f'导入汇总: {ok}/{len(results)} 成功')
    return results


# ===========================================================================
# 验证
# ===========================================================================
def verify_note(item_key):
    """验证条目是否已有精读笔记（notes，而非 PDF 高亮）。

    ⚠ Zotero MCP 的 get_annotations 只查 PDF 高亮注释。
    ⚠ search_annotations 强制要求 q/colors/tags 至少一个过滤条件。
    这里用 q='精读笔记'（v2.0 模板 h1 的固定开头）检索，
    再在结果里按 itemKey 过滤。
    终极确认仍以 Zotero 客户端的"笔记"标签页为准。
    """
    result = call_tool('search_annotations',
                       {'q': '精读笔记', 'type': 'note', 'limit': 100})
    if not result:
        return {'has_note': False, 'error': 'search_annotations 无响应'}

    try:
        data = json.loads(result)
        notes = data.get('data') or data.get('notes') or []
        # 字段语义：note.itemKey = 笔记自身的 key；
        #          note.parentKey = 所属条目的 key（用于过滤）
        mine = []
        for n in notes:
            parent = (n.get('parentKey') or n.get('parentItemKey') or '')
            if item_key.lower() in str(parent).lower():
                mine.append(n)
        return {
            'has_note': len(mine) > 0,
            'note_count': len(mine),
            'matched_total': len(notes),
            'previews': [str(n.get('content', n.get('note', '')))[:80]
                         for n in mine[:3]],
            'hint': '最可靠验证：Zotero 客户端 → 选中条目 → 笔记标签页',
        }
    except (json.JSONDecodeError, TypeError) as e:
        return {'has_note': False, 'error': f'解析失败: {e}'}


# ===========================================================================
# 命令行入口
# ===========================================================================
def main():
    ap = argparse.ArgumentParser(
        description='v2.0 批判性精读笔记批量导入 Zotero（MCP HTTP 直连）')
    ap.add_argument('--init', action='store_true', help='仅建立 MCP 会话（诊断）')
    ap.add_argument('--config', help='JSON 配置文件路径')
    ap.add_argument('--html-dir', help='HTML 笔记目录（按文件名自动匹配 itemKey）')
    ap.add_argument('--action', choices=['create', 'update'], default='create')
    ap.add_argument('--replace', action='store_true', help='导入前清理旧笔记')
    ap.add_argument('--verify', metavar='ITEMKEY', help='仅验证指定条目的笔记状态')
    args = ap.parse_args()

    print('=' * 60)
    print('精读笔记 → Zotero 批量导入 v2.0 (deep-read-zotero skill)')
    print('=' * 60)

    # --- 模式 1：诊断 ---
    if args.init:
        init_mcp()
        return

    # --- 模式 2：验证 ---
    if args.verify:
        init_mcp()
        print(f'\n验证 {args.verify}:')
        for k, v in verify_note(args.verify).items():
            print(f'  {k}: {v}')
        return

    # --- 模式 3：导入 ---
    if args.config:
        notes = load_notes_from_config(args.config)
    elif args.html_dir:
        notes = load_notes_from_dir(args.html_dir)
    else:
        ap.print_help()
        return

    if not notes:
        print('没有可导入的笔记')
        return

    init_mcp()
    results = batch_import(notes, action=args.action, replace=args.replace)

    # 落盘导入报告，便于复查
    report = os.path.join(os.path.dirname(__file__), 'import_report.json')
    with open(report, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f'报告已保存: {report}')


if __name__ == '__main__':
    main()
