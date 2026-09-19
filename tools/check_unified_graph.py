"""Independently reconcile generated artifacts against all input records."""
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "unified_kg"


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def lines(name):
    # Some source labels contain Unicode paragraph separators; only LF delimits JSONL.
    with (PACKAGE / name).open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream]


def check():
    manifest = read(PACKAGE / "manifest.json")
    all_nodes, all_edges = lines("nodes.jsonl"), lines("edges.jsonl")
    nodes = {n["node_id"]: n for n in all_nodes}
    edges = {e["edge_id"]: e for e in all_edges}
    assert len(nodes) == len(all_nodes) == manifest["statistics"]["nodes"]
    assert len(edges) == len(all_edges) == manifest["statistics"]["edges"]
    assert all(e["head"] in nodes and e["tail"] in nodes for e in all_edges)
    media_base = (PACKAGE / manifest["media_base_relative_to_manifest"]).resolve()
    preserved_nodes, preserved_edges = 0, 0
    for source in manifest["inputs"]:
        path = ROOT / source["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == source["sha256"], path
        if path.parent.name == "courses":
            data = read(path)
            assert read(PACKAGE / "courses" / path.name) == data
            records = sum((data[k] for k in ["knowledge_nodes", "summary_blocks", "summary_items", "callouts",
                                            "boundary_groups", "structural_anchors", "images"]), [])
            records += data["floating_topics"]["roots"] + data["floating_topics"]["items"]
            for item in records:
                assert nodes[item["id"]]["properties"] == item, item["id"]
                preserved_nodes += 1
            for item in data["hierarchy_relations"] + data["semantic_relations"]:
                actual = edges[item["id"]]
                assert actual["properties"] == item
                assert (actual["head"], actual["tail"]) == (item["source_id"], item["target_id"])
                assert actual["direction"] == item.get("direction", "forward")
                preserved_edges += 1
            for item in data["images"]:
                assert hashlib.sha256((media_base / item["file"]).read_bytes()).hexdigest() == item["sha256"]
        elif path.suffix == ".csv":
            with path.open(encoding="utf-8-sig", newline="") as stream:
                for item in csv.DictReader(stream):
                    if "node_id" in item:
                        assert nodes["LEGACY:" + item["node_id"]]["properties"] == item
                        preserved_nodes += 1
                    else:
                        actual = edges["LEGACY:" + item["edge_id"]]
                        assert actual["properties"] == item
                        assert actual["head"] == "LEGACY:" + item["head"]
                        assert actual["tail"] == "LEGACY:" + item["tail"]
                        preserved_edges += 1
    overview = read(PACKAGE / "overview.json")
    assert overview == read(media_base / "跨课程总览.json")
    for item in overview["nodes"]:
        assert nodes[item["id"]]["properties"] == item
        preserved_nodes += 1
    for item in overview["relations"]:
        assert edges[item["id"]]["properties"] == item
        assert edges[item["id"]]["direction"] == item["direction"]
        preserved_edges += 1
    for item in lines("mapping_candidates.jsonl"):
        assert item["status"] == "pending_review"
        assert item["legacy_node_id"] in nodes
        assert all(cid in nodes for cid in item["candidate_node_ids"])
    catalog_targets = {e["tail"] for e in all_edges if e["head"] == "CATALOG:ROOT"}
    assert catalog_targets == {c["root_id"] for c in manifest["courses"]}
    assert len(catalog_targets) == 26
    print(f"PASS: {len(nodes)} unique nodes, {len(edges)} valid edges, 26 course entries.")
    print(f"PASS: {preserved_nodes} source entity records and {preserved_edges} source relation records preserved exactly.")
    print("PASS: course files, source fingerprints, image hashes, directions and pending mappings verified.")


if __name__ == "__main__":
    check()
