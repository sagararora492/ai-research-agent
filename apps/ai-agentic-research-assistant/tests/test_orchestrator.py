from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agentic_research_assistant.orchestrator import ResearchOrchestrator


class ResearchOrchestratorTest(unittest.TestCase):
    def test_run_builds_three_research_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            orchestrator = ResearchOrchestrator()

            report = orchestrator.run(
                "AI Agentic Research Assistant",
                storage_root=Path(tmp_dir),
            )

            self.assertEqual(report.question.topic, "AI Agentic Research Assistant")
            self.assertEqual(len(report.tasks), 3)
            self.assertEqual(len(report.findings), 3)
            self.assertEqual(len(report.sources), 9)
            self.assertIn("# Research Brief: AI Agentic Research Assistant", report.markdown)
            self.assertIn("## Recommended Next Steps", report.markdown)
            self.assertIsNotNone(report.stored_session)

            stored_session = report.stored_session
            assert stored_session is not None

            self.assertTrue(Path(stored_session.report_path).exists())
            self.assertTrue(Path(stored_session.sources_path).exists())
            self.assertTrue(Path(stored_session.manifest_path).exists())
            self.assertTrue(Path(stored_session.source_artifacts_dir).exists())

            sources = json.loads(Path(stored_session.sources_path).read_text(encoding="utf-8"))
            manifest = json.loads(Path(stored_session.manifest_path).read_text(encoding="utf-8"))

            self.assertEqual(len(sources), 9)
            self.assertEqual(manifest["source_count"], 9)
            self.assertEqual(manifest["topic"], "AI Agentic Research Assistant")
            self.assertEqual(manifest["source_artifacts_dir"], stored_session.source_artifacts_dir)
            self.assertTrue(all(source["status"] == "seeded" for source in sources))
            self.assertTrue(all(source["storage_path"] for source in sources))
            first_artifact_path = Path(sources[0]["storage_path"])
            self.assertTrue(first_artifact_path.exists())
            self.assertIn(
                "## Raw Source Content",
                first_artifact_path.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
