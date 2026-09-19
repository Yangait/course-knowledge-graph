"""Versioned, additive Neo4j import. Default is offline validation only."""
import argparse
import hashlib
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

from check_unified_graph import check

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "unified_kg"
BATCH_SIZE = 400
RELATIONS = frozenset("""HAS_COURSE CONTAINS SEMANTIC_LINK ANNOTATES SUMMARIZES GROUP_MEMBER
HAS_IMAGE CONTAINS_AUXILIARY HAS_STRUCTURE REFERS_TO_COURSE COURSE_EDITION_OF
BELONGS_TO_COURSE BELONGS_TO_TOPIC HAS_OPERATION HAS_PROPERTY IS_A IMPLEMENTED_BY
USES PREREQUISITE_OF ENSURES OPTIMIZES COMPARE_WITH CONFUSED_WITH APPLIED_IN
EVALUATED_BY SOLVES CAUSES ILLUSTRATED_BY""".split())


def read_rows(filename):
    with (PACKAGE / filename).open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream]


def serialized(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def numeric(value, cast):
    return cast(value) if value not in (None, "") else None


def prepare(manifest, nodes, edges):
    """Adapt nested source records to legal Neo4j scalar/list properties."""
    courses = {c["course_id"]: c["name"] for c in manifest["courses"]}
    prepared_nodes, prepared_edges = [], defaultdict(list)
    node_ids, edge_ids = set(), set()
    for n in nodes:
        if n["node_id"] in node_ids:
            raise ValueError("Duplicate node ID")
        node_ids.add(n["node_id"])
        p = n["properties"]
        props = dict(node_id=n["node_id"], name=n["name"], entity_type=n["entity_type"],
                     course_id=n.get("course_id"), course=courses.get(n.get("course_id")),
                     origin=n["origin"], searchable=n["searchable"], source=n.get("source_file"),
                     definition=p.get("definition"), alias=p.get("alias"), text=p.get("text"),
                     topic=p.get("topic"), path=p.get("path"), parent_id=p.get("parent_id"),
                     depth=p.get("depth"), book_page=p.get("book_page"),
                     evidence_text=p.get("evidence_text"), source_section=p.get("source_section"),
                     importance=numeric(p.get("importance"), int), difficulty=numeric(p.get("difficulty"), int),
                     image_ids=p.get("image_ids", []), media_file=p.get("file"), media_sha256=p.get("sha256"),
                     owner_id=p.get("owner_id"), owner_resolution=p.get("owner_resolution"),
                     properties_json=serialized(p))
        prepared_nodes.append({k: v for k, v in props.items() if v is not None})
    for e in edges:
        if e["edge_id"] in edge_ids:
            raise ValueError("Duplicate edge ID")
        edge_ids.add(e["edge_id"])
        kind = e["relation_type"]
        if kind not in RELATIONS:
            raise ValueError("Unsupported relation type")
        if e["head"] not in node_ids or e["tail"] not in node_ids:
            raise ValueError("Missing relationship endpoint")
        if e["direction"] not in {"forward", "backward", "both", "none"}:
            raise ValueError("Unsupported relationship direction")
        p = e["properties"]
        props = dict(edge_id=e["edge_id"], origin=e["origin"], direction=e["direction"],
                     relation_text=p.get("relation_text"), raw_relation_text=p.get("raw_relation_text"),
                     relation_status=p.get("relation_status"), reason=p.get("reason"), source=p.get("source"),
                     confidence=numeric(p.get("confidence"), float), evidence_text=p.get("evidence_text"),
                     source_section=p.get("source_section"), book_page=p.get("book_page"),
                     properties_json=serialized(p))
        prepared_edges[kind].append(dict(head=e["head"], tail=e["tail"],
                                        props={k: v for k, v in props.items() if v is not None}))
    return prepared_nodes, dict(prepared_edges)


def package_id():
    digest = hashlib.sha256()
    for filename in ["manifest.json", "nodes.jsonl", "edges.jsonl"]:
        digest.update(filename.encode())
        digest.update((PACKAGE / filename).read_bytes())
    return "u26_" + digest.hexdigest()[:24]


def batches(rows):
    for start in range(0, len(rows), BATCH_SIZE):
        yield rows[start:start + BATCH_SIZE]


def write_nodes(tx, dataset, rows):
    tx.run("""UNWIND $rows AS row
        MERGE (n:UnifiedKGNode {dataset_id: $dataset, node_id: row.node_id})
        SET n = row, n.dataset_id = $dataset""", dataset=dataset, rows=rows).consume()


def write_edges(tx, dataset, kind, rows):
    if kind not in RELATIONS:
        raise ValueError("Unsupported relation type")
    record = tx.run(f"""UNWIND $rows AS row
        MATCH (a:UnifiedKGNode {{dataset_id: $dataset, node_id: row.head}})
        MATCH (b:UnifiedKGNode {{dataset_id: $dataset, node_id: row.tail}})
        MERGE (a)-[r:`{kind}` {{dataset_id: $dataset, edge_id: row.props.edge_id}}]->(b)
        SET r = row.props, r.dataset_id = $dataset
        RETURN count(r) AS written""", dataset=dataset, rows=rows).single()
    if record["written"] != len(rows):
        raise ValueError("Relationship write count mismatch")


def verify(session, dataset, expected_nodes, expected_edges):
    """Compare all persisted properties and endpoints, not only aggregate counts."""
    got_nodes = session.run("""MATCH (n:UnifiedKGNode {dataset_id:$dataset})
        RETURN properties(n) AS props""", dataset=dataset).data()
    actual_nodes = {}
    for record in got_nodes:
        props = record["props"]
        props.pop("dataset_id")
        if props["node_id"] in actual_nodes:
            raise ValueError("Duplicate database node")
        actual_nodes[props["node_id"]] = props
    if actual_nodes != {n["node_id"]: n for n in expected_nodes}:
        raise ValueError("Stored node properties differ from package")
    got_edges = session.run("""MATCH (a)-[r]->(b) WHERE r.dataset_id=$dataset
        RETURN a.node_id AS head, b.node_id AS tail, a.dataset_id AS head_dataset,
        b.dataset_id AS tail_dataset, type(r) AS kind, properties(r) AS props""", dataset=dataset).data()
    actual_edges = {}
    for record in got_edges:
        if record.pop("head_dataset") != dataset or record.pop("tail_dataset") != dataset:
            raise ValueError("Cross-version relationship detected")
        props = record["props"]
        props.pop("dataset_id")
        key = props["edge_id"]
        if key in actual_edges:
            raise ValueError("Duplicate database relationship")
        actual_edges[key] = record
    wanted = {r["props"]["edge_id"]: dict(kind=kind, **r) for kind, rows in expected_edges.items() for r in rows}
    if actual_edges != wanted:
        raise ValueError("Stored relationships differ from package")
    return dict(nodes=len(actual_nodes), relationships=len(actual_edges),
                courses=sum(n["entity_type"] == "course_root" for n in expected_nodes),
                images=sum(n["entity_type"] == "image" for n in expected_nodes),
                verified="all_properties_and_endpoints")


def legacy_fingerprint(session):
    """Read-only integrity fingerprint of the old application's graph."""
    records = session.run("""MATCH (n:KGNode)
        RETURN n.node_id AS id, labels(n) AS labels, properties(n) AS props""").data()
    for r in records:
        r["labels"].sort()
    relations = session.run("""MATCH (a:KGNode)-[r]->(b:KGNode)
        RETURN a.node_id AS head, b.node_id AS tail, type(r) AS kind, properties(r) AS props""").data()
    content = serialized(sorted(serialized(r) for r in records) + sorted(serialized(r) for r in relations))
    return dict(nodes=len(records), relationships=len(relations), sha256=hashlib.sha256(content.encode()).hexdigest())


def connect():
    load_dotenv(ROOT / "kg_qa_system" / ".env")
    required = ["NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD"]
    if any(not os.getenv(k) for k in required):
        raise ValueError("Missing Neo4j configuration")
    return GraphDatabase.driver(os.environ["NEO4J_URI"],
                                auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
                                connection_timeout=5, connection_acquisition_timeout=15, max_transaction_retry_time=15)


def execute(apply=False, verify_only=False):
    check()
    manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
    nodes, edges = prepare(manifest, read_rows("nodes.jsonl"), read_rows("edges.jsonl"))
    dataset = package_id()
    report = dict(dataset_id=dataset, mode="dry_run", nodes=len(nodes),
                  relationships=sum(map(len, edges.values())), courses=len(manifest["courses"]),
                  target_label="UnifiedKGNode", original_label="KGNode", status="validated")
    if not apply and not verify_only:
        return report
    with connect() as driver:
        driver.verify_connectivity()
        with driver.session(database=os.getenv("NEO4J_DATABASE", "neo4j")) as session:
            if verify_only:
                report.update(mode="verify", status="verified", verification=verify(session, dataset, nodes, edges))
                return report
            before = legacy_fingerprint(session)
            session.run("""CREATE CONSTRAINT unified_kg_node_key IF NOT EXISTS
                FOR (n:UnifiedKGNode) REQUIRE (n.dataset_id, n.node_id) IS UNIQUE""").consume()
            session.run("""CREATE CONSTRAINT unified_kg_dataset_key IF NOT EXISTS
                FOR (d:UnifiedKGDataset) REQUIRE d.dataset_id IS UNIQUE""").consume()
            session.run("""CREATE INDEX unified_kg_course IF NOT EXISTS
                FOR (n:UnifiedKGNode) ON (n.dataset_id, n.course_id)""").consume()
            existing = session.run("""MATCH (d:UnifiedKGDataset {dataset_id:$dataset})
                RETURN d.status AS status""", dataset=dataset).single()
            if existing and existing["status"] == "ready":
                report.update(mode="apply", status="already_ready", verification=verify(session, dataset, nodes, edges))
                return report
            session.run("""MERGE (d:UnifiedKGDataset {dataset_id:$dataset})
                SET d.status='importing', d.schema_version=$schema, d.started_at=datetime(),
                    d.manifest_json=$manifest""", dataset=dataset, schema=manifest["schema_version"],
                        manifest=serialized(manifest)).consume()
            try:
                for batch in batches(nodes):
                    session.execute_write(write_nodes, dataset, batch)
                print(f"Imported {len(nodes)} nodes.", flush=True)
                for kind, rows in sorted(edges.items()):
                    for batch in batches(rows):
                        session.execute_write(write_edges, dataset, kind, batch)
                counts = verify(session, dataset, nodes, edges)
                after = legacy_fingerprint(session)
                if before != after:
                    raise ValueError("Old graph changed during import; inspect before activating")
                session.run("""MATCH (d:UnifiedKGDataset {dataset_id:$dataset})
                    SET d.status='ready', d.completed_at=datetime(), d.node_count=$nodes,
                        d.relationship_count=$edges, d.course_count=26""",
                            dataset=dataset, nodes=len(nodes), edges=report["relationships"]).consume()
                report.update(mode="apply", status="ready", verification=counts, original_graph_unchanged=True,
                              original_graph=before)
            except Exception:
                session.run("""MATCH (d:UnifiedKGDataset {dataset_id:$dataset})
                    SET d.status='incomplete'""", dataset=dataset).consume()
                raise
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--apply", action="store_true", help="Import the validated package without changing KGNode data")
    modes.add_argument("--verify-only", action="store_true", help="Read and compare previously imported data")
    args = parser.parse_args()
    try:
        report = execute(args.apply, args.verify_only)
    except Exception as error:
        # Do not print connection URLs, credentials, or source payloads in exceptions.
        message = "Offline validation failed; rerun the checker and tests." if isinstance(error, (ValueError, AssertionError)) else "Check Neo4j availability and configuration."
        print(f"Import not completed: {type(error).__name__}. {message}")
        raise SystemExit(1) from None
    report["checked_at"] = datetime.now(timezone.utc).isoformat()
    filename = "neo4j_import_result.json" if args.apply else "neo4j_verify_result.json" if args.verify_only else "neo4j_import_plan.json"
    (PACKAGE / filename).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
