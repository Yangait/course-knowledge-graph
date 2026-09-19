"""Regressions for new EMMX notes, media and stable question links."""
import hashlib
import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from api import app
from graph_routes import MINDMAP_PACKAGE, course_data, local_node
from unified_graph import PACKAGE


class MindmapConversionTests(unittest.TestCase):
    def test_original_svg_is_served_unchanged_and_all_main_nodes_are_clickable(self):
        client = TestClient(app)
        course = client.get("/api/graph/courses/C01").json()
        original = course["original_map"]
        self.assertEqual(original["main_nodes_mapped"], 544)
        ids = {h["id"] for h in original["hotspots"]}
        self.assertTrue({n["id"] for n in course["knowledge_nodes"]}.issubset(ids))
        response = client.get(original["url"])
        self.assertEqual(response.status_code, 200)
        source = PACKAGE.parent / "知识导图svg" / "高等数学.svg"
        self.assertEqual(response.content, source.read_bytes())
        self.assertEqual(hashlib.sha256(response.content).hexdigest(), original["sha256"])
        self.assertIn("sandbox", response.headers["content-security-policy"])
        self.assertEqual(client.get("/api/graph/courses/M02/original.svg").status_code, 404)
        self.assertNotIn("original_map", client.get("/api/graph/courses/M02").json())

    def test_all_27_original_maps_and_media_preserve_their_sources(self):
        client = TestClient(app)
        manifest = client.get("/api/graph/courses").json()
        count = 0
        for entry in manifest["courses"] + manifest["overviews"]:
            data = client.get("/api/graph/courses/" + entry["course_id"]).json()
            original = data.get("original_map")
            if not original:
                continue
            count += 1
            source = PACKAGE.parent / original["source_file"]
            self.assertEqual((MINDMAP_PACKAGE / "original" / original["file"]).read_bytes(), source.read_bytes())
            ids = {h["id"] for h in original["hotspots"]}
            self.assertEqual(len(ids), len(original["hotspots"]))
            if not original["separate_edition"]:
                self.assertTrue({n["id"] for n in data["knowledge_nodes"]}.issubset(ids))
            for h in original["hotspots"]:
                self.assertGreaterEqual(h["x"], 0)
                self.assertGreaterEqual(h["y"], 0)
                self.assertLessEqual(h["x"]+h["width"], original["width"])
                self.assertLessEqual(h["y"]+h["height"], original["height"])
        self.assertEqual(count, 27)

    def test_database_compact_source_ids_never_alias_full_course_ids(self):
        client = TestClient(app)
        original = client.get("/api/graph/courses/C12").json()["original_map"]
        self.assertTrue(original["separate_edition"])
        self.assertEqual(original["main_nodes_mapped"], 1)
        new = client.get("/api/graph/node", params={"node_id": "SVG:C12:523"}).json()
        self.assertEqual(new["node"]["name"], "数据结构")
        self.assertFalse(new["node"]["searchable"])
        self.assertIn("数据结构", new["question_prompt"])
        self.assertNotEqual(new["node"]["name"], local_node("C12:K:523")["node"]["name"])
        self.assertTrue(new["relationships"])

    def test_expanded_svg_canvas_preserves_drawing_and_gzip_negotiation(self):
        import xml.etree.ElementTree as ET
        client = TestClient(app)
        for cid in ["C09", "C10", "C11", "C16"]:
            original = client.get(f"/api/graph/courses/{cid}").json()["original_map"]
            source = ET.fromstring((PACKAGE.parent / original["source_file"]).read_bytes())
            expanded = ET.fromstring((MINDMAP_PACKAGE / "original" / original["display_file"]).read_bytes())
            self.assertTrue(original["canvas_expanded"])
            self.assertEqual([ET.tostring(e) for e in source], [ET.tostring(e) for e in expanded])
        original = client.get("/api/graph/courses/C09").json()["original_map"]
        gz = client.get(original["url"], headers={"accept-encoding": "gzip"})
        identity = client.get(original["url"], headers={"accept-encoding": "gzip;q=0"})
        self.assertEqual(gz.content, identity.content)
        self.assertEqual(gz.headers["content-encoding"], "gzip")
        self.assertNotIn("content-encoding", identity.headers)
        self.assertEqual(hashlib.sha256(gz.content).hexdigest(), original["display_sha256"])

    def test_unregistered_svg_and_source_topic_are_not_exposed(self):
        client = TestClient(app)
        self.assertEqual(client.get("/api/graph/courses/not-a-course/original.svg").status_code, 404)
        from graph_routes import original_map
        self.assertIsNone(original_map("../../kg_qa_system/.env"))

    def test_every_original_node_id_and_hierarchy_is_retained(self):
        for path in (PACKAGE / "courses").glob("*.json"):
            old = json.loads(path.read_text(encoding="utf-8"))
            new = course_data(old["meta"]["course_id"])
            self.assertEqual({n["id"] for n in old["knowledge_nodes"]},
                             {n["id"] for n in new["knowledge_nodes"]})
            self.assertEqual(old["hierarchy_relations"], new["hierarchy_relations"])
            self.assertEqual([(r["source_id"], r["target_id"], r["direction"]) for r in old["semantic_relations"]],
                             [(r["source_id"], r["target_id"], r["direction"]) for r in new["semantic_relations"]])

    def test_all_images_resolve_and_match_the_archive_hash(self):
        count = 0
        for path in (MINDMAP_PACKAGE / "courses").glob("*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            for image in data["images"]:
                location = (MINDMAP_PACKAGE / image["file"]).resolve()
                self.assertTrue(location.is_relative_to(MINDMAP_PACKAGE.resolve()))
                self.assertEqual(hashlib.sha256(location.read_bytes()).hexdigest(), image["sha256"])
                count += 1
        self.assertEqual(count, 1956)

    def test_notes_are_separate_from_short_node_titles(self):
        data = local_node("C17:K:106")
        self.assertEqual(data["node"]["name"], "定义")
        self.assertIn("海量数据", data["details"]["note_text"])
        self.assertTrue(data["node"]["searchable"])

    @patch("graph_routes.neighbors", return_value=[])
    def test_inline_note_picture_can_be_loaded_through_its_owner(self, _):
        course = course_data("C18")
        image = next(i for i in course["images"] if i.get("placement") == "note")
        client = TestClient(app)
        data = client.get("/api/graph/node", params={"node_id": image["owner_id"]}).json()
        picture = next(i for i in data["images"] if i["id"] == image["id"])
        response = client.get(picture["url"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(hashlib.sha256(response.content).hexdigest(), image["sha256"])

    @patch("graph_routes.neighbors", return_value=[dict(related_node_id="LEGACY:sample", related_name="前置知识",
            related_course_id="C07", relation_type="PREREQUISITE_OF", direction="incoming", relation_text=None)])
    def test_existing_neo4j_relations_remain_visible(self, _):
        data = TestClient(app).get("/api/graph/node", params={"node_id": "C07:K:101"}).json()
        self.assertIn("PREREQUISITE_OF", [r["relation_type"] for r in data["relationships"]])

    def test_binary_only_course_is_honestly_marked_as_compatibility_copy(self):
        self.assertEqual(course_data("C01")["meta"]["conversion_status"], "compatibility_copy")
        self.assertIn("尚未完整解析", course_data("C01")["meta"]["conversion_note"])

    def test_course_overview_has_resolvable_relations(self):
        client = TestClient(app)
        overview = client.get("/api/graph/courses").json()["overviews"]
        self.assertEqual([item["course_id"] for item in overview], ["M01"])
        for entry in overview:
            data = client.get("/api/graph/courses/" + entry["course_id"]).json()
            ids = {n["id"] for n in data["knowledge_nodes"]}
            for rel in data["semantic_relations"]:
                self.assertIn(rel["source_id"], ids)
                self.assertIn(rel["target_id"], ids)
            detail = client.get("/api/graph/node", params={"node_id": entry["root_id"]}).json()
            self.assertFalse(detail["node"]["searchable"])


if __name__ == "__main__":
    unittest.main()
