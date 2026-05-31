"""
Overwatcher — Phase 10.

Polls the project directory every POLL_INTERVAL seconds.
Builds a live AST-based import graph for Python files.
Also checks which known services are alive on their ports.

Graph schema stored in Redis:
  intel:graph → {
    "nodes": [
      {"id": "server/main.py", "type": "file", "lang": "python",
       "label": "main.py", "functions": [...], "imports": [...],
       "size": 283, "mtime": 1234567890.0},
      {"id": "svc_redis", "type": "service", "label": "Redis :6379",
       "port": 6379, "alive": true},
      ...
    ],
    "edges": [
      {"from": "server/main.py", "to": "server/auth.py", "type": "imports"},
      ...
    ],
    "last_updated": 1234567890.0,
    "file_count": 42,
    "service_count": 6,
  }

No external dependencies — uses stdlib ast, subprocess + Redis.
"""
import ast
import asyncio
import json
import subprocess
import time
from pathlib import Path
from typing import Optional

import redis

from server.config import REDIS_URL
from observability.logger import log

_GRAPH_KEY    = "intel:graph"
_POLL_INTERVAL = 30   # seconds between scans
_WATCH_EXTS   = {".py", ".ts", ".tsx", ".js", ".jsx", ".swift"}
_IGNORE_DIRS  = {
    "__pycache__", "node_modules", ".git", "venv", ".venv",
    "chromadb", "backups", ".next", "dist", "build",
}

_running = False
_KNOWN_SERVICES = [
    {"id": "svc_fastapi",    "label": "FastAPI :8000",    "port": 8000},
    {"id": "svc_redis",      "label": "Redis :6379",       "port": 6379},
    {"id": "svc_ollama",     "label": "Ollama :11434",     "port": 11434},
    {"id": "svc_prometheus", "label": "Prometheus :9090",  "port": 9090},
    {"id": "svc_mqtt",       "label": "MQTT :1883",        "port": 1883},
    {"id": "svc_grafana",    "label": "Grafana :3000",     "port": 3000},
]


# ── Redis ─────────────────────────────────────────────────────────────────────

def _redis() -> Optional[redis.Redis]:
    try:
        r = redis.from_url(REDIS_URL, decode_responses=True,
                           socket_connect_timeout=1)
        r.ping()
        return r
    except Exception:
        return None


# ── AST analysis ──────────────────────────────────────────────────────────────

def _analyze_python(path: Path, root: Path) -> dict:
    node_id = str(path.relative_to(root))
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except Exception:
        return {
            "id": node_id, "type": "file", "lang": "python",
            "label": path.name, "path": node_id,
            "functions": [], "imports": [], "size": 0,
        }

    functions: list[str] = []
    imports:   list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # only top-level and class-level functions
            functions.append(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)

    return {
        "id": node_id,
        "type": "file",
        "lang": "python",
        "label": path.name,
        "path": node_id,
        "functions": list(dict.fromkeys(functions))[:20],
        "imports": list(dict.fromkeys(imports))[:20],
        "size": len(source.splitlines()),
        "mtime": path.stat().st_mtime,
    }


def _analyze_generic(path: Path, root: Path) -> dict:
    node_id = str(path.relative_to(root))
    try:
        size = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
    except Exception:
        size = 0
    return {
        "id": node_id,
        "type": "file",
        "lang": path.suffix.lstrip(".") or "unknown",
        "label": path.name,
        "path": node_id,
        "functions": [],
        "imports": [],
        "size": size,
        "mtime": path.stat().st_mtime,
    }


def _build_import_edges(nodes: list[dict]) -> list[dict]:
    """Match import strings to known file node IDs."""
    # module name → node id (Python only)
    module_map: dict[str, str] = {}
    for n in nodes:
        if n.get("lang") == "python":
            mod = n["id"].replace("/", ".").removesuffix(".py")
            module_map[mod] = n["id"]

    edges: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for n in nodes:
        for imp in n.get("imports", []):
            target = module_map.get(imp)
            if target and target != n["id"]:
                key = (n["id"], target)
                if key not in seen:
                    seen.add(key)
                    edges.append({"from": n["id"], "to": target,
                                  "type": "imports"})
    return edges


def _check_services() -> list[dict]:
    result: list[dict] = []
    for svc in _KNOWN_SERVICES:
        try:
            out = subprocess.run(
                ["lsof", "-ti", f"tcp:{svc['port']}"],
                capture_output=True, timeout=2,
            )
            alive = out.returncode == 0 and bool(out.stdout.strip())
        except Exception:
            alive = False
        result.append({**svc, "type": "service", "alive": alive})
    return result


def build_graph(project_root: Path) -> dict:
    """Full synchronous scan — call from a thread."""
    nodes: list[dict] = []

    for path in project_root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in _WATCH_EXTS:
            continue
        if any(part in _IGNORE_DIRS for part in path.parts):
            continue
        if path.suffix == ".py":
            nodes.append(_analyze_python(path, project_root))
        else:
            nodes.append(_analyze_generic(path, project_root))

    edges = _build_import_edges(nodes)
    services = _check_services()

    return {
        "nodes": nodes + services,
        "edges": edges,
        "last_updated": time.time(),
        "file_count": len(nodes),
        "service_count": len(services),
    }


# ── Public accessors ──────────────────────────────────────────────────────────

def get_graph() -> dict:
    r = _redis()
    if r:
        raw = r.get(_GRAPH_KEY)
        if raw:
            return json.loads(raw)
    return {"nodes": [], "edges": [], "last_updated": 0,
            "file_count": 0, "service_count": 0}


def _save_graph(graph: dict) -> None:
    r = _redis()
    if r:
        r.set(_GRAPH_KEY, json.dumps(graph))


# ── Background polling loop ───────────────────────────────────────────────────

async def run_overwatcher(project_root: Path, broadcast_fn=None) -> None:
    """
    Poll for file changes; rebuild graph when anything changes.
    broadcast_fn: async callable(dict) pushed to WebSocket clients.
    """
    global _running
    _running = True
    log.info("overwatcher_started", root=str(project_root))

    prev_mtimes: dict[str, float] = {}

    while _running:
        try:
            changed = False
            for path in project_root.rglob("*"):
                if not path.is_file():
                    continue
                if path.suffix not in _WATCH_EXTS:
                    continue
                if any(part in _IGNORE_DIRS for part in path.parts):
                    continue
                rel = str(path.relative_to(project_root))
                mtime = path.stat().st_mtime
                if prev_mtimes.get(rel) != mtime:
                    prev_mtimes[rel] = mtime
                    changed = True

            if changed or not get_graph().get("nodes"):
                graph = await asyncio.to_thread(build_graph, project_root)
                _save_graph(graph)
                log.info("overwatcher_updated",
                         nodes=len(graph["nodes"]),
                         edges=len(graph["edges"]))
                if broadcast_fn:
                    await broadcast_fn({"type": "graph_update", **graph})

        except Exception as e:
            log.warn("overwatcher_error", error=str(e))

        await asyncio.sleep(_POLL_INTERVAL)


def stop_overwatcher() -> None:
    global _running
    _running = False
