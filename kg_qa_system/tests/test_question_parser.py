"""问题解析器的离线单元测试。"""

import os
import unittest


# 模块初始化需要配置项；单元测试不会真的访问这些地址。
os.environ.setdefault("DASHSCOPE_API_KEY", "unit-test-key")
os.environ.setdefault(
    "DASHSCOPE_BASE_URL",
    "https://example.invalid/v1",
)

from question_parser import (  # noqa: E402
    detect_relation_by_rule,
    validate_parse_result,
)


class RelationRuleTests(unittest.TestCase):
    def test_detects_outgoing_operation_relation(self):
        result = detect_relation_by_rule("栈有哪些操作？")

        self.assertEqual(
            result,
            {
                "relation_type": "HAS_OPERATION",
                "direction": "outgoing",
            },
        )

    def test_distinguishes_prerequisite_direction(self):
        incoming = detect_relation_by_rule("虚拟内存需要先学什么？")
        outgoing = detect_relation_by_rule("数据结构是谁的前置？")

        self.assertEqual(incoming["direction"], "incoming")
        self.assertEqual(outgoing["direction"], "outgoing")

    def test_returns_none_without_explicit_relation(self):
        self.assertIsNone(detect_relation_by_rule("什么是虚拟内存？"))


class ParseValidationTests(unittest.TestCase):
    def test_normalizes_and_deduplicates_result(self):
        result = validate_parse_result(
            {
                "entities": [" 栈 ", "栈"],
                "anchor_entity": None,
                "relation_type": None,
                "direction": "incoming",
                "question_type": "unknown",
                "complexity": "unknown",
            }
        )

        self.assertEqual(result["entities"], ["栈"])
        self.assertEqual(result["anchor_entity"], "栈")
        self.assertEqual(result["question_type"], "general")
        self.assertEqual(result["complexity"], "simple")
        self.assertIsNone(result["direction"])

    def test_rejects_relation_outside_whitelist(self):
        with self.assertRaisesRegex(ValueError, "不存在的关系"):
            validate_parse_result(
                {
                    "entities": ["栈"],
                    "anchor_entity": "栈",
                    "relation_type": "MADE_UP_RELATION",
                    "direction": "outgoing",
                }
            )


if __name__ == "__main__":
    unittest.main()
