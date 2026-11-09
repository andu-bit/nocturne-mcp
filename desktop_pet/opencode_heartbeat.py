#!/usr/bin/env python3
"""
OpenCode Heartbeat - Session Keep-Alive Script
保活 OpenCode 的 session，定期发送心跳消息

特性：
- 发送心跳前检查是否有权限等待批准
- 如果有权限等待批准，暂停发送心跳
- 每次心跳附带屏幕截图
- 解析 AI 回复中的 [speak] 标签，触发桌面气泡 + TTS
- 无 SSE 长连接，减少内存占用

Usage:
    python opencode_heartbeat.py
"""

import requests
import time
import datetime
import threading
import os
from pathlib import Path
from typing import Optional, List
from dotenv import find_dotenv, load_dotenv

from heartbeat_engine import (
    HeartbeatConfig,
    ScreenshotMode,
    build_heartbeat_message,
    build_email_section,
    capture_screenshot,
    fetch_unread_emails,
    trigger_speak,
    process_response,
)

_dotenv_path = find_dotenv(usecwd=True)
if _dotenv_path:
    load_dotenv(_dotenv_path)


def require_env(name: str) -> str:
    """読取必需環境変量，缺失時拋出可讀錯誤。"""
    value = os.getenv(name)
    if not value:
        raise ValueError(
            f"缺少环境变量 {name}。请在 .env 中设置它后再运行脚本。"
        )
    return value


# ============================================================
# 配置区
# ============================================================

# OpenCode API 地址（默认本地）
OPENCODE_BASE_URL = "http://localhost:4096"

# OpenCode API 身份验证与 Session ID 从 .env 读取
OPENCODE_USERNAME = require_env("OPENCODE_USERNAME")
OPENCODE_PASSWORD = require_env("OPENCODE_PASSWORD")
SESSION_ID = require_env("SESSION_ID")

# 心跳间隔（秒）
# 建议 300-600 秒（5-10分钟），太频繁会浪费 token
HEARTBEAT_INTERVAL_SECONDS = 900

# 是否显示详细日志
VERBOSE = True

ENGINE_CONFIG = HeartbeatConfig(
    source_name="opencode_heartbeat.py",
    screenshot_mode=ScreenshotMode(
        os.getenv("AG_SCREENSHOT_MODE", "attach")
    ),
)

# ============================================================
# 全局状态
# ============================================================

# 心跳锁 - 防止并发发送
heartbeat_lock = threading.Lock()
is_heartbeat_in_progress = False
last_heartbeat_start_time = None


# ============================================================
# 权限检查 (REST API 轮询)
# ============================================================


def get_pending_permissions() -> List[dict]:
    """通过 REST API 获取所有 pending permissions"""
    url = f"{OPENCODE_BASE_URL}/permission"

    try:
        auth = (OPENCODE_USERNAME, OPENCODE_PASSWORD) if OPENCODE_USERNAME else None
        response = requests.get(url, timeout=10, auth=auth)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        log(f"[WARN] 获取权限列表失败: {e}")
        return []


def has_pending_permissions_for_session() -> bool:
    """检查当前 session 是否有等待批准的权限"""
    permissions = get_pending_permissions()

    # 过滤出当前 session 的权限请求
    session_permissions = [p for p in permissions if p.get("sessionID") == SESSION_ID]

    if session_permissions:
        for perm in session_permissions:
            perm_id = perm.get("id", "unknown")
            log(f"[PERM] 发现待批准权限: {perm_id}")

    return len(session_permissions) > 0


def get_session_status() -> Optional[str]:
    """通过 /session/status 获取当前 session 的状态（idle/busy/unknown）"""
    url = f"{OPENCODE_BASE_URL}/session/status"
    try:
        auth = (OPENCODE_USERNAME, OPENCODE_PASSWORD) if OPENCODE_USERNAME else None
        response = requests.get(url, timeout=10, auth=auth)
        response.raise_for_status()
        statuses = response.json()
        session_info = statuses.get(SESSION_ID, {})
        return session_info.get("type")
    except requests.exceptions.RequestException as e:
        log(f"[WARN] 获取 session 状态失败: {e}")
        return None


