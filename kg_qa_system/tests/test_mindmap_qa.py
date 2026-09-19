"""Selected diagram sources stay distinct from database identifiers and saved chats."""
import json
import os
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("DASHSCOPE_API_KEY", "test")
os.environ.setdefault("DASHSCOPE_BASE_URL", "https://example.invalid/v1")
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USERNAME", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")

from fastapi.testclient import TestClient
from neo4j.exceptions import ServiceUnavailable
from api import app, build_evidence
from answer_generator import generate_answer
from conversation_context import resolve_request
from mindmap_context import build_mindmap_context, graph_supplements, same_concept
from qa_system import answer_question
import chat_store

ANSWER = dict(answer="根据当前导图讲解。", answer_mode="hybrid", model="test", total_tokens=10, graph_results=[])


class DiagramSourceTests(unittest.TestCase):
    def test_high_math_uses_svg_structure_and_source(self):
        context = build_mindmap_context("C01:K:938")
        self.assertEqual(context["name"], "10.重积分")
        self.assertEqual(context["path"], "高等数学 > 10.重积分")
        self.assertEqual(context["source"], "知识导图svg/高等数学.svg")
        self.assertTrue({"二重积分", "三重积分", "重积分的应用"}.issubset({n["name"] for n in context["descendants"]}))

    def test_new_notes_and_descendant_text_reach_context(self):
        context = build_mindmap_context("C14:K:112")
        self.assertIn("重要的元素", context["notes"])
        self.assertTrue(any("软件危机" in n["text"] for n in context["descendants"]))
        self.assertLessEqual(len(json.dumps(context, ensure_ascii=False)), 22000)

    def test_compact_database_ids_and_root_cannot_import_full_edition(self):
        context = build_mindmap_context("SVG:C12:523")
        self.assertEqual(context["name"], "数据结构")
        self.assertEqual(context["path"], "数据库 > 数据结构")
        self.assertEqual({n["name"] for n in context["descendants"]}, {"树", "图"})
        root = build_mindmap_context("C12:K:101")
        self.assertTrue(all(n["node_id"].startswith("SVG:C12:") for n in root["descendants"]))
        self.assertNotIn("布尔型", json.dumps(root, ensure_ascii=False))
        # Old full-edition links remain available as their own EMMX source.
        full = build_mindmap_context("C12:K:523")
        self.assertEqual(full["name"], "布尔型")
        self.assertEqual(full["source"], "知识导图/数据库.emmx")

    def test_invalid_or_removed_sources_are_rejected_without_database_lookup(self):
        client = TestClient(app)
        for node in ("../../.env", "C01:K:does-not-exist", "M02:K:101"):
            self.assertEqual(client.get("/api/mindmap/node", params={"node_id": node}).status_code, 404)

    def test_id_equality_does_not_override_name_course_and_path(self):
        primary = dict(node_id="C12:K:523", name="数据结构", course_id="C12", path="数据库 > 数据结构")
        valid = dict(primary, node_id="different-id")
        self.assertTrue(same_concept(primary, valid))
        for candidate in (dict(primary, name="布尔型"), dict(primary, course_id="C07"),
                          dict(primary, path="数据库 > 另一章 > 数据结构"), dict(primary, path=None)):
            self.assertFalse(same_concept(primary, candidate))

    @patch("mindmap_context.query_entity_context")
    @patch("mindmap_context.find_entity_candidates")
    def test_only_verified_candidates_can_supply_database_context(self, find, query):
        primary = build_mindmap_context("SVG:C12:523")
        correct = dict(primary, node_id="verified-different-id", evidence_type="entity_context")
        find.return_value = [dict(correct, node_id=primary["node_id"], name="布尔型"), correct]
        query.return_value = [correct]
        result = graph_supplements(primary)
        query.assert_called_once_with("verified-different-id", limit=8)
        self.assertEqual(result[0]["display_node_id"], primary["node_id"])
        self.assertEqual(result[0]["evidence_role"], "verified_graph_supplement")

    @patch("qa_system.generate_answer", return_value=ANSWER)
    @patch("mindmap_context.find_entity_candidates", side_effect=ServiceUnavailable("offline"))
    @patch("qa_system.parse_question", return_value={"complexity": "simple"})
    @patch("qa_system.resolve_request", return_value=dict(status="resolved", question="解释高等数学的重积分", total_tokens=3))
    def test_database_failure_keeps_diagram_evidence_and_followup_focus(self, resolve, parse, find, generate):
        history = [dict(role="user", content="它是什么"), dict(role="assistant", content="重积分的说明")]
        result = answer_question("再举一个例子", mindmap_node_id="C01:K:938", history=history, answer_style="detailed")
        self.assertEqual(resolve.call_args.kwargs["focus"]["name"], "10.重积分")
        self.assertEqual(result["graph_results"][0]["evidence_type"], "mindmap_context")
        self.assertEqual(generate.call_args.kwargs["history"], history)
        self.assertEqual(generate.call_args.kwargs["answer_style"], "detailed")
        self.assertEqual(result["total_tokens"], 13)

    @patch("conversation_context.client")
    def test_first_pronoun_question_has_selected_source_without_fake_chat_history(self, client):
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(dict(
                status="resolved", question="请解释高等数学中的重积分", clarification=""))))],
            usage=SimpleNamespace(total_tokens=2))
        focus = dict(name="10.重积分", course="高等数学", path="高等数学 > 10.重积分")
        resolve_request("解释一下它", focus=focus)
        payload = json.loads(client.chat.completions.create.call_args.kwargs["messages"][1]["content"])
        self.assertEqual(payload["selected_mindmap_topic"], focus)
        self.assertEqual(payload["history"], [])
        self.assertEqual(payload["current_request"], "解释一下它")

    @patch("answer_generator.client")
    def test_long_diagram_notes_and_source_priority_reach_answer_model(self, client):
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="说明"))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=10, total_tokens=20))
        primary = build_mindmap_context("C14:K:112")
        primary["notes"] = "这是新导图的备注。" * 150 + "备注结尾必须保留"
        generate_answer("详细解释", {}, [primary])
        messages = client.chat.completions.create.call_args.kwargs["messages"]
        self.assertIn("备注结尾必须保留", messages[-1]["content"])
        self.assertIn("主要资料", messages[-1]["content"])
        self.assertIn("不能用旧版的内容替换当前导图", messages[0]["content"])
        self.assertNotIn(primary["node_id"], messages[-1]["content"])
        evidence = build_evidence([primary])[0]
        self.assertEqual(evidence.context_source, "mindmap")
        self.assertEqual(evidence.node_id, primary["node_id"])


class DiagramChatTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "chats.sqlite3"
        patcher = patch("chat_store.DB_PATH", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(app)

    @patch("api.node_record", side_effect=AssertionError("Must not resolve a diagram ID as a database ID"))
    @patch("api.answer_question", return_value=ANSWER)
    def test_new_diagram_chat_persists_source_and_cancel_restores_normal_qa(self, answer, lookup):
        chat = self.client.post("/api/conversations").json()["id"]
        payload = dict(question="解释一下它", conversation_id=chat, request_id="diagram_request_0001",
                       node_id="SVG:C12:523", context_source="mindmap")
        self.assertEqual(self.client.post("/api/ask", json=payload).status_code, 200)
        self.assertEqual(answer.call_args.kwargs["mindmap_node_id"], "SVG:C12:523")
        reopened = TestClient(app)
        reopened.cookies.update(self.client.cookies)
        saved = reopened.get("/api/conversations/" + chat).json()
        self.assertEqual(saved["context_source"], "mindmap")
        self.assertEqual(saved["node_id"], "SVG:C12:523")
        payload.update(question="举例", request_id="diagram_request_0002")
        self.assertEqual(reopened.post("/api/ask", json=payload).status_code, 200)
        self.assertEqual(len(answer.call_args.kwargs["history"]), 2)
        payload.update(question="换个话题", request_id="diagram_request_0003", node_id=None, context_source="knowledge_graph")
        self.assertEqual(reopened.post("/api/ask", json=payload).status_code, 200)
        self.assertNotIn("mindmap_node_id", answer.call_args.kwargs)
        saved = reopened.get("/api/conversations/" + chat).json()
        self.assertIsNone(saved["node_id"])
        self.assertEqual(len(saved["messages"]), 6)

    @patch("api.answer_question")
    def test_invalid_source_or_course_never_calls_model(self, answer):
        for payload, status in [
            (dict(question="解释", context_source="mindmap"), 422),
            (dict(question="解释", context_source="mindmap", node_id="C01:K:no"), 404),
            (dict(question="解释", context_source="mindmap", node_id="C01:K:938", course_id="C14"), 404),
            (dict(question="解释", context_source="untrusted", node_id="C01:K:938"), 422),
        ]:
            self.assertEqual(self.client.post("/api/ask", json=payload).status_code, status)
        answer.assert_not_called()

    def test_old_history_migration_keeps_existing_records_and_graph_source(self):
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY, owner TEXT, title TEXT, created_at REAL, updated_at REAL, course_id TEXT, node_id TEXT, busy_token TEXT, busy_until REAL DEFAULT 0)")
            db.execute("INSERT INTO conversations VALUES ('old-chat', 'owner', '原来的聊天', 1, 1, 'C01', 'C01:K:938', NULL, 0)")
        db.close()
        old = chat_store.get_chat("owner", "old-chat")
        self.assertEqual(old["title"], "原来的聊天")
        self.assertEqual(old["node_id"], "C01:K:938")
        self.assertEqual(old["context_source"], "knowledge_graph")


if __name__ == "__main__":
    unittest.main()
