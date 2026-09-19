"""Course diagrams and source details. Only manifest-listed media are served."""
import json
import logging
from functools import lru_cache
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from neo4j.exceptions import DriverError, Neo4jError

from unified_graph import PACKAGE, graph_scope, neighbors, node_record, relative_direction

# Website assets are independent of the versioned Neo4j import package.
MINDMAP_PACKAGE = PACKAGE.parent / "web_mindmaps"
REMOVED_AUXILIARY_MAPS = {"M02", "M03", "M04", "M05"}


def display_package():
    return MINDMAP_PACKAGE if (MINDMAP_PACKAGE / "manifest.json").is_file() else PACKAGE

router = APIRouter()


@lru_cache(maxsize=1)
def manifest():
    data = json.loads((display_package() / "manifest.json").read_text(encoding="utf-8"))
    data["overviews"] = [m for m in data.get("overviews", []) if m["course_id"] not in REMOVED_AUXILIARY_MAPS]
    data["statistics"]["overviews"] = len(data["overviews"])
    return data


@lru_cache(maxsize=32)
def course_data(course_id):
    entry = next((c for c in [*manifest()["courses"], *manifest().get("overviews", [])]
                  if c["course_id"] == course_id), None)
    if not entry:
        raise HTTPException(404, "课程不存在")
    return json.loads((display_package() / entry["file"]).read_text(encoding="utf-8"))


@router.get("/api/graph/courses")
def courses():
    return {"courses": manifest()["courses"], "overviews": manifest().get("overviews", []),
            "statistics": manifest()["statistics"]}


@router.get("/api/graph/courses/{course_id}")
def course(course_id: str):
    data = course_data(course_id)
    original = original_map(course_id)
    return dict(data, original_map=original) if original else data


@lru_cache(maxsize=32)
def original_map(course_id):
    if not any(c["course_id"] == course_id for c in [*manifest()["courses"], *manifest().get("overviews", [])]):
        return None
    path = MINDMAP_PACKAGE / "original" / f"{course_id}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


@router.get("/api/graph/courses/{course_id}/original.svg")
def original_svg(course_id: str, request: Request, source: bool = False):
    original = original_map(course_id)
    if not original:
        raise HTTPException(404, "此课程暂无原图")
    root = (MINDMAP_PACKAGE / "original").resolve()
    path = (root / original["file" if source else "display_file"]).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(404, "原图文件不存在")
    headers = {"X-Content-Type-Options": "nosniff", "Vary": "Accept-Encoding",
               "Cache-Control": "public, max-age=3600" if request.query_params.get("v") else "no-cache",
               "Content-Security-Policy": "default-src 'none'; img-src data:; style-src 'unsafe-inline'; sandbox"}
    # Send precompressed large diagrams; decompressed SVG remains the exact display asset.
    gzip_ok = False
    for part in request.headers.get("accept-encoding", "").split(","):
        fields = [s.strip() for s in part.split(";")]
        if fields[0].lower() == "gzip":
            try:
                gzip_ok = all(float(s[2:]) > 0 for s in fields[1:] if s.startswith("q="))
            except ValueError:
                gzip_ok = False
    compressed = path.with_suffix(path.suffix + ".gz")
    if gzip_ok and not source and compressed.is_file():
        path = compressed
        headers["Content-Encoding"] = "gzip"
    return FileResponse(path, media_type="image/svg+xml", headers=headers)


@lru_cache(maxsize=32)
def display_index(course_id):
    c = course_data(course_id)
    nodes = [*c["knowledge_nodes"], *c["floating_topics"]["roots"], *c["floating_topics"]["items"],
             *c["summary_blocks"], *c["summary_items"], *c["callouts"],
             *c["structural_anchors"], *c["boundary_groups"], *(original_map(course_id) or {}).get("extra_nodes", [])]
    return {n["id"]: n for n in nodes}


