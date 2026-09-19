import json
import unittest
from copy import deepcopy

from import_unified_neo4j import PACKAGE, prepare, read_rows


class ImportValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
        cls.source_nodes = read_rows("nodes.jsonl")
        cls.source_edges = read_rows("edges.jsonl")
        cls.nodes, cls.edges = prepare(cls.manifest, cls.source_nodes, cls.source_edges)

    def test_entire_package_uses_neo4j_property_values(self):
        for props in self.nodes + [r["props"] for rows in self.edges.values() for r in rows]:
            for value in props.values():
                self.assertIsInstance(value, (str, bool, int, float, list))
                if isinstance(value, list):
                    self.assertTrue(all(isinstance(v, str) for v in value))

    def test_raw_content_survives_property_conversion(self):
        converted = {n["node_id"]: n for n in self.nodes}
        for original in self.source_nodes:
            self.assertEqual(json.loads(converted[original["node_id"]]["properties_json"]), original["properties"])
        converted_edges = {r["props"]["edge_id"]: r["props"] for rows in self.edges.values() for r in rows}
        for original in self.source_edges:
            self.assertEqual(json.loads(converted_edges[original["edge_id"]]["properties_json"]), original["properties"])
            self.assertEqual(converted_edges[original["edge_id"]]["direction"], original["direction"])

    def test_unlabeled_semantic_links_do_not_gain_invented_meanings(self):
        unnamed = [r["props"] for r in self.edges["SEMANTIC_LINK"] if r["props"].get("relation_status") == "unlabeled"]
        self.assertGreaterEqual(len(unnamed), 194)
        self.assertTrue(all(not p.get("relation_text") for p in unnamed))
        self.assertTrue(all(not p.get("reason") for p in unnamed))

    def test_bad_endpoint_rejected_before_any_database_write(self):
        edge = deepcopy(self.source_edges[0])
        edge["tail"] = "DOES_NOT_EXIST"
        with self.assertRaisesRegex(ValueError, "endpoint"):
            prepare(self.manifest, self.source_nodes, [edge])

    def test_dynamic_type_injection_rejected(self):
        edge = deepcopy(self.source_edges[0])
        edge["relation_type"] = "X`]->(n) DELETE n //"
        with self.assertRaisesRegex(ValueError, "relation type"):
            prepare(self.manifest, self.source_nodes, [edge])

    def test_duplicate_ids_rejected(self):
        with self.assertRaisesRegex(ValueError, "Duplicate node"):
            prepare(self.manifest, self.source_nodes + self.source_nodes[:1], [])
        with self.assertRaisesRegex(ValueError, "Duplicate edge"):
            prepare(self.manifest, self.source_nodes, self.source_edges[:1] * 2)


if __name__ == "__main__":
    unittest.main()
