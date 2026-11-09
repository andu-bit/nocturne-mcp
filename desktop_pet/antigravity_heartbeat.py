#!/usr/bin/env python3
"""
AntiGravity Heartbeat - CDP Session Keep-Alive
通过 Chrome DevTools Protocol 向 AntiGravity IDE 注入心跳消息

与 opencode_heartbeat.py 的区别：
  - OpenCode 有 REST API (localhost:4096)  → 直接 HTTP 调用
  - AntiGravity 无外部 API              → CDP 操作浏览器 DOM

前置条件:
  1. AntiGravity 以远程调试端口启动：
     在快捷方式目标末尾加 --remote-debugging-port=9222

Usage:
    python antigravity_heartbeat.py              # 正常心跳
    python antigravity_heartbeat.py --probe      # 探测 DOM 结构（调试用）
    python antigravity_heartbeat.py --once       # 只跑一次心跳就退出
"""

import json
import asyncio
import time
import datetime
import os
import sys
import threading
import urllib.request
from typing import Optional

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

# Windows asyncio compatibility
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

try:
    import websockets
    import websockets.asyncio.client as ws_client

    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False


# ============================================================
# 配置区
# ============================================================

# CDP 远程调试端口（与 AntiGravity 启动参数一致）
CDP_PORT = int(os.getenv("AG_CDP_PORT", "9222"))

# 心跳间隔（秒）
HEARTBEAT_INTERVAL_SECONDS = int(os.getenv("AG_HEARTBEAT_INTERVAL", "900"))

# AI 生成超时（秒）- 超过此时间视为卡死
GENERATION_TIMEOUT = int(os.getenv("AG_GENERATION_TIMEOUT", "600"))

# 生成状态轮询间隔（秒）
GENERATION_POLL_INTERVAL = 3
VERBOSE = True

ENGINE_CONFIG = HeartbeatConfig(
    source_name="antigravity_heartbeat.py (CDP injection)",
    screenshot_mode=ScreenshotMode(
        os.getenv("AG_SCREENSHOT_MODE", "disabled")
    ),
)

# ============================================================
# 全局状态
# ============================================================

heartbeat_lock = threading.Lock()
is_heartbeat_in_progress = False


# ============================================================
# 日志
# ============================================================


def log(msg: str):
    if VERBOSE:
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] {msg}")


# ============================================================
# CDP Layer - 与浏览器的原始通信
# ============================================================


def discover_target(port: int) -> Optional[str]:
    """通过 /json 端点发现 AntiGravity 的 CDP 目标，返回 WebSocket URL。"""
    try:
        url = f"http://localhost:{port}/json"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=3) as resp:
            targets = json.loads(resp.read().decode())
    except Exception as e:
        log(f"[CDP] 无法连接调试端口 localhost:{port} — {e}")
        return None

    best = None
    best_score = -999

    for t in targets:
        if t.get("type") != "page":
            continue

        title = t.get("title", "")
        t_url = t.get("url", "")

        # 硬过滤：跳过无法调试的目标
        if t_url.startswith("data:"):
            continue
        if t_url.startswith("chrome-extension://"):
            continue
        if "devtools" in t_url.lower():
            continue
        if not t.get("webSocketDebuggerUrl"):
            continue

        score = 0

        # 加分：工作台、AntiGravity 关键字
        if "workbench" in title.lower() or "workbench" in t_url.lower():
            score += 8
        if "antigravity" in title.lower():
            score += 3
        # Electron 主窗口通常用 file:// 或 http://localhost
        if t_url.startswith("file://") or "localhost" in t_url:
            score += 1

        # 减分
        if "extension" in t_url.lower():
            score -= 10

        if score > best_score:
            best_score = score
            best = t

    if best:
        ws_url = best.get("webSocketDebuggerUrl")
        if ws_url:
            log(f"[CDP] 发现目标: {best.get('title', '?')[:60]} (score={best_score})")
            return ws_url

    log(f"[CDP] 在 {len(targets)} 个目标中未找到合适的 AntiGravity 页面")
    return None


