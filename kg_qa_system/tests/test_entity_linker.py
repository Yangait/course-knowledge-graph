"""实体链接器的离线单元测试。"""

import os
import unittest
from unittest.mock import patch


# 模块初始化需要配置项；测试中的数据库函数均会被模拟。
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USERNAME", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "unit-test-password")

from entity_linker import link_entity  # noqa: E402


def candidate(node_id, score=100, importance=5):
    return {
        "node_id": node_id,
        "name": "栈",
        "match_score": score,
        "importance": importance,
    }


class EntityLinkerTests(unittest.TestCase):
    @patch("entity_linker.find_entity_candidates", return_value=[])
    def test_returns_not_found_without_candidates(self, _find):
        result = link_entity("不存在的实体")

        self.assertEqual(result["status"], "not_found")
        self.assertIsNone(result["selected"])

    @patch("entity_linker.count_relations_for_node", return_value=0)
    @patch("entity_linker.find_entity_candidates")
    def test_selects_unique_best_name_match(self, find, _count):
        find.return_value = [
            candidate("DS_CON_001", score=100),
            candidate("OS_CON_001", score=70),
        ]

        result = link_entity("栈")

        self.assertEqual(result["status"], "linked")
        self.assertEqual(result["resolution_method"], "name_match")
        self.assertEqual(result["selected"]["node_id"], "DS_CON_001")

    @patch("entity_linker.count_relations_for_node")
    @patch("entity_linker.find_entity_candidates")
    def test_relation_context_can_resolve_ambiguity(self, find, count):
        find.return_value = [
            candidate("DS_CON_001"),
            candidate("OS_CON_001"),
        ]
        count.side_effect = [2, 0]

        result = link_entity(
            "栈",
            relation_type="HAS_OPERATION",
            direction="outgoing",
        )

        self.assertEqual(result["status"], "linked")
        self.assertEqual(result["resolution_method"], "relation_context")
        self.assertEqual(result["selected"]["node_id"], "DS_CON_001")

    @patch("entity_linker.find_entity_candidates")
    def test_keeps_equal_candidates_ambiguous(self, find):
        find.return_value = [
            candidate("DS_CON_001"),
            candidate("OS_CON_001"),
        ]

        result = link_entity("栈")

        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(len(result["candidates"]), 2)


if __name__ == "__main__":
    unittest.main()
