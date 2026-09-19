# 26门课程统一图谱的 Neo4j 接入

使用现有 `kg_qa_system/.env` 中的 Neo4j 连接配置，不涉及大模型配置。

## 导入方式

在项目根目录执行：

```powershell
# 离线校验和生成导入计划，不连接数据库
.\kg_qa_system\.venv\Scripts\python.exe tools\import_unified_neo4j.py

# 数据库启动后执行实际导入
.\kg_qa_system\.venv\Scripts\python.exe tools\import_unified_neo4j.py --apply

# 只读核对数据库中的全部实体、关系、属性和端点
.\kg_qa_system\.venv\Scripts\python.exe tools\import_unified_neo4j.py --verify-only
```

## 保留旧数据与版本管理

原有问答系统使用 `KGNode`，本次导入只写 `UnifiedKGNode` 和 `UnifiedKGDataset`，不删除、改写旧图谱。旧 CSV 的补充内容在新版图谱中使用 `LEGACY:` 编号，因此数据库总节点数会包含旧系统数据和新版数据各自的记录，不代表实体已去重。

版本编号由本次 manifest、实体文件和关系文件内容计算，保存在生成的 `neo4j_import_plan.json` 中。相同数据重跑会复用同一版本；已导入并验收通过的版本只进行核对。数据修改后产生新版本，不覆盖之前版本。请勿同时启动多个导入进程。

导入按批次提交；中断可能留下部分版本数据，但不会将它标为可用。排除故障后，使用同一数据包重新执行 `--apply` 可补齐。只有完成全部属性比对、关系端点比对及旧图谱前后指纹核对，版本状态才变为 `ready`。

## 查看课程入口

在 Neo4j Browser 中执行：

```cypher
MATCH (d:UnifiedKGDataset)
RETURN d.dataset_id, d.status, d.node_count, d.relationship_count;
```

将返回的目标版本编号用于查询：

```cypher
MATCH (n:UnifiedKGNode {dataset_id: '替换为版本编号', entity_type: 'course_root'})
RETURN n.course_id, n.name ORDER BY n.course_id;
```

后续网页与问答必须显式选择状态为 `ready` 的版本，并限制查询的 `dataset_id`。当前问答代码尚未切换，仍读取原来的九门课程。

## 属性与语义约定

- 知识点名称、课程、定义、路径、来源、别名、图片编号等可查询字段展开为属性。
- 完整源记录保存于 `properties_json`；嵌套结构不能直接存为 Neo4j 属性，因此采用 JSON 字符串保存。
- 媒体保存路径和校验值，不将图片二进制内容存进 Neo4j。图片定位使用 manifest 中的媒体根路径。
- `SEMANTIC_LINK` 的真实关系文字在 `relation_text`；无标签关系不编造名称。
- 图中存储箭头沿原始 source_id 到 target_id。解释语义方向必须读取 `direction`：`forward` 正向，`backward` 反向，`both` 双向，`none` 无方向。不得直接用箭头推断先修或因果。
- `COURSE_EDITION_OF`、`REFERS_TO_COURSE` 为资料入口映射；它们不是知识点等价关系。
- 611个同名候选保留在本地审核文件，不导入为可信等价关系。

导入成功后生成 `neo4j_import_result.json`；只有该文件报告 `ready` 或 `already_ready` 且本次命令成功，才算完成数据库接入。离线计划的 `validated` 仅表示数据通过预检。
