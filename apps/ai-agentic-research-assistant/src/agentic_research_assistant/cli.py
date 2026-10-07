from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .config import build_orchestrator
from .providers import ProviderError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="research-assistant", description="Research a topic with traceable source evidence.")
    parser.add_argument("topic", help="The topic or question to research.")
    parser.add_argument("--audience", default="product and engineering stakeholders")
    parser.add_argument("--outcome", default="a decision-ready research brief")
    parser.add_argument("--provider", choices=["plan", "local", "tavily"], default="plan")
    parser.add_argument("--documents", type=Path, help="JSON array of title, content, and optional URL objects.")
    parser.add_argument("--synthesis", choices=["extractive", "openai"], default="extractive")
    parser.add_argument("--model", default="", help="OpenAI model ID; defaults to OPENAI_MODEL.")
    parser.add_argument("--agent-config", type=Path, help="JSON model profiles and per-agent assignments.")
    parser.add_argument("--models-config", type=Path, help="Local model profiles for an assignments-only agent file.")
    parser.add_argument("--max-sources", type=int, default=3, help="Sources per task (1–10).")
    parser.add_argument("--max-searches", type=int, help="Override the session search budget.")
    parser.add_argument("--timeout", type=float, default=30, help="Provider request timeout in seconds (up to 120).")
    parser.add_argument("--storage-root", type=Path)
    parser.add_argument("--no-persist", action="store_true")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.documents and args.provider != "local":
            raise ValueError("Use --provider local with --documents.")
        if args.provider == "local" and not args.documents:
            raise ValueError("Local research requires --documents PATH.")
        documents = json.loads(args.documents.read_text(encoding="utf-8")) if args.documents else None
        agent_config = json.loads(args.agent_config.read_text(encoding="utf-8")) if args.agent_config else None
        if args.agent_config and not isinstance(agent_config, dict):
            raise ValueError("Agent configuration must be a JSON object.")
        if args.models_config:
            if agent_config is None:
                raise ValueError("Use --agent-config with --models-config.")
            if "models" in agent_config:
                raise ValueError("Use either inline models or --models-config, not both.")
            agent_config["models"] = json.loads(args.models_config.read_text(encoding="utf-8"))
        orchestrator = build_orchestrator(args.provider, documents, args.synthesis, args.model,
                                          args.max_sources, args.max_searches, args.timeout, agent_config)
        report = orchestrator.run(args.topic, args.audience, args.outcome,
                                  persist=not args.no_persist, storage_root=args.storage_root)
        sys.stdout.write(json.dumps(asdict(report), indent=2, default=str) + "\n"
                         if args.format == "json" else report.markdown)
        if report.stored_session:
            print(f"Stored session: {report.stored_session.storage_dir}", file=sys.stderr)
        return 0
    except (ValueError, OSError, ProviderError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Research cancelled.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
