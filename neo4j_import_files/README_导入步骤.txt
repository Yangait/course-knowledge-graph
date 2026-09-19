Neo4j 导入文件说明

本目录包含：
1. nodes.csv
2. relationships.csv
3. cross_course_relationships.csv
4. import_incremental.py
5. import_neo4j.cypher
6. check_queries.cypher

数据规模：
- 课程数：9
- 节点数：2701
- 课程内部关系数：10472
- 跨课程关系数：158
- 关系总数：10630
- 实体类型：16
- 关系类型：18

推荐使用方法（增量导入，不清空数据库）：
1. 启动 Neo4j Desktop 中的 course-kg 实例。
2. 在项目虚拟环境中安装 neo4j 和 python-dotenv。
3. 在本目录运行：
   ..\kg_qa_system\.venv\Scripts\python.exe import_incremental.py
4. 运行 check_queries.cypher 中的查询做检查和展示。

传统LOAD CSV方法：
1. 将三个CSV复制到Neo4j实例的import文件夹。
2. 在Neo4j Browser中运行import_neo4j.cypher。
3. 注意：import_neo4j.cypher目前主要导入节点和课程内部关系；
   跨课程关系推荐使用import_incremental.py统一导入。

注意：
- import_incremental.py 使用MERGE，可安全重复运行。
- import_neo4j.cypher 已取消默认清空数据库。
- 不要在未备份时手动运行 MATCH (n) DETACH DELETE n。
