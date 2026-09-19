"""会话持久化、隔离、重试和模型上下文的回归测试。"""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("DASHSCOPE_API_KEY", "test")
os.environ.setdefault("DASHSCOPE_BASE_URL", "https://example.invalid/v1")
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USERNAME", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")

from fastapi.testclient import TestClient
from neo4j.exceptions import ServiceUnavailable
from api import app
import chat_store
from qa_system import answer_question
from question_parser import parse_question
from answer_generator import generate_answer


ANSWER = dict(answer="虚拟内存通过地址映射提供独立的地址空间。", answer_mode="llm_only", model="test", total_tokens=12, graph_results=[])
HISTORY = [dict(role="user", content="什么是虚拟内存？"), dict(role="assistant", content="虚拟内存是一种内存管理机制。")]


class ChatHistoryTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        patcher = patch("chat_store.DB_PATH", Path(directory.name) / "chats.sqlite3")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(app)
        self.chat = self.client.post("/api/conversations").json()["id"]

    def ask(self, question="什么是虚拟内存？", request_id="request_0000000001", chat=None):
        return self.client.post("/api/ask", json=dict(question=question, conversation_id=chat or self.chat, request_id=request_id))

    @patch("api.answer_question", return_value=ANSWER)
    def test_history_survives_new_client_and_is_passed_to_next_turn(self, answer):
        self.assertEqual(self.ask().status_code, 200)
        reopened = TestClient(app)
        reopened.cookies.update(self.client.cookies)
        loaded = reopened.get("/api/conversations/" + self.chat).json()
        self.assertEqual([m["role"] for m in loaded["messages"]], ["user", "assistant"])
        self.assertEqual(loaded["messages"][1]["content"], ANSWER["answer"])
        self.assertEqual(loaded["title"], "什么是虚拟内存？")
        self.assertEqual(self.ask("它有什么优点？", "request_0000000002").status_code, 200)
        history = answer.call_args.kwargs["history"]
        self.assertEqual(history[0]["content"], "什么是虚拟内存？")
        self.assertEqual(history[1]["content"], ANSWER["answer"])

    @patch("api.answer_question", return_value=ANSWER)
    def test_new_chat_has_no_previous_context(self, answer):
        self.ask()
        second = self.client.post("/api/conversations").json()["id"]
        self.ask("今天聊什么？", chat=second)
        self.assertNotIn("history", answer.call_args.kwargs)

    @patch("api.answer_question", return_value=ANSWER)
    def test_other_browser_cannot_read_modify_delete_or_ask_in_chat(self, answer):
        stranger = TestClient(app)
        self.assertEqual(stranger.get("/api/conversations").json()["conversations"], [])
        url = "/api/conversations/" + self.chat
        self.assertEqual(stranger.get(url).status_code, 404)
        self.assertEqual(stranger.patch(url, json={"title":"changed"}).status_code, 404)
        self.assertEqual(stranger.delete(url).status_code, 404)
        self.assertEqual(stranger.post("/api/ask", json={"conversation_id":self.chat,"question":"偷看历史"}).status_code, 404)
        answer.assert_not_called()

    @patch("api.answer_question", return_value=ANSWER)
    def test_retry_same_request_saves_and_calls_model_only_once(self, answer):
        first, second = self.ask(), self.ask()
        self.assertEqual(first.json(), second.json())
        answer.assert_called_once()
        self.assertEqual(len(self.client.get("/api/conversations/"+self.chat).json()["messages"]), 2)

    @patch("api.answer_question", side_effect=[RuntimeError("failed"), ANSWER])
    def test_failed_answer_releases_lock_without_polluting_history(self, answer):
        self.assertEqual(self.ask().status_code, 502)
        self.assertEqual(self.client.get("/api/conversations/"+self.chat).json()["messages"], [])
        self.assertEqual(self.ask().status_code, 200)
        self.assertNotIn("history", answer.call_args.kwargs)

    def test_busy_conversation_rejects_overlapping_turn_and_delete(self):
        owner = chat_store.owner_key(self.client.cookies[chat_store.COOKIE_NAME])
        token, _, _ = chat_store.begin_turn(owner, self.chat, "running")
        self.assertEqual(self.ask().status_code, 409)
        self.assertEqual(self.client.delete("/api/conversations/"+self.chat).status_code, 409)
        chat_store.release_turn(owner, self.chat, token)

    @patch("api.answer_question", return_value=ANSWER)
    def test_rename_and_delete_persist(self, answer):
        self.ask()
        url = "/api/conversations/" + self.chat
        self.assertEqual(self.client.patch(url, json={"title":"内存学习"}).status_code, 200)
        self.assertEqual(self.client.get(url).json()["title"], "内存学习")
        self.assertEqual(self.client.delete(url).status_code, 200)
        self.assertEqual(self.client.get(url).status_code, 404)
        with chat_store.database() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM exchanges").fetchone()[0], 0)

    @patch("api.answer_question", return_value=ANSWER)
    def test_full_history_is_saved_while_context_is_bounded(self, answer):
        for i in range(12):
            self.assertEqual(self.ask(str(i), f"request_{i:016d}").status_code, 200)
        self.assertEqual(len(answer.call_args.kwargs["history"]), 20)
        self.assertEqual(len(self.client.get("/api/conversations/"+self.chat).json()["messages"]), 24)

    @patch("api.answer_question")
    def test_old_analysis_opening_is_normalized_on_read_without_rewriting_database(self, answer):
        raw = "“这”指代前文讨论的数据库索引，其核心作用如下：加速检索。"
        answer.return_value = dict(ANSWER, answer=raw)
        self.ask("这有什么用")
        loaded = self.client.get("/api/conversations/"+self.chat).json()
        shown = loaded["messages"][1]
        self.assertEqual(shown["content"], "数据库索引的核心作用如下：加速检索。")
        self.assertEqual(shown["result"]["answer"], shown["content"])
        with chat_store.database() as db:
            stored = db.execute("SELECT response FROM exchanges WHERE conversation_id=?", (self.chat,)).fetchone()[0]
            self.assertEqual(json.loads(stored)["answer"], raw)
        self.ask("说详细一点", "request_0000000002")
        self.assertEqual(answer.call_args.kwargs["history"][1]["content"], shown["content"])


