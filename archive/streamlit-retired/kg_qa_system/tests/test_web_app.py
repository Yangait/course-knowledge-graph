"""Streamlit 页面辅助逻辑的离线单元测试。"""

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

from web_app import (  # noqa: E402
    build_assistant_message,
    mode_label,
    safe_database_status,
    summarize_graph_results,
)


class WebAppHelperTests(unittest.TestCase):
    def test_mode_label_is_user_friendly(self):
        self.assertEqual(
            mode_label("knowledge_graph"),
            "知识图谱增强",
        )
        self.assertEqual(mode_label("custom"), "custom")

    def test_builds_assistant_message(self):
        message = build_assistant_message(
            {
                "answer": "测试回答",
                "answer_mode": "knowledge_graph",
                "model": "test-model",
                "total_tokens": 12,
                "parsed_result": {"anchor_entity": "栈"},
                "linked_result": {"status": "linked"},
                "graph_results": [{"related_name": "进栈"}],
            }
        )

        self.assertEqual(message["role"], "assistant")
        self.assertEqual(message["content"], "测试回答")
        self.assertEqual(message["meta"]["graph_result_count"], 1)

    def test_summarizes_relation_and_context_results(self):
        summary = summarize_graph_results(
            [
                {
                    "anchor_name": "栈",
                    "relation_type": "HAS_OPERATION",
                    "related_name": "进栈",
                    "related_course": "数据结构",
                },
                {
                    "evidence_type": "entity_context",
                    "name": "虚拟内存",
                    "course": "操作系统",
                    "relationships": [{}, {}],
                },
            ]
        )

        self.assertEqual(summary[0]["相关实体"], "进栈")
        self.assertEqual(summary[1]["相关实体"], "2 条相邻知识")

    @patch(
        "web_app.check_database",
        return_value={
            "nodes": 2701,
            "relationships": 10630,
            "cross_course_relationships": 158,
        },
    )
    def test_safe_database_status_success(self, _check):
        result = safe_database_status()

        self.assertTrue(result["ok"])
        self.assertEqual(result["nodes"], 2701)

    @patch(
        "web_app.check_database",
        side_effect=RuntimeError("offline"),
    )
    def test_safe_database_status_failure(self, _check):
        result = safe_database_status()

        self.assertFalse(result["ok"])
        self.assertIn("offline", result["error"])


if __name__ == "__main__":
    unittest.main()
