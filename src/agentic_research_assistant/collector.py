from __future__ import annotations

from pathlib import Path

from .models import ResearchQuestion, ResearchSource, ResearchTask, StoredSession


class SourceCollector:
    """Materializes planned source records into stored source artifacts."""

    def collect(
        self,
        question: ResearchQuestion,
        tasks: list[ResearchTask],
        sources: list[ResearchSource],
        session: StoredSession,
    ) -> list[ResearchSource]:
        task_map = {task.title: task for task in tasks}
        collected_sources: list[ResearchSource] = []
        artifacts_dir = Path(session.source_artifacts_dir)
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        for source in sources:
            task = task_map[source.task_title]
            artifact_path = artifacts_dir / f"{source.source_id}.md"
            if source.status == "collected":
                artifact_path.write_text(
                    f"# {source.title}\n\nSource ID: {source.source_id}\nURL: {source.url}\n\n"
                    f"## Raw Source Content\n\n{source.content}\n", encoding="utf-8",
                )
                source.storage_path = str(artifact_path)
                collected_sources.append(source)
                continue
            artifact_path.write_text(
                self._build_source_artifact(question, task, source),
                encoding="utf-8",
            )
            source.status = "seeded"
            source.storage_path = str(artifact_path)
            source.metadata["collector"] = "offline_bootstrap"
            source.metadata["artifact_format"] = "markdown"
            source.metadata["topic"] = question.topic
            collected_sources.append(source)

        return collected_sources

    def _build_source_artifact(
        self,
        question: ResearchQuestion,
        task: ResearchTask,
        source: ResearchSource,
    ) -> str:
        evidence_need = source.metadata.get("evidence_need", source.title)
        search_query = (
            f"{question.topic} {task.title} {evidence_need}".replace(":", " ").strip()
        )
        lines = [
            f"# {source.title}",
            "",
            "## Source Record",
            f"- Source ID: {source.source_id}",
            f"- Status: seeded",
            f"- Type: {source.source_type}",
            f"- Task: {source.task_title}",
            "",
            "## Collection Objective",
            source.description,
            "",
            "## Research Context",
            f"- Topic: {question.topic}",
            f"- Audience: {question.audience}",
            f"- Desired outcome: {question.desired_outcome}",
            f"- Task objective: {task.objective}",
            "",
            "## Evidence Need",
            evidence_need,
            "",
            "## Suggested Search Query",
            search_query,
            "",
            "## Normalized Notes",
            "- Add the source URL here",
            "- Add publication or publisher here",
            "- Add author here",
            "- Add publication date here",
            "- Add a concise evidence summary here",
            "- Add a citation-ready excerpt here",
            "",
            "## Raw Source Content",
            "Not collected yet. Replace this section with fetched or imported source material.",
            "",
        ]
        return "\n".join(lines)
