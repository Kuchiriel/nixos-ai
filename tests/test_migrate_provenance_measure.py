import importlib.util
import io
import json
import pathlib
import unittest
from contextlib import redirect_stdout
from importlib.machinery import SourceFileLoader


SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "migrate-provenance.py"
SPEC = importlib.util.spec_from_loader(
    "migrate_provenance_measure",
    SourceFileLoader("migrate_provenance_measure", str(SCRIPT)),
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class MigrateProvenanceMeasureTests(unittest.TestCase):
    def test_payload_branch_uses_payload_not_checkout_head(self):
        self.assertEqual("main", MODULE.payload_branch({"payload": {"branch": "main"}}))
        self.assertEqual("unknown", MODULE.payload_branch({"payload": {"branch": "unknown"}}))
        self.assertEqual("", MODULE.payload_branch({"payload": {}}))
        self.assertEqual("", MODULE.payload_branch({}))

    def test_measure_filters_each_query_by_its_own_point_branch(self):
        points = [
            {"id": "p-main", "vector": {"dense": [1.0]}, "payload": {"branch": "main"}},
            {"id": "p-unknown", "vector": {"dense": [2.0]}, "payload": {"branch": "unknown"}},
            {"id": "p-missing", "vector": {"dense": [3.0]}, "payload": {}},
        ]
        seen_filters = []

        def fake_scroll_all(collection, n, with_vectors=False, with_payload=False):
            self.assertEqual("code_index", collection)
            self.assertTrue(with_vectors)
            self.assertTrue(with_payload)
            return points[:n]

        def fake_req(method, path, body=None, timeout=180):
            self.assertEqual("POST", method)
            self.assertEqual("/collections/code_index/points/query", path)
            branch = body["filter"]["must"][0]["match"]["value"]
            seen_filters.append(branch)
            point_id = "p-main" if branch == "main" else "p-unknown"
            return {"result": {"points": [{"id": point_id}]}}

        def fail_provenance():
            raise AssertionError("measure must not use checkout HEAD as the filter")

        old_scroll, old_req, old_provenance = (
            MODULE.scroll_all,
            MODULE.req,
            MODULE.provenance,
        )
        MODULE.scroll_all = fake_scroll_all
        MODULE.req = fake_req
        MODULE.provenance = fail_provenance
        try:
            out = io.StringIO()
            with redirect_stdout(out):
                MODULE.measure("code_index", 3)
        finally:
            MODULE.scroll_all = old_scroll
            MODULE.req = old_req
            MODULE.provenance = old_provenance

        result = json.loads(out.getvalue())
        self.assertEqual(["main", "unknown"], seen_filters)
        self.assertEqual(2, result["queries"])
        self.assertEqual(1.0, result["recall_at_8"])
        self.assertEqual("point_branch", result["filter_mode"])
        self.assertEqual({"main": 1, "unknown": 1}, result["filters"])
        self.assertEqual(1, result["skipped_no_branch"])


if __name__ == "__main__":
    unittest.main()
