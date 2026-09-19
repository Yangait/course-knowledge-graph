import os

from dotenv import load_dotenv
from neo4j import GraphDatabase


load_dotenv()

uri = os.getenv("NEO4J_URI")
username = os.getenv("NEO4J_USERNAME")
password = os.getenv("NEO4J_PASSWORD")
database = os.getenv("NEO4J_DATABASE", "neo4j")

if not uri:
    raise RuntimeError("没有读取到NEO4J_URI")

if not username:
    raise RuntimeError("没有读取到NEO4J_USERNAME")

if not password:
    raise RuntimeError("没有读取到NEO4J_PASSWORD")


driver = GraphDatabase.driver(
    uri,
    auth=(username, password)
)


def check_database() -> dict:
    """检查Neo4j连接和知识图谱数据量。"""

    driver.verify_connectivity()

    with driver.session(database=database) as session:
        node_count = session.run(
            "MATCH (n) RETURN count(n) AS count"
        ).single()["count"]

        relationship_count = session.run(
            "MATCH ()-[r]->() RETURN count(r) AS count"
        ).single()["count"]

        cross_course_count = session.run(
            """
            MATCH ()-[r]->()
            WHERE r.edge_id STARTS WITH 'XCR_E_'
            RETURN count(r) AS count
            """
        ).single()["count"]

    return {
        "nodes": node_count,
        "relationships": relationship_count,
        "cross_course_relationships": cross_course_count
    }


def search_knowledge(keyword: str) -> list[dict]:
    """根据关键词检索知识节点及其相邻关系。"""

    query = """
    MATCH (n:KGNode)
    WHERE toLower(n.name) CONTAINS toLower($keyword)
       OR toLower(coalesce(n.alias, '')) CONTAINS toLower($keyword)

    WITH n
    ORDER BY
        CASE WHEN toLower(n.name) = toLower($keyword)
             THEN 0
             ELSE 1
        END,
        coalesce(n.importance, 0) DESC
    LIMIT 5

    OPTIONAL MATCH (n)-[r]-(m:KGNode)

    RETURN
        n.node_id AS node_id,
        n.name AS name,
        n.entity_type AS entity_type,
        n.course AS course,
        n.definition AS definition,
        n.source AS source,
        n.book_page AS book_page,
        collect(
            DISTINCT {
                relation: type(r),
                related_name: m.name,
                reason: r.reason
            }
        )[0..10] AS relationships
    """

    with driver.session(database=database) as session:
        result = session.run(
            query,
            keyword=keyword
        )

        return [record.data() for record in result]

def find_entity_candidates(
    entity_name: str
) -> list[dict]:
    """根据实体名称查找候选节点。"""

    if not entity_name or not entity_name.strip():
        return []

    query = """
    MATCH (n:KGNode)

    WITH
        n,
        [
            alias IN split(coalesce(n.alias, ''), ',')
            | trim(alias)
        ] AS aliases

    WHERE
        toLower(n.name) = toLower($entity_name)
        OR any(
            alias IN aliases
            WHERE toLower(alias) = toLower($entity_name)
        )
        OR toLower(n.name) CONTAINS toLower($entity_name)
        OR toLower($entity_name) CONTAINS toLower(n.name)
        OR any(
            alias IN aliases
            WHERE toLower(alias) CONTAINS toLower($entity_name)
        )

    WITH
        n,
        aliases,
        CASE
            WHEN toLower(n.name) = toLower($entity_name)
                THEN 100

            WHEN any(
                alias IN aliases
                WHERE toLower(alias) = toLower($entity_name)
            )
                THEN 90

            WHEN toLower(n.name) CONTAINS toLower($entity_name)
                THEN 70

            WHEN toLower($entity_name) CONTAINS toLower(n.name)
                THEN 60

            ELSE 50
        END AS match_score

    RETURN
        n.node_id AS node_id,
        n.name AS name,
        n.alias AS alias,
        n.entity_type AS entity_type,
        n.course AS course,
        n.definition AS definition,
        n.importance AS importance,
        match_score

    ORDER BY
        match_score DESC,
        coalesce(n.importance, 0) DESC,
        size(n.name) DESC

    LIMIT 5
    """

    with driver.session(database=database) as session:
        result = session.run(
            query,
            entity_name=entity_name.strip()
        )

        return [record.data() for record in result]

def count_relations_for_node(
    node_id: str,
    relation_type: str,
    direction: str
) -> int:
    """统计节点在指定关系和方向上的关系数量。"""

    if direction == "incoming":
        query = """
        MATCH (other:KGNode)-[r]->(node:KGNode {node_id: $node_id})
        WHERE type(r) = $relation_type
        RETURN count(r) AS count
        """

    elif direction == "outgoing":
        query = """
        MATCH (node:KGNode {node_id: $node_id})-[r]->(other:KGNode)
        WHERE type(r) = $relation_type
        RETURN count(r) AS count
        """

    elif direction == "both":
        query = """
        MATCH (node:KGNode {node_id: $node_id})-[r]-(other:KGNode)
        WHERE type(r) = $relation_type
        RETURN count(r) AS count
        """

    else:
        raise ValueError(
            "direction只能是incoming、outgoing或both"
        )

    with driver.session(database=database) as session:
        record = session.run(
            query,
            node_id=node_id,
            relation_type=relation_type
        ).single()

        return record["count"]