def wait_until_ready(poll_interval: int = 10, max_wait: int = 900) -> bool:
    """统一排队：轮询等待所有阻塞条件清除。返回 True=可以发送, False=超时放弃。
    阻塞条件：权限待批准 / 上一个心跳未完成 / AI 正在回复(busy)
    """
    waited = 0
    last_reason = ""

    while waited < max_wait:
        reason = ""

        if has_pending_permissions_for_session():
            reason = "权限待批准"
        elif is_heartbeat_in_progress:
            reason = "上一个心跳未完成"
        else:
            status = get_session_status()
            if status is not None and status != "idle":
                reason = f"AI 正在回复 (status={status})"

        if not reason:
            if waited > 0:
                log(f"[QUEUE] 阻塞已解除 (等待了 {waited}秒)，准备发送心跳")
            return True

        if reason != last_reason:
            log(f"[QUEUE] 心跳排队等待: {reason}")
            last_reason = reason

        time.sleep(poll_interval)
        waited += poll_interval

    log(f"[QUEUE] 等待超时 ({max_wait}秒, 最后阻塞: {last_reason})，放弃本次心跳")
    return False


# ============================================================
# 核心逻辑
# ============================================================


def log(msg: str):
    if VERBOSE:
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {msg}")


def send_heartbeat(
    session_id: str, message: str, screenshot_path: Optional[str] = None
) -> Optional[dict]:
    """向 OpenCode session 发送消息，可选附带截图。"""
    url = f"{OPENCODE_BASE_URL}/session/{session_id}/message"

    parts: list[dict] = [{"type": "text", "text": message}]
    if screenshot_path:
        file_url = Path(screenshot_path).as_uri()
        parts.append(
            {
                "type": "file",
                "url": file_url,
                "mime": "image/png",
                "filename": "screen.png",
            }
        )

    payload = {"parts": parts}
    headers = {"Content-Type": "application/json"}

    try:
        auth = (OPENCODE_USERNAME, OPENCODE_PASSWORD) if OPENCODE_USERNAME else None
        response = requests.post(
            url, json=payload, headers=headers, timeout=None, auth=auth
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] 发送心跳失败: {e}")
        return None


def extract_response_text(response: dict) -> str:
    """从 API 响应中提取文本内容"""
    if not response:
        return "(无响应)"

    parts = response.get("parts", [])
    texts = []
    for part in parts:
        if part.get("type") == "text":
            texts.append(part.get("text", ""))

    return "\n".join(texts) if texts else "(无文本内容)"


def get_all_messages(session_id: str) -> Optional[list[dict]]:
    """通过 REST API 获取会话的所有消息"""
    url = f"{OPENCODE_BASE_URL}/session/{session_id}/message"
    try:
        auth = (OPENCODE_USERNAME, OPENCODE_PASSWORD) if OPENCODE_USERNAME else None
        response = requests.get(url, timeout=10, auth=auth)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        log(f"[WARN] 获取消息列表失败: {e}")
        return None


