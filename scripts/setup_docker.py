"""
Docker deployment setup for Nocturne Memory.

Generates secure credentials and writes:
  - .env          (POSTGRES_PASSWORD for docker-compose)
  - config.json   (app settings with Docker-appropriate defaults)

Usage:
  python scripts/setup_docker.py
  python scripts/setup_docker.py --port 8080   # custom Nginx port
"""

import json
import secrets
import sys
import re
from pathlib import Path
from urllib.parse import quote, unquote

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
CONFIG_PATH = ROOT / "config.json"


def generate_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def _read_existing_env() -> dict[str, str]:
    """Parse an existing .env into a dict (simple KEY=VALUE, no shell expansion)."""
    kvs: dict[str, str] = {}
    if not ENV_PATH.exists():
        return kvs
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        kvs[k.strip()] = v.strip()
    return kvs


def _extract_pg_credentials_from_url(url: str) -> tuple[str | None, str | None, str | None]:
    """Extract (user, password, db) from postgresql+asyncpg://user:password@host.../db..."""
    if not url:
        return None, None, None
    match = re.search(r"://([^:]+):([^@]+)@[^/]+/([^?]+)", url)
    if match:
        return unquote(match.group(1)), unquote(match.group(2)), unquote(match.group(3))
    return None, None, None


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Setup Nocturne Memory for Docker deployment")
    parser.add_argument("--port", type=int, default=None, help="Nginx port (default: 80)")
    parser.add_argument("--force", action="store_true", help="Overwrite existing files")
    args = parser.parse_args()

    # --- Read existing sources ---
    existing_config = {}
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                existing_config = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    existing_env = _read_existing_env()

    # --- Resolve API token: config.json (SSOT) > .env (one-time migration) > generate ---
    if args.force:
        api_token = generate_token(32)
    else:
        api_token = (
            existing_config.get("api_token")
            or existing_env.get("API_TOKEN")  # migrate from old .env once
            or generate_token(32)
        )

    # --- Resolve Postgres credentials ---
    # We ALWAYS preserve existing credentials if they exist, even with --force.
    # Postgres only uses these variables on first initialization. Changing them later breaks the connection.
    pg_user = existing_env.get("POSTGRES_USER")
    pg_password = existing_env.get("POSTGRES_PASSWORD")
    pg_db = existing_env.get("POSTGRES_DB")
    
    # Fallback: If .env is missing/empty but config.json has the database URL, extract it from there.
    if (not pg_user or not pg_password or not pg_db) and "database_url" in existing_config:
        u, p, d = _extract_pg_credentials_from_url(existing_config["database_url"])
        pg_user = pg_user or u
        pg_password = pg_password or p
        pg_db = pg_db or d
        
    pg_user = pg_user or "nocturne"
    pg_password = pg_password or generate_token(24)
    pg_db = pg_db or "nocturne_memory"

    # --- Resolve Nginx port ---
    if args.port is not None:
        nginx_port = args.port
    else:
        nginx_port = int(existing_env.get("NGINX_PORT", 80))

    # --- .env (strictly for Docker-level provisioning, e.g. Postgres init) ---
    # Always preserve Postgres credentials (Postgres only reads them on first init),
    # but update NGINX_PORT to match --port so the printed URL is accurate.
    env_existed = ENV_PATH.exists()
    env_lines = [
        f"POSTGRES_USER={pg_user}",
        f"POSTGRES_PASSWORD={pg_password}",
        f"POSTGRES_DB={pg_db}",
    ]
    if nginx_port != 80:
        env_lines.append(f"NGINX_PORT={nginx_port}")
    ENV_PATH.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
    print(f"[OK] {'Updated' if env_existed else 'Generated'} {ENV_PATH.relative_to(ROOT)}")

    # --- config.json (App SSOT) ---
    docker_required = {
        "database_url": f"postgresql+asyncpg://{quote(pg_user, safe='')}:{quote(pg_password, safe='')}@postgres:5432/{quote(pg_db, safe='')}?ssl=disable",
        "host": "0.0.0.0",
        "web_port": 8233,
        "auto_open_browser": False,
        "api_token": api_token,
    }
    docker_defaults = {
        "valid_domains": ["core", "writer", "game", "notes", "narrative"],
        "boot_uris": {"": ["core://agent", "core://my_user", "core://agent/my_user"]},
        "cors_origins": None,
        "public_readonly_mcp": False,
    }

    if CONFIG_PATH.exists() and not args.force:
        config = dict(existing_config)
        patched = [k for k, v in docker_required.items() if config.get(k) != v]
        config.update(docker_required)
        for k, v in docker_defaults.items():
            config.setdefault(k, v)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
            f.write("\n")
        if patched:
            print(f"[OK] Updated {CONFIG_PATH.relative_to(ROOT)} (patched: {', '.join(patched)})")
        else:
            print(f"[OK] {CONFIG_PATH.relative_to(ROOT)} already up to date")
    else:
        config = dict(docker_defaults)
        config.update(docker_required)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"[OK] Generated {CONFIG_PATH.relative_to(ROOT)}")

    # --- Summary ---
    print()
    print("=" * 60)
    print("  Nocturne Memory — Docker Setup Complete")
    print("=" * 60)
    print()
    print("  Next steps:")
    print("    docker compose up -d --build")
    print()
    print("  Note for Linux users:")
    print("    To allow the Dashboard to save settings, give the container user (UID 1000) write access:")
    print("    sudo chown 1000 config.json")
    print()
    print(f"  Dashboard:  http://localhost{'' if nginx_port == 80 else ':' + str(nginx_port)}")
    print(f"  SSE:        http://localhost{'' if nginx_port == 80 else ':' + str(nginx_port)}/sse")
    print(f"  HTTP MCP:   http://localhost{'' if nginx_port == 80 else ':' + str(nginx_port)}/mcp")
    print()
    print(f"  API Token (copy this for your MCP client config):")
    print(f"    {api_token}")
    print()
    print("  MCP client config example:")
    port_suffix = "" if nginx_port == 80 else f":{nginx_port}"
    print(f'    "url": "http://<your-ip>{port_suffix}/mcp"')
    print(f'    "headers": {{"Authorization": "Bearer {api_token}"}}')
    print()


if __name__ == "__main__":
    main()
