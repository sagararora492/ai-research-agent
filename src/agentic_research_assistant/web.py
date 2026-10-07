"""Local-only web UI. API keys stay in the server process."""
from __future__ import annotations

import argparse
import json
import os
import threading
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .config import build_orchestrator
from .providers import ProviderError
from .llm import ModelProfile

STATIC = Path(__file__).with_name("static")


def run_research(payload: dict, storage_root: Path | None = None, model_profiles: dict | None = None) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Request must be a JSON object.")
    provider = payload.get("provider", "local")
    synthesis = payload.get("synthesis", "extractive")
    model = payload.get("model", "")
    if not all(isinstance(value, str) for value in (provider, synthesis, model)):
        raise ValueError("Provider, synthesis, and model must be strings.")
    max_sources = payload.get("max_sources", 3)
    if type(max_sources) is not int:
        raise ValueError("Source limit must be an integer.")
    persist = payload.get("persist", True)
    if type(persist) is not bool:
        raise ValueError("Persist must be a boolean.")
    agent_config = payload.get("agent_config")
    if agent_config is not None:
        if not isinstance(agent_config, dict) or "models" in agent_config:
            raise ValueError("Send agent assignments only; model profiles and credentials are configured locally.")
        agent_config = {**agent_config, "models": model_profiles or {}}
    orchestrator = build_orchestrator(provider, payload.get("documents"), synthesis, model, max_sources,
                                      max_searches=payload.get("max_searches"), agent_config=agent_config)
    report = orchestrator.run(payload.get("topic", ""),
                              payload.get("audience", "product and engineering stakeholders"),
                              payload.get("outcome", "a decision-ready research brief"),
                              persist=persist, storage_root=storage_root)
    return asdict(report)


class ResearchServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], storage_root: Path | None = None, model_profiles: dict | None = None):
        super().__init__(address, ResearchHandler)
        self.storage_root = storage_root
        self.model_profiles = model_profiles or {}
        self.research_lock = threading.Lock()


class ResearchHandler(BaseHTTPRequestHandler):
    server: ResearchServer

    def log_message(self, fmt, *args):
        # Avoid logging topics, source text, or keys.
        pass

    def _same_origin(self) -> bool:
        port = self.server.server_address[1]
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        return host in allowed and (origin is None or origin == f"http://{host}")

    def _send(self, status: int, body: bytes, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, status: int, data: dict) -> None:
        self._send(status, json.dumps(data, default=str).encode())

    def do_GET(self):
        if not self._same_origin():
            self._json(403, {"error": "Only same-origin localhost requests are allowed."})
            return
        route = urlsplit(self.path).path
        if route == "/api/config":
            self._json(200, {"tavily": bool(os.environ.get("TAVILY_API_KEY")),
                             "models": {name: {"provider": profile["provider"], "model": profile["model"]}
                                        for name, profile in getattr(self.server, "model_profiles", {}).items()},
                             "openai": bool(os.environ.get("OPENAI_API_KEY")),
                             "anthropic": bool(os.environ.get("ANTHROPIC_API_KEY")),
                             "gemini": bool(os.environ.get("GEMINI_API_KEY")),
                             "model": os.environ.get("OPENAI_MODEL", "")})
            return
        assets = {"/": ("index.html", "text/html; charset=utf-8"),
                  "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                  "/style.css": ("style.css", "text/css; charset=utf-8"),
                  "/demo.json": ("demo.json", "application/json"),
                  "/agents-mixed.json": ("agents-mixed.json", "application/json")}
        if route not in assets:
            self._json(404, {"error": "Not found."})
            return
        name, content_type = assets[route]
        self._send(200, (STATIC / name).read_bytes(), content_type)

    def do_POST(self):
        if not self._same_origin():
            self._json(403, {"error": "Only same-origin localhost requests are allowed."})
            return
        if self.path != "/api/research":
            self._json(404, {"error": "Not found."})
            return
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            self._json(415, {"error": "Use application/json."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 2_000_000:
                self._json(413, {"error": "Request must be between 1 byte and 2 MB."})
                return
        except ValueError:
            self._json(400, {"error": "Invalid request length."})
            return
        if not self.server.research_lock.acquire(blocking=False):
            self._json(409, {"error": "A research session is already running. Try again when it finishes."})
            return
        try:
            self.connection.settimeout(15)
            payload = json.loads(self.rfile.read(length))
            result = run_research(payload, self.server.storage_root, getattr(self.server, "model_profiles", {}))
            self._json(200, result)
        except (ValueError, UnicodeError, ProviderError) as exc:
            self._json(400, {"error": str(exc)})
        except OSError:
            self._json(500, {"error": "Could not read or save this session. Check local storage permissions."})
        except Exception:
            self._json(500, {"error": "Research failed unexpectedly. Retry or use the CLI for diagnosis."})
        finally:
            self.server.research_lock.release()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Start the local research assistant web app.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--storage-root", type=Path)
    parser.add_argument("--models-config", type=Path, help="Local JSON file containing named model profiles.")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535.")
    try:
        profiles = json.loads(args.models_config.read_text(encoding="utf-8")) if args.models_config else {}
        if not isinstance(profiles, dict):
            raise ValueError("Model configuration must be an object of named profiles.")
        for profile in profiles.values():
            ModelProfile.parse(profile)
        with ResearchServer(("127.0.0.1", args.port), args.storage_root, profiles) as server:
            print(f"Research assistant: http://127.0.0.1:{args.port}", flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError) as exc:
        print(f"Could not start web app: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
