"""将九门课程知识图谱增量导入Neo4j。

特点：
1. 使用MERGE，不清空现有数据库。
2. 同一份数据可重复运行，不会重复创建相同edge_id的关系。
3. 同时导入课程内部关系与跨课程关系。
"""

import csv
import os
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase


IMPORT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = IMPORT_DIR.parent
ENV_PATH = PROJECT_ROOT / "kg_qa_system" / ".env"

NODE_FILE = IMPORT_DIR / "nodes.csv"
RELATIONSHIP_FILES = [
    IMPORT_DIR / "relationships.csv",
    IMPORT_DIR / "cross_course_relationships.csv",
]

BATCH_SIZE = 500

ALLOWED_RELATION_TYPES = {
    "APPLIED_IN",
    "BELONGS_TO_COURSE",
    "BELONGS_TO_TOPIC",
    "CAUSES",
    "COMPARE_WITH",
    "CONFUSED_WITH",
    "CONTAINS",
    "ENSURES",
    "EVALUATED_BY",
    "HAS_OPERATION",
    "HAS_PROPERTY",
    "ILLUSTRATED_BY",
    "IMPLEMENTED_BY",
    "IS_A",
    "OPTIMIZES",
    "PREREQUISITE_OF",
    "SOLVES",
    "USES",
}

ALLOWED_ENTITY_TYPES = {
    "Algorithm",
    "Application",
    "ComputingObject",
    "Concept",
    "Course",
    "DataStructure",
    "Example",
    "Mechanism",
    "Metric",
    "Model",
    "Operation",
    "Problem",
    "Property",
    "Protocol",
    "SyntaxElement",
    "Topic",
}


def read_csv_rows(file_path: Path) -> list[dict]:
    """读取带BOM或不带BOM的UTF-8 CSV。"""

    with file_path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def chunks(rows: list[dict], size: int):
    """把大量数据拆成多个批次。"""

    for start in range(0, len(rows), size):
        yield rows[start:start + size]


def normalize_optional_integer(value: str):
    value = (value or "").strip()
    return int(value) if value else None


def normalize_optional_float(value: str):
    value = (value or "").strip()
    return float(value) if value else None


def prepare_node_rows(rows: list[dict]) -> list[dict]:
    result = []

    for row in rows:
        entity_type = (row.get("entity_type") or "").strip()

        if entity_type not in ALLOWED_ENTITY_TYPES:
            raise ValueError(
                f"节点{row.get('node_id')}具有非法实体类型：{entity_type}"
            )

        normalized = row.copy()
        normalized["difficulty"] = normalize_optional_integer(
            row.get("difficulty", "")
        )
        normalized["importance"] = normalize_optional_integer(
            row.get("importance", "")
        )
        result.append(normalized)

    return result


def prepare_relationship_rows(
    rows: list[dict]
) -> dict[str, list[dict]]:
    """按关系类型分组，关系类型稍后只从白名单写入Cypher。"""

    grouped = {}

    for row in rows:
        relation_type = (row.get("relation_type") or "").strip()

        if relation_type not in ALLOWED_RELATION_TYPES:
            raise ValueError(
                f"关系{row.get('edge_id')}具有非法类型：{relation_type}"
            )

        normalized = row.copy()
        normalized["confidence"] = normalize_optional_float(
            row.get("confidence", "")
        )

        grouped.setdefault(relation_type, []).append(normalized)

    return grouped


def upsert_nodes(transaction, rows: list[dict]):
    transaction.run(
        """
        UNWIND $rows AS row
        MERGE (node:KGNode {node_id: row.node_id})
        SET node.name = row.name,
            node.entity_type = row.entity_type,
            node.course = row.course,
            node.topic = row.topic,
            node.definition = row.definition,
            node.alias = row.alias,
            node.difficulty = row.difficulty,
            node.importance = row.importance,
            node.source = row.source,
            node.source_section = row.source_section,
            node.book_page = row.book_page,
            node.evidence_text = row.evidence_text
        """,
        rows=rows,
    ).consume()


def add_entity_label(transaction, entity_type: str):
    # entity_type已经通过白名单验证，因此可安全用于标签名称。
    transaction.run(
        f"""
        MATCH (node:KGNode {{entity_type: $entity_type}})
        SET node:`{entity_type}`
        """,
        entity_type=entity_type,
    ).consume()


def upsert_relationships(
    transaction,
    relation_type: str,
    rows: list[dict],
):
    # relation_type已经通过白名单验证，因此可安全用于关系名称。
    transaction.run(
        f"""
        UNWIND $rows AS row
        MATCH (head:KGNode {{node_id: row.head}})
        MATCH (tail:KGNode {{node_id: row.tail}})
        MERGE (head)-[relation:`{relation_type}` {{edge_id: row.edge_id}}]->(tail)
        SET relation.head_name = row.head_name,
            relation.tail_name = row.tail_name,
            relation.reason = row.reason,
            relation.source = row.source,
            relation.confidence = row.confidence,
            relation.source_section = row.source_section,
            relation.book_page = row.book_page,
            relation.evidence_text = row.evidence_text
        """,
        rows=rows,
    ).consume()


def get_database_counts(session) -> dict:
    record = session.run(
        """
        MATCH (node)
        WITH count(node) AS nodes
        MATCH ()-[relation]->()
        RETURN
            nodes,
            count(relation) AS relationships,
            count(
                CASE
                    WHEN relation.edge_id STARTS WITH 'XCR_E_'
                    THEN 1
                END
            ) AS cross_course_relationships
        """
    ).single()

    return record.data()


def main():
    load_dotenv(ENV_PATH)

    uri = os.getenv("NEO4J_URI")
    username = os.getenv("NEO4J_USERNAME")
    password = os.getenv("NEO4J_PASSWORD")
    database = os.getenv("NEO4J_DATABASE", "neo4j")

    if not uri or not username or not password:
        raise RuntimeError(".env中缺少Neo4j连接配置")

    node_rows = prepare_node_rows(read_csv_rows(NODE_FILE))

    relationship_rows = []
    for file_path in RELATIONSHIP_FILES:
        relationship_rows.extend(read_csv_rows(file_path))

    grouped_relationships = prepare_relationship_rows(
        relationship_rows
    )

    driver = GraphDatabase.driver(
        uri,
        auth=(username, password),
    )

    try:
        driver.verify_connectivity()

        with driver.session(database=database) as session:
            before = get_database_counts(session)

            session.run(
                """
                CREATE CONSTRAINT kg_node_id IF NOT EXISTS
                FOR (node:KGNode)
                REQUIRE node.node_id IS UNIQUE
                """
            ).consume()

            for batch in chunks(node_rows, BATCH_SIZE):
                session.execute_write(upsert_nodes, batch)

            for entity_type in sorted(ALLOWED_ENTITY_TYPES):
                session.execute_write(
                    add_entity_label,
                    entity_type,
                )

            for relation_type in sorted(grouped_relationships):
                rows = grouped_relationships[relation_type]

                for batch in chunks(rows, BATCH_SIZE):
                    session.execute_write(
                        upsert_relationships,
                        relation_type,
                        batch,
                    )

            after = get_database_counts(session)

            courses = session.run(
                """
                MATCH (node:KGNode)
                RETURN node.course AS course, count(node) AS nodes
                ORDER BY nodes DESC
                """
            ).data()

        print("增量导入成功")
        print("导入前：", before)
        print("导入后：", after)
        print("课程节点统计：")

        for course in courses:
            print(f"- {course['course']}：{course['nodes']}")

    finally:
        driver.close()


if __name__ == "__main__":
    main()
