from __future__ import annotations

from .models import ResearchQuestion, ResearchTask


class ResearchPlanner:
    """Creates a lightweight task graph for a research topic."""

    def build_plan(self, question: ResearchQuestion) -> list[ResearchTask]:
        topic = question.topic.strip()
        return [
            ResearchTask(
                title="Scope the problem",
                objective=f"Define the boundaries, users, and business stakes for {topic}.",
                evidence_to_collect=[
                    "Primary user needs",
                    "Operational constraints",
                    "Success metrics",
                ],
            ),
            ResearchTask(
                title="Map the landscape",
                objective=f"Identify the market, tooling, and workflow patterns related to {topic}.",
                evidence_to_collect=[
                    "Current alternatives",
                    "Workflow bottlenecks",
                    "Adoption patterns",
                ],
            ),
            ResearchTask(
                title="Assess risks and opportunities",
                objective=f"Surface implementation risks, differentiators, and decision criteria for {topic}.",
                evidence_to_collect=[
                    "Technical risks",
                    "Compliance or trust concerns",
                    "High-leverage opportunities",
                ],
            ),
        ]
