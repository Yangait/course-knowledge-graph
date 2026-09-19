import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("DASHSCOPE_API_KEY", "test")
os.environ.setdefault("DASHSCOPE_BASE_URL", "https://example.invalid/v1")
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USERNAME", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")

from conversation_context import resolve_request, validate_context
from qa_system import answer_question

HISTORY = [dict(role="user",content="数据库索引有什么作用？"),
           dict(role="assistant",content="数据库索引可以加速查询。")]


class ContextResolutionTests(unittest.TestCase):
    @patch("conversation_context.client")
    def test_standalone_without_history_needs_no_extra_model_call(self, client):
        result = resolve_request("解释数据库事务")
        self.assertEqual(result["question"], "解释数据库事务")
        client.chat.completions.create.assert_not_called()

    @patch("conversation_context.client")
    def test_resolution_uses_complete_history_and_preserves_request(self, client):
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(dict(
                status="resolved",question="数据库索引是干什么的？只写两条。",clarification=""))))],
            usage=SimpleNamespace(total_tokens=23))
        result = resolve_request("他是干什么的，只写两条", HISTORY)
        request = json.loads(client.chat.completions.create.call_args.kwargs["messages"][1]["content"])
        self.assertEqual(request["current_request"], "他是干什么的，只写两条")
        self.assertEqual(request["history"], HISTORY)
        self.assertEqual(result["question"], "数据库索引是干什么的？只写两条。")
        self.assertEqual(result["total_tokens"], 23)

    def test_invalid_resolution_cannot_silently_become_a_task(self):
        for result in (
            {}, {"status":"guessed","question":"索引"},
            {"status":"resolved","question":""},
            {"status":"resolved","question":"索引","clarification":"指什么"},
            {"status":"needs_clarification","question":"索引","clarification":"指什么"},
            {"status":"needs_clarification","question":"","clarification":""},
        ):
            with self.subTest(result=result), self.assertRaises(ValueError):
                validate_context(result)

    @patch("qa_system.generate_answer", return_value=dict(answer="直接答案",answer_mode="llm_only",model="test",total_tokens=10))
    @patch("qa_system.link_entity", return_value={"status":"not_found"})
    @patch("qa_system.parse_question", return_value=dict(anchor_entity="索引",entities=["索引"],relation_type=None,direction=None))
    @patch("qa_system.resolve_request", return_value=dict(status="resolved",question="数据库索引有什么作用？只写两条。",clarification="",total_tokens=5))
    def test_retrieval_and_generation_share_resolved_task(self, resolve, parse, link, generate):
        result = answer_question("他是干什么的，只写两条", history=HISTORY)
        parse.assert_called_once_with("数据库索引有什么作用？只写两条。")
        self.assertEqual(generate.call_args.kwargs["user_question"], parse.call_args.args[0])
        self.assertEqual(result["parsed_result"]["original_question"], "他是干什么的，只写两条")
        self.assertEqual(result["total_tokens"], 15)

    @patch("qa_system.generate_answer")
    @patch("qa_system.link_entity")
    @patch("qa_system.parse_question")
    @patch("qa_system.resolve_request", return_value=dict(status="needs_clarification",question="",clarification="你想问索引还是事务？",total_tokens=5))
    def test_real_ambiguity_asks_once_without_guessing_or_retrieving(self, resolve, parse, link, generate):
        result = answer_question("他有什么限制？", history=HISTORY)
        self.assertEqual(result["answer"], "你想问索引还是事务？")
        parse.assert_not_called()
        link.assert_not_called()
        generate.assert_not_called()

    @patch("qa_system.generate_answer", return_value=dict(answer="事务保证一组操作的完整执行。",answer_mode="llm_only",model="test",total_tokens=10))
    @patch("qa_system.link_entity", return_value={"status":"not_found"})
    @patch("qa_system.parse_question", return_value=dict(anchor_entity="事务",entities=["事务"],relation_type=None,direction=None))
    @patch("qa_system.resolve_request", return_value=dict(status="standalone",question="换个话题，解释数据库事务",clarification="",total_tokens=5))
    def test_new_topic_is_used_without_forcing_old_entity(self, resolve, parse, link, generate):
        answer_question("换个话题，解释数据库事务", history=HISTORY)
        self.assertIn("事务", parse.call_args.args[0])
        self.assertNotIn("索引", generate.call_args.kwargs["user_question"])


if __name__ == "__main__":
    unittest.main()
