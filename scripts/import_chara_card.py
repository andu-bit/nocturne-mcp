"""
SillyTavern 角色卡 -> Nocturne Memory 导入工具

从酒馆角色卡 PNG 中提取角色数据，清洗前端代码，
通过 MCP stdio 接口直接调用 create_memory 注入到 narrative:// domain。

用法:
    python import_chara_card.py <角色卡.png> [--domain narrative] [--dry-run]

所有节点平摊在 domain 根节点下，路径由用户后续自行调整。
"""

import asyncio
import base64
import json
import re
import sys
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PIL import Image
from pypinyin import lazy_pinyin

# ---------------------------------------------------------------------------
# 1. 提取：从 PNG 读取 chara JSON
# ---------------------------------------------------------------------------


def extract_chara_json(png_path: str) -> dict:
    """从角色卡 PNG 的 tEXt chunk 中提取 JSON 数据。"""
    img = Image.open(png_path)
    chara = img.text.get("chara")
    if not chara:
        raise ValueError(f"{png_path} 中没有找到 chara 元数据")
    return json.loads(base64.b64decode(chara).decode("utf-8"))


# ---------------------------------------------------------------------------
# 2. 清洗：识别并剔除前端代码
# ---------------------------------------------------------------------------

# 检测一段文本是否是纯前端代码（HTML/CSS/JS 占比过高）
_HTML_RE = re.compile(
    r"<(?:div|span|style|script|section|head|body|link|meta|svg|canvas|"
    r"button|input|form|table|tr|td|html|!DOCTYPE)[>\s/]",
    re.IGNORECASE,
)
_CSS_RE = re.compile(
    r"(?:border-radius|font-family|background-color|animation|keyframes|"
    r"@import\s+url|@media|position:\s*(?:absolute|relative|fixed)|"
    r"display:\s*(?:flex|grid|none))",
    re.IGNORECASE,
)
_JS_RE = re.compile(
    r"(?:querySelector|getElementById|addEventListener|onclick|"
    r"function\s*\(|=>\s*\{|\.classList|\.style\.|document\.|window\.)",
    re.IGNORECASE,
)


def _frontend_score(text: str) -> float:
    """返回 0-1 之间的前端代码占比估计。"""
    if not text.strip():
        return 0.0
    html = len(_HTML_RE.findall(text))
    css = len(_CSS_RE.findall(text))
    js = len(_JS_RE.findall(text))
    # 每个匹配大约代表 ~50 字符的前端代码
    estimated_frontend_chars = (html + css + js) * 50
    return min(1.0, estimated_frontend_chars / max(len(text), 1))


def is_frontend_only(text: str, threshold: float = 0.3) -> bool:
    """文本是否主要由前端代码构成。"""
    return _frontend_score(text) > threshold


def is_script_entry(text: str) -> bool:
    """是否是酒馆助手脚本（伪代码/JS 事件监听）。"""
    indicators = [
        "_.ChangeOn(",
        "_.On(",
        "_.Emit(",
        "系统.事件标记",
        "// ==",
    ]
    return any(ind in text for ind in indicators)


# ---------------------------------------------------------------------------
# 3. 转换：角色卡 -> MemoryNode 列表
# ---------------------------------------------------------------------------


@dataclass
class MemoryNode:
    """一条待写入的记忆。"""
    title: str
    content: str
    priority: int = 5
    disclosure: str = ""


def _clean_text(text: str) -> str:
    """清理酒馆模板语法，保留纯文本。"""
    text = text.replace("{{char}}", "{char}")
    text = text.replace("{{user}}", "{user}")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # 去掉卡作者的 meta 信息行
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        # 跳过纯指令行（"禁止xxx！"）和作者签名
        if re.match(r"^禁止.+！$", line.strip()):
            continue
        if re.match(r"^#\s*作者[：:]", line.strip()):
            continue
        if "discord.gg/" in line.lower():
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def _strip_status_block(text: str) -> str:
    """去除 <当前状态>...</当前状态> 块（酒馆 UI 渲染用）。"""
    return re.sub(
        r"<当前状态>.*?</当前状态>",
        "",
        text,
        flags=re.DOTALL,
    ).strip()


