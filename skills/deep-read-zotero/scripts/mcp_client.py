# -*- coding: utf-8 -*-
"""
mcp_client.py — Zotero MCP HTTP 直连客户端
==========================================

v2.0（deep-read-zotero skill）

【为什么需要这个文件】
    Claude Code 客户端的 mcp__zotero-mcp__* 工具偶尔会被标记为不可用
    （"No such tool available"），但 Zotero MCP 服务器本身一直在
    127.0.0.1:23120 正常运行。本客户端绕开 Claude Code 客户端，
    直接用 Python 标准库（urllib）走 MCP 2024-11-05 的 Streamable HTTP
    传输协议调用 Zotero，24 个工具全部可用，零第三方依赖。

【MCP Streamable HTTP 协议三步握手】
    1. POST initialize            → 响应头返回 mcp-session-id（会话凭证）
    2. POST notifications/initialized → 完成握手（无响应体）
    3. POST tools/list / tools/call   → 带上 mcp-session-id 调用工具
    响应体是 SSE 格式："event: message\\ndata: {JSON}\\n\\n"
    （非流式模式下也可能直接返回纯 JSON，两种都兼容）

【使用示例】
    from mcp_client import init_mcp, call_tool

    init_mcp()                                        # 建会话
    tools = list_tools()                              # 列出 24 个工具
    note  = call_tool('write_note', {                 # 写一条笔记
        'itemKey': 'LKNAGJ4N',
        'content': '<h1>精读笔记</h1>',
        'action': 'create',
    })

【Zotero MCP 服务器】
    名称：zotero-integrated-mcp ｜ 版本：1.1.0 ｜ 端口：127.0.0.1:23120
    24 个工具分四组：
      读：get_libraries / search_library / search_annotations / get_item_details /
          get_annotations / get_content / get_collections / search_collections /
          get_collection_details / get_collection_items / get_subcollections /
          search_fulltext / get_item_abstract / fulltext_database
      分类管理：create_collection / update_collection / delete_collection /
               add_items_to_collection / remove_items_from_collection
      写：write_note / write_tag / write_metadata / write_item
      删：delete_collection（分类级，默认不删条目）

⚠ 已知坑（截至 2026-08）：
    - get_annotations 只查 PDF 高亮注释，不查 notes → 验证笔记
      要用 search_annotations(type='note') 或 Zotero 客户端
    - write_tag 传含中文的 tag 时服务器可能报 Parse error
      （UTF-8 载荷解析 bug）→ tag 用英文/拼音；笔记正文中文正常
    - get_content 对大 PDF 可能超时（timeout 30s 不够）→ 建议先用
      fulltext_database
"""
import urllib.request
import json
import sys

# ---------------------------------------------------------------------------
# 配置区：Zotero MCP 服务器地址（zotero-mcp 插件默认端口 23120）
# ---------------------------------------------------------------------------
URL = 'http://127.0.0.1:23120/mcp'

# 会话 ID 存在 list 里是为了让 call_mcp 内部可以就地修改
# （Python 闭包对外层变量重新赋值需要 global/nonlocal，list 包装最省事）
SESSION_ID = [None]

# 终端在 Windows 下默认 GBK，强制切 UTF-8 避免打印中文报错
sys.stdout.reconfigure(encoding='utf-8')


def _parse_sse(body):
    """解析 MCP 响应体。

    MCP Streamable HTTP 的响应可能是两种格式：
      a) SSE 流：多行 "event: message\\ndata: {JSON}"，取第一行 data 的 JSON
      b) 纯 JSON：直接 json.loads
    返回解析后的 dict。
    """
    for line in body.split('\n'):
        line = line.strip()
        if line.startswith('data: '):
            return json.loads(line[6:])
    return json.loads(body)


