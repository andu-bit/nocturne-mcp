# Analytics API — session analytics for the Nocturne dashboard.
#
# Supports multiple sources (auto-detected / env-configurable):
#   - opencode : reads OpenCode's SQLite DB (~/.local/share/opencode/opencode.db)
#   - omp      : reads OMP (Oh My Pi) JSONL transcripts (~/.omp/agent/sessions)
#
# Env:
#   ANALYTICS_SOURCE   = opencode | omp | auto (default: auto)
#   OPENCODE_DB        = path to opencode.db
#   OMP_SESSION_DIR    = path to OMP session dir (legacy)
#
# Endpoints (compatible shape): /overview, /daily, /models, /skills
# Pure stdlib + sqlite3 — FastAPI runs sync endpoints in a threadpool.

from __future__ import annotations

import glob
import json
import os
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from fastapi import APIRouter, Query

router = APIRouter(prefix="/analytics", tags=["analytics"])

OMP_SESSION_DIR = os.environ.get("OMP_SESSION_DIR", "/home/alexx/.omp/agent/sessions")
OPENCODE_DB = os.path.expanduser(
    os.environ.get("OPENCODE_DB", "~/.local/share/opencode/opencode.db")
)
ANALYTICS_SOURCE = os.environ.get("ANALYTICS_SOURCE", "auto").strip().lower()

# Skill/memory tools tracked by the skills endpoint.
SKILL_LOAD_TOOLS = {"recall", "reflect", "learn", "skill", "gsd_read_state", "opencode_read_mcp_resource"}
SKILL_EDIT_TOOLS = {"retain", "memory_edit", "manage_skill", "create_memory", "manage_triggers", "gsd_write_state"}


def _source() -> str:
    if ANALYTICS_SOURCE in ("opencode", "omp"):
        return ANALYTICS_SOURCE
    # auto: prefer opencode if DB exists
    if os.path.exists(OPENCODE_DB):
        return "opencode"
    if os.path.isdir(OMP_SESSION_DIR):
        return "omp"
    return "opencode"


# ── OMP (legacy JSONL) ──────────────────────────────────────────────────────

def _omp_session_files() -> List[str]:
    return sorted(glob.glob(os.path.join(OMP_SESSION_DIR, "**", "*.jsonl"), recursive=True))


def _iso_ts(ts: Any) -> Optional[float]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _omp_records() -> Iterable[Tuple[str, str, Dict[str, Any]]]:
    for path in _omp_session_files():
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    kind = rec.get("type")
                    if kind:
                        yield path, kind, rec
        except OSError:
            continue


# ── OpenCode (SQLite) ───────────────────────────────────────────────────────

def _oc_conn() -> sqlite3.Connection:
    # read-only, tolerate WAL from live opencode
    uri = f"file:{OPENCODE_DB}?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=5)


def _oc_model_str(model_val: Any) -> str:
    if not model_val:
        return ""
    if isinstance(model_val, dict):
        pid = model_val.get("providerID") or model_val.get("provider") or ""
        mid = model_val.get("id") or model_val.get("modelID") or ""
        if pid and mid:
            return f"{pid}/{mid}"
        return mid or pid or json.dumps(model_val, ensure_ascii=False)
    if isinstance(model_val, str):
        s = model_val.strip()
        if s.startswith("{"):
            try:
                return _oc_model_str(json.loads(s))
            except Exception:
                return s
        return s
    return str(model_val)


def _oc_provider(model_str: str) -> str:
    if not model_str:
        return "unknown"
    if "/" in model_str:
        return model_str.split("/", 1)[0] or "unknown"
    return model_str


def _ms_to_day(ts_ms: Any) -> Optional[str]:
    if ts_ms is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts_ms) / 1000.0).strftime("%Y-%m-%d")
    except Exception:
        return None


def _ms_to_ts(ts_ms: Any) -> Optional[float]:
    if ts_ms is None:
        return None
    try:
        return int(ts_ms) / 1000.0
    except Exception:
        return None


# ── Overview ────────────────────────────────────────────────────────────────

