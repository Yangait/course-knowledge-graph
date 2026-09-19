// Neo4j 导入脚本：先把 nodes.csv 和 relationships.csv 放到 Neo4j 的 import 文件夹里
// 然后在 Neo4j Browser / Cypher Shell 中运行本脚本

// 0. 本脚本不再默认清空数据库。
// 如需重建数据库，必须先确认备份，再手动运行：
// MATCH (n) DETACH DELETE n;

// 1. 建唯一约束，避免重复导入节点
CREATE CONSTRAINT kg_node_id IF NOT EXISTS FOR (n:KGNode) REQUIRE n.node_id IS UNIQUE;

// 2. 导入节点
LOAD CSV WITH HEADERS FROM 'file:///nodes.csv' AS row
MERGE (n:KGNode {node_id: row.node_id})
SET n.name = row.name,
    n.entity_type = row.entity_type,
    n.course = row.course,
    n.topic = row.topic,
    n.definition = row.definition,
    n.alias = row.alias,
    n.difficulty = CASE row.difficulty WHEN '' THEN null ELSE toInteger(row.difficulty) END,
    n.importance = CASE row.importance WHEN '' THEN null ELSE toInteger(row.importance) END,
    n.source = row.source,
    n.source_section = row.source_section,
    n.book_page = row.book_page,
    n.evidence_text = row.evidence_text;

// 3. 给不同实体类型打上额外标签，方便 Neo4j 可视化
MATCH (n:KGNode {entity_type: 'Algorithm'}) SET n:Algorithm;
MATCH (n:KGNode {entity_type: 'Application'}) SET n:Application;
MATCH (n:KGNode {entity_type: 'ComputingObject'}) SET n:ComputingObject;
MATCH (n:KGNode {entity_type: 'Concept'}) SET n:Concept;
MATCH (n:KGNode {entity_type: 'Course'}) SET n:Course;
MATCH (n:KGNode {entity_type: 'DataStructure'}) SET n:DataStructure;
MATCH (n:KGNode {entity_type: 'Example'}) SET n:Example;
MATCH (n:KGNode {entity_type: 'Mechanism'}) SET n:Mechanism;
MATCH (n:KGNode {entity_type: 'Metric'}) SET n:Metric;
MATCH (n:KGNode {entity_type: 'Model'}) SET n:Model;
MATCH (n:KGNode {entity_type: 'Operation'}) SET n:Operation;
MATCH (n:KGNode {entity_type: 'Problem'}) SET n:Problem;
MATCH (n:KGNode {entity_type: 'Property'}) SET n:Property;
MATCH (n:KGNode {entity_type: 'Protocol'}) SET n:Protocol;
MATCH (n:KGNode {entity_type: 'SyntaxElement'}) SET n:SyntaxElement;
MATCH (n:KGNode {entity_type: 'Topic'}) SET n:Topic;

// 4. 导入关系
// APPLIED_IN
LOAD CSV WITH HEADERS FROM 'file:///relationships.csv' AS row
WITH row WHERE row.relation_type = 'APPLIED_IN'
MATCH (h:KGNode {node_id: row.head})
MATCH (t:KGNode {node_id: row.tail})
MERGE (h)-[r:APPLIED_IN {edge_id: row.edge_id}]->(t)
SET r.head_name = row.head_name,
    r.tail_name = row.tail_name,
    r.reason = row.reason,
    r.source = row.source,
    r.confidence = CASE row.confidence WHEN '' THEN null ELSE toFloat(row.confidence) END,
    r.source_section = row.source_section,
    r.book_page = row.book_page,
    r.evidence_text = row.evidence_text;

// BELONGS_TO_COURSE
LOAD CSV WITH HEADERS FROM 'file:///relationships.csv' AS row
WITH row WHERE row.relation_type = 'BELONGS_TO_COURSE'
MATCH (h:KGNode {node_id: row.head})
MATCH (t:KGNode {node_id: row.tail})
MERGE (h)-[r:BELONGS_TO_COURSE {edge_id: row.edge_id}]->(t)
SET r.head_name = row.head_name,
    r.tail_name = row.tail_name,
    r.reason = row.reason,
    r.source = row.source,
    r.confidence = CASE row.confidence WHEN '' THEN null ELSE toFloat(row.confidence) END,
    r.source_section = row.source_section,
    r.book_page = row.book_page,
    r.evidence_text = row.evidence_text;

