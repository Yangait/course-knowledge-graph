"""Read the selected website diagram as evidence, independently of Neo4j IDs."""
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from collections import defaultdict, deque
from functools import lru_cache
from html.parser import HTMLParser

from fastapi import HTTPException
from neo4j.exceptions import DriverError, Neo4jError

from graph_routes import MINDMAP_PACKAGE, course_data, display_index, original_map
from unified_graph import find_entity_candidates, graph_scope, query_entity_context, query_related_nodes

SVG = "{http://www.w3.org/2000/svg}"
ED = "{https://www.edrawsoft.com/xml/2017/SVGExtensions/}"


class NoteText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, text):
        self.parts.append(text)

    def handle_endtag(self, tag):
        if tag in {"p", "div", "li", "br"}:
            self.parts.append("\n")


def bounded(text, limit=4000):
    text = str(text or "").strip()
    return text if len(text) <= limit else text[:limit] + "…（内容已截取）"


def block_text(node, field):
    return "\n".join(b["text"] for b in node.get(field, []) if b.get("type") == "text" and b.get("text"))


def course_id_for(node_id):
    parts = node_id.split(":")
    return parts[1] if len(parts) == 3 and parts[0] == "SVG" else parts[0]


@lru_cache(maxsize=8)
def diagram_nodes(cid):
    """Cache extracted text only; never retain the potentially large SVG image tree."""
    course, index, original = course_data(cid), display_index(cid), original_map(cid)
    nodes = {}
    for key, n in index.items():
        nodes[key] = dict(node_id=key, name=n["label"], path=n.get("path", n["label"]),
                          parent_id=n.get("parent_id"), text=block_text(n, "content_blocks") or n.get("definition") or n.get("text", ""),
                          notes=block_text(n, "note_blocks") or n.get("note_text", ""),
                          image_count=len(n.get("image_ids", [])), source=course["meta"]["source_file"])
    if not original:
        return nodes, []
    root = (MINDMAP_PACKAGE / "original").resolve()
    path = (root / original["file"]).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(404, "导图原文件不存在")
    tree = ET.parse(path).getroot()
    groups = {g.get("id"): g for g in tree if g.tag == SVG + "g" and g.get(ED + "width")}
    bindings = {h["source_id"]: h["id"] for h in original["hotspots"]}
    original_ids = set(bindings.values())
    relations = []
    for sid, key in bindings.items():
        group, n = groups.get(sid), nodes.get(key)
        if group is None or n is None:
            continue
        text = "".join("".join(e.itertext()) for e in group.findall(SVG + "text")).strip()
        parser = NoteText()
        for e in group.iter():
            if e.get(ED + "note"):
                parser.feed(e.get(ED + "note"))
        notes = "".join(parser.parts).strip()
        n["source"] = original["source_file"]
        n["name"] = text if text and text != "中心主题" else n["name"]
        # SVG text/notes are authoritative. Matched, newly converted EMMX is supplementary text.
        if course["meta"].get("conversion_status") == "compatibility_copy" or original.get("separate_edition"):
            n["text"], n["notes"] = text, notes
        else:
            n["text"] = text or n["text"]
            if notes:
                n["notes"] = notes
            elif n["notes"]:
                n["source"] += "；备注：" + course["meta"]["source_file"]
        parent, seen = group.get(ED + "parentid"), set()
        while parent and parent not in bindings and parent in groups and parent not in seen:
            seen.add(parent)
            parent = groups[parent].get(ED + "parentid")
        n["parent_id"] = bindings.get(parent)
    for key in original_ids:
        n = nodes.get(key)
        if not n:
            continue
        chain, seen, current = [], set(), n
        while current and current["node_id"] not in seen:
            seen.add(current["node_id"])
            chain.append(current["name"])
            current = nodes.get(current["parent_id"])
        chain.reverse()
        if key != original["root_id"] and chain[0] != course["meta"]["course_name"]:
            chain.insert(0, course["meta"]["course_name"])
        n["path"] = " > ".join(chain)
    for group in tree:
        if group.get(ED + "type") != "relation":
            continue
        a, b = bindings.get(group.get(ED + "fromid")), bindings.get(group.get(ED + "toid"))
        if a and b:
            label = "".join("".join(e.itertext()) for e in group.findall(SVG + "text")).strip()
            relations.append(dict(source_id=a, target_id=b, relation_text=label if label not in {"", "标签"} else "原图关联（未命名）"))
    return nodes, relations