def _overview_opencode() -> Dict[str, Any]:
    with _oc_conn() as c:
        c.row_factory = sqlite3.Row
        total_sessions = c.execute(
            "SELECT COUNT(*) FROM session_v2 WHERE time_archived IS NULL"
        ).fetchone()[0]
        total_messages = c.execute("SELECT COUNT(*) FROM session_message").fetchone()[0]
        tok = c.execute(
            """SELECT
                COALESCE(SUM(tokens_input),0),
                COALESCE(SUM(tokens_output),0),
                COALESCE(SUM(tokens_cache_read),0),
                COALESCE(SUM(tokens_cache_write),0)
               FROM session_v2 WHERE time_archived IS NULL"""
        ).fetchone()
        by_source: Dict[str, int] = {}
        for r in c.execute(
            "SELECT model, COUNT(*) n FROM session_v2 WHERE time_archived IS NULL GROUP BY model"
        ).fetchall():
            prov = _oc_provider(_oc_model_str(r["model"]))
            by_source[prov] = by_source.get(prov, 0) + int(r["n"])
    return {
        "source": "opencode",
        "total_sessions": int(total_sessions),
        "total_messages": int(total_messages),
        "input_tokens": int(tok[0]),
        "output_tokens": int(tok[1]),
        "cache_read_tokens": int(tok[2]),
        "cache_write_tokens": int(tok[3]),
        "total_tokens": int(tok[0]) + int(tok[1]),
        "by_source": by_source,
        "db": OPENCODE_DB,
    }


def _overview_omp() -> Dict[str, Any]:
    total_sessions = 0
    total_messages = 0
    input_tokens = 0
    output_tokens = 0
    cache_read_tokens = 0
    cache_write_tokens = 0
    provider_by_file: Dict[str, str] = {}
    session_files: set = set()
    for path, kind, rec in _omp_records():
        if kind == "session":
            total_sessions += 1
            session_files.add(path)
        elif kind == "model_change":
            model = rec.get("model") or ""
            provider = model.split("/", 1)[0] if "/" in model else (model or "local")
            provider_by_file[path] = provider
        elif kind == "message":
            total_messages += 1
            u = (rec.get("message") or {}).get("usage") or {}
            input_tokens += u.get("input", 0) or 0
            output_tokens += u.get("output", 0) or 0
            cache_read_tokens += u.get("cacheRead", 0) or 0
            cache_write_tokens += u.get("cacheWrite", 0) or 0
    by_provider: Dict[str, int] = {}
    for path in session_files:
        provider = provider_by_file.get(path, "local")
        by_provider[provider] = by_provider.get(provider, 0) + 1
    return {
        "source": "omp",
        "total_sessions": total_sessions,
        "total_messages": total_messages,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
        "total_tokens": input_tokens + output_tokens,
        "by_source": by_provider,
        "db": OMP_SESSION_DIR,
    }


@router.get("/overview")
def analytics_overview() -> Dict[str, Any]:
    """Totals: sessions, messages, tokens, per-provider breakdown."""
    try:
        return _overview_opencode() if _source() == "opencode" else _overview_omp()
    except Exception as e:
        return {"source": _source(), "error": str(e), "total_sessions": 0, "total_messages": 0,
                "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0,
                "total_tokens": 0, "by_source": {}, "db": OPENCODE_DB if _source() == "opencode" else OMP_SESSION_DIR}


# ── Daily ───────────────────────────────────────────────────────────────────

