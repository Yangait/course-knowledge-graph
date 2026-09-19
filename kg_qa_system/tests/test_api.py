"""FastAPI 接口的离线基础测试。"""

import os
import unittest
from unittest.mock import patch


os.environ.setdefault("DASHSCOPE_API_KEY", "unit-test-key")
os.environ.setdefault(
    "DASHSCOPE_BASE_URL",
    "https://example.invalid/v1",
)
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USERNAME", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "unit-test-password")

from fastapi.testclient import TestClient  # noqa: E402

from api import app  # noqa: E402


class HealthEndpointTests(unittest.TestCase):
    @patch(
        "api.check_database",
        return_value={
            "nodes": 2701,
            "relationships": 10630,
            "cross_course_relationships": 158,
        },
    )
    def test_health_reports_connected_database(self, _check):
        response = TestClient(app).get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertEqual(
            response.json()["neo4j"]["status"],
            "connected",
        )
        self.assertEqual(response.json()["neo4j"]["nodes"], 2701)

    @patch(
        "api.check_database",
        side_effect=RuntimeError("password=should-not-leak"),
    )
    def test_health_hides_database_error_details(self, _check):
        response = TestClient(app).get("/api/health")
        body = response.text

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "degraded")
        self.assertEqual(
            response.json()["service"]["status"],
            "running",
        )
        self.assertEqual(
            response.json()["neo4j"]["status"],
            "disconnected",
        )
        self.assertNotIn("should-not-leak", body)


