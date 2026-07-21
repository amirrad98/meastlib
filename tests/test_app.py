import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from backend import app as app_module
from backend.app import remove_batch_history, safe_highlight_snippet


class AppTests(unittest.TestCase):
    def test_highlight_snippets_only_allow_emphasis_tags(self):
        snippet = '<script>alert("x")</script> <em>کتاب</em>'
        safe = safe_highlight_snippet(snippet)
        self.assertNotIn("<script>", safe)
        self.assertIn("&lt;script&gt;", safe)
        self.assertIn("<em>کتاب</em>", safe)

    def test_failed_batch_history_removal_preserves_external_content(self):
        batch_id = "a" * 32
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batches = root / "batches"
            work = batches / "work" / batch_id
            work.mkdir(parents=True)
            (work / "analysis.json").write_text("{}", encoding="utf-8")
            batches.mkdir(parents=True, exist_ok=True)
            (batches / f"{batch_id}.json").write_text(
                json.dumps({"id": batch_id, "status": "partial"}), encoding="utf-8"
            )
            jobs_file = root / "jobs.json"
            test_jobs = [
                {"id": "batch-job", "item_id": f"batch:{batch_id}", "status": "failed"},
                {"id": "book-job", "item_id": "book-1", "status": "succeeded"},
            ]
            with (
                patch.object(app_module, "BATCHES_DIR", batches),
                patch.object(app_module, "JOBS_FILE", jobs_file),
                patch.object(app_module, "jobs", test_jobs),
            ):
                result = remove_batch_history(batch_id)

            self.assertEqual(result, {"removed": batch_id})
            self.assertFalse((batches / f"{batch_id}.json").exists())
            self.assertFalse(work.exists())
            self.assertEqual([job["id"] for job in test_jobs], ["book-job"])

    def test_running_batch_history_cannot_be_removed(self):
        batch_id = "b" * 32
        with tempfile.TemporaryDirectory() as directory:
            batches = Path(directory)
            state = batches / f"{batch_id}.json"
            state.write_text(json.dumps({"id": batch_id, "status": "running"}), encoding="utf-8")
            with (
                patch.object(app_module, "BATCHES_DIR", batches),
                patch.object(app_module, "jobs", []),
                self.assertRaises(HTTPException) as raised,
            ):
                remove_batch_history(batch_id)
            self.assertEqual(raised.exception.status_code, 409)
            self.assertTrue(state.exists())


if __name__ == "__main__":
    unittest.main()
