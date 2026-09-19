"""Answer capacity is independent of model routing and preserves user constraints."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("DASHSCOPE_API_KEY", "unit-test-key")
os.environ.setdefault("DASHSCOPE_BASE_URL", "https://example.invalid/v1")

from answer_generator import generate_answer, fast_model, strong_model


class AnswerDepthTests(unittest.TestCase):
    @patch("answer_generator.client")
    def test_selected_style_reaches_model_without_changing_question(self, client):
        from answer_generator import ANSWER_STYLES
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="回答"))],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=10, total_tokens=110),
        )
        for style, instruction in ANSWER_STYLES.items():
            with self.subTest(style=style):
                generate_answer("只用两句话解释栈", {}, [], answer_style=style)
                prompt = client.chat.completions.create.call_args.kwargs["messages"][-1]["content"]
                self.assertIn(instruction, prompt)
                self.assertIn("只用两句话解释栈", prompt)
                self.assertIn("字数、条数或格式优先", prompt)

    @patch("answer_generator.client")
    def test_simple_topic_has_room_for_a_full_lesson_without_changing_model(self, client):
        long_answer = "详细讲解及逐步示例。" * 350
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=long_answer))],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=4000, total_tokens=4100),
        )
        result = generate_answer("从零开始详细解释B树", {"complexity": "simple"}, [])
        call = client.chat.completions.create.call_args.kwargs
        self.assertEqual(call["model"], fast_model)
        self.assertFalse(call["extra_body"]["enable_thinking"])
        self.assertGreaterEqual(call["max_tokens"], 6000)
        self.assertEqual(result["answer"], long_answer)

    @patch("answer_generator.client")
    def test_current_length_constraint_and_history_reach_the_selected_model(self, client):
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="第一句。第二句。"))],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=10, total_tokens=110),
        )
        history = [{"role": "user", "content": "详细解释B树"},
                   {"role": "assistant", "content": "B树是多路平衡查找树。"}]
        result = generate_answer("只用两句话总结B树", {"complexity": "complex"}, [], history)
        call = client.chat.completions.create.call_args.kwargs
        self.assertEqual(call["model"], strong_model)
        self.assertEqual(call["messages"][1:3], history)
        self.assertIn("只用两句话总结B树", call["messages"][-1]["content"])
        self.assertEqual(result["answer"], "第一句。第二句。")


if __name__ == "__main__":
    unittest.main()