@router.get("/daily")
def analytics_daily(days: int = Query(7, ge=1, le=365)) -> Dict[str, Any]:
    """Per-day sessions/messages for the last `days` days (zero-filled)."""
    today = date.today()
    start = today - timedelta(days=days - 1)
    start_ms = int(datetime(start.year, start.month, start.day).timestamp() * 1000)
    s_by_day: Dict[str, int] = {}
    m_by_day: Dict[str, int] = {}
    tok_by_day: Dict[str, List[int]] = {}

    if _source() == "opencode":
        try:
            with _oc_conn() as c:
                c.row_factory = sqlite3.Row
                # sessions created per day (tokens attributed to session creation day as best-effort)
                for r in c.execute(
                    """SELECT date(time_created/1000,'unixepoch','localtime') d,
                              COUNT(*) n,
                              COALESCE(SUM(tokens_input),0) ti,
                              COALESCE(SUM(tokens_output),0) to2,
                              COALESCE(SUM(tokens_cache_read),0) tcr,
                              COALESCE(SUM(tokens_cache_write),0) tcw
                       FROM session_v2
                       WHERE time_archived IS NULL AND time_created >= ?
                       GROUP BY d""",
                    (start_ms,),
                ).fetchall():
                    d = r["d"]
                    if d:
                        s_by_day[d] = int(r["n"])
                        tok_by_day[d] = [int(r["ti"]), int(r["to2"]), int(r["tcr"]), int(r["tcw"])]
                for r in c.execute(
                    """SELECT date(time_created/1000,'unixepoch','localtime') d, COUNT(*) n
                       FROM session_message WHERE time_created >= ? GROUP BY d""",
                    (start_ms,),
                ).fetchall():
                    if r["d"]:
                        m_by_day[r["d"]] = int(r["n"])
        except Exception:
            pass
    else:
        start_ts = start_ms / 1000.0
        for _, kind, rec in _omp_records():
            ts = _iso_ts(rec.get("timestamp"))
            if ts is None or ts < start_ts:
                continue
            day = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            if kind == "session":
                s_by_day[day] = s_by_day.get(day, 0) + 1
            elif kind == "message":
                m_by_day[day] = m_by_day.get(day, 0) + 1
                u = (rec.get("message") or {}).get("usage") or {}
                t = tok_by_day.setdefault(day, [0, 0, 0, 0])
                t[0] += u.get("input", 0) or 0
                t[1] += u.get("output", 0) or 0
                t[2] += u.get("cacheRead", 0) or 0
                t[3] += u.get("cacheWrite", 0) or 0

    out: List[Dict[str, Any]] = []
    for i in range(days):
        d = (start + timedelta(days=i)).isoformat()
        t = tok_by_day.get(d, [0, 0, 0, 0])
        out.append({
            "day": d, "sessions": s_by_day.get(d, 0), "messages": m_by_day.get(d, 0),
            "input_tokens": t[0], "output_tokens": t[1],
            "cache_read_tokens": t[2], "cache_write_tokens": t[3],
            "tokens": t[0] + t[1],
        })
    return {"source": _source(), "days": out}


# ── Models ──────────────────────────────────────────────────────────────────

