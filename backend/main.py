# pyright: reportMissingImports=false

"""
Main Entrypoint for Nocturne Memory Web Server.

Launches the unified web application which hosts both the REST API and the 
static frontend SPA admin dashboard.
"""

import argparse
import os
import sys

# Ensure we can import from backend modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import config as _cfg
from auth import enforce_network_auth
from web_app import build_web_app

# 正式启动路径只有 python main.py，host 从 config 读。
# 但仍需嗅探 uvicorn CLI 的覆盖源，遇到公网无 token 时直接拒绝启动。
_parser = argparse.ArgumentParser(add_help=False)
_parser.add_argument("--host", type=str)
_args, _ = _parser.parse_known_args()
_host = _args.host or os.environ.get("UVICORN_HOST") or _cfg.get("host")
enforce_network_auth(host=_host)

# Build the unified ASGI web app (API + Frontend SPA)
app = build_web_app()

if __name__ == "__main__":
    import uvicorn

    host = _cfg.get("host")
    port = int(_cfg.get("web_port"))
    enforce_network_auth(host=host)
    
    print(f"Memory API starting on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)