// BELONGS_TO_TOPIC
LOAD CSV WITH HEADERS FROM 'file:///relationships.csv' AS row
WITH row WHERE row.relation_type = 'BELONGS_TO_TOPIC'
MATCH (h:KGNode {node_id: row.head})
MATCH (t:KGNode {node_id: row.tail})
MERGE (h)-[r:BELONGS_TO_TOPIC {edge_id: row.edge_id}]->(t)
SET r.head_name = row.head_name,
    r.tail_name = row.tail_name,
    r.reason = row.reason,
    r.source = row.source,
    r.confidence = CASE row.confidence WHEN '' THEN null ELSE toFloat(row.confidence) END,
    r.source_section = row.source_section,
    r.book_page = row.book_page,
    r.evidence_text = row.evidence_text;

// CAUSES
LOAD CSV WITH HEADERS FROM 'file:///relationships.csv' AS row
WITH row WHERE row.relation_type = 'CAUSES'
MATCH (h:KGNode {node_id: row.head})
MATCH (t:KGNode {node_id: row.tail})
MERGE (h)-[r:CAUSES {edge_id: row.edge_id}]->(t)
SET r.head_name = row.head_name,
    r.tail_name = row.tail_name,
    r.reason = row.reason,
    r.source = row.source,
    r.confidence = CASE row.confidence WHEN '' THEN null ELSE toFloat(row.confidence) END,
    r.source_section = row.source_section,
    r.book_page = row.book_page,
    r.evidence_text = row.evidence_text;

// COMPARE_WITH
LOAD CSV WITH HEADERS FROM 'file:///relationships.csv' AS row
WITH row WHERE row.relation_type = 'COMPARE_WITH'
MATCH (h:KGNode {node_id: row.head})
MATCH (t:KGNode {node_id: row.tail})
MERGE (h)-[r:COMPARE_WITH {edge_id: row.edge_id}]->(t)
SET r.head_name = row.head_name,
    r.tail_name = row.tail_name,
    r.reason = row.reason,
    r.source = row.source,
    r.confidence = CASE row.confidence WHEN '' THEN null ELSE toFloat(row.confidence) END,
    r.source_section = row.source_section,
    r.book_page = row.book_page,
    r.evidence_text = row.evidence_text;

// CONFUSED_WITH
LOAD CSV WITH HEADERS FROM 'file:///relationships.csv' AS row
WITH row WHERE row.relation_type = 'CONFUSED_WITH'
MATCH (h:KGNode {node_id: row.head})
MATCH (t:KGNode {node_id: row.tail})
MERGE (h)-[r:CONFUSED_WITH {edge_id: row.edge_id}]->(t)
SET r.head_name = row.head_name,
    r.tail_name = row.tail_name,
    r.reason = row.reason,
    r.source = row.source,
    r.confidence = CASE row.confidence WHEN '' THEN null ELSE toFloat(row.confidence) END,
    r.source_section = row.source_section,
    r.book_page = row.book_page,
    r.evidence_text = row.evidence_text;

// CONTAINS
LOAD CSV WITH HEADERS FROM 'file:///relationships.csv' AS row
WITH row WHERE row.relation_type = 'CONTAINS'
MATCH (h:KGNode {node_id: row.head})
MATCH (t:KGNode {node_id: row.tail})
MERGE (h)-[r:CONTAINS {edge_id: row.edge_id}]->(t)
SET r.head_name = row.head_name,
    r.tail_name = row.tail_name,
    r.reason = row.reason,
    r.source = row.source,
    r.confidence = CASE row.confidence WHEN '' THEN null ELSE toFloat(row.confidence) END,
    r.source_section = row.source_section,
    r.book_page = row.book_page,
    r.evidence_text = row.evidence_text;

