from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime

from .models import Citation, ResearchFinding, ResearchQuestion, ResearchSource, ResearchTask
from .providers import ProviderError, SearchProvider, tokens


class Researcher:
    """Search, rank, deduplicate, and extract traceable evidence with a bounded budget."""

    def __init__(self, provider: SearchProvider | None = None, max_sources: int = 3,
                 max_searches: int = 6) -> None:
        if type(max_sources) is not int or not 1 <= max_sources <= 10 or type(max_searches) is not int or max_searches < 1:
            raise ValueError("Use 1–10 sources per task and a positive search budget.")
        self.provider = provider
        self.max_sources = max_sources
        self.max_searches = max_searches

    def investigate(self, question: ResearchQuestion, tasks: list[ResearchTask]
                    ) -> tuple[list[ResearchFinding], list[ResearchSource]]:
        if self.provider is None:
            return self._plan_only(tasks)
        sources: dict[str, ResearchSource] = {}
        searches = 0

        def search(task: ResearchTask, query: str) -> None:
            nonlocal searches
            searches += 1
            task.search_queries.append(query)
            try:
                results = self.provider.search(query, self.max_sources)
            except ProviderError as exc:
                task.errors.append(str(exc))
                return
            for result in sorted(results, key=lambda item: item.score, reverse=True)[:self.max_sources]:
                if not result.content.strip():
                    continue
                identity = result.url or hashlib.sha256(result.content.encode()).hexdigest()
                if identity in sources:
                    existing = sources[identity]
                    if task.title not in existing.task_titles:
                        existing.task_titles.append(task.title)
                    continue
                source_id = f"S{len(sources) + 1}"
                sources[identity] = ResearchSource(
                    source_id=source_id, task_title=task.title, task_titles=[task.title],
                    title=result.title, source_type="document" if result.content_kind == "imported" else "web",
                    status="collected", description=result.content[:240], url=result.url,
                    content=result.content, score=result.score,
                    metadata={"retrieved_at": datetime.now(UTC).isoformat(),
                              "published_at": result.published_at, "content_kind": result.content_kind,
                              "query": query},
                )

        # Give each task one search before spending spare budget on empty tasks.
        for task in tasks:
            if searches < self.max_searches:
                search(task, f"{question.topic} {' '.join(task.evidence_to_collect)}")
        for task in tasks:
            if searches < self.max_searches and not any(task.title in s.task_titles for s in sources.values()):
                search(task, question.topic)
        findings = []
        for task in tasks:
            task_tokens = tokens(" ".join(task.evidence_to_collect))
            relevant = sorted((s for s in sources.values() if task.title in s.task_titles),
                              key=lambda s: (len(task_tokens & tokens(s.content)), s.score), reverse=True)
            citations = []
            query_tokens = tokens(question.topic + " " + " ".join(task.evidence_to_collect))
            for source in relevant[:self.max_sources]:
                passages = [p.strip() for p in re.split(r"(?<=[.!?])\s+|\n+", source.content) if p.strip()]
                best = max(passages, key=lambda p: 3 * len(task_tokens & tokens(p))
                           + len(query_tokens & tokens(p)))
                citations.append(Citation(source.source_id, best[:350]))
            findings.append(ResearchFinding(
                task_title=task.title,
                insight="Relevant source excerpts are listed below; they have not been independently verified."
                        if citations else "No usable evidence was found for this task.",
                evidence_gaps=task.errors + (["Review source authority, relevance, contradictions, and coverage before deciding."]
                                            if citations else [f"Collect evidence for: {e}" for e in task.evidence_to_collect]),
                confidence="low", citations=citations,
            ))
        return findings, list(sources.values())

    @staticmethod
    def _plan_only(tasks: list[ResearchTask]) -> tuple[list[ResearchFinding], list[ResearchSource]]:
        findings, sources = [], []
        for task_index, task in enumerate(tasks, 1):
            findings.append(ResearchFinding(task.title, "Research is planned; no evidence has been collected.",
                                             list(task.evidence_to_collect)))
            for index, need in enumerate(task.evidence_to_collect, 1):
                sources.append(ResearchSource(
                    source_id=f"task-{task_index}-source-{index}", task_title=task.title,
                    title=f"{task.title}: {need}", source_type="research_target", status="planned",
                    description=f"Collect evidence about {need.lower()}.", metadata={"evidence_need": need},
                    task_titles=[task.title],
                ))
        return findings, sources