class CDPSession:
    """最小 CDP 客户端 - JSON-RPC over WebSocket。"""

    def __init__(self, ws):
        self.ws = ws
        self._msg_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._listener_task: Optional[asyncio.Task] = None

    async def start(self):
        self._listener_task = asyncio.create_task(self._listen())
        await self.send("Runtime.enable")

    async def close(self):
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass

    async def _listen(self):
        """后台监听：将 CDP 响应路由到对应的 Future。"""
        try:
            async for raw in self.ws:
                data = json.loads(raw)
                msg_id = data.get("id")
                if msg_id is not None and msg_id in self._pending:
                    self._pending[msg_id].set_result(data)
                # CDP 事件（无 id）直接丢弃
        except Exception:
            # 连接断开时取消所有等待中的 Future
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(ConnectionError("CDP WebSocket closed"))

    async def send(self, method: str, params: dict = None, timeout: float = 15):
        self._msg_id += 1
        msg_id = self._msg_id
        msg = {"id": msg_id, "method": method}
        if params:
            msg["params"] = params

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending[msg_id] = future

        try:
            await self.ws.send(json.dumps(msg))
            result = await asyncio.wait_for(future, timeout=timeout)
            if "error" in result:
                raise RuntimeError(f"CDP error: {result['error']}")
            return result.get("result", {})
        finally:
            self._pending.pop(msg_id, None)

    async def evaluate(
        self, expression: str, await_promise: bool = False, timeout: float = 15
    ):
        """在页面上下文中执行 JavaScript，返回值。"""
        params = {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": await_promise,
        }
        result = await self.send("Runtime.evaluate", params, timeout=timeout)

        if "exceptionDetails" in result:
            exc = result["exceptionDetails"]
            desc = exc.get("text", "unknown")
            if "exception" in exc:
                desc = exc["exception"].get("description", desc)
            raise RuntimeError(f"JS exception: {desc}")

        return result.get("result", {}).get("value")


# ============================================================
# AntiGravity DOM 交互 - 注入的 JavaScript 代码
# ============================================================

# --- 步骤 1: 向编辑器注入文字（同步） ---
INJECT_TEXT_JS = """
(() => {
    const editor = [...document.querySelectorAll('[contenteditable="true"]')]
        .filter(e => e.offsetParent !== null)
        .pop();
    if (!editor) return { ok: false, reason: "editor_not_found" };

    editor.focus();
    document.execCommand("selectAll", false, null);
    document.execCommand("delete", false, null);

    const text = __HEARTBEAT_TEXT__;
    let inserted = false;
    try { inserted = !!document.execCommand("insertText", false, text); } catch {}
    if (!inserted) {
        editor.textContent = text;
        editor.dispatchEvent(new InputEvent("beforeinput", {
            bubbles: true, inputType: "insertText", data: text
        }));
        editor.dispatchEvent(new InputEvent("input", {
            bubbles: true, inputType: "insertText", data: text
        }));
    }

    return { ok: true, inserted: inserted };
})()
"""

# --- 步骤 2: 点击发送按钮（同步，文字注入后稍等再调用） ---
CLICK_SEND_JS = """
(() => {
    const submitSelectors = [
        'button[data-testid="send-button"]',
        'button[data-tooltip-id="input-send-button-send-tooltip"]',
    ];

    for (const sel of submitSelectors) {
        const btn = document.querySelector(sel);
        if (btn && btn.offsetParent !== null) {
            btn.click();
            return { ok: true, method: "click_submit", selector: sel };
        }
    }

    // Fallback: Enter 键
    const editor = [...document.querySelectorAll('[contenteditable="true"]')]
        .filter(e => e.offsetParent !== null)
        .pop();
    if (editor) {
        editor.dispatchEvent(new KeyboardEvent("keydown", {
            bubbles: true, key: "Enter", code: "Enter"
        }));
        editor.dispatchEvent(new KeyboardEvent("keyup", {
            bubbles: true, key: "Enter", code: "Enter"
        }));
        return { ok: true, method: "enter_key" };
    }

    return { ok: false, reason: "send_button_not_found" };
})()
"""

