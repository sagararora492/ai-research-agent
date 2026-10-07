from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from agentic_research_assistant.cli import main
from agentic_research_assistant.config import build_orchestrator
from agentic_research_assistant.models import Citation, ResearchFinding
from agentic_research_assistant.orchestrator import ResearchOrchestrator
from agentic_research_assistant.providers import (
    JsonClient, LocalSearchProvider, ProviderError, SearchResult, TavilySearchProvider, canonical_url,
)
from agentic_research_assistant.researcher import Researcher
from agentic_research_assistant.synthesizer import OpenAISynthesizer, validate_citations
from agentic_research_assistant.web import run_research

DOCUMENTS = [
    {"title": "Search evaluation", "url": "https://example.com/research?utm_source=demo",
     "content": "Research assistants need source citations. Technical risks include unsupported findings. User needs include traceability."},
    {"title": "Workflow", "content": "Research workflows need source inspection. Current alternatives include manual search. Success metrics include verified citations."},
]


def local_run(**kwargs):
    return build_orchestrator("local", DOCUMENTS).run("Research assistants", **kwargs)


class ResearchTests(unittest.TestCase):
    def test_local_research_persists_content_findings_and_queries(self):
        with tempfile.TemporaryDirectory() as directory:
            report = local_run(storage_root=Path(directory))
            self.assertEqual(len(report.sources), 2)
            validate_citations(report.findings, report.sources)
            self.assertTrue(all(f.citations for f in report.findings))
            source = report.sources[0]
            self.assertEqual(source.url, "https://example.com/research")
            self.assertIn(source.content, Path(source.storage_path).read_text())
            manifest = json.loads(Path(report.stored_session.manifest_path).read_text())
            self.assertEqual(manifest["status"], "completed")
            self.assertEqual(manifest["findings"], [asdict(f) for f in report.findings])
            self.assertTrue(manifest["tasks"][0]["search_queries"])

    def test_no_persist_still_collects_and_does_not_write(self):
        with tempfile.TemporaryDirectory() as directory:
            report = local_run(persist=False, storage_root=Path(directory))
            self.assertTrue(report.findings[0].citations)
            self.assertIsNone(report.stored_session)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_repeated_session_names_and_long_topics(self):
        with tempfile.TemporaryDirectory() as directory:
            first = local_run(storage_root=Path(directory))
            second = local_run(storage_root=Path(directory))
            self.assertNotEqual(first.stored_session.session_id, second.stored_session.session_id)
            ResearchOrchestrator().run("x" * 2000, storage_root=Path(directory))

    def test_empty_topic_and_invalid_config(self):
        for topic in (" ", "x" * 2001, None):
            with self.assertRaises(ValueError):
                ResearchOrchestrator().run(topic, persist=False)
        for options in ({"max_sources": 0}, {"max_searches": 1}, {"timeout": float("nan")}):
            with self.assertRaises(ValueError):
                build_orchestrator(**options)

    def test_planning_does_not_invent_claims(self):
        report = ResearchOrchestrator().run("Astronomy", persist=False)
        self.assertIn("Planning only", report.markdown)
        self.assertTrue(all(f.confidence == "low" and not f.citations for f in report.findings))
        self.assertNotIn("generic chatbot", report.markdown)

    def test_search_budget_and_followup(self):
        provider = Mock()
        provider.search.return_value = []
        report = ResearchOrchestrator(researcher=Researcher(provider, max_searches=4)).run("Question", persist=False)
        self.assertEqual(provider.search.call_count, 4)
        self.assertEqual([len(t.search_queries) for t in report.tasks], [2, 1, 1])
        self.assertEqual(report.sources, [])
        self.assertTrue(all(not f.citations for f in report.findings))

    def test_failed_search_surfaces_warnings(self):
        provider = Mock()
        provider.search.side_effect = ProviderError("Provider connection failed.")
        report = ResearchOrchestrator(researcher=Researcher(provider)).run("Question", persist=False)
        self.assertTrue(report.warnings)
        self.assertIn("Run Warnings", report.markdown)
        self.assertFalse(report.sources)

    def test_followup_can_recover_empty_search(self):
        provider = Mock()
        provider.search.side_effect = [[], [], [], [SearchResult("Evidence", "", "A useful source passage.")], [], []]
        report = ResearchOrchestrator(researcher=Researcher(provider)).run("Question", persist=False)
        self.assertEqual(len(report.sources), 1)
        self.assertTrue(report.findings[0].citations)

    def test_local_validation_and_unrelated_documents(self):
        for documents in (None, [], [{}], [{"title": "Bad", "content": "text", "url": "javascript:alert(1)"}]):
            with self.assertRaises(ValueError):
                LocalSearchProvider(documents)
        self.assertEqual(LocalSearchProvider(DOCUMENTS).search("penguins Antarctica", 3), [])

    def test_citation_validation(self):
        report = local_run(persist=False)
        original = report.findings[0]
        for citation in (Citation("missing", "source"), Citation(report.sources[0].source_id, "fabricated quote")):
            with self.assertRaises(ValueError):
                validate_citations([ResearchFinding(original.task_title, "Claim", citations=[citation])], report.sources)
        with self.assertRaises(ValueError):
            validate_citations([ResearchFinding(original.task_title, "Claim", confidence="high")], report.sources)

    def test_model_success_and_invalid_citation_fallback(self):
        report = local_run(persist=False)
        data = {"findings": [asdict(f) for f in report.findings]}
        client = Mock()
        client.post.return_value = {"status": "completed", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": json.dumps(data)}]}]}
        synth = OpenAISynthesizer("test-key", "test-model", client)
        self.assertEqual(synth.synthesize(report.question, report.tasks, report.findings, report.sources), report.findings)
        request = client.post.call_args.args[2]
        self.assertFalse(request["store"])
        self.assertTrue(request["text"]["format"]["strict"])
        data["findings"][0]["citations"][0]["source_id"] = "invented"
        client.post.return_value["output"][0]["content"][0]["text"] = json.dumps(data)
        orchestrator = build_orchestrator("local", DOCUMENTS)
        orchestrator.synthesizer = synth
        fallback = orchestrator.run("Research assistants", persist=False)
        self.assertIn("validation", fallback.warnings[0])
        validate_citations(fallback.findings, fallback.sources)

    def test_model_refusal_and_truncation(self):
        report = local_run(persist=False)
        for payload in ({"status": "incomplete", "output": []},
                        {"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal"}]}]},
                        {"status": "completed", "output": None}):
            client = Mock()
            client.post.return_value = payload
            with self.assertRaises(ProviderError):
                OpenAISynthesizer("key", "model", client).synthesize(report.question, report.tasks, report.findings, report.sources)

    def test_cli_json_and_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "documents.json"
            path.write_text(json.dumps(DOCUMENTS))
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(["Research", "--provider", "local", "--documents", str(path), "--no-persist", "--format", "json"])
            self.assertEqual(code, 0)
            self.assertTrue(json.loads(stdout.getvalue())["sources"])
            with redirect_stderr(stderr):
                self.assertEqual(main(["Research", "--provider", "local"]), 1)
            self.assertIn("requires --documents", stderr.getvalue())

    def test_web_uses_pipeline_and_validates_inputs(self):
        result = run_research({"topic": "Research", "provider": "local", "documents": DOCUMENTS, "persist": False})
        self.assertTrue(result["findings"][0]["citations"])
        for payload in ([], {"max_sources": True}, {"persist": "false"}, {"provider": []}):
            with self.assertRaises(ValueError):
                run_research(payload)

    def test_credentials_fail_without_network(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(ValueError, "TAVILY_API_KEY"):
                build_orchestrator("tavily")
            with self.assertRaisesRegex(ValueError, "OPENAI_API_KEY"):
                build_orchestrator("local", DOCUMENTS, "openai", "test-model")


class ProviderTests(unittest.TestCase):
    def test_url_canonicalization(self):
        self.assertEqual(canonical_url("https://EXAMPLE.com:443/a?utm_source=x&b=2&a=1#top"), "https://example.com/a?a=1&b=2")
        for url in ("javascript:alert(1)", "https://user:pass@example.com", "https://[invalid", "https://host:bad", "https://host/a b"):
            self.assertEqual(canonical_url(url), "")

    def test_tavily_normalization_ranking_and_snippets(self):
        client = Mock()
        client.post.return_value = {"results": [
            {"title": "Snippet", "url": "https://example.com/one", "content": "Excerpt", "raw_content": None, "score": .2},
            {"title": "Full", "url": "https://example.com/two", "content": "Excerpt", "raw_content": "Full text", "score": .9},
            {"title": "Unsafe", "url": "javascript:alert(1)", "content": "text"}]}
        results = TavilySearchProvider("key", client).search("query", 3)
        self.assertEqual([r.title for r in results], ["Full", "Snippet"])
        self.assertEqual(results[1].content_kind, "snippet")
        self.assertEqual(client.post.call_args.args[2]["include_raw_content"], "text")

    @patch("agentic_research_assistant.providers.time.sleep")
    @patch("agentic_research_assistant.providers.build_opener")
    def test_transport_retries_and_redacts_errors(self, opener, sleep):
        opener.return_value.open.side_effect = HTTPError("https://api.example.com", 429, "secret-key", {}, None)
        with self.assertRaises(ProviderError) as context:
            JsonClient().post("https://api.example.com", "secret-key", {})
        self.assertEqual(opener.return_value.open.call_count, 3)
        self.assertNotIn("secret-key", str(context.exception))
        opener.return_value.open.reset_mock()
        opener.return_value.open.side_effect = HTTPError("https://api.example.com", 401, "secret-key", {}, None)
        with self.assertRaises(ProviderError):
            JsonClient().post("https://api.example.com", "secret-key", {})
        self.assertEqual(opener.return_value.open.call_count, 1)

    @patch("agentic_research_assistant.providers.build_opener")
    def test_invalid_or_oversized_json(self, opener):
        response = opener.return_value.open.return_value.__enter__.return_value
        for body in (b"not json", b"[]", b"x" * 8_000_001):
            response.read.return_value = body
            with self.assertRaises(ProviderError):
                JsonClient().post("https://api.example.com", "key", {})


if __name__ == "__main__":
    unittest.main()
