// 常用检查 / 展示查询

// 1. 查看总规模
MATCH (n) RETURN count(n) AS 节点数;
MATCH ()-[r]->() RETURN count(r) AS 关系数;

// 2. 查看九门课程节点数量
MATCH (n:KGNode)
RETURN n.course AS 课程, count(n) AS 节点数
ORDER BY 节点数 DESC;

// 3. 查询某个知识点的一跳关系，例如“栈”
MATCH p=(n:KGNode {name:'栈'})-[r]-(m)
RETURN p
LIMIT 50;

// 4. 查询某门课的章节结构，例如“操作系统”
MATCH p=(c:Course {name:'操作系统'})-[r:CONTAINS]->(t:Topic)
RETURN p
LIMIT 100;

// 5. 查询一个知识点的前置知识
MATCH p=(pre)-[:PREREQUISITE_OF]->(n:KGNode {name:'虚拟内存'})
RETURN p
LIMIT 50;

// 6. 查询跨课程关系
MATCH p=(a:KGNode)-[r]->(b:KGNode)
WHERE a.course <> b.course
RETURN p
LIMIT 100;

// 7. 查询某种关系数量
MATCH ()-[r]->()
RETURN type(r) AS 关系类型, count(r) AS 数量
ORDER BY 数量 DESC;