# --- 检测是否正在生成 ---
IS_GENERATING_JS = """
(() => {
    // 策略 1: Cancel 按钮（生成中 send 按钮变为 cancel，tooltip-id 跟着变）
    const cancelBtn = document.querySelector(
        '[data-tooltip-id="input-send-button-cancel-tooltip"]'
    );
    if (cancelBtn && cancelBtn.offsetParent !== null)
        return { generating: true, strategy: 1, detail: "cancel-tooltip visible" };

    // 策略 2: send-button 存在但 aria-label 变成了 stop/cancel 相关
    const sendBtn = document.querySelector('button[data-testid="send-button"]');
    if (sendBtn) {
        const label = (sendBtn.getAttribute('aria-label') || '').toLowerCase();
        if (label.includes('stop') || label.includes('cancel'))
            return { generating: true, strategy: 2, detail: "aria-label=" + label };
    }

    // 策略 3 已移除：animate-spin/animate-pulse 匹配聊天区内的装饰性 SVG，
    // 空闲时也会误报。策略 1+2 已足够检测生成状态。

    return { generating: false };
})()
"""

# --- 检测用户是否正在使用编辑器 ---
IS_USER_ACTIVE_JS = """
(() => {
    const editor = [...document.querySelectorAll('[contenteditable="true"]')]
        .filter(e => e.offsetParent !== null)
        .pop();
    if (!editor) return { active: false, reason: "no_editor" };

    const text = (editor.innerText || editor.textContent || "").trim();
    const isFocused = document.activeElement === editor
        || editor.contains(document.activeElement);

    // 编辑器里有内容 = 用户在打字（还没发送）
    if (text.length > 0) return { active: true, reason: "editor_has_content", len: text.length };
    // 编辑器被聚焦 = 用户可能正要打字
    if (isFocused) return { active: true, reason: "editor_focused" };

    return { active: false };
})()
"""

# --- 检测 AI 回合是否尚未完成（工具审批等待/多步执行间隙）---
# 信号：AntiGravity 在回合完全结束后才会在末尾追加时间戳（如 "22:17"）。
# 如果最后一个 turn 有 AI 内容但没有时间戳 → 回合尚未完成。
IS_TURN_INCOMPLETE_JS = """
(() => {
    const scrollArea = document.querySelector('.scrollbar-hide');
    if (!scrollArea) return { incomplete: false };

    const wrapper = scrollArea.querySelector('.mx-auto > div');
    if (!wrapper) return { incomplete: false };

    let msgContainer = null;
    for (const c of wrapper.children) {
        if (c.children.length > 0 && c.className.includes('flex-col')) {
            msgContainer = c;
            break;
        }
    }
    if (!msgContainer || msgContainer.children.length === 0) return { incomplete: false };

    const lastTurn = msgContainer.children[msgContainer.children.length - 1];
    const turnInner = lastTurn.querySelector('.group.w-full');

    // 没有 AI 回复区域 → 可能是空对话，不阻塞
    if (!turnInner || turnInner.children.length < 2) return { incomplete: false };

    // 回合完成时，整个 turn 的 innerText 末尾会出现时间戳（如 "22:17"）
    const text = (lastTurn.innerText || '').trim();
    const hasTimestamp = /\\d{1,2}:\\d{2}\\s*$/.test(text);

    if (!hasTimestamp) {
        return { incomplete: true, textEnd: text.slice(-60) };
    }

    return { incomplete: false };
})()
"""

