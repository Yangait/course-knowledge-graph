# 26门课程知识图谱最终数据

这是从 `！！！最终emmx版本.zip` 重新解析并完成最终结构校验的数据版本。**不包含网站代码。**

## 推荐使用顺序

- 查看总体情况：`总索引.json`
- 查看校验过程：`reports/质量校验报告.md`
- 单门课程开发：`courses/Cxx_课程名.json`
- Excel/数据库导入：`tables/*.csv`
- 图片展示：`media/Cxx/`

## 单门课程 JSON 主要字段

- `main_tree`：清理后的课程主知识树
- `knowledge_nodes`：主知识节点平铺表
- `hierarchy_relations`：父子层级
- `floating_topics`：原 EMMX 的 Floating 节点及下级内容
- `summary_blocks` / `summary_items`：总结块和总结明细
- `callouts`：注释
- `semantic_relations`：额外知识关系
- `images`：图片元数据和本地文件路径
- `boundary_groups` / `structural_anchors`：只为完整保留原关系而存在的辅助结构
- `potential_duplicates`：疑似重复但未自动删除的源节点

## Neo4j 建议

主知识节点可作为 `:Knowledge`，`hierarchy_relations` 导入 `:CONTAINS`。
`semantic_relations` 建议先保留 `relation_text` 作为关系属性，后续再根据项目需要规范化关系类型，避免错误合并语义。

## 数据规模

主知识节点 18,391，层级关系 18,365，语义关系 732，图片 1,039。
