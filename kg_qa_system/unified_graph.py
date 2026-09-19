"""Version-scoped access to the verified 26-course Neo4j graph."""
import hashlib
import os
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

PACKAGE = Path(__file__).resolve().parents[1] / "unified_kg"
load_dotenv(Path(__file__).resolve().parent / ".env")
database = os.getenv("NEO4J_DATABASE", "neo4j")
driver = GraphDatabase.driver(os.environ["NEO4J_URI"],
    auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
    connection_timeout=5, connection_acquisition_timeout=15)
_course = ContextVar("graph_course", default=None)


@contextmanager
def graph_scope(course_id=None):
    token = _course.set(course_id)
    try:
        yield
    finally:
        _course.reset(token)


@lru_cache(maxsize=1)
def dataset_id():
    digest = hashlib.sha256()
    for filename in ("manifest.json", "nodes.jsonl", "edges.jsonl"):
        digest.update(filename.encode())
        digest.update((PACKAGE / filename).read_bytes())
    return "u26_" + digest.hexdigest()[:24]


def read_graph(query, **params):
    with driver.session(database=database) as session:
        ready = session.run("MATCH (d:UnifiedKGDataset {dataset_id:$dataset, status:'ready'}) RETURN d.dataset_id AS id",
                            dataset=dataset_id()).single()
        if not ready:
            raise RuntimeError("新版图谱尚未完成导入校验")
        return session.run(query, dataset=dataset_id(), **params).data()


def check_database():
    nodes = read_graph("MATCH (n:UnifiedKGNode {dataset_id:$dataset}) RETURN count(n) AS count")[0]["count"]
    rels = read_graph("MATCH ()-[r]->() WHERE r.dataset_id=$dataset RETURN count(r) AS count")[0]["count"]
    cross = read_graph("""MATCH ()-[r]->() WHERE r.dataset_id=$dataset AND
        (r.origin='emmx_overview' OR r.edge_id STARTS WITH 'LEGACY:XCR_') RETURN count(r) AS count""")[0]["count"]
    return dict(nodes=nodes, relationships=rels, cross_course_relationships=cross, courses=26, dataset_id=dataset_id())


def find_entity_candidates(entity_name):
    if not entity_name or not entity_name.strip():
        return []
    return read_graph("""MATCH (n:UnifiedKGNode {dataset_id:$dataset})
        WHERE n.searchable=true AND ($course IS NULL OR n.course_id=$course)
        WITH n, toLower(n.name) AS name, [a IN split(coalesce(n.alias,''), ',') | toLower(trim(a))] AS aliases
        WHERE name=$term OR $term IN aliases OR name CONTAINS $term
        WITH n, CASE WHEN name=$term THEN 100 WHEN $term IN aliases THEN 95 ELSE 60 END AS score
        RETURN n.node_id AS node_id, n.name AS name, n.entity_type AS entity_type,
            n.course AS course, n.course_id AS course_id, n.definition AS definition,
            n.path AS path, n.alias AS alias, n.origin AS origin,
            coalesce(n.importance, 0) AS importance, score AS match_score
        ORDER BY match_score DESC, importance DESC, size(n.name), n.node_id
        LIMIT 24""", course=_course.get(), term=entity_name.strip().casefold())


def node_record(node_id):
    rows = read_graph("""MATCH (n:UnifiedKGNode {dataset_id:$dataset, node_id:$node})
        WHERE $course IS NULL OR n.course_id=$course RETURN properties(n) AS n""",
        node=node_id, course=_course.get())
    return rows[0]["n"] if rows else None


def relative_direction(stored, starts_at_anchor):
    if stored in ("none", "both"):
        return stored
    forward = starts_at_anchor if stored == "forward" else not starts_at_anchor
    return "outgoing" if forward else "incoming"