# --- 提取最新的 AI 回复 ---
# DOM 路径: .scrollbar-hide > .mx-auto > div > div[flex-col gap-y-3]
#   每个 turn: div.flex.items-start > div.flex.flex-col.group.w-full
#     children[0] = 用户消息 (sticky)
#     children[1] = AI 回复
EXTRACT_RESPONSE_JS = """
(() => {
    // 1. 找消息列表
    const scrollArea = document.querySelector(".scrollbar-hide");
    if (!scrollArea) return { ok: false, text: "(scrollbar-hide not found)" };

    const wrapper = scrollArea.querySelector(".mx-auto > div");
    if (!wrapper) return { ok: false, text: "(mx-auto wrapper not found)" };

    // wrapper.children: [divider, msgContainer, divider, ...]
    // msgContainer 是有 childCount > 0 且包含 flex-col 的那个
    let msgContainer = null;
    for (const c of wrapper.children) {
        if (c.children.length > 0 && c.className.includes("flex-col")) {
            msgContainer = c;
            break;
        }
    }
    if (!msgContainer || msgContainer.children.length === 0) {
        return { ok: false, text: "(no message container)" };
    }

    // 2. 取最后一个 turn
    const lastTurn = msgContainer.children[msgContainer.children.length - 1];
    const turnInner = lastTurn.querySelector(".group.w-full");
    if (!turnInner || turnInner.children.length < 2) {
        return { ok: false, text: "(turn structure unexpected)" };
    }

    // 3. children[0] = 用户消息, children[1..n] = AI 回复（可能多个工具调用块）
    //    收集所有 AI 输出块的文本
    const parts = [];
    for (let i = 1; i < turnInner.children.length; i++) {
        const block = turnInner.children[i];
        const t = (block.innerText || "").trim();
        if (t) parts.push(t);
    }
    let text = parts.join("\\n\\n");

    // 4. 去掉末尾的时间戳（格式如 "7:26" 或 "15:03"）
    text = text.replace(/\\n\\d{1,2}:\\d{2}\\s*$/, "").trim();

    return { ok: true, text: text, blocks: parts.length };
})()
"""

# --- 探测 DOM 结构（调试用） ---
PROBE_DOM_JS = """
(() => {
    const R = {};

    // ── 编辑器 ──
    // 已知能命中：div.max-h-[300px].rounded-md.cursor-text
    const ce = document.querySelectorAll('[contenteditable="true"]');
    R.contenteditables = [...ce].map(e => ({
        visible: e.offsetParent !== null,
        tag: e.tagName,
        classes: e.className.slice(0, 120),
        parent: e.parentElement ? e.parentElement.className.slice(0, 120) : null,
    }));

    // ── 所有 button（找发送/取消按钮）──
    const btns = document.querySelectorAll('button');
    R.buttons = [...btns].filter(b => b.offsetParent !== null).map(b => {
        const svg = b.querySelector('svg');
        return {
            ariaLabel: b.getAttribute('aria-label') || '',
            title: b.getAttribute('title') || '',
            disabled: b.disabled,
            classes: b.className.slice(0, 100),
            dataAttrs: [...b.attributes]
                .filter(a => a.name.startsWith('data-'))
                .map(a => a.name + '=' + a.value.slice(0, 40)),
            innerText: (b.innerText || '').slice(0, 40),
            hasSvg: !!svg,
            svgClasses: svg ? svg.className.baseVal.slice(0, 80) : null,
        };
    });

    // ── 所有 SVG（找图标类型）──
    const svgs = document.querySelectorAll('svg[class]');
    R.svgIcons = [...svgs].slice(0, 30).map(s => s.className.baseVal.slice(0, 80));

    // ── 滚动容器 / 消息容器（找对话区域）──
    // 查找有 overflow-y scroll/auto 的大容器
    const scrollables = [...document.querySelectorAll('div')].filter(d => {
        const s = getComputedStyle(d);
        return (s.overflowY === 'auto' || s.overflowY === 'scroll')
            && d.scrollHeight > 300
            && d.offsetParent !== null;
    });
    R.scrollContainers = scrollables.map(d => ({
        id: d.id || null,
        classes: d.className.slice(0, 120),
        childCount: d.children.length,
        scrollHeight: d.scrollHeight,
        role: d.getAttribute('role'),
        dataAttrs: [...d.attributes]
            .filter(a => a.name.startsWith('data-'))
            .map(a => a.name + '=' + a.value.slice(0, 40)),
    }));

    // ── 带 data- 属性的元素（找消息角色标记）──
    const dataEls = [...document.querySelectorAll('[data-role], [data-message-role], [data-testid], [data-type]')];
    R.dataMarkedElements = dataEls.slice(0, 20).map(e => ({
        tag: e.tagName,
        attrs: [...e.attributes]
            .filter(a => a.name.startsWith('data-'))
            .map(a => a.name + '=' + a.value.slice(0, 60)),
        textLen: (e.innerText || '').length,
    }));

    // ── 编辑器附近的按钮（最可能是发送按钮）──
    const editor = document.querySelector('[contenteditable="true"]');
    if (editor) {
        // 向上找包含编辑器的表单/容器，再在里面找 button
        let container = editor.parentElement;
        for (let i = 0; i < 5 && container; i++) {
            const localBtns = container.querySelectorAll('button');
            if (localBtns.length > 0 && localBtns.length < 10) {
                R.editorNearbyButtons = [...localBtns].map(b => ({
                    ariaLabel: b.getAttribute('aria-label') || '',
                    title: b.getAttribute('title') || '',
                    disabled: b.disabled,
                    classes: b.className.slice(0, 100),
                    innerText: (b.innerText || '').slice(0, 40),
                    hasSvg: !!b.querySelector('svg'),
                    html: b.outerHTML.slice(0, 300),
                }));
                R.editorContainerLevel = i;
                break;
            }
            container = container.parentElement;
        }
    }

    return R;
})()
"""