def call_mcp(method, params=None, msg_id=1, timeout=30):
    """向 Zotero MCP 服务器发送一条 JSON-RPC 2.0 请求。

    参数：
        method   : MCP 方法名，如 'initialize' / 'tools/list' / 'tools/call'
        params   : 方法参数 dict
        msg_id   : JSON-RPC 请求 id（整数递增即可）
        timeout  : HTTP 超时秒数。get_content 等重工具建议调大。

    返回：
        (http_status, raw_body)

    副作用：
        首次 initialize 时会把响应头的 mcp-session-id 缓存到 SESSION_ID，
        之后的请求自动带上会话头。
    """
    payload = {'jsonrpc': '2.0', 'id': msg_id, 'method': method, 'params': params or {}}

    headers = {
        'Content-Type': 'application/json',
        # Accept 必须同时声明 json 和 text/event-stream，
        # 否则某些 MCP 服务器拒绝（协议规范要求）
        'Accept': 'application/json, text/event-stream',
    }
    if SESSION_ID[0]:
        # 会话凭证：initialize 的响应头里拿到的
        headers['mcp-session-id'] = SESSION_ID[0]

    req = urllib.request.Request(
        URL, data=json.dumps(payload).encode('utf-8'), headers=headers
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        # 缓存会话 ID（只在第一次拿到时存）
        sid = r.headers.get('mcp-session-id')
        if sid and not SESSION_ID[0]:
            SESSION_ID[0] = sid
        body = r.read().decode('utf-8')
    return r.status, body


def init_mcp():
    """建立 MCP 会话（三步握手中的第 1、2 步）。

    第 1 步：initialize —— 交换协议版本和能力，拿到会话 ID
    第 2 步：notifications/initialized —— 通知服务器握手完成
            （通知没有 id 字段，服务器不回响应体，异常可忽略）

    返回服务器信息 dict（name / version），失败抛异常。
    """
    status, body = call_mcp('initialize', {
        'protocolVersion': '2024-11-05',
        'capabilities': {},                      # 客户端能力（空即可）
        'clientInfo': {'name': 'claude-code', 'version': '2.0'},
    }, msg_id=1)
    d = _parse_sse(body)
    info = d.get('result', {}).get('serverInfo', {})
    print(f"MCP 会话建立: status={status}, server={info.get('name')} v{info.get('version')}")

    # 第 2 步：initialized 通知（无 id，服务器可能不回包，忽略一切异常）
    try:
        req = urllib.request.Request(
            URL,
            data=json.dumps({'jsonrpc': '2.0', 'method': 'notifications/initialized',
                             'params': {}}).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass
    return info


def list_tools():
    """列出 Zotero MCP 提供的全部工具（24 个）。

    返回 dict 列表，每项含 name / description / inputSchema。
    """
    status, body = call_mcp('tools/list', msg_id=2)
    d = _parse_sse(body)
    tools = d.get('result', {}).get('tools', [])
    print(f'可用工具共 {len(tools)} 个:')
    for t in tools:
        print(f"  - {t.get('name')}: {t.get('description', '')[:70]}")
    return tools


def call_tool(name, arguments, msg_id=10, timeout=30):
    """调用一个 Zotero MCP 工具并返回结果文本。

    参数：
        name      : 工具名，如 'write_note' / 'get_item_details'
        arguments : 工具参数 dict（结构见各工具的 inputSchema）
        timeout   : 重工具（get_content）建议 60-120

    返回：
        str  — result.content[0].text（MCP 把结果包在 content 数组里）
        dict — 某些工具直接返回结构化 result（没有 content 数组时）

    出错时（JSON-RPC error）返回 None 并打印错误。
    """
    status, body = call_mcp('tools/call', {'name': name, 'arguments': arguments},
                            msg_id=msg_id, timeout=timeout)
    d = _parse_sse(body)

    # JSON-RPC 层错误（如工具不存在、参数校验失败）
    if 'error' in d:
        print(f"MCP error [{name}]: {d['error']}")
        return None

    result = d.get('result', {})

    # isError=True 表示工具执行时抛了异常（但 HTTP 200），
    # 内容仍在 content 里原样返回，交给调用方判断
    if result.get('isError'):
        err_text = ''
        for c in result.get('content', []):
            if c.get('type') == 'text':
                err_text = c.get('text', '')
                break
        print(f"Tool error [{name}]: {err_text[:200]}")

    # 常规情况：结果包在 content[0].text
    content = result.get('content', [])
    if content and isinstance(content, list):
        for c in content:
            if c.get('type') == 'text':
                return c.get('text', '')

    # 少数工具直接返回结构化 result
    return result if result else None


# ---------------------------------------------------------------------------
# 命令行自检：python mcp_client.py 直接跑会做一次完整握手 + 列工具
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    init_mcp()
    print()
    list_tools()
