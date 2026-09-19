import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DASHSCOPE_API_KEY", "unit-test-key")
os.environ.setdefault("DASHSCOPE_BASE_URL", "https://example.invalid/v1")
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USERNAME", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "unit-test-password")

from fastapi.testclient import TestClient
from api import app, build_evidence
from unified_graph import relative_direction, graph_scope, find_entity_candidates


class UnifiedGraphTests(unittest.TestCase):
    def test_all_original_arrow_directions(self):
        self.assertEqual(relative_direction("forward", True), "outgoing")
        self.assertEqual(relative_direction("forward", False), "incoming")
        self.assertEqual(relative_direction("backward", True), "incoming")
        self.assertEqual(relative_direction("backward", False), "outgoing")
        for value in ("both", "none"):
            self.assertEqual(relative_direction(value, True), value)
            self.assertEqual(relative_direction(value, False), value)

    @patch("unified_graph.read_graph", return_value=[])
    def test_course_scope_is_reset_after_request(self, read):
        with graph_scope("C16"):
            find_entity_candidates("机器学习")
            self.assertEqual(read.call_args.kwargs["course"], "C16")
        find_entity_candidates("栈")
        self.assertIsNone(read.call_args.kwargs["course"])

    def test_course_catalog_and_tree_preserve_all_courses(self):
        client = TestClient(app)
        courses = client.get("/api/graph/courses").json()["courses"]
        self.assertEqual(len(courses), 26)
        total = 0
        for course in courses:
            data = client.get("/api/graph/courses/" + course["course_id"]).json()
            total += len(data["knowledge_nodes"])
            self.assertEqual(data["main_tree"][0]["id"], course["root_id"])
        self.assertEqual(total, 18391)

    def test_media_endpoint_only_serves_registered_images(self):
        client = TestClient(app)
        data = client.get("/api/graph/courses/C07").json()
        image = data["images"][0]
        response = client.get("/api/graph/image", params={"image_id":image["id"]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.content), image["file_size"])
        self.assertEqual(client.get("/api/graph/image", params={"image_id":"../../kg_qa_system/.env"}).status_code,404)
        self.assertEqual(client.get("/api/graph/courses/C99").status_code,404)

    @patch("api.answer_question")
    @patch("api.node_record", return_value=None)
    def test_mismatched_focused_node_does_not_call_model(self, node, answer):
        result = TestClient(app).post("/api/ask",json={"question":"解释这个知识点", "course_id":"C16", "node_id":"C07:K:716"})
        self.assertEqual(result.status_code,404)
        answer.assert_not_called()

    def test_evidence_keeps_source_location_and_original_relation(self):
        items = build_evidence([dict(evidence_type="entity_context",node_id="C07:K:716",course_id="C07",name="栈",
            relationships=[dict(related_name="线性表",relation_type="SEMANTIC_LINK",relation_text="特殊线性表",direction="outgoing")])])
        self.assertEqual(items[0].node_id,"C07:K:716")
        self.assertEqual(items[0].course_id,"C07")
        self.assertEqual(items[0].relation,"特殊线性表")
        self.assertEqual(items[0].direction,"outgoing")


if __name__ == "__main__":
    unittest.main()
