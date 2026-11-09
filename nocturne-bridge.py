#!/usr/bin/env python3
"""
nocturne-bridge — direct Nocturne memory access (no MCP, no LLM, zero API cost)
Queries the Nocturne SQLite DB directly (nodes/paths/memories).
Usage:
  nocturne-bridge search QUERY [--limit 5]
  nocturne-bridge read core://agent/transport_terminal_emulator/pos_express_transit_build
  nocturne-bridge boot
"""
import os, sqlite3, argparse

DB = os.environ.get("NOCTURNE_DB", "/root/nocturne_memory/nocturne_data.db")

def conn():
    return sqlite3.connect(DB)

def uri_to_parts(uri):
    # core://domain/path
    rest = uri.split("://", 1)[1] if "://" in uri else uri
    if "/" in rest:
        domain, path = rest.split("/", 1)
    else:
        domain, path = rest, ""
    return domain, path

def search(q, limit=5):
    c = conn()
    like = f"%{q}%"
    rows = c.execute(
        """SELECT p.domain, p.path, substr(m.content, 1, 120)
           FROM paths p JOIN memories m ON m.node_uuid = p.node_uuid
           WHERE (m.content LIKE ? OR p.path LIKE ?)
             AND m.deprecated = 0
           ORDER BY m.created_at DESC LIMIT ?""",
        (like, like, limit),
    ).fetchall()
    for domain, path, snippet in rows:
        print(f"core://{domain}/{path}\n    {snippet}")
    if not rows:
        print("(no matches)")
    c.close()

def read(uri):
    domain, path = uri_to_parts(uri)
    c = conn()
    # try exact: domain + path
    row = c.execute(
        """SELECT m.content FROM paths p JOIN memories m ON m.node_uuid = p.node_uuid
           WHERE p.domain = ? AND p.path = ? AND m.deprecated = 0""",
        (domain, path),
    ).fetchone()
    # try full path in one column (some stores keep 'domain/path' inside path)
    if not row:
        row = c.execute(
            """SELECT m.content FROM paths p JOIN memories m ON m.node_uuid = p.node_uuid
               WHERE p.path = ? AND m.deprecated = 0 ORDER BY m.created_at DESC LIMIT 1""",
            (uri.split("://", 1)[1],),
        ).fetchone()
    # prefix match
    if not row:
        row = c.execute(
            """SELECT m.content FROM paths p JOIN memories m ON m.node_uuid = p.node_uuid
               WHERE p.path LIKE ? AND m.deprecated = 0 ORDER BY m.created_at DESC LIMIT 1""",
            (path + "%",),
        ).fetchone()
    if row:
        print(row[0])
    else:
        print(f"NOT FOUND: {uri}")
    c.close()

def boot():
    c = conn()
    rows = c.execute(
        """SELECT p.domain, p.path FROM paths p
           JOIN memories m ON m.node_uuid = p.node_uuid
           WHERE m.deprecated = 0
           ORDER BY m.created_at DESC LIMIT 12"""
    ).fetchall()
    for domain, path in rows:
        print(f"core://{domain}/{path}")
    c.close()

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Nocturne memory bridge")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("search"); s.add_argument("query"); s.add_argument("--limit", type=int, default=5)
    r = sub.add_parser("read"); r.add_argument("uri")
    sub.add_parser("boot")
    a = ap.parse_args()
    if a.cmd == "search":
        search(a.query, a.limit)
    elif a.cmd == "read":
        read(a.uri)
    elif a.cmd == "boot":
        boot()
    else:
        ap.print_help()
