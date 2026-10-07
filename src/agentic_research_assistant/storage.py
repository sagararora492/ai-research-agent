from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .models import ResearchReport, StoredSession


class SourceStorage:
    """Persists research session artifacts to the local filesystem."""

    def __init__(self, root_dir: Path | None = None) -> None:
        self.root_dir = root_dir or self.default_root_dir()

    @staticmethod
    def default_root_dir() -> Path:
        return Path.cwd() / "data" / "research_sessions"

    def initialize_session(self, topic: str) -> StoredSession:
        session_id = self._build_session_id(topic)
        session_dir = self.root_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=False)
        source_artifacts_dir = session_dir / "sources"
        source_artifacts_dir.mkdir(parents=True, exist_ok=False)

        return StoredSession(
            session_id=session_id,
            created_at=datetime.now(UTC),
            storage_dir=str(session_dir),
            source_artifacts_dir=str(source_artifacts_dir),
            report_path=str(session_dir / "report.md"),
            sources_path=str(session_dir / "sources.json"),
            manifest_path=str(session_dir / "session.json"),
        )

    def persist(
        self,
        report: ResearchReport,
        session: StoredSession | None = None,
    ) -> StoredSession:
        stored_session = session or self.initialize_session(report.question.topic)

        Path(stored_session.report_path).write_text(report.markdown, encoding="utf-8")
        Path(stored_session.sources_path).write_text(
            json.dumps([asdict(source) for source in report.sources], indent=2),
            encoding="utf-8",
        )

        manifest = {
            "schema_version": 2,
            "agent_config": report.agent_config,
            "agent_runs": [asdict(run) for run in report.agent_runs],
            "status": "completed",
            "mode": report.mode,
            "warnings": report.warnings,
            "tasks": [asdict(task) for task in report.tasks],
            "findings": [asdict(finding) for finding in report.findings],
            "session_id": stored_session.session_id,
            "created_at": stored_session.created_at.isoformat(),
            "topic": report.question.topic,
            "audience": report.question.audience,
            "desired_outcome": report.question.desired_outcome,
            "task_count": len(report.tasks),
            "finding_count": len(report.findings),
            "source_count": len(report.sources),
            "source_artifacts_dir": stored_session.source_artifacts_dir,
            "report_path": stored_session.report_path,
            "sources_path": stored_session.sources_path,
        }
        Path(stored_session.manifest_path).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return stored_session

    def _build_session_id(self, topic: str) -> str:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")
        return f"{timestamp}-{slug[:80] or 'research-session'}-{uuid4().hex[:12]}"