# ============================================================
# AntiGravity 交互函数
# ============================================================


async def inject_message(cdp: CDPSession, text: str) -> bool:
    """向编辑器注入文字并点击发送。"""
    safe_text = json.dumps(text)
    inject_js = INJECT_TEXT_JS.replace("__HEARTBEAT_TEXT__", safe_text)

    # 步骤 1: 注入文字
    result = await cdp.evaluate(inject_js, timeout=10)
    if not isinstance(result, dict) or not result.get("ok"):
        reason = result.get("reason") if isinstance(result, dict) else result
        log(f"[AG] 文字注入失败: {reason}")
        return False
    log(f"[AG] 文字已注入 (execCommand={result.get('inserted')})")

    # 等 UI 刷新（React 需要一个 tick 来响应 input 事件）
    await asyncio.sleep(0.5)

    # 步骤 2: 点击发送
    result = await cdp.evaluate(CLICK_SEND_JS, timeout=10)
    if isinstance(result, dict) and result.get("ok"):
        log(f"[AG] 发送成功 (method={result.get('method')})")
        return True
    else:
        reason = result.get("reason") if isinstance(result, dict) else result
        log(f"[AG] 发送失败: {reason}")
        return False


async def check_generating(cdp: CDPSession) -> bool:
    """检查 AI 是否正在生成回复。"""
    try:
        result = await cdp.evaluate(IS_GENERATING_JS)
        if isinstance(result, dict):
            if result.get("generating"):
                log(f"[AG] 生成检测触发: 策略{result.get('strategy')} — {result.get('detail','?')}")
                return True
            return False
        return bool(result)
    except Exception as e:
        log(f"[AG] 生成状态检查失败: {e}")
        return False


async def check_turn_incomplete(cdp: CDPSession) -> tuple[bool, str]:
    """检查最后一个 AI 回合是否尚未完成（工具审批中、多步执行间隙等）。"""
    try:
        result = await cdp.evaluate(IS_TURN_INCOMPLETE_JS)
        if isinstance(result, dict) and result.get("incomplete"):
            detail = result.get("textEnd", "")
            return True, detail
        return False, ""
    except Exception as e:
        log(f"[AG] 回合完整性检查失败: {e}")
        return False, ""