class AskEndpointTests(unittest.TestCase):
    @patch("api.answer_question")
    def test_answer_style_is_validated_and_forwarded(self, answer):
        answer.return_value = dict(answer="回答", answer_mode="llm_only", model="test", total_tokens=1)
        client = TestClient(app)
        for style in ("concise", "detailed"):
            with self.subTest(style=style):
                response = client.post("/api/ask", json={"question": "什么是栈？", "answer_style": style})
                self.assertEqual(response.status_code, 200)
                answer.assert_called_with("什么是栈？", answer_style=style)
        answer.reset_mock()
        response = client.post("/api/ask", json={"question": "什么是栈？", "answer_style": "invalid"})
        self.assertEqual(response.status_code, 422)
        answer.assert_not_called()

    @patch("api.answer_question")
    def test_ask_trims_question_and_returns_selected_fields(self, answer):
        answer.return_value = {
            "status": "success",
            "answer": "栈支持进栈和出栈。",
            "answer_mode": "knowledge_graph",
            "model": "test-model",
            "total_tokens": 42,
            "parsed_result": {"anchor_entity": "栈"},
            "linked_result": {"status": "linked"},
            "graph_results": [
                {
                    "anchor_node_id": "DS_CON_001",
                    "anchor_name": "栈",
                    "related_node_id": "DS_OPE_001",
                    "related_name": "进栈",
                    "related_course": "数据结构",
                    "relation_type": "HAS_OPERATION",
                    "direction": "outgoing",
                    "reason": "进栈用于向栈顶插入元素。",
                    "source": "《数据结构》教材",
                    "book_page": "63",
                    "confidence": 0.96,
                }
            ],
        }

        response = TestClient(app).post(
            "/api/ask",
            json={"question": "  栈有哪些操作？  "},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "answer": "栈支持进栈和出栈。",
                "answer_mode": "knowledge_graph",
                "model": "test-model",
                "total_tokens": 42,
                "evidence": [
                    {
                        "core_concept": "栈",
                        "related_concept": "进栈",
                        "relation": "具有操作",
                        "reason": "进栈用于向栈顶插入元素。",
                        "course": "数据结构",
                        "source": "《数据结构》教材（页码：63）",
                        "confidence": 0.96,
                    }
                ],
            },
        )
        answer.assert_called_once_with("栈有哪些操作？")

    @patch("api.answer_question")
    def test_ask_flattens_entity_context_evidence(self, answer):
        answer.return_value = {
            "status": "success",
            "answer": "虚拟内存与页表有关。",
            "answer_mode": "hybrid",
            "model": "test-model",
            "total_tokens": 20,
            "graph_results": [
                {
                    "evidence_type": "entity_context",
                    "node_id": "OS_CON_001",
                    "name": "虚拟内存",
                    "course": "操作系统",
                    "source": "《操作系统》教材",
                    "book_page": "120",
                    "relationships": [
                        {
                            "relation_type": "USES",
                            "direction": "outgoing",
                            "related_name": "页表",
                            "reason": "地址转换需要查询页表。",
                            "confidence": 0.92,
                        }
                    ],
                }
            ],
        }

        response = TestClient(app).post(
            "/api/ask",
            json={"question": "虚拟内存使用什么？"},
        )
        item = response.json()["evidence"][0]

        self.assertEqual(response.status_code, 200)
        self.assertEqual(item["core_concept"], "虚拟内存")
        self.assertEqual(item["related_concept"], "页表")
        self.assertEqual(item["relation"], "使用或依赖")
        self.assertNotIn("node_id", response.text)
        self.assertNotIn("outgoing", response.text)

    @patch("api.answer_question")
    def test_ask_returns_empty_evidence_without_graph_results(self, answer):
        answer.return_value = {
            "status": "success",
            "answer": "模型直接回答。",
            "answer_mode": "llm_only",
            "model": "test-model",
            "total_tokens": 9,
            "graph_results": [],
        }

        response = TestClient(app).post(
            "/api/ask",
            json={"question": "一个图谱外的问题"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["evidence"], [])

    @patch("api.answer_question")
    def test_ask_limits_evidence_and_omits_empty_fields(self, answer):
        graph_results = [
            {
                "anchor_name": "排序",
                "related_name": f"算法{i}",
                "relation_type": "CONTAINS",
                "direction": "outgoing",
                "anchor_node_id": f"INTERNAL_{i}",
            }
            for i in range(12)
        ]
        answer.return_value = {
            "status": "success",
            "answer": "排序包含多种算法。",
            "answer_mode": "knowledge_graph",
            "model": "test-model",
            "total_tokens": 18,
            "graph_results": graph_results,
        }

        response = TestClient(app).post(
            "/api/ask",
            json={"question": "排序包含什么？"},
        )
        evidence = response.json()["evidence"]

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(evidence), 8)
        self.assertTrue(all(value is not None for item in evidence for value in item.values()))
        self.assertNotIn("INTERNAL_", response.text)
        self.assertNotIn("outgoing", response.text)

    @patch("api.answer_question")
    def test_ask_rejects_blank_question_without_calling_model(self, answer):
        response = TestClient(app).post(
            "/api/ask",
            json={"question": "   "},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["error"]["code"],
            "validation_error",
        )
        self.assertIn("不能为空", response.text)
        answer.assert_not_called()

    @patch("api.answer_question")
    def test_ask_rejects_question_over_limit(self, answer):
        response = TestClient(app).post(
            "/api/ask",
            json={"question": "问" * 501},
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("500", response.text)
        answer.assert_not_called()

    @patch("api.answer_question")
    def test_ask_rejects_non_string_question(self, answer):
        response = TestClient(app).post(
            "/api/ask",
            json={"question": 123},
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("必须是字符串", response.text)
        answer.assert_not_called()

    @patch(
        "api.answer_question",
        side_effect=RuntimeError(
            "API_KEY=secret password=secret .env traceback"
        ),
    )
    def test_ask_hides_internal_error_details(self, _answer):
        response = TestClient(app).post(
            "/api/ask",
            json={"question": "什么是栈？"},
        )
        body = response.text

        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.json()["error"]["code"],
            "qa_service_unavailable",
        )
        self.assertNotIn("API_KEY", body)
        self.assertNotIn("password", body)
        self.assertNotIn("traceback", body)

    @patch(
        "api.answer_question",
        return_value={"status": "success"},
    )
    def test_ask_handles_invalid_core_result_safely(self, _answer):
        response = TestClient(app).post(
            "/api/ask",
            json={"question": "什么是栈？"},
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.json()["error"]["code"],
            "qa_service_unavailable",
        )


class LifespanTests(unittest.TestCase):
    @patch("api.driver.close")
    def test_driver_closes_once_when_service_stops(self, close):
        with TestClient(app):
            close.assert_not_called()

        close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
