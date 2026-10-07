from __future__ import annotations

from datetime import datetime
from dataclasses import dataclass, field


@dataclass(slots=True)
class ResearchQuestion:
    topic: str
    audience: str = "product and engineering stakeholders"
    desired_outcome: str = "a decision-ready research brief"


@dataclass(slots=True)
class ResearchTask:
    title: str
    objective: str
    evidence_to_collect: list[str] = field(default_factory=list)
    search_queries: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    agent_id: str = ""


@dataclass(slots=True)
class Citation:
    source_id: str
    excerpt: str


@dataclass(slots=True)
class ResearchFinding:
    task_title: str
    insight: str
    evidence_gaps: list[str] = field(default_factory=list)
    confidence: str = "low"
    citations: list[Citation] = field(default_factory=list)
    agent_id: str = ""


@dataclass(slots=True)
class AgentRun:
    agent_id: str
    role: str
    model_profile: str | None
    provider: str
    model: str
    status: str = "completed"
    duration_ms: int = 0
    usage: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    findings: list[ResearchFinding] = field(default_factory=list)


@dataclass(slots=True)
class ResearchSource:
    source_id: str
    task_title: str
    title: str
    source_type: str
    status: str
    description: str
    storage_path: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)
    url: str = ""
    content: str = ""
    score: float = 0.0
    task_titles: list[str] = field(default_factory=list)


@dataclass(slots=True)
class StoredSession:
    session_id: str
    created_at: datetime
    storage_dir: str
    source_artifacts_dir: str
    report_path: str
    sources_path: str
    manifest_path: str


@dataclass(slots=True)
class ResearchReport:
    question: ResearchQuestion
    tasks: list[ResearchTask]
    findings: list[ResearchFinding]
    sources: list[ResearchSource]
    markdown: str
    stored_session: StoredSession | None = None
    warnings: list[str] = field(default_factory=list)
    mode: str = "plan"
    agent_runs: list[AgentRun] = field(default_factory=list)
    agent_config: dict = field(default_factory=dict)
