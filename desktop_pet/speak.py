#!/usr/bin/env python3
"""
Nocturne Desktop Pet - Speech Bubble + TTS
Standalone script: shows a transparent overlay bubble, plays TTS, exits.

Usage:
    python speak.py "要说的话"
    python speak.py "Hello world" --voice en-US-GuyNeural
"""

import sys
import os
import asyncio
import tempfile
import tkinter as tk
import re
import argparse
import ctypes
import threading

try:
    import edge_tts

    HAS_EDGE_TTS = True
except ImportError:
    HAS_EDGE_TTS = False

try:
    import pyttsx3

    HAS_PYTTSX3 = True
except ImportError:
    HAS_PYTTSX3 = False


# ============================================================
# Config
# ============================================================

VOICES = {
    "zh": "zh-CN-YunxiNeural",
    "ja": "ja-JP-KeitaNeural",
    "en": "en-US-GuyNeural",
}

BUBBLE_BG = "#1e1e2e"
BUBBLE_FG = "#cdd6f4"
BUBBLE_FONT_FAMILY = "Yu Gothic UI Semibold"
BUBBLE_FONT_SIZE = 13
BUBBLE_MAX_WIDTH = 420
BUBBLE_PADDING = 18
BUBBLE_CORNER_RADIUS = 16
BUBBLE_MARGIN_RIGHT = 24
BUBBLE_MARGIN_BOTTOM = 72
TRANSPARENT_KEY = "#fe01fe"

FADE_OUT_DELAY_MS = 1200
READING_SPEED_MS_PER_CHAR = 180
MIN_DISPLAY_MS = 3000


# ============================================================
# Language detection
# ============================================================


def detect_language(text: str) -> str:
    if re.search(r"[\u4E00-\u9FFF]", text):
        return "zh"
    if re.search(r"[a-zA-Z]", text):
        return "en"
    if re.search(r"[\u3040-\u309F\u30A0-\u30FF]", text):
        return "ja"
    return "zh"


# ============================================================
# TTS
# ============================================================


async def _edge_tts(text: str, voice: str, path: str):
    comm = edge_tts.Communicate(text, voice)
    await comm.save(path)


def generate_audio(text: str, voice: str) -> str | None:
    """Generate TTS audio file. Returns path on success, None on failure."""
    fd, audio_path = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)

    if HAS_EDGE_TTS:
        try:
            asyncio.run(_edge_tts(text, voice, audio_path))
            if os.path.getsize(audio_path) > 0:
                return audio_path
        except Exception as e:
            print(f"[edge-tts] {e}", file=sys.stderr)

    if HAS_PYTTSX3:
        try:
            wav_path = audio_path.replace(".mp3", ".wav")
            engine = pyttsx3.init()
            engine.save_to_file(text, wav_path)
            engine.runAndWait()
            if os.path.exists(wav_path) and os.path.getsize(wav_path) > 0:
                try:
                    os.unlink(audio_path)
                except OSError:
                    pass
                return wav_path
        except Exception as e:
            print(f"[pyttsx3] {e}", file=sys.stderr)

    try:
        os.unlink(audio_path)
    except OSError:
        pass
    return None


# ============================================================
# Audio playback via Windows MCI (zero dependencies)
# ============================================================


def _mci_send(command: str) -> int:
    """Send an MCI command string. Returns 0 on success."""
    return ctypes.windll.winmm.mciSendStringW(command, None, 0, 0)


def play_audio_blocking(path: str):
    """Play an audio file using Windows MCI. Blocks until playback finishes."""
    abs_path = os.path.abspath(path).replace("\\", "/")
    _mci_send("close nocturne_voice")
    _mci_send(f'open "{abs_path}" type mpegvideo alias nocturne_voice')
    _mci_send("play nocturne_voice wait")
    _mci_send("close nocturne_voice")


# ============================================================
# GUI
# ============================================================


def _round_rect(canvas, x1, y1, x2, y2, r=25, **kw):
    pts = [
        x1 + r, y1,
        x2 - r, y1,
        x2, y1,
        x2, y1 + r,
        x2, y2 - r,
        x2, y2,
        x2 - r, y2,
        x1 + r, y2,
        x1, y2,
        x1, y2 - r,
        x1, y1 + r,
        x1, y1,
    ]
    return canvas.create_polygon(pts, smooth=True, **kw)


class Bubble:
    def __init__(self, text: str):
        self.root = tk.Tk()
        self.root.withdraw()

        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=TRANSPARENT_KEY)
        self.root.attributes("-transparentcolor", TRANSPARENT_KEY)

        self._draw(text)
        self._position()
        self.root.deiconify()

    def _draw(self, text: str):
        wrap = BUBBLE_MAX_WIDTH - 2 * BUBBLE_PADDING
        probe = tk.Label(
            self.root, text=text,
            font=(BUBBLE_FONT_FAMILY, BUBBLE_FONT_SIZE),
            wraplength=wrap,
        )
        probe.update_idletasks()
        tw, th = probe.winfo_reqwidth(), probe.winfo_reqheight()
        probe.destroy()

        cw = tw + 2 * BUBBLE_PADDING + 4
        ch = th + 2 * BUBBLE_PADDING + 4

        c = tk.Canvas(
            self.root, width=cw, height=ch,
            bg=TRANSPARENT_KEY, highlightthickness=0,
        )
        c.pack()

        _round_rect(
            c, 2, 2, cw - 2, ch - 2,
            r=BUBBLE_CORNER_RADIUS, fill=BUBBLE_BG, outline="#313244",
        )
        c.create_text(
            BUBBLE_PADDING + 2, BUBBLE_PADDING + 2,
            text=text,
            font=(BUBBLE_FONT_FAMILY, BUBBLE_FONT_SIZE),
            fill=BUBBLE_FG, width=wrap, anchor="nw",
        )

    def _position(self):
        self.root.update_idletasks()
        w = self.root.winfo_reqwidth()
        h = self.root.winfo_reqheight()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        
        x = sw - w - BUBBLE_MARGIN_RIGHT
        y = (sh - h) // 2  # 垂直居中
        self.root.geometry(f"+{x}+{y}")

    def after(self, ms, fn):
        self.root.after(ms, fn)

    def close(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def mainloop(self):
        self.root.mainloop()


# ============================================================
# Main
# ============================================================


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("text")
    parser.add_argument("--voice", default=None)
    args = parser.parse_args()

    text = args.text.strip()
    if not text:
        return

    lang = detect_language(text)
    voice = args.voice or VOICES.get(lang, VOICES["zh"])

    audio_path = generate_audio(text, voice)
    bubble = Bubble(text)

    if audio_path:
        def play_then_close():
            try:
                play_audio_blocking(audio_path)
            except Exception as e:
                print(f"[playback] {e}", file=sys.stderr)
            bubble.root.after(FADE_OUT_DELAY_MS, bubble.close)

        audio_thread = threading.Thread(target=play_then_close, daemon=True)
        audio_thread.start()
    else:
        reading_ms = max(MIN_DISPLAY_MS, len(text) * READING_SPEED_MS_PER_CHAR)
        bubble.after(reading_ms, bubble.close)

    bubble.mainloop()

    if audio_path:
        try:
            os.unlink(audio_path)
        except OSError:
            pass


if __name__ == "__main__":
    main()