async def check_user_active(cdp: CDPSession) -> tuple[bool, str]:
    """检查用户是否正在使用编辑器。返回 (是否活跃, 原因)。"""
    try:
        result = await cdp.evaluate(IS_USER_ACTIVE_JS)
        if isinstance(result, dict):
            return result.get("active", False), result.get("reason", "")
        return False, ""
    except Exception as e:
        log(f"[AG] 用户活跃检查失败: {e}")
        return False, ""


async def wait_for_completion(
    cdp: CDPSession, timeout: int = GENERATION_TIMEOUT
) -> bool:
    """轮询等待 AI 回合完成。返回 True=完成, False=超时。

    检测两层状态：
    1. 生成状态：cancel 按钮可见 → AI 正在流式输出
    2. 回合完成：末尾出现时间戳 → 整个回合（含工具调用）已结束
    """
    # 给一点时间让生成启动
    await asyncio.sleep(3)

    if not await check_generating(cdp):
        await asyncio.sleep(2)
        if not await check_generating(cdp):
            # 没有检测到生成。检查回合是否已完成
            incomplete, detail = await check_turn_incomplete(cdp)
            if not incomplete:
                log("[AG] 生成似乎瞬间完成（或未启动）")
                return True
            log(f"[AG] 回合未完成，进入等待... (末尾: ...{detail[-40:]})")

    elapsed = 0
    last_status = ""
    while elapsed < timeout:
        await asyncio.sleep(GENERATION_POLL_INTERVAL)
        elapsed += GENERATION_POLL_INTERVAL

        # 先检查是否在流式生成
        if await check_generating(cdp):
            if last_status != "generating":
                log("[AG] AI 正在生成回复，等待中...")
                last_status = "generating"
            elif elapsed % 30 == 0:
                log(f"[AG] 仍在生成... ({elapsed}s)")
            continue

        # 生成停了，检查回合是否真正完成
        incomplete, detail = await check_turn_incomplete(cdp)
        if not incomplete:
            log(f"[AG] 回合完成 (耗时 ~{elapsed}s)")
            return True

        # 回合未完成（工具审批等待中、多步执行间隙等），继续轮询
        if last_status != "incomplete":
            log(f"[AG] 生成暂停，回合未完成，继续等待... (末尾: ...{detail[-40:]})")
            last_status = "incomplete"
        elif elapsed % 30 == 0:
            log(f"[AG] 仍在等待回合完成... ({elapsed}s)")

    log(f"[AG] 超时 ({timeout}s)")
    return False


async def extract_response(cdp: CDPSession) -> str:
    """从页面 DOM 中提取最新的 AI 回复文本。"""
    try:
        result = await cdp.evaluate(EXTRACT_RESPONSE_JS)
        if isinstance(result, dict):
            blocks = result.get("blocks", "?")
            log(f"[AG] 提取到 {blocks} 个输出块")
            return result.get("text", "(empty)")
        return str(result) if result else "(empty)"
    except Exception as e:
        log(f"[AG] 回复提取失败: {e}")
        return f"(extraction error: {e})"


async def probe_dom(cdp: CDPSession) -> dict:
    """探测 AntiGravity 的 DOM 结构（调试用）。"""
    return await cdp.evaluate(PROBE_DOM_JS)


# ============================================================
# 阻塞检测
# ============================================================


