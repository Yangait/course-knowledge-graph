"""Build a lossless, offline interchange package; never connect to Neo4j or an LLM."""
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "26门课程知识图谱_最终数据_含图片" / "26门课程知识图谱_最终数据"
OUTPUT = ROOT / "unified_kg"
COURSE_ALIASES = {"数据库系统概论": "数据库"}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def fingerprint(path):
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def jsonlines(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def build():
    nodes, edges, course_entries, files, candidates = {}, {}, [], [], []
    courses = [(p, read_json(p)) for p in sorted((SOURCE / "courses").glob("*.json"))]
    index = read_json(SOURCE / "总索引.json")
    overview = read_json(SOURCE / "跨课程总览.json")
    course_ids, roots, name_index = {}, {}, defaultdict(list)
    image_checks = 0

    def node(key, name, kind, origin, source_file, payload, course_id=None, searchable=True):
        if key in nodes:
            raise ValueError(f"Duplicate node: {key}")
        nodes[key] = dict(node_id=key, name=name, entity_type=kind, course_id=course_id,
                          origin=origin, source_file=source_file, searchable=searchable, properties=payload)

    def edge(key, head, tail, kind, origin, payload=None, direction="forward"):
        if key in edges:
            raise ValueError(f"Duplicate edge: {key}")
        edges[key] = dict(edge_id=key, head=head, tail=tail, relation_type=kind,
                          origin=origin, direction=direction, properties=payload or {})

    node("CATALOG:ROOT", "计算机课程知识图谱", "catalog", "integration", None, {}, searchable=False)
    for path, course in courses:
        files.append(fingerprint(path))
        meta = course["meta"]
        cid, cname = meta["course_id"], meta["course_name"]
        course_ids[cname] = cid
        root = course["main_tree"]
        if len(root) != 1:
            raise ValueError(f"Expected one root: {cid}")
        roots[cid] = root[0]["id"]
        flat = course["knowledge_nodes"]
        tree_ids, tree_pairs = [], set()

        def visit(items, parent=None):
            for item in items:
                tree_ids.append(item["id"])
                if parent:
                    tree_pairs.add((parent, item["id"]))
                visit(item.get("children", []), item["id"])

        visit(root)
        actual_pairs = {(e["source_id"], e["target_id"]) for e in course["hierarchy_relations"]}
        if (Counter(tree_ids) != Counter(n["id"] for n in flat)
                or len(tree_ids) != len(set(tree_ids)) or tree_pairs != actual_pairs
                or len(course["hierarchy_relations"]) != len(flat) - 1):
            raise ValueError(f"Tree mismatch: {cid}")
        parent_pairs = {(n["parent_id"], n["id"]) for n in flat if n.get("parent_id")}
        if parent_pairs != tree_pairs:
            raise ValueError(f"Parent mismatch: {cid}")
        course_entries.append(dict(course_id=cid, name=cname, root_id=roots[cid],
                                   file=f"courses/{path.name}", source_file=meta["source_file"],
                                   knowledge_nodes=len(flat), images=len(course["images"])))
        groups = [flat, course["floating_topics"]["roots"], course["floating_topics"]["items"],
                  course["summary_blocks"], course["summary_items"], course["callouts"],
                  course["boundary_groups"], course["structural_anchors"]]
        for group in groups:
            for item in group:
                kind = item["entity_type"]
                node(item["id"], item.get("label", ""), kind, "emmx", meta["source_file"], item, cid,
                     kind not in {"boundary_group", "structural_anchor"})
        for item in flat:
            name_index[(cid, item["label"].strip().casefold())].append(item["id"])
        edge(f"CATALOG:{cid}", "CATALOG:ROOT", roots[cid], "HAS_COURSE", "integration")
        for item in course["hierarchy_relations"]:
            edge(item["id"], item["source_id"], item["target_id"], "CONTAINS", "emmx", item)
        for item in course["semantic_relations"]:
            edge(item["id"], item["source_id"], item["target_id"], "SEMANTIC_LINK", "emmx", item, item["direction"])
        for group in [course["floating_topics"]["items"], course["summary_items"]]:
            for item in group:
                if item.get("parent_id"):
                    edge(f"AUX:PARENT:{item['id']}", item["parent_id"], item["id"], "CONTAINS_AUXILIARY", "emmx")
        for group, field, rel in [(course["callouts"], "target_ids", "ANNOTATES"),
                                  (course["summary_blocks"], "covered_entity_ids", "SUMMARIZES"),
                                  (course["boundary_groups"], "member_entity_ids", "GROUP_MEMBER")]:
            for item in group:
                for target in dict.fromkeys(item[field]):
                    edge(f"AUX:{rel}:{item['id']}:{target}", item["id"], target, rel, "emmx")
        for item in course["structural_anchors"]:
            if item.get("nearest_parent_id"):
                edge(f"AUX:ANCHOR:{item['id']}", item["nearest_parent_id"], item["id"], "HAS_STRUCTURE", "emmx")
        for item in course["images"]:
            media = (SOURCE / item["file"]).resolve()
            if not media.is_relative_to(SOURCE.resolve()):
                raise ValueError(f"Unsafe image path: {item['id']}")
            if media.stat().st_size != item["file_size"] or hashlib.sha256(media.read_bytes()).hexdigest() != item["sha256"]:
                raise ValueError(f"Image mismatch: {item['id']}")
            image_checks += 1
            node(item["id"], Path(item["file"]).name, "image", "emmx", meta["source_file"], item, cid, False)
            if item.get("owner_id"):
                edge(f"AUX:IMAGE:{item['id']}", item["owner_id"], item["id"], "HAS_IMAGE", "emmx")

    for item in overview["nodes"]:
        cid = item.get("linked_course_id")
        node(item["id"], item["label"], item["entity_type"], "emmx_overview", overview["meta"]["source_file"], item, cid, False)
        if cid:
            edge(f"MAP:{item['id']}", item["id"], roots[cid], "REFERS_TO_COURSE", "integration")
    for item in overview["relations"]:
        edge(item["id"], item["source_id"], item["target_id"], "SEMANTIC_LINK", "emmx_overview", item, item["direction"])

    legacy_path = ROOT / "neo4j_import_files" / "nodes.csv"
    legacy_nodes = read_csv(legacy_path)
    files.append(fingerprint(legacy_path))
    legacy_courses = []
    for item in legacy_nodes:
        cid = course_ids.get(COURSE_ALIASES.get(item["course"], item["course"]))
        if not cid:
            raise ValueError(f"Unmapped legacy course: {item['course']}")
        key = "LEGACY:" + item["node_id"]
        node(key, item["name"], item["entity_type"], "legacy_csv", item["source"], item, cid)
        if item["entity_type"] == "Course":
            legacy_courses.append(key)
            edge(f"MAP:{key}", key, roots[cid], "COURSE_EDITION_OF", "integration",
                 {"basis": "明确课程名称映射；保留两套课程内容", "course_id": cid})
        else:
            matches = name_index.get((cid, item["name"].strip().casefold()), [])
            if matches:
                candidates.append(dict(legacy_node_id=key, name=item["name"], course_id=cid,
                                       candidate_node_ids=matches, status="pending_review",
                                       basis="同课程名称完全匹配；尚未验证语义与层级，不作为图谱等价关系"))
    for filename in ["relationships.csv", "cross_course_relationships.csv"]:
        path = ROOT / "neo4j_import_files" / filename
        files.append(fingerprint(path))
        for item in read_csv(path):
            edge("LEGACY:" + item["edge_id"], "LEGACY:" + item["head"], "LEGACY:" + item["tail"],
                 item["relation_type"], "legacy_csv", item)

    # Validate every endpoint and image backlink before writing any published output.
    for item in edges.values():
        if item["head"] not in nodes or item["tail"] not in nodes:
            raise ValueError(f"Dangling edge: {item['edge_id']}")
    for item in nodes.values():
        for iid in item["properties"].get("image_ids", []):
            if iid not in nodes or nodes[iid]["entity_type"] != "image":
                raise ValueError(f"Dangling image: {item['node_id']} -> {iid}")
    actual = dict(main_knowledge_nodes=sum(len(c["knowledge_nodes"]) for _, c in courses),
                  hierarchy_relations=sum(len(c["hierarchy_relations"]) for _, c in courses),
                  semantic_relations=sum(len(c["semantic_relations"]) for _, c in courses), images=image_checks)
    for key, count in actual.items():
        if count != index["totals"][key]:
            raise ValueError(f"Source total mismatch: {key}")
    if len(courses) != index["course_count"]:
        raise ValueError("Course count mismatch")

    stats = dict(courses=len(courses), nodes=len(nodes), edges=len(edges),
                 legacy_nodes=len(legacy_nodes), legacy_courses=len(legacy_courses),
                 candidate_mappings=len(candidates),
                 nodes_by_origin=dict(Counter(n["origin"] for n in nodes.values())),
                 edges_by_origin=dict(Counter(e["origin"] for e in edges.values())),
                 node_types=dict(Counter(n["entity_type"] for n in nodes.values())),
                 edge_types=dict(Counter(e["relation_type"] for e in edges.values())), **actual)
    for filename in ["总索引.json", "跨课程总览.json"]:
        files.append(fingerprint(SOURCE / filename))
    manifest = dict(schema_version="unified-kg-1", catalog_root="CATALOG:ROOT", statistics=stats,
                    media_base_relative_to_manifest="../" + SOURCE.relative_to(ROOT).as_posix(),
                    courses=course_entries, inputs=files,
                    legacy_source="本地 neo4j_import_files 导入快照；未连接数据库核实当前状态",
                    original_emmx_available=False,
                    policies={"same_name": "候选映射不等于同一实体，未自动合并", "semantic_direction": "保留原始 forward/backward/both/none；反向、双向和无方向不能按存储箭头推断单向因果",
                              "source_trust": "旧版声明的教材来源及内容未经原教材复核", "images": "保留资源和归属，尚未 OCR 或多模态解读",
                              "media": "图片留在原始包，不能单独移动 unified_kg 后丢弃原始包"})
    OUTPUT.mkdir(exist_ok=True)
    for path, course in courses:
        dump(OUTPUT / "courses" / path.name, course)
    dump(OUTPUT / "overview.json", overview)
    jsonlines(OUTPUT / "nodes.jsonl", nodes.values())
    jsonlines(OUTPUT / "edges.jsonl", edges.values())
    jsonlines(OUTPUT / "mapping_candidates.jsonl", candidates)
    dump(OUTPUT / "manifest.json", manifest)
    dump(OUTPUT / "validation.json", dict(status="passed", checks=["唯一节点与关系编号", "26门课程树与平铺节点及父子边一致",
         "所有边端点存在", "图片反向引用存在", "1039张图片大小和SHA256一致", "源统计一致"], statistics=stats))
    report = f"""# 第一阶段：统一知识图谱数据整理报告

已生成可供后续 Neo4j 导入与网页导图使用的统一数据包。本阶段没有修改现有问答代码，没有调用模型，也没有写入数据库。

## 整理结果

- 课程：{len(courses)} 门；新版主知识节点：{actual['main_knowledge_nodes']:,}。
- 新版层级关系：{actual['hierarchy_relations']:,}；课程内部语义关系：{actual['semantic_relations']:,}。
- 旧版节点 {len(legacy_nodes):,} 个、关系 10,630 条全部保留，含定义、别名、页码、证据和关系说明。
- 统一包共 {len(nodes):,} 个实体、{len(edges):,} 条关系。实体包括知识点、图片、注释和辅助结构，不能全部称作知识点；关系包括派生的课程入口和内容归属关系。
- 图片 {image_checks:,} 张全部通过文件大小与 SHA256 校验；未提取图片内文字。
- {len(legacy_courses)} 个旧版课程入口已关联新版课程；{len(candidates)} 个旧知识点有同课程同名候选，未自动合并或传播其定义。

## 已保留的细节

完整课程树、浮动项、总结块及明细、注释、原始关系文字和方向、布局坐标、图片归属、重复项标记及已移除占位记录。各源记录原字段保存在 properties 中，课程 JSON 保留完整原对象。

## 使用方式

- `manifest.json`：26门课程入口、规模、源文件指纹、媒体位置。
- `nodes.jsonl` / `edges.jsonl`：统一实体与关系，每行一个 JSON；不是可直接送入旧版 CSV 导入脚本的文件。
- `courses/`：供网页导图使用，保留原始 main_tree、layout、images 等结构；与统一图谱共享知识点编号。
- `overview.json`：原始跨课程总览，已通过 REFERS_TO_COURSE 关联对应课程根节点。
- `mapping_candidates.jsonl`：待审核的同名映射，不属于可信等价关系。
- `validation.json`：本次机器校验结果。

## 边界与后续接入要求

1. 使用已解析的26门课程数据包；当前没有原 EMMX 文件，无法重新核对解析是否忠实于源导图。
2. 旧版使用本地 CSV 快照，未核实其与运行中 Neo4j 的一致性；原有教材引用未经教材原件复核。
3. 新版课程内部194条关系没有明确名称，仍保留原状态，不能擅自当作“前置知识”。跨课程总览缺少 C20；统一课程入口包含 C20，但未凭空增加学科关系。
4. 8组潜在重复项保留。候选同名映射只供审核，不能自动当作等价知识传播证据。
5. 图片仍位于原始数据包；根据 manifest 的媒体根路径与图片 file 字段定位，需同时保留两个目录。
6. Neo4j 属性不支持嵌套对象；下一阶段需编写新适配器，选择性展开字段并序列化原始 properties，同时保留语义关系方向。
7. 网页展示以新版课程树为主，旧版作为有来源的补充内容；问答检索要排除无文字结构实体，并区别层级关系、语义关系和资料归属关系。

复现：在项目根目录执行 `kg_qa_system\\.venv\\Scripts\\python.exe tools\\build_unified_graph.py`。脚本仅写入 unified_kg，不连接任何外部服务。
"""
    (OUTPUT / "整合报告.md").write_text(report, encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    build()
