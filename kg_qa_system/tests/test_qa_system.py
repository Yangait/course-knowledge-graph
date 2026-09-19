"""问答编排流程的离线单元测试。"""

import os
import unittest
from unittest.mock import patch


# 模块初始化需要配置项；外部调用会在测试中被模拟。
os.environ.setdefault("DASHSCOPE_API_KEY", "unit-test-key")
os.environ.setdefault(
    "DASHSCOPE_BASE_URL",
    "https://example.invalid/v1",
)
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USERNAME", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "unit-test-password")

from qa_system import answer_question  # noqa: E402


class AnswerQuestionTests(unittest.TestCase):
    @patch("qa_system.generate_answer")
    @patch("qa_system.query_related_nodes")
    @patch("qa_system.link_entity")
    @patch("qa_system.parse_question")
    def test_relation_question_uses_graph_evidence(
        self,
        parse,
        link,
        query,
        generate,
    ):
        parse.return_value = {
            "anchor_entity": "栈",
            "entities": ["栈"],
            "relation_type": "HAS_OPERATION",
            "direction": "outgoing",
            "complexity": "simple",
        }
        link.return_value = {
            "status": "linked",
            "selected": {"node_id": "DS_CON_001"},
            "candidates": [],
        }
        query.return_value = [
            {
                "anchor_node_id": "DS_CON_001",
                "anchor_name": "栈",
                "related_node_id": "DS_OPE_001",
                "related_name": "进栈",
                "relation_type": "HAS_OPERATION",
            }
        ]
        generate.return_value = {
            "answer": "栈支持进栈操作。",
            "answer_mode": "knowledge_graph",
            "model": "test-model",
            "total_tokens": 10,
        }

        result = answer_question("栈有哪些操作？")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["answer_mode"], "knowledge_graph")
        self.assertEqual(len(result["graph_results"]), 1)
        query.assert_called_once_with(
            node_id="DS_CON_001",
            relation_type="HAS_OPERATION",
            direction="outgoing",
        )
        evidence = generate.call_args.kwargs["graph_results"]
        self.assertEqual(evidence[0]["related_name"], "进栈")

    @patch("qa_system.generate_answer")
    @patch("qa_system.link_entity")
    @patch("qa_system.parse_question")
    def test_not_found_entity_falls_back_to_llm(
        self,
        parse,
        link,
        generate,
    ):
        parse.return_value = {
            "anchor_entity": "未知概念",
            "entities": ["未知概念"],
            "relation_type": None,
            "direction": None,
            "complexity": "simple",
        }
        link.return_value = {
            "status": "not_found",
            "selected": None,
            "candidates": [],
        }
        generate.return_value = {
            "answer": "模型补充回答。",
            "answer_mode": "llm_only",
            "model": "test-model",
            "total_tokens": 8,
        }

        result = answer_question("什么是未知概念？", answer_style="detailed")

        self.assertEqual(result["answer_mode"], "llm_only")
        self.assertEqual(result["graph_results"], [])
        generate.assert_called_once()
        self.assertEqual(generate.call_args.kwargs["answer_style"], "detailed")

    @patch("qa_system.generate_answer")
    @patch("qa_system._answer_question")
    def test_database_failure_keeps_answer_style(self, process, generate):
        from neo4j.exceptions import ServiceUnavailable
        process.side_effect = ServiceUnavailable("offline")
        generate.return_value = dict(answer="短回答", answer_mode="llm_only", model="test", total_tokens=1)
        result = answer_question("什么是栈？", answer_style="concise")
        self.assertEqual(result["answer"], "短回答")
        self.assertEqual(generate.call_args.kwargs["answer_style"], "concise")


if __name__ == "__main__":
    unittest.main()