def wait_until_ready(poll_interval: int = 10, max_wait: int = 300) -> bool:
    """等待 AntiGravity 空闲。返回 True=可以发送, False=超时。

    检查条件：
    1. CDP 目标可达
    2. AI 没有正在生成
    3. 上一个心跳没有在进行中
    """
    waited = 0
    last_reason = ""

    while waited < max_wait:
        reason = ""

        if is_heartbeat_in_progress:
            reason = "上一个心跳未完成"
        else:
            # 快速检查：能否连上 CDP + AI 是否在生成 + 用户是否在打字
            ws_url = discover_target(CDP_PORT)
            if not ws_url:
                reason = "CDP 目标不可达"
            else:
                try:
                    reason = asyncio.run(_quick_check_busy(ws_url))
                except Exception as e:
                    reason = f"CDP 检查失败: {e}"

        if not reason:
            if waited > 0:
                log(f"[QUEUE] 阻塞已解除 (等待了 {waited}s)")
            return True

        if reason != last_reason:
            log(f"[QUEUE] 心跳排队: {reason}")
            last_reason = reason

        time.sleep(poll_interval)
        waited += poll_interval

    log(f"[QUEUE] 等待超时 ({max_wait}s, {last_reason})，放弃本次心跳")
    return False


async def _quick_check_busy(ws_url: str) -> str:
    """快速连接 CDP 检查是否忙碌。返回阻塞原因字符串，空串=空闲。"""
    async with ws_client.connect(ws_url, close_timeout=3) as ws:
        cdp = CDPSession(ws)
        await cdp.start()
        try:
            if await check_generating(cdp):
                return "AI 正在生成回复"
            incomplete, detail = await check_turn_incomplete(cdp)
            if incomplete:
                return "AI 回合未完成（可能在等待工具审批）"
            active, reason = await check_user_active(cdp)
            if active and reason == "editor_has_content":
                return "用户正在编辑器中输入"
            # editor_focused 不阻塞——AntiGravity 默认聚焦编辑器
            return ""
        finally:
            await cdp.close()


# ============================================================
# 核心：单次心跳
# ============================================================


async def _do_heartbeat_async(heartbeat_count: int, test_mode: bool = False):
    """异步执行一次完整的心跳周期。"""
    # 1. 发现目标
    ws_url = discover_target(CDP_PORT)
    if not ws_url:
        log(f"[ERROR] 心跳 #{heartbeat_count} 失败: 无 CDP 目标")
        return

    # 2. 连接 WebSocket
    try:
        async with ws_client.connect(ws_url, close_timeout=5) as ws:
            cdp = CDPSession(ws)
            await cdp.start()

            try:
                if test_mode:
                    # 测试模式：短消息，不截图不查邮件
                    message = "[TEST] Heartbeat injection test. Reply with: [speak]test ok[/speak]"
                    log("测试模式：发送短消息")
                else:
                    screenshot_path = capture_screenshot(ENGINE_CONFIG, log)
                    screenshot_taken = screenshot_path is not None
                    if screenshot_taken:
                        kb = os.path.getsize(screenshot_path) // 1024
                        log(f"截图完成 ({kb} KB) → {screenshot_path}")

                    message = build_heartbeat_message(
                        ENGINE_CONFIG, screenshot_taken=screenshot_taken
                    )

                    if ENGINE_CONFIG.email_enabled:
                        emails = fetch_unread_emails(log)
                        log(f"邮箱: {len(emails)} 封未读")
                        if emails:
                            message += build_email_section(emails, ENGINE_CONFIG)

                # 6. 注入消息
                log(f"发送心跳 #{heartbeat_count}...")
                start = time.time()

                if not await inject_message(cdp, message):
                    log(f"[ERROR] 心跳 #{heartbeat_count} 注入失败")
                    return

                # 7. 等待 AI 生成完成
                completed = await wait_for_completion(cdp)
                elapsed = time.time() - start

                if completed:
                    log(f"心跳 #{heartbeat_count} 完成 (耗时 {elapsed:.1f}s)")
                else:
                    log(f"心跳 #{heartbeat_count} 超时 (耗时 {elapsed:.1f}s)")

                # 8. 提取回复
                await asyncio.sleep(1)  # 等 DOM 更新
                reply = await extract_response(cdp)

                actions = process_response(reply)
                if actions.speak_text:
                    trigger_speak(actions.speak_text, ENGINE_CONFIG, log)

                # 10. 日志摘要
                summary = reply[:200] + "..." if len(reply) > 200 else reply
                log(f"回复摘要: {summary}")

            finally:
                await cdp.close()

    except Exception as e:
        log(f"[ERROR] 心跳 #{heartbeat_count} 异常: {e}")