def _to_safe_title(text: str, fallback: str = "untitled") -> str:
    """将任意文本转为合法的 memory title（ASCII only）。"""
    # 先用拼音替换中文字符
    result = []
    for char in text:
        if re.match(r"[a-zA-Z0-9_-]", char):
            result.append(char)
        elif "一" <= char <= "鿿":
            pinyin = lazy_pinyin(char)
            result.append(pinyin[0] if pinyin else "")
        elif char in (" ", "　", ":", "：", "/", "\\", "(", ")", "（", "）"):
            result.append("_")
        # 其他字符直接丢弃
    safe = "_".join("".join(result).split("_"))  # 不会有连续下划线
    safe = re.sub(r"_+", "_", safe).strip("_")
    return safe if safe else fallback


def convert_card(card_data: dict, char_name: str) -> list[MemoryNode]:
    """将角色卡数据转换为 MemoryNode 列表。"""
    data = card_data.get("data", card_data)
    nodes: list[MemoryNode] = []
    safe_name = _to_safe_title(char_name, fallback="char")

    # --- 顶层字段 ---

    # 主设定（description）
    desc = _clean_text(data.get("description", ""))
    if desc:
        nodes.append(MemoryNode(
            title=f"{safe_name}_profile",
            content=desc,
            priority=5,
            disclosure="当涉及「角色档案」设定时",
        ))

    # 性格（personality）
    personality = _clean_text(data.get("personality", ""))
    if personality:
        nodes.append(MemoryNode(
            title=f"{safe_name}_personality",
            content=personality,
            priority=5,
            disclosure="当涉及「性格」设定时",
        ))

    # 场景（scenario）
    scenario = _clean_text(data.get("scenario", ""))
    if scenario:
        nodes.append(MemoryNode(
            title=f"{safe_name}_scenario",
            content=scenario,
            priority=5,
            disclosure="当涉及「场景」设定时",
        ))

    # 对话示例（mes_example）
    mes_example = _clean_text(data.get("mes_example", ""))
    if mes_example:
        nodes.append(MemoryNode(
            title=f"{safe_name}_dialogue_examples",
            content=mes_example,
            priority=6,
            disclosure="当涉及「对话示例」设定时",
        ))

    # 开场白（alternate_greetings + first_mes）
    greetings = []
    first = _clean_text(data.get("first_mes", ""))
    if first:
        greetings.append(first)
    for g in data.get("alternate_greetings", []):
        cleaned = _strip_status_block(_clean_text(g))
        if cleaned:
            greetings.append(cleaned)

    if greetings:
        combined = "\n\n---\n\n".join(
            f"## 开场白 {i+1}\n{g}" for i, g in enumerate(greetings)
        )
        nodes.append(MemoryNode(
            title=f"{safe_name}_greetings",
            content=combined,
            priority=6,
            disclosure="当涉及「开场白」设定时",
        ))

    # 系统提示词（system_prompt）
    sys_prompt = _clean_text(data.get("system_prompt", ""))
    if sys_prompt:
        nodes.append(MemoryNode(
            title=f"{safe_name}_system_prompt",
            content=sys_prompt,
            priority=4,
            disclosure="当涉及「系统指令 / 扮演约束」设定时",
        ))

    # 后置指令（post_history_instructions）
    post_hist = _clean_text(data.get("post_history_instructions", ""))
    if post_hist:
        nodes.append(MemoryNode(
            title=f"{safe_name}_post_history_instructions",
            content=post_hist,
            priority=4,
            disclosure="当涉及「后置指令 / 行为约束」设定时",
        ))

    # 深度插入提示词（extensions.depth_prompt）
    depth_prompt = _clean_text(
        data.get("extensions", {}).get("depth_prompt", {}).get("prompt", "")
    )
    if depth_prompt:
        depth = data["extensions"]["depth_prompt"].get("depth", "?")
        depth_role = data["extensions"]["depth_prompt"].get("role", "system")
        nodes.append(MemoryNode(
            title=f"{safe_name}_depth_prompt",
            content=f"[depth={depth}, role={depth_role}]\n{depth_prompt}",
            priority=4,
            disclosure="当涉及「深度插入指令」设定时",
        ))

    # --- 世界书条目 ---
    book = data.get("character_book", {})
    entries = book.get("entries", [])

    for i, entry in enumerate(entries):
        name = entry.get("name", entry.get("comment", f"entry_{i}"))
        content = entry.get("content", "")
        keys = entry.get("keys", [])

        # 跳过空内容
        if not content.strip():
            continue

        # 跳过前端代码和脚本
        if is_frontend_only(content):
            print(f"  [跳过/前端] {name}")
            continue
        if is_script_entry(content):
            print(f"  [跳过/脚本] {name}")
            continue

        cleaned = _clean_text(content)
        if not cleaned:
            continue

        # title 清理：中文转拼音，只保留 ASCII 合法字符
        safe_title = _to_safe_title(name, fallback=f"entry_{i}")

        # 如果有 keys，附加到内容开头作为上下文
        if keys:
            cleaned = f"[触发词: {', '.join(keys)}]\n{cleaned}"

        nodes.append(MemoryNode(
            title=f"wb_{safe_title}",
            content=cleaned,
            priority=6,
            disclosure=f"当涉及「{name}」设定时",
        ))

    # --- 跳过 extensions.regex_scripts（纯 UI 渲染） ---

    return nodes