def build_mindmap_context(node_id, question=""):
    cid = course_id_for(node_id)
    course = course_data(cid)
    nodes, relations = diagram_nodes(cid)
    selected = nodes.get(node_id)
    if selected is None:
        raise HTTPException(404, "当前导图中没有这个知识点，请重新选择")
    original = original_map(cid) or {}
    original_ids = {h["id"] for h in original.get("hotspots", [])}
    # The compact diagram's shared root must never pull in the full edition's children.
    source_ids = original_ids if original.get("separate_edition") and node_id in original_ids else set(nodes)
    children = defaultdict(list)
    for n in nodes.values():
        if n["parent_id"] in source_ids and n["node_id"] in source_ids:
            children[n["parent_id"]].append(n["node_id"])
    queue, seen, descendants = deque(children[node_id]), {node_id}, []
    while queue:
        key = queue.popleft()
        if key in seen:
            continue
        seen.add(key)
        descendants.append(nodes[key])
        queue.extend(children[key])
    # Prioritize explicitly named branches while retaining breadth for general explanations.
    terms = set(re.findall(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]{2,}", question.casefold()))
    def score(n):
        name = n["name"].casefold()
        return int(len(name) >= 2 and name in question.casefold()) * 100 + sum(t in n["path"].casefold() for t in terms)
    descendants.sort(key=score, reverse=True)
    def record(n):
        return {key: bounded(n.get(key), 4000 if key in {"text", "notes"} else 1200)
                for key in ("node_id", "name", "path", "text", "notes", "source")}
    related = []
    for r in relations:
        if node_id in {r["source_id"], r["target_id"]}:
            other = r["target_id"] if r["source_id"] == node_id else r["source_id"]
            related.append(dict(record(nodes[other]), relation=r["relation_text"]))
    # Annotations attached to converted branches are separate from definitions.
    annotations = []
    if course["meta"].get("conversion_status") == "converted" and not (original.get("separate_edition") and node_id in original_ids):
        for n in [*course["callouts"], *course["summary_blocks"]]:
            if seen.intersection(n.get("target_ids", []) + n.get("covered_entity_ids", [])) and n["id"] in nodes:
                annotations.append(record(nodes[n["id"]]))
    result = dict(record(selected), evidence_type="mindmap_context", origin="web_mindmap",
                  course_id=cid, course=course["meta"]["course_name"],
                  descendants=[record(n) for n in descendants[:80]], related=related[:12], annotations=annotations[:12],
                  image_count=selected["image_count"], truncated=len(descendants) > 80)
    # Bound the whole record without the old renderer's 800-character note truncation.
    for key in ("annotations", "related", "descendants"):
        while result[key] and len(json.dumps(result, ensure_ascii=False)) > 22000:
            result[key].pop()
            result["truncated"] = True
    if "…（内容已截取）" in json.dumps(result, ensure_ascii=False):
        result["truncated"] = True
    return result


def normalized_name(value):
    value = unicodedata.normalize("NFKC", value or "").casefold()
    value = re.sub(r"^\s*\d+(?:\.\d+)*[.、\s]+", "", value)
    return re.sub(r"\s+", "", value)


def same_concept(primary, candidate):
    """Conservative cross-source matching: course, name and complete path, never ID alone."""
    if candidate.get("course_id") != primary["course_id"] or normalized_name(candidate.get("name")) != normalized_name(primary["name"]):
        return False
    def path(value):
        return [normalized_name(part) for part in (value or "").split(">") if part.strip()]
    return bool(candidate.get("path")) and path(candidate["path"]) == path(primary["path"])


def graph_supplements(primary, parsed=None):
    try:
        with graph_scope(primary["course_id"]):
            candidates = find_entity_candidates(primary["name"])
            matched = [n for n in candidates if same_concept(primary, n)]
            result = []
            for n in matched[:2]:
                for item in query_entity_context(n["node_id"], limit=8):
                    if same_concept(primary, item):
                        result.append(dict(item, evidence_role="verified_graph_supplement", display_node_id=primary["node_id"]))
                        if parsed and parsed.get("relation_type") and parsed.get("direction") in {"incoming", "outgoing", "both"}:
                            result.extend(dict(r, evidence_role="verified_graph_supplement", display_node_id=primary["node_id"])
                                          for r in query_related_nodes(n["node_id"], parsed["relation_type"], parsed["direction"]))
            return result
    except (DriverError, Neo4jError, RuntimeError):
        # Diagram questions continue with the local source if Neo4j is unavailable/unimported.
        return []