def do_heartbeat(heartbeat_count: int, test_mode: bool = False):
    """在线程中执行心跳（同步包装）。"""
    global is_heartbeat_in_progress
    with heartbeat_lock:
        is_heartbeat_in_progress = True
    try:
        asyncio.run(_do_heartbeat_async(heartbeat_count, test_mode=test_mode))
    finally:
        with heartbeat_lock:
            is_heartbeat_in_progress = False


# ============================================================
# 探测模式
# ============================================================


async def _run_probe():
    """探测 AntiGravity DOM 结构并打印结果。"""
    ws_url = discover_target(CDP_PORT)
    if not ws_url:
        print("[PROBE] 无法发现 CDP 目标。请确认：")
        print(f"  1. AntiGravity 正在运行")
        print(f"  2. 启动参数包含 --remote-debugging-port={CDP_PORT}")
        return

    async with ws_client.connect(ws_url, close_timeout=5) as ws:
        cdp = CDPSession(ws)
        await cdp.start()
        try:
            result = await probe_dom(cdp)
            print("\n" + "=" * 60)
            print("AntiGravity DOM Probe Results")
            print("=" * 60)
            print(json.dumps(result, indent=2, ensure_ascii=False))

            # 额外测试
            print("\n--- Generation Status ---")
            gen = await check_generating(cdp)
            print(f"Is generating: {gen}")

            print("\n--- Response Extraction Test ---")
            resp = await extract_response(cdp)
            print(f"Last response ({len(resp)} chars): {resp[:300]}...")

        finally:
            await cdp.close()


# ============================================================
# Main
# ============================================================


def main():
    if not HAS_WEBSOCKETS:
        print("[FATAL] 缺少 websockets 库。运行: pip install websockets")
        sys.exit(1)

    # 探测模式
    if "--probe" in sys.argv:
        asyncio.run(_run_probe())
        return

    # 测试模式：发一条短消息验证流程
    test_mode = "--test" in sys.argv
    once_mode = "--once" in sys.argv or test_mode

    print("=" * 60)
    print("AntiGravity Heartbeat - CDP Session Keep-Alive")
    print("=" * 60)
    print(f"CDP 端口: {CDP_PORT}")
    print(f"心跳间隔: {HEARTBEAT_INTERVAL_SECONDS}s ({HEARTBEAT_INTERVAL_SECONDS // 60} min)")
    print(f"生成超时: {GENERATION_TIMEOUT}s")
    print(f"截图模式: {ENGINE_CONFIG.screenshot_mode.value}")
    print("=" * 60)
    print("特性:")
    print(f"  - 消息注入: CDP Runtime.evaluate")
    print(f"  - 完成检测: Cancel 按钮可见性轮询")
    print(f"  - 桌面宠物: {'启用' if os.path.exists(ENGINE_CONFIG.speak_script) else '未找到 speak.py'}")
    if once_mode:
        print("  - 模式: 单次运行")
    print("按 Ctrl+C 停止\n")

    heartbeat_count = 0
    skipped_count = 0

    try:
        while True:
            if wait_until_ready():
                heartbeat_count += 1
                if once_mode:
                    do_heartbeat(heartbeat_count, test_mode=test_mode)
                    break
                t = threading.Thread(
                    target=do_heartbeat, args=(heartbeat_count,), daemon=True
                )
                t.start()
            else:
                skipped_count += 1
                log(f"累计跳过 {skipped_count} 次心跳")

            log(f"等待 {HEARTBEAT_INTERVAL_SECONDS}s...\n")
            time.sleep(HEARTBEAT_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        print(f"\n已停止。发送 {heartbeat_count} 次心跳，跳过 {skipped_count} 次。")
        if is_heartbeat_in_progress:
            print("注意: 最后一个心跳可能还在后台运行。")


if __name__ == "__main__":
    main()