# ---------------------------------------------------------------------------
# 4. 注入：通过 MCP stdio 调用 create_memory
# ---------------------------------------------------------------------------


async def inject_to_memory(
    nodes: list[MemoryNode],
    domain: str = "narrative",
    dry_run: bool = False,
):
    """连接 MCP server，逐条调用 create_memory。"""
    if dry_run:
        print(f"\n[DRY RUN] 将创建 {len(nodes)} 条记忆到 {domain}://\n")
        for node in nodes:
            print(f"  {domain}://{node.title}")
            print(f"    priority: {node.priority}")
            print(f"    disclosure: {node.disclosure}")
            print(f"    content: {node.content[:80]}...")
            print()
        return

    from mcp.client.session import ClientSession
    from mcp.client.stdio import stdio_client, StdioServerParameters

    # 定位 MCP server
    server_script = (
        Path(__file__).resolve().parent.parent / "backend" / "mcp_server.py"
    )
    if not server_script.exists():
        raise FileNotFoundError(f"MCP server not found: {server_script}")

    server_params = StdioServerParameters(
        command="python",
        args=[str(server_script)],
    )

    print(f"\n[连接] MCP server: {server_script}")

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            print("[就绪] MCP session 已建立\n")

            parent_uri = f"{domain}://"
            success = 0
            failed = 0

            for node in nodes:
                try:
                    result = await session.call_tool(
                        "create_memory",
                        arguments={
                            "parent_uri": parent_uri,
                            "content": node.content,
                            "priority": node.priority,
                            "disclosure": node.disclosure,
                            "title": node.title,
                        },
                    )
                    # 提取结果文本
                    result_text = ""
                    if result.content:
                        for block in result.content:
                            if hasattr(block, "text"):
                                result_text = block.text
                                break

                    if "Error" in result_text:
                        print(f"  [失败] {node.title}: {result_text}")
                        failed += 1
                    else:
                        print(f"  [成功] {node.title}")
                        success += 1
                except Exception as e:
                    print(f"  [异常] {node.title}: {e}")
                    failed += 1

            print(f"\n[完成] 成功: {success}, 失败: {failed}")


# ---------------------------------------------------------------------------
# 5. CLI 入口
# ---------------------------------------------------------------------------


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="SillyTavern 角色卡 -> Nocturne Memory 导入工具",
    )
    parser.add_argument("png_path", help="角色卡 PNG 文件路径")
    parser.add_argument(
        "--domain", default="narrative", help="目标 domain (默认: narrative)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="只预览，不实际写入"
    )
    args = parser.parse_args()

    # 提取
    print(f"[提取] {args.png_path}")
    card_data = extract_chara_json(args.png_path)

    data = card_data.get("data", card_data)
    char_name = data.get("name", "unknown")
    print(f"[角色] {char_name}")

    # 转换
    nodes = convert_card(card_data, char_name)
    print(f"[转换] 生成 {len(nodes)} 条记忆节点")

    # 注入
    asyncio.run(inject_to_memory(nodes, domain=args.domain, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