def neighbors(node_id, limit=40, relation_type=None):
    rows = read_graph("""MATCH (a:UnifiedKGNode {dataset_id:$dataset, node_id:$node})-[r]-(b:UnifiedKGNode)
        WHERE r.dataset_id=$dataset AND b.dataset_id=$dataset
            AND ($course IS NULL OR a.course_id=$course)
            AND ($kind IS NULL OR type(r)=$kind)
        RETURN properties(b) AS b, properties(r) AS relationship, type(r) AS kind,
            startNode(r)=a AS starts
        ORDER BY CASE WHEN type(r) IN ['ANNOTATES','SUMMARIZES','SEMANTIC_LINK'] THEN 0
            WHEN type(r)='CONTAINS' AND startNode(r)=a THEN 1
            WHEN type(r)='CONTAINS' THEN 2 ELSE 3 END, r.edge_id LIMIT $limit""",
        node=node_id, course=_course.get(), kind=relation_type, limit=limit)
    result = []
    if relation_type is None:
        overview = read_graph("""MATCH (a:UnifiedKGNode {dataset_id:$dataset,node_id:$node})
            <-[:REFERS_TO_COURSE]-(ref:UnifiedKGNode)-[r:SEMANTIC_LINK]-(b:UnifiedKGNode)
            WHERE r.dataset_id=$dataset AND b.dataset_id=$dataset
            AND ($course IS NULL OR a.course_id=$course)
            OPTIONAL MATCH (b)-[:REFERS_TO_COURSE]->(course:UnifiedKGNode {dataset_id:$dataset})
            RETURN coalesce(course,b) AS target, properties(r) AS props, startNode(r)=ref AS starts
            ORDER BY r.edge_id LIMIT 20""", node=node_id, course=_course.get())
        for row in overview:
            b, r = row["target"], row["props"]
            result.append(dict(related_node_id=b["node_id"], related_name=b["name"], related_type=b["entity_type"],
                related_course=b.get("course"), related_course_id=b.get("course_id"), related_definition=None,
                relation_type="SEMANTIC_LINK", relation_text=r.get("relation_text"),
                direction=relative_direction(r.get("direction", "none"), row["starts"]),
                reason="跨课程总览中的原始连线；未命名连线不代表先修关系", source="26门课程总览.emmx", confidence=None))
    for row in rows:
        b, r = row["b"], row["relationship"]
        result.append(dict(related_node_id=b["node_id"], related_name=b["name"],
            related_type=b["entity_type"], related_course=b.get("course"), related_course_id=b.get("course_id"),
            related_definition=b.get("definition") or b.get("text"), related_path=b.get("path"),
            relation_type=row["kind"], relation_text=r.get("relation_text"),
            direction=relative_direction(r.get("direction", "forward"), row["starts"]),
            reason=r.get("reason"), source=r.get("source") or b.get("source"), confidence=r.get("confidence")))
    return result


def query_related_nodes(node_id, relation_type, direction):
    if direction not in {"incoming", "outgoing", "both"}:
        raise ValueError("Invalid direction")
    anchor = node_record(node_id)
    if not anchor:
        return []
    result = []
    for item in neighbors(node_id, 80, relation_type):
        if direction != "both" and item["direction"] not in {direction, "both"}:
            continue
        result.append(dict(item, anchor_node_id=node_id, anchor_name=anchor["name"],
                           course_id=anchor.get("course_id"), course=anchor.get("course"),
                           origin=anchor.get("origin"), related_entity_type=item["related_type"]))
    return result[:30]


def count_relations_for_node(node_id, relation_type, direction):
    return len(query_related_nodes(node_id, relation_type, direction))


def query_entity_context(node_id, limit=10):
    n = node_record(node_id)
    if not n:
        return []
    limit = max(1, min(limit, 20))
    relations = [r for r in neighbors(node_id, 60) if r["relation_type"] not in
                 {"HAS_IMAGE", "GROUP_MEMBER", "HAS_STRUCTURE", "HAS_COURSE", "COURSE_EDITION_OF", "REFERS_TO_COURSE"}][:limit]
    descendants = read_graph("""MATCH p=(a:UnifiedKGNode {dataset_id:$dataset,node_id:$node})
        -[:CONTAINS*2..3]->(b:UnifiedKGNode {dataset_id:$dataset})
        RETURN b.node_id AS node_id, b.name AS name, b.path AS path ORDER BY length(p), b.node_id LIMIT 24""", node=node_id)
    return [dict(evidence_type="entity_context", node_id=node_id, name=n["name"],
        entity_type=n["entity_type"], course=n.get("course"), course_id=n.get("course_id"),
        definition=n.get("definition") or n.get("text"), path=n.get("path"),
        source=n.get("source"), book_page=n.get("book_page"), origin=n.get("origin"),
        relationships=relations, descendants=descendants, image_ids=n.get("image_ids", []))]