def query_related_nodes(
    node_id: str,
    relation_type: str,
    direction: str
) -> list[dict]:
    """按节点、关系类型和方向查询相关节点。"""

    if not node_id:
        raise ValueError("node_id不能为空")

    if not relation_type:
        raise ValueError("relation_type不能为空")

    if direction == "incoming":
        query = """
        MATCH (related:KGNode)-[r]->(
            anchor:KGNode {node_id: $node_id}
        )
        WHERE type(r) = $relation_type

        RETURN
            anchor.node_id AS anchor_node_id,
            anchor.name AS anchor_name,

            related.node_id AS related_node_id,
            related.name AS related_name,
            related.entity_type AS related_entity_type,
            related.course AS related_course,
            related.definition AS related_definition,
            related.importance AS related_importance,

            type(r) AS relation_type,
            'incoming' AS direction,
            r.reason AS reason,
            r.source AS source,
            r.confidence AS confidence,
            r.source_section AS source_section,
            r.book_page AS book_page,
            r.evidence_text AS evidence_text

        ORDER BY
            coalesce(r.confidence, 0) DESC,
            coalesce(related.importance, 0) DESC,
            related.name
        """

    elif direction == "outgoing":
        query = """
        MATCH (
            anchor:KGNode {node_id: $node_id}
        )-[r]->(related:KGNode)
        WHERE type(r) = $relation_type

        RETURN
            anchor.node_id AS anchor_node_id,
            anchor.name AS anchor_name,

            related.node_id AS related_node_id,
            related.name AS related_name,
            related.entity_type AS related_entity_type,
            related.course AS related_course,
            related.definition AS related_definition,
            related.importance AS related_importance,

            type(r) AS relation_type,
            'outgoing' AS direction,
            r.reason AS reason,
            r.source AS source,
            r.confidence AS confidence,
            r.source_section AS source_section,
            r.book_page AS book_page,
            r.evidence_text AS evidence_text

        ORDER BY
            coalesce(r.confidence, 0) DESC,
            coalesce(related.importance, 0) DESC,
            related.name
        """

    elif direction == "both":
        query = """
        MATCH (
            anchor:KGNode {node_id: $node_id}
        )-[r]-(related:KGNode)
        WHERE type(r) = $relation_type

        RETURN
            anchor.node_id AS anchor_node_id,
            anchor.name AS anchor_name,

            related.node_id AS related_node_id,
            related.name AS related_name,
            related.entity_type AS related_entity_type,
            related.course AS related_course,
            related.definition AS related_definition,
            related.importance AS related_importance,

            type(r) AS relation_type,

            CASE
                WHEN startNode(r) = anchor
                THEN 'outgoing'
                ELSE 'incoming'
            END AS direction,

            r.reason AS reason,
            r.source AS source,
            r.confidence AS confidence,
            r.source_section AS source_section,
            r.book_page AS book_page,
            r.evidence_text AS evidence_text

        ORDER BY
            coalesce(r.confidence, 0) DESC,
            coalesce(related.importance, 0) DESC,
            related.name
        """

    else:
        raise ValueError(
            "direction只能是incoming、outgoing或both"
        )

    with driver.session(database=database) as session:
        result = session.run(
            query,
            node_id=node_id,
            relation_type=relation_type
        )

        return [record.data() for record in result]

def query_entity_context(
    node_id: str,
    limit: int = 10
) -> list[dict]:
    """查询实体自身信息及周边知识。"""

    if not node_id:
        return []

    # 限制证据数量，控制Token消耗
    limit = max(1, min(limit, 20))

    query = """
    MATCH (anchor:KGNode {node_id: $node_id})

    OPTIONAL MATCH (anchor)-[r]-(related:KGNode)

    WITH
        anchor,
        r,
        related,

        CASE
            WHEN r IS NULL THEN null
            WHEN startNode(r) = anchor THEN 'outgoing'
            ELSE 'incoming'
        END AS direction,

        CASE type(r)
            WHEN 'IS_A' THEN 0
            WHEN 'HAS_PROPERTY' THEN 0
            WHEN 'HAS_OPERATION' THEN 0
            WHEN 'SOLVES' THEN 0
            WHEN 'USES' THEN 0
            WHEN 'APPLIED_IN' THEN 0
            WHEN 'IMPLEMENTED_BY' THEN 0
            WHEN 'CAUSES' THEN 0
            WHEN 'ENSURES' THEN 0
            WHEN 'PREREQUISITE_OF' THEN 1
            WHEN 'CONTAINS' THEN 1
            ELSE 2
        END AS relation_priority

    ORDER BY
        relation_priority,
        coalesce(r.confidence, 0) DESC,
        coalesce(related.importance, 0) DESC

    WITH
        anchor,
        collect(
            CASE
                WHEN r IS NULL THEN null
                ELSE {
                    relation_type: type(r),
                    direction: direction,
                    related_name: related.name,
                    related_type: related.entity_type,
                    related_definition: related.definition,
                    reason: r.reason,
                    source: r.source,
                    confidence: r.confidence
                }
            END
        )[0..$limit] AS raw_relationships

    RETURN
        'entity_context' AS evidence_type,
        anchor.node_id AS node_id,
        anchor.name AS name,
        anchor.entity_type AS entity_type,
        anchor.course AS course,
        anchor.definition AS definition,
        anchor.source AS source,
        anchor.book_page AS book_page,
        [
            item IN raw_relationships
            WHERE item IS NOT NULL
        ] AS relationships
    """

    with driver.session(database=database) as session:
        record = session.run(
            query,
            node_id=node_id,
            limit=limit
        ).single()

        if record is None:
            return []

        return [record.data()]

if __name__ == "__main__":
    try:
        result = check_database()

        print("Neo4j连接成功")
        print("节点数量：", result["nodes"])
        print("关系数量：", result["relationships"])
        print("跨课程关系数量：", result["cross_course_relationships"])
    finally:
        driver.close()
