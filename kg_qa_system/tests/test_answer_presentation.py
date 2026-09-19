import unittest
from answer_presentation import present_answer, prepare_history


class AnswerPresentationTests(unittest.TestCase):
    def test_both_reported_openings_become_direct_answers(self):
        body = "1. **加速检索**：避免全表扫描。\n2. 排序。"
        for opening in (
            '“这有什么用”通常指代前文提到的**数据库索引**。其核心作用如下：\n\n',
            '“这”指代前文讨论的**数据库索引**，其核心作用如下：\n\n',
        ):
            result = present_answer(opening + body, "这有什么用")
            self.assertEqual(result, "**数据库索引**的核心作用如下：\n\n" + body)

    def test_list_and_pronoun_sentence_retain_substantive_content(self):
        self.assertEqual(present_answer("它指的是上文提到的栈。它支持进栈。", "它有哪些操作"), "栈支持进栈。")
        self.assertEqual(present_answer("这个指代之前介绍的索引。1. 加速查询", "有什么用"), "索引：\n\n1. 加速查询")

    def test_explicit_pronoun_question_and_rewriting_are_unchanged(self):
        answer = "“这”指代前文讨论的数据库索引。其作用如下：加速查询。"
        for question in ("这指的是什么？", "解释这个代词的指代", "请逐字引用原文", "分析这句话的语法"):
            self.assertEqual(present_answer(answer, question), answer)

    def test_clarification_technical_explanation_and_code_are_unchanged(self):
        for answer in (
            "你指的是索引还是事务？",
            "“这”指代前文讨论的索引或是事务。其作用不同。",
            "指针指的是保存内存地址的变量。解题步骤如下：\n1. 获取地址。",
            "```python\n# 这指代前文讨论的对象\nprint('hello')\n```",
            "数据库索引主要用于加速查询。",
            "例如：‘这’指代前文讨论的对象。",
        ):
            self.assertEqual(present_answer(answer, "请解释"), answer)

    def test_history_copy_preserves_original_and_user_text(self):
        raw = "“这”指代前文讨论的数据库索引，其核心作用如下：加速查询。"
        original = [dict(role="user", content="这有什么用"), dict(role="assistant", content=raw)]
        prepared = prepare_history(original)
        self.assertEqual(prepared[1]["content"], "数据库索引的核心作用如下：加速查询。")
        self.assertEqual(original[1]["content"], raw)
        self.assertEqual(prepared[0], original[0])


if __name__ == "__main__":
    unittest.main()