class ContextModelTests(unittest.TestCase):
    def setUp(self):
        patcher = patch("qa_system.resolve_request", return_value=dict(
            status="resolved", question="虚拟内存有哪些优点？", clarification="", total_tokens=0))
        patcher.start()
        self.addCleanup(patcher.stop)

    @patch("qa_system.generate_answer", return_value=ANSWER)
    @patch("qa_system.link_entity", return_value={"status":"not_found"})
    @patch("qa_system.parse_question", return_value=dict(anchor_entity="虚拟内存",entities=[],relation_type=None,direction=None))
    def test_history_reaches_both_parser_and_answer_without_graph(self, parse, link, generate):
        result = answer_question("它有哪些优点？", history=HISTORY)
        parse.assert_called_once_with("虚拟内存有哪些优点？")
        self.assertEqual(generate.call_args.kwargs["user_question"], "虚拟内存有哪些优点？")
        self.assertEqual(generate.call_args.kwargs["history"], HISTORY)
        self.assertEqual(result["graph_results"], [])

    @patch("qa_system.generate_answer", return_value=ANSWER)
    @patch("qa_system.link_entity", side_effect=ServiceUnavailable("offline"))
    @patch("qa_system.parse_question", return_value=dict(anchor_entity="虚拟内存",entities=[],relation_type=None,direction=None))
    def test_graph_unavailable_still_generates_with_history(self, parse, link, generate):
        result = answer_question("它有哪些优点？", history=HISTORY)
        self.assertEqual(result["status"], "success")
        self.assertEqual(generate.call_args.kwargs["history"], HISTORY)
        self.assertEqual(generate.call_args.kwargs["graph_results"], [])

    @patch("question_parser.client")
    def test_parser_receives_history_and_returns_resolved_entity(self, client):
        parsed = dict(anchor_entity="虚拟内存", entities=["虚拟内存"], relation_type=None, direction=None)
        client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(parsed)))])
        result = parse_question("它有哪些优点？", history=HISTORY)
        messages = client.chat.completions.create.call_args.kwargs["messages"]
        self.assertIn("什么是虚拟内存", messages[1]["content"])
        self.assertEqual(result["anchor_entity"], "虚拟内存")

    @patch("answer_generator.client")
    def test_answer_uses_real_role_history_and_direct_fallback_policy(self, client):
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="它可以提供独立地址空间。"))],
            usage=SimpleNamespace(prompt_tokens=10,completion_tokens=10,total_tokens=20))
        generate_answer("它有哪些优点？", {}, [], history=HISTORY)
        messages = client.chat.completions.create.call_args.kwargs["messages"]
        self.assertEqual(messages[1:3], HISTORY)
        self.assertIn("直接回答", messages[0]["content"])
        self.assertIn("不要告诉用户", messages[0]["content"])
        self.assertIn("它有哪些优点", messages[-1]["content"])


if __name__ == "__main__":
    unittest.main()