def local_node(node_id):
    parts = node_id.split(":")
    source_only = len(parts) == 3 and parts[0] == "SVG"
    cid = parts[1] if source_only else parts[0]
    if not any(c["course_id"] == cid for c in [*manifest()["courses"], *manifest().get("overviews", [])]):
        return None
    c, index = course_data(cid), display_index(cid)
    p = index.get(node_id)
    if p is None:
        return None
    related = []

    def relation(source, target, kind, direction="forward", text=None):
        if node_id not in {source, target}:
            return
        other = target if source == node_id else source
        if other not in index:
            return
        related.append(dict(related_node_id=other, related_name=index[other]["label"], related_course_id=cid,
                            relation_type=kind, relation_text=text,
                            direction=relative_direction(direction, source == node_id)))

    for r in c["hierarchy_relations"]:
        relation(r["source_id"], r["target_id"], "CONTAINS")
    for r in c["semantic_relations"]:
        relation(r["source_id"], r["target_id"], "SEMANTIC_LINK", r["direction"], r.get("relation_text"))
    for group in [c["floating_topics"]["items"], c["summary_items"]]:
        for item in group:
            if item.get("parent_id"):
                relation(item["parent_id"], item["id"], "CONTAINS_AUXILIARY")
    for group, field, kind in [(c["callouts"], "target_ids", "ANNOTATES"),
                               (c["summary_blocks"], "covered_entity_ids", "SUMMARIZES"),
                               (c["boundary_groups"], "member_entity_ids", "GROUP_MEMBER")]:
        for item in group:
            for target in item.get(field, []):
                relation(item["id"], target, kind)
    for item in c["structural_anchors"]:
        if item.get("nearest_parent_id"):
            relation(item["nearest_parent_id"], item["id"], "HAS_STRUCTURE")
    original = original_map(cid) or {}
    for r in original.get("source_relations", []):
        relation(r["source_id"], r["target_id"], r["relation_type"], r["direction"], r.get("relation_text"))
    images = [dict(i, url="/api/graph/image?image_id=" + quote(i["id"])) for i in c["images"]
              if i.get("owner_id") == node_id or i["id"] in p.get("image_ids", [])]
    return dict(node=dict(node_id=node_id, name=p["label"], course_id=cid, course=c["meta"]["course_name"],
                          origin="svg" if source_only else "emmx", path=p.get("path"), searchable=cid.startswith("C") and not source_only,
                          source=original["source_file"] if source_only else c["meta"]["source_file"], ask_source="mindmap"), details=p,
                relationships=related, relationships_truncated=False, images=images,
                question_prompt=(f"请解释{c['meta']['course_name']}中的“{p['label']}”。知识路径：{p.get('path', p['label'])}"[:480]
                                 if source_only else None))


@router.get("/api/graph/node")
def node(node_id: str = Query(min_length=1, max_length=160)):
    local = local_node(node_id) if display_package() == MINDMAP_PACKAGE else None
    if local:
        # Preserve existing cross-course/legacy relationships alongside new display content.
        if node_id.startswith("C"):
            try:
                with graph_scope():
                    original = neighbors(node_id, 150)
                key = lambda r: (r["related_node_id"], r["relation_type"], r["direction"], r.get("relation_text"))
                known = {key(r) for r in local["relationships"]}
                for r in original:
                    if r["relation_type"] != "HAS_IMAGE" and key(r) not in known:
                        local["relationships"].append(r)
                        known.add(key(r))
                local["relationships_truncated"] = len(original) >= 150
            except (DriverError, Neo4jError, RuntimeError):
                logging.getLogger(__name__).info("Neo4j unavailable; serving converted mindmap details")
        return local
    with graph_scope():
        record = node_record(node_id)
        if not record:
            raise HTTPException(404, "知识点不存在")
        payload = json.loads(record.pop("properties_json", "{}"))
        record.pop("dataset_id", None)
        related = neighbors(node_id, 150)
    images = []
    if record.get("course_id"):
        c = course_data(record["course_id"])
        for item in c["images"]:
            if item.get("owner_id") == node_id or item["id"] in payload.get("image_ids", []):
                images.append(dict(item, url="/api/graph/image?image_id=" + quote(item["id"])))
    return dict(node=record, details=payload, relationships=related, images=images,
                relationships_truncated=len(related) == 150)


@router.get("/api/graph/image")
def image_file(image_id: str = Query(min_length=1, max_length=160)):
    cid = image_id.split(":", 1)[0]
    images = course_data(cid)["images"]
    item = next((i for i in images if i["id"] == image_id), None)
    if not item:
        raise HTTPException(404, "图片不存在")
    root = (display_package() / manifest()["media_base_relative_to_manifest"]).resolve()
    path = (root / item["file"]).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(404, "图片文件不存在")
    return FileResponse(path, headers={"X-Content-Type-Options": "nosniff"})