def do_heartbeat(heartbeat_count: int):
    """执行单次心跳（在单独线程中运行）"""
    global is_heartbeat_in_progress, last_heartbeat_start_time

    with heartbeat_lock:
        is_heartbeat_in_progress = True
        last_heartbeat_start_time = datetime.datetime.now()

    try:
        # 获取心跳前的消息总数，以便后续提取心跳过程中的所有中间消息
        messages_before = get_all_messages(SESSION_ID)

        screenshot_path = capture_screenshot(ENGINE_CONFIG, log)
        screenshot_taken = screenshot_path is not None
        if screenshot_path:
            kb = os.path.getsize(screenshot_path) // 1024
            log(f"截图完成 ({kb} KB) → {screenshot_path}")
        else:
            log("截图不可用，发送纯文本心跳")

        message = build_heartbeat_message(
            ENGINE_CONFIG, screenshot_taken=screenshot_taken
        )

        if ENGINE_CONFIG.email_enabled:
            emails = fetch_unread_emails(log)
            log(f"邮箱检查完成: 找到 {len(emails)} 封未读邮件")
            if emails:
                message += build_email_section(emails, ENGINE_CONFIG)
                log(f"提示了 {len(emails)} 封未读邮件的存在")

        log(f"发送心跳 #{heartbeat_count}...")
        start_time = time.time()
        response = send_heartbeat(SESSION_ID, message, screenshot_path)
        elapsed = time.time() - start_time

        if response:
            log(f"心跳 #{heartbeat_count} 成功 (耗时 {elapsed:.1f}秒)")

            # 获取心跳后的消息列表，提取新增的 assistant 消息
            messages_after = get_all_messages(SESSION_ID)

            full_reply = ""

            if messages_before is not None and messages_after is not None:
                count_before = len(messages_before)
                new_messages = messages_after[count_before:]

                all_assistant_texts = []
                for msg in new_messages:
                    if msg.get("info", {}).get("role") == "assistant":
                        all_assistant_texts.append(extract_response_text(msg))

                full_reply = "\n".join(all_assistant_texts)

            # 如果未能成功通过历史记录获取新增消息（或者由于其他原因解析为空），回退使用本次心跳直接返回的最后一条响应文本
            if not full_reply:
                full_reply = extract_response_text(response)

            actions = process_response(full_reply)
            if actions.speak_text:
                trigger_speak(actions.speak_text, ENGINE_CONFIG, log)

            # 日志仅打印最后一次响应的摘要
            reply = extract_response_text(response)
            if len(reply) > 200:
                reply = reply[:200] + "..."
            log(f"回复摘要: {reply}")

            info = response.get("info", {})
            tokens = info.get("tokens", {})
            if tokens:
                log(
                    f"Token: input={tokens.get('input', 0)}, output={tokens.get('output', 0)}"
                )
        else:
            log(f"心跳 #{heartbeat_count} 失败")

    finally:
        with heartbeat_lock:
            is_heartbeat_in_progress = False


def main():
    """主循环"""
    global is_heartbeat_in_progress, last_heartbeat_start_time

    print("=" * 60)
    print("OpenCode Heartbeat - Session Keep-Alive")
    print("=" * 60)
    print(f"Session ID: {SESSION_ID}")
    print(
        f"心跳间隔: {HEARTBEAT_INTERVAL_SECONDS} 秒 ({HEARTBEAT_INTERVAL_SECONDS // 60} 分钟)"
    )
    print(f"API 地址: {OPENCODE_BASE_URL}")
    print(f"截图模式: {ENGINE_CONFIG.screenshot_mode.value}")
    print("=" * 60)
    print("特性:")
    print("  - 统一排队机制: 权限待批/AI回复中/上次心跳未完 → 轮询等待")
    print(f"  - 桌面宠物: {'启用' if os.path.exists(ENGINE_CONFIG.speak_script) else '未找到 speak.py'}")
    print("  - 无 SSE 长连接")
    print("按 Ctrl+C 停止\n")

    heartbeat_count = 0
    skipped_count = 0

    try:
        while True:
            # 统一排队：等待所有阻塞条件清除后再发送
            if wait_until_ready():
                heartbeat_count += 1
                heartbeat_thread = threading.Thread(
                    target=do_heartbeat, args=(heartbeat_count,), daemon=True
                )
                heartbeat_thread.start()
            else:
                skipped_count += 1
                log(f"累计跳过 {skipped_count} 次心跳\n")

            log(f"等待 {HEARTBEAT_INTERVAL_SECONDS} 秒后检查下一次心跳...\n")
            time.sleep(HEARTBEAT_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        print("\n\n已停止心跳程序。")
        print(f"共发送 {heartbeat_count} 次心跳，跳过 {skipped_count} 次。")

        if is_heartbeat_in_progress:
            print("注意: 最后一个心跳可能还在后台运行中。")


if __name__ == "__main__":
    main()