// ENSURES
LOAD CSV WITH HEADERS FROM 'file:///relationships.csv' AS row
WITH row WHERE row.relation_type = 'ENSURES'
MATCH (h:KGNode {node_id: row.head})
MATCH (t:KGNode {node_id: row.tail})
MERGE (h)-[r:ENSURES {edge_id: row.edge_id}]->(t)
SET r.head_name = row.head_name,
    r.tail_name = row.tail_name,
    r.reason = row.reason,
    r.source = row.source,
    r.confidence = CASE row.confidence WHEN '' THEN null ELSE toFloat(row.confidence) END,
    r.source_section = row.source_section,
    r.book_page = row.book_page,
    r.evidence_text = row.evidence_text;

// EVALUATED_BY
LOAD CSV WITH HEADERS FROM 'file:///relationships.csv' AS row
WITH row WHERE row.relation_type = 'EVALUATED_BY'
MATCH (h:KGNode {node_id: row.head})
MATCH (t:KGNode {node_id: row.tail})
MERGE (h)-[r:EVALUATED_BY {edge_id: row.edge_id}]->(t)
SET r.head_name = row.head_name,
    r.tail_name = row.tail_name,
    r.reason = row.reason,
    r.source = row.source,
    r.confidence = CASE row.confidence WHEN '' THEN null ELSE toFloat(row.confidence) END,
    r.source_section = row.source_section,
    r.book_page = row.book_page,
    r.evidence_text = row.evidence_text;

// HAS_OPERATION
LOAD CSV WITH HEADERS FROM 'file:///relationships.csv' AS row
WITH row WHERE row.relation_type = 'HAS_OPERATION'
MATCH (h:KGNode {node_id: row.head})
MATCH (t:KGNode {node_id: row.tail})
MERGE (h)-[r:HAS_OPERATION {edge_id: row.edge_id}]->(t)
SET r.head_name = row.head_name,
    r.tail_name = row.tail_name,
    r.reason = row.reason,
    r.source = row.source,
    r.confidence = CASE row.confidence WHEN '' THEN null ELSE toFloat(row.confidence) END,
    r.source_section = row.source_section,
    r.book_page = row.book_page,
    r.evidence_text = row.evidence_text;

// HAS_PROPERTY
LOAD CSV WITH HEADERS FROM 'file:///relationships.csv' AS row
WITH row WHERE row.relation_type = 'HAS_PROPERTY'
MATCH (h:KGNode {node_id: row.head})
MATCH (t:KGNode {node_id: row.tail})
MERGE (h)-[r:HAS_PROPERTY {edge_id: row.edge_id}]->(t)
SET r.head_name = row.head_name,
    r.tail_name = row.tail_name,
    r.reason = row.reason,
    r.source = row.source,
    r.confidence = CASE row.confidence WHEN '' THEN null ELSE toFloat(row.confidence) END,
    r.source_section = row.source_section,
    r.book_page = row.book_page,
    r.evidence_text = row.evidence_text;

// ILLUSTRATED_BY
LOAD CSV WITH HEADERS FROM 'file:///relationships.csv' AS row
WITH row WHERE row.relation_type = 'ILLUSTRATED_BY'
MATCH (h:KGNode {node_id: row.head})
MATCH (t:KGNode {node_id: row.tail})
MERGE (h)-[r:ILLUSTRATED_BY {edge_id: row.edge_id}]->(t)
SET r.head_name = row.head_name,
    r.tail_name = row.tail_name,
    r.reason = row.reason,
    r.source = row.source,
    r.confidence = CASE row.confidence WHEN '' THEN null ELSE toFloat(row.confidence) END,
    r.source_section = row.source_section,
    r.book_page = row.book_page,
    r.evidence_text = row.evidence_text;

// IMPLEMENTED_BY
LOAD CSV WITH HEADERS FROM 'file:///relationships.csv' AS row
WITH row WHERE row.relation_type = 'IMPLEMENTED_BY'
MATCH (h:KGNode {node_id: row.head})
MATCH (t:KGNode {node_id: row.tail})
MERGE (h)-[r:IMPLEMENTED_BY {edge_id: row.edge_id}]->(t)
SET r.head_name = row.head_name,
    r.tail_name = row.tail_name,
    r.reason = row.reason,
    r.source = row.source,
    r.confidence = CASE row.confidence WHEN '' THEN null ELSE toFloat(row.confidence) END,
    r.source_section = row.source_section,
    r.book_page = row.book_page,
    r.evidence_text = row.evidence_text;