@router.get("/models")
def analytics_models() -> Dict[str, Any]:
    """Per-model breakdown: sessions, tokens."""
    if _source() == "opencode":
        try:
            with _oc_conn() as c:
                c.row_factory = sqlite3.Row
                rows = c.execute(
                    """SELECT model,
                              COUNT(*) sessions,
                              COALESCE(SUM(tokens_input),0) ti,
                              COALESCE(SUM(tokens_output),0) to2,
                              COALESCE(SUM(tokens_cache_read),0) tcr,
                              COALESCE(SUM(tokens_cache_write),0) tcw,
                              MAX(time_updated) last_used_at
                       FROM session_v2 WHERE time_archived IS NULL
                       GROUP BY model"""
                ).fetchall()
                msg_counts: Dict[str, int] = {}
                # best-effort: count messages per session model via join
                for r in c.execute(
                    """SELECT s.model, COUNT(m.id) n
                       FROM session_v2 s LEFT JOIN session_message m ON m.session_id=s.id
                       WHERE s.time_archived IS NULL GROUP BY s.model"""
                ).fetchall():
                    msg_counts[_oc_model_str(r["model"])] = int(r["n"])
                models = []
                for r in rows:
                    mstr = _oc_model_str(r["model"]) or "(unknown)"
                    ti, to2 = int(r["ti"]), int(r["to2"])
                    tcr, tcw = int(r["tcr"]), int(r["tcw"])
                    models.append({
                        "model": mstr, "sessions": int(r["sessions"]),
                        "messages": msg_counts.get(mstr, 0),
                        "input_tokens": ti, "output_tokens": to2,
                        "tokens": ti + to2, "cache_tokens": tcr + tcw,
                        "last_used_at": _ms_to_ts(r["last_used_at"]),
                    })
                models.sort(key=lambda s: s["tokens"], reverse=True)
                return {"source": "opencode", "models": models}
        except Exception as e:
            return {"source": "opencode", "models": [], "error": str(e)}

    # omp
    agg: Dict[str, Dict[str, Any]] = {}
    for path, kind, rec in _omp_records():
        if kind != "message":
            continue
        m = rec.get("message") or {}
        model = m.get("model") or "(unknown)"
        u = m.get("usage") or {}
        ts = _iso_ts(rec.get("timestamp")) or 0
        a = agg.setdefault(model, {"sessions": set(), "messages": 0, "input_tokens": 0,
                                   "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0, "last_used_at": 0})
        a["sessions"].add(path); a["messages"] += 1
        a["input_tokens"] += u.get("input", 0) or 0
        a["output_tokens"] += u.get("output", 0) or 0
        a["cache_read_tokens"] += u.get("cacheRead", 0) or 0
        a["cache_write_tokens"] += u.get("cacheWrite", 0) or 0
        if ts > a["last_used_at"]: a["last_used_at"] = ts
    models = [{"model": k, "sessions": len(v["sessions"]), "messages": v["messages"],
               "input_tokens": v["input_tokens"], "output_tokens": v["output_tokens"],
               "tokens": v["input_tokens"] + v["output_tokens"],
               "cache_tokens": v["cache_read_tokens"] + v["cache_write_tokens"],
               "last_used_at": v["last_used_at"] or None} for k, v in agg.items()]
    models.sort(key=lambda s: s["tokens"], reverse=True)
    return {"source": "omp", "models": models}


# ── Skills / Tools ──────────────────────────────────────────────────────────

def _extract_tool_names_opencode() -> Iterable[Tuple[str, Optional[float]]]:
    """Yield (tool_name, ts_seconds) from opencode session_message data (best-effort)."""
    try:
        with _oc_conn() as c:
            c.row_factory = sqlite3.Row
            # scan assistant messages; data is JSON
            for r in c.execute(
                "SELECT data, time_created FROM session_message WHERE type='assistant' ORDER BY time_created DESC LIMIT 5000"
            ).fetchall():
                ts = _ms_to_ts(r["time_created"])
                try:
                    d = json.loads(r["data"] or "{}")
                except Exception:
                    continue
                for item in d.get("content") or []:
                    if not isinstance(item, dict):
                        continue
                    t = item.get("type")
                    if t in ("tool", "toolCall", "tool-call", "tool_use"):
                        name = item.get("name") or item.get("tool") or (item.get("toolCall") or {}).get("name")
                        if name:
                            yield str(name), ts
    except Exception:
        return


@router.get("/skills")
def analytics_skills(limit: int = Query(15, ge=1, le=100)) -> Dict[str, Any]:
    """Top tool/skill usage: loads, edits, last used."""
    agg: Dict[str, Dict[str, Any]] = {}

    if _source() == "opencode":
        for name, ts in _extract_tool_names_opencode():
            a = agg.setdefault(name, {"loads": 0, "edits": 0, "total": 0, "last_used_at": 0})
            if name in SKILL_EDIT_TOOLS: a["edits"] += 1
            else: a["loads"] += 1
            a["total"] += 1
            if ts and ts > a["last_used_at"]: a["last_used_at"] = ts
    else:
        for _, kind, rec in _omp_records():
            if kind != "message": continue
            m = rec.get("message") or {}
            ts = _iso_ts(rec.get("timestamp")) or 0
            for cc in m.get("content") or []:
                if not isinstance(cc, dict) or cc.get("type") != "toolCall": continue
                name = cc.get("name") or ""
                if not name: continue
                a = agg.setdefault(name, {"loads": 0, "edits": 0, "total": 0, "last_used_at": 0})
                if name in SKILL_EDIT_TOOLS: a["edits"] += 1
                else: a["loads"] += 1
                a["total"] += 1
                if ts > a["last_used_at"]: a["last_used_at"] = ts

    skills = [{"skill": k, "loads": v["loads"], "edits": v["edits"], "total": v["total"],
               "last_used_at": v["last_used_at"] or None} for k, v in agg.items()]
    skills.sort(key=lambda s: (s["total"], s["last_used_at"] or 0), reverse=True)
    return {"source": _source(), "skills": skills[:limit]}
