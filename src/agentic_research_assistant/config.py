"""Shared configuration for the CLI and local web app."""
from __future__ import annotations

import os

from .orchestrator import ResearchOrchestrator
from .providers import JsonClient, LocalSearchProvider, TavilySearchProvider
from .researcher import Researcher
from .synthesizer import OpenAISynthesizer, Synthesizer
from .harness import AgentHarness, HarnessConfig


def build_orchestrator(provider: str = "plan", documents: list[dict] | None = None,
                       synthesis: str = "extractive", model: str = "", max_sources: int = 3,
                       max_searches: int | None = None, timeout: float = 30,
                       agent_config: dict | None = None) -> ResearchOrchestrator:
    client = JsonClient(timeout=timeout)
    if provider == "local":
        search = LocalSearchProvider(documents)
    elif provider == "tavily":
        search = TavilySearchProvider(os.environ.get("TAVILY_API_KEY", ""), client)
    elif provider == "plan":
        search = None
    else:
        raise ValueError("Unknown search provider.")
    if agent_config is not None:
        if provider == "plan":
            raise ValueError("An agent team requires local documents or web search.")
        if synthesis != "extractive" or model:
            raise ValueError("Use model assignments in the agent configuration instead of --synthesis or --model.")
        if not isinstance(agent_config, dict):
            raise ValueError("Agent configuration must be an object.")
        data = dict(agent_config)
        if max_searches is not None:
            data["max_searches"] = max_searches
        team = HarnessConfig.parse(data)
        researcher = Researcher(search, max_sources, team.max_searches)
        return ResearchOrchestrator(researcher=researcher,
                                    harness=AgentHarness(team, search, max_sources, timeout))
    budget = 6 if max_searches is None else max_searches
    if type(budget) is not int or budget < 3:
        raise ValueError("Use at least 3 searches for the standard three-task pipeline.")
    if synthesis == "openai":
        if provider == "plan":
            raise ValueError("Model synthesis requires local documents or web search.")
        synth = OpenAISynthesizer(os.environ.get("OPENAI_API_KEY", ""), model or os.environ.get("OPENAI_MODEL", ""), client)
    elif synthesis == "extractive":
        synth = Synthesizer()
    else:
        raise ValueError("Unknown synthesis provider.")
    return ResearchOrchestrator(researcher=Researcher(search, max_sources, budget), synthesizer=synth)
