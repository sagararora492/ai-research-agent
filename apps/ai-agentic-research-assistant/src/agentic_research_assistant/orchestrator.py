from __future__ import annotations

from pathlib import Path
from dataclasses import asdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .harness import AgentHarness

from .collector import SourceCollector
from .models import ResearchQuestion, ResearchReport
from .planner import ResearchPlanner
from .researcher import Researcher
from .storage import SourceStorage
from .synthesizer import Synthesizer
from .providers import ProviderError


class ResearchOrchestrator:
    """Coordinates the planner, researcher, and synthesizer agents."""

    def __init__(
        self,
        planner: ResearchPlanner | None = None,
        researcher: Researcher | None = None,
        collector: SourceCollector | None = None,
        synthesizer: Synthesizer | None = None,
        storage: SourceStorage | None = None,
        harness: AgentHarness | None = None,
    ) -> None:
        self.planner = planner or ResearchPlanner()
        self.researcher = researcher or Researcher()
        self.collector = collector or SourceCollector()
        self.synthesizer = synthesizer or Synthesizer()
        self.storage = storage or SourceStorage()
        self.harness = harness

    def run(
        self,
        topic: str,
        audience: str = "product and engineering stakeholders",
        desired_outcome: str = "a decision-ready research brief",
        persist: bool = True,
        storage_root: Path | None = None,
    ) -> ResearchReport:
        for label, value in (("Topic", topic), ("Audience", audience), ("Outcome", desired_outcome)):
            if not isinstance(value, str) or not value.strip() or len(value) > 2000:
                raise ValueError(f"{label} must contain 1–2000 characters.")
        question = ResearchQuestion(
            topic=topic.strip(),
            audience=audience.strip(),
            desired_outcome=desired_outcome.strip(),
        )
        agent_runs, agent_config = [], {}
        if self.harness is not None:
            tasks, findings, sources, agent_runs, warnings = self.harness.execute(question)
            agent_config = asdict(self.harness.config)
        else:
            tasks = self.planner.build_plan(question)
            findings, sources = self.researcher.investigate(question, tasks)
            warnings = [f"{task.title}: {error}" for task in tasks for error in task.errors]
            try:
                findings = self.synthesizer.synthesize(question, tasks, findings, sources)
            except ProviderError as exc:
                warnings.append(str(exc))
        storage = SourceStorage(storage_root) if storage_root is not None else self.storage
        stored_session = None
        if persist:
            stored_session = storage.initialize_session(question.topic)
            sources = self.collector.collect(question, tasks, sources, stored_session)
        markdown = self.synthesizer.to_markdown(question, tasks, findings, sources)
        if agent_runs:
            from .synthesizer import plain
            markdown += "\n## Agent Execution\n\n"
            for run in agent_runs:
                markdown += (f"- **{plain(run.agent_id)}** ({run.role}): {plain(run.provider)} / "
                             f"{plain(run.model)} — {run.status}; {run.duration_ms} ms.\n")
        if warnings:
            from .synthesizer import plain
            markdown += "\n## Run Warnings\n\n" + "\n".join(f"- {plain(w)}" for w in warnings) + "\n"
        report = ResearchReport(
            question=question,
            tasks=tasks,
            findings=findings,
            sources=sources,
            markdown=markdown,
            warnings=warnings,
            mode="research" if self.researcher.provider is not None else "plan",
            agent_runs=agent_runs,
            agent_config=agent_config,
        )
        if persist:
            report.stored_session = storage.persist(report, stored_session)
        return report