// IS_A
LOAD CSV WITH HEADERS FROM 'file:///relationships.csv' AS row
WITH row WHERE row.relation_type = 'IS_A'
MATCH (h:KGNode {node_id: row.head})
MATCH (t:KGNode {node_id: row.tail})
MERGE (h)-[r:IS_A {edge_id: row.edge_id}]->(t)
SET r.head_name = row.head_name,
    r.tail_name = row.tail_name,
    r.reason = row.reason,
    r.source = row.source,
    r.confidence = CASE row.confidence WHEN '' THEN null ELSE toFloat(row.confidence) END,
    r.source_section = row.source_section,
    r.book_page = row.book_page,
    r.evidence_text = row.evidence_text;

// OPTIMIZES
LOAD CSV WITH HEADERS FROM 'file:///relationships.csv' AS row
WITH row WHERE row.relation_type = 'OPTIMIZES'
MATCH (h:KGNode {node_id: row.head})
MATCH (t:KGNode {node_id: row.tail})
MERGE (h)-[r:OPTIMIZES {edge_id: row.edge_id}]->(t)
SET r.head_name = row.head_name,
    r.tail_name = row.tail_name,
    r.reason = row.reason,
    r.source = row.source,
    r.confidence = CASE row.confidence WHEN '' THEN null ELSE toFloat(row.confidence) END,
    r.source_section = row.source_section,
    r.book_page = row.book_page,
    r.evidence_text = row.evidence_text;

// PREREQUISITE_OF
LOAD CSV WITH HEADERS FROM 'file:///relationships.csv' AS row
WITH row WHERE row.relation_type = 'PREREQUISITE_OF'
MATCH (h:KGNode {node_id: row.head})
MATCH (t:KGNode {node_id: row.tail})
MERGE (h)-[r:PREREQUISITE_OF {edge_id: row.edge_id}]->(t)
SET r.head_name = row.head_name,
    r.tail_name = row.tail_name,
    r.reason = row.reason,
    r.source = row.source,
    r.confidence = CASE row.confidence WHEN '' THEN null ELSE toFloat(row.confidence) END,
    r.source_section = row.source_section,
    r.book_page = row.book_page,
    r.evidence_text = row.evidence_text;

// SOLVES
LOAD CSV WITH HEADERS FROM 'file:///relationships.csv' AS row
WITH row WHERE row.relation_type = 'SOLVES'
MATCH (h:KGNode {node_id: row.head})
MATCH (t:KGNode {node_id: row.tail})
MERGE (h)-[r:SOLVES {edge_id: row.edge_id}]->(t)
SET r.head_name = row.head_name,
    r.tail_name = row.tail_name,
    r.reason = row.reason,
    r.source = row.source,
    r.confidence = CASE row.confidence WHEN '' THEN null ELSE toFloat(row.confidence) END,
    r.source_section = row.source_section,
    r.book_page = row.book_page,
    r.evidence_text = row.evidence_text;

// USES
LOAD CSV WITH HEADERS FROM 'file:///relationships.csv' AS row
WITH row WHERE row.relation_type = 'USES'
MATCH (h:KGNode {node_id: row.head})
MATCH (t:KGNode {node_id: row.tail})
MERGE (h)-[r:USES {edge_id: row.edge_id}]->(t)
SET r.head_name = row.head_name,
    r.tail_name = row.tail_name,
    r.reason = row.reason,
    r.source = row.source,
    r.confidence = CASE row.confidence WHEN '' THEN null ELSE toFloat(row.confidence) END,
    r.source_section = row.source_section,
    r.book_page = row.book_page,
    r.evidence_text = row.evidence_text;


// 5. 导入后检查
MATCH (n) RETURN count(n) AS 节点数;
MATCH ()-[r]->() RETURN count(r) AS 关系数;
MATCH (n:KGNode) RETURN n.course AS course, count(n) AS nodes ORDER BY nodes DESC;
MATCH ()-[r]->() RETURN type(r) AS relation_type, count(r) AS cnt ORDER BY cnt DESC;
