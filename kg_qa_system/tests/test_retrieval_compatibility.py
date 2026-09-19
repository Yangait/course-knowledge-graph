"""旧图谱、新导图及聚焦问答的兼容性回归测试；不调用外部模型。"""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("DASHSCOPE_API_KEY", "unit-test-key")
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USERNAME", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "unit-test-password")

from qa_system import answer_question, source_companions
from entity_linker import link_entity
from answer_generator import generate_answer


def node(node_id, course="C09", origin="emmx"):
    return dict(node_id=node_id, name="虚拟内存", course_id=course,
                course="操作系统" if course == "C09" else "嵌入式系统", origin=origin,
                match_score=100, importance=0)


class RetrievalCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.mocks = {}
        for name in ("parse_question", "link_entity", "query_related_nodes",
                     "query_entity_context", "generate_answer", "find_entity_candidates"):
            patcher = patch("qa_system." + name)
            self.mocks[name] = patcher.start()
            self.addCleanup(patcher.stop)
        self.mocks["parse_question"].return_value = dict(
            anchor_entity="虚拟内存", entities=["虚拟内存"],
            relation_type="PREREQUISITE_OF", direction="incoming", complexity="simple")
        self.mocks["generate_answer"].return_value = dict(
            answer="测试回答", answer_mode="hybrid", model="test", total_tokens=0)
        self.mocks["find_entity_candidates"].return_value = []
        self.mocks["query_related_nodes"].return_value = []
        self.mocks["query_entity_context"].side_effect = lambda node_id, limit: [
            dict(node(node_id), evidence_type="entity_context", relationships=[])]

    def test_third_legacy_candidate_is_searched_without_faking_prerequisites(self):
        candidates = [node("C09:K:584"), node("C19:K:1538", "C19"),
                      node("LEGACY:OS_CON_065", origin="legacy")]
        self.mocks["link_entity"].return_value = dict(status="ambiguous", candidates=candidates)

        def related(node_id, relation_type, direction):
            if node_id.startswith("LEGACY:") and relation_type == "USES":
                return [dict(anchor_node_id=node_id, related_name="局部性原理",
                             relation_type="USES", direction="outgoing")]
            return []

        self.mocks["query_related_nodes"].side_effect = related
        result = answer_question("虚拟内存需要先学什么？")
        dependencies = [r for r in result["graph_results"] if r.get("evidence_role") == "dependency_context"]
        self.assertEqual(len(dependencies), 1)
        self.assertEqual(dependencies[0]["related_name"], "局部性原理")
        self.assertEqual(dependencies[0]["relation_type"], "USES")
        self.assertTrue(result["parsed_result"]["retrieval_notes"])

    def test_confirmed_prerequisite_does_not_trigger_dependency_fallback(self):
        self.mocks["link_entity"].return_value = dict(
            status="linked", selected=node("old"), candidates=[])
        self.mocks["query_related_nodes"].return_value = [dict(
            anchor_node_id="old", related_name="逻辑地址", relation_type="PREREQUISITE_OF")]
        result = answer_question("需要先学什么？")
        self.assertEqual(len(result["graph_results"]), 1)
        self.mocks["query_related_nodes"].assert_called_once_with(
            node_id="old", relation_type="PREREQUISITE_OF", direction="incoming")

    def test_focused_node_can_reference_legacy_from_same_course_only(self):
        focused = node("C09:K:584")
        self.mocks["query_entity_context"].side_effect = None
        self.mocks["query_entity_context"].return_value = [dict(focused, evidence_type="entity_context")]
        self.mocks["find_entity_candidates"].return_value = [focused,
            node("legacy_os", origin="legacy"), node("legacy_other", "C19", "legacy")]
        result = answer_question("需要先学什么？", focused_node_id=focused["node_id"])
        queried = {call.kwargs["node_id"] for call in self.mocks["query_related_nodes"].call_args_list}
        self.assertEqual(queried, {"C09:K:584", "legacy_os"})
        self.assertEqual(result["linked_result"]["status"], "focused")
        self.mocks["link_entity"].assert_not_called()

    def test_companions_are_exact_same_course_separate_sources(self):
        selected = node("native")
        same = node("legacy", origin="legacy")
        other = node("other", "C19", "legacy")
        fuzzy = dict(node("fuzzy", origin="legacy"), name="页式虚拟内存")
        self.assertEqual(source_companions(selected, [same, other, fuzzy, selected]), [same])

    def test_relation_endpoint_does_not_suppress_its_requested_context(self):
        self.mocks["parse_question"].return_value.update(entities=["虚拟内存", "局部性原理"])
        self.mocks["link_entity"].side_effect = [
            dict(status="linked", selected=node("memory"), candidates=[]),
            dict(status="linked", selected=dict(node_id="locality"), candidates=[])]
        self.mocks["query_related_nodes"].return_value = [dict(
            anchor_node_id="memory", related_node_id="locality", relation_type="PREREQUISITE_OF")]
        answer_question("虚拟内存和局部性原理有什么关系？")
        self.mocks["query_entity_context"].assert_called_once_with(node_id="locality", limit=6)


class LinkingCompatibilityTests(unittest.TestCase):
    @patch("entity_linker.count_relations_for_node", side_effect=[0, 8])
    @patch("entity_linker.find_entity_candidates")
    def test_fuzzy_entity_with_more_relations_does_not_replace_exact_match(self, find, count):
        find.return_value = [node("exact"), dict(node("fuzzy"), name="页式虚拟内存", match_score=60)]
        result = link_entity("虚拟内存", "PREREQUISITE_OF", "incoming")
        self.assertEqual(result["selected"]["node_id"], "exact")

    @patch("entity_linker.find_entity_candidates")
    def test_original_importance_breaks_same_name_tie(self, find):
        find.return_value = [node("native"), dict(node("legacy", origin="legacy"), importance=5)]
        self.assertEqual(link_entity("虚拟内存")["selected"]["node_id"], "legacy")


class AnswerEvidenceTests(unittest.TestCase):
    @patch("answer_generator.client")
    def test_model_receives_readable_relations_and_dependency_boundary(self, client):
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="建议先理解局部性原理。"))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=10, total_tokens=20))
        evidence = [dict(anchor_node_id="LEGACY:OS_CON_065", anchor_name="虚拟内存",
            related_name="局部性原理", relation_type="USES", direction="outgoing",
            origin="legacy_csv", evidence_role="dependency_context")]
        generate_answer("需要先学什么？", dict(relation_type="PREREQUISITE_OF", direction="incoming"), evidence)
        prompt = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
        self.assertIn("使用或依赖", prompt)
        self.assertIn("不能当作明确先修关系", prompt)
        self.assertIn("原有知识图谱", prompt)
        for code in ("PREREQUISITE_OF", "USES", "LEGACY:OS_CON_065", "legacy_csv"):
            self.assertNotIn(code, prompt)
        self.assertEqual(evidence[0]["relation_type"], "USES")


if __name__ == "__main__":
    unittest.main()
