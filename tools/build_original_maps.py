"""Publish original SVG artwork and verified node bindings, without changing Neo4j."""
import base64
import gzip
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "知识导图svg"
PACKAGE = ROOT / "web_mindmaps"
DEST = PACKAGE / "original"
ED = "{https://www.edrawsoft.com/xml/2017/SVGExtensions/}"
SVG = "{http://www.w3.org/2000/svg}"
HREF = "{http://www.w3.org/1999/xlink}href"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def normalized(text):
    return re.sub(r"\s+", "", text or "").casefold()


def nodes(course):
    return [*course["knowledge_nodes"], *course["floating_topics"]["roots"],
            *course["floating_topics"]["items"], *course["summary_blocks"],
            *course["summary_items"], *course["callouts"], *course["structural_anchors"],
            *course["boundary_groups"]]


def label(group):
    return "".join("".join(e.itertext()) for e in group.findall(SVG + "text")).strip()


class NoteText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, text):
        self.parts.append(text)

    def handle_endtag(self, tag):
        if tag in {"p", "div", "li"}:
            self.parts.append("\n")


def notes(group):
    parser = NoteText()
    for e in group.iter():
        if e.get(ED + "note"):
            parser.feed(e.get(ED + "note"))
    return "".join(parser.parts).strip()


def bounds(group):
    match = re.fullmatch(r"matrix\(([^)]+)\)", group.get("transform", ""))
    if not match:
        raise ValueError(f"Unsupported transform: {group.get('id')}")
    a, b, c, d, x, y = map(float, re.split(r"[,\s]+", match[1]))
    if (a, b, c, d) != (1, 0, 0, 1):
        raise ValueError(f"Nontranslation transform: {group.get('id')}")
    return dict(x=x, y=y, width=float(group.get(ED + "width")), height=float(group.get(ED + "height")))


def validate_svg(svg):
    for e in svg.iter():
        if e.tag.rsplit("}", 1)[-1] in {"script", "foreignObject", "iframe"}:
            raise ValueError("Active SVG content is not supported")
        for key, value in e.attrib.items():
            if key.lower().startswith("on"):
                raise ValueError("Unexpected SVG event handler")
            if key.rsplit("}", 1)[-1] == "href" and not value.startswith(("#", "data:image/")):
                raise ValueError("SVG depends on an external resource")


def image_hashes(group, elements):
    images = list(group.iter(SVG + "image"))
    for use in group.iter(SVG + "use"):
        target = elements.get(use.get(HREF, "").lstrip("#"))
        if target is not None:
            images.extend(target.iter(SVG + "image"))
    hashes = set()
    for image in images:
        value = image.get(HREF, image.get("href", ""))
        if value.startswith("data:image/") and ";base64," in value:
            hashes.add(hashlib.sha256(base64.b64decode(value.split(",", 1)[1])).hexdigest())
    return hashes


def convert(entry, path):
    course = read(PACKAGE / entry["file"])
    cid = entry["course_id"]
    blob = path.read_bytes()
    svg = ET.fromstring(blob)
    validate_svg(svg)
    elements = {e.get("id"): e for e in svg.iter() if e.get("id")}
    groups = {g.get("id"): g for g in svg if g.tag == SVG + "g" and g.get(ED + "width")}
    by_source = {str(n["source_id"]): n for n in nodes(course)}
    main_ids = {n["id"] for n in course["knowledge_nodes"]}
    owned_images = defaultdict(set)
    for image in course["images"]:
        owned_images[image.get("owner_id")].add(image["sha256"])
    # This edition has colliding source IDs; never match it to old nodes by ID.
    separate_edition = path.stem == "数据库精简"
    hotspots, extra_nodes, source_bindings, methods, skipped = [], [], {}, {}, []
    for sid, group in groups.items():
        n = by_source.get(sid)
        text = label(group)
        method = None
        if n and not separate_edition:
            if normalized(text) in {normalized(n["label"]), normalized(n.get("source_label", n["label"]))}:
                method = "source_id_and_text"
            elif n["entity_type"] in {"course_root", "overview_node"} and text == "中心主题":
                method = "canonical_root"
            elif not text and owned_images[n["id"]] & image_hashes(group, elements):
                method = "source_id_and_image_hash"
            elif n["id"] not in main_ids and not text:
                method = "auxiliary_source_id"
            if not method and n["id"] in main_ids:
                raise ValueError(f"Main node does not match original artwork: {cid}:{sid}: {text}")
        if separate_edition:
            if sid == entry["root_id"].split(":")[-1] and normalized(text) == normalized(entry["name"]):
                n, method = by_source[sid], "canonical_root"
            else:
                note = notes(group)
                n = dict(id=f"SVG:{cid}:{sid}", source_id=sid, course_id=cid, course_name=entry["name"],
                         label=text or "图示说明", entity_type="original_topic", note_text=note,
                         note_blocks=[dict(type="text", text=note)] if note else [], image_ids=[])
                extra_nodes.append(n)
                method = "separate_edition"
        if not method:
            skipped.append(dict(source_id=sid, label=text))
            continue
        hotspots.append(dict(id=n["id"], label=n["label"], source_id=sid, **bounds(group)))
        source_bindings[sid] = n["id"]
        methods[n["id"]] = method
    main_mapped = main_ids & {h["id"] for h in hotspots}
    if not separate_edition and main_ids != main_mapped:
        raise ValueError(f"Main nodes missing from SVG: {cid}: {main_ids-main_mapped}")
    original_width, original_height = float(svg.get("width")), float(svg.get("height"))
    boxes = [bounds(group) for group in groups.values()]
    min_x = min([0, *[b["x"] - 4 for b in boxes]])
    min_y = min([0, *[b["y"] - 4 for b in boxes]])
    max_x = max([original_width, *[b["x"] + b["width"] + 4 for b in boxes]])
    max_y = max([original_height, *[b["y"] + b["height"] + 4 for b in boxes]])
    width, height = max_x-min_x, max_y-min_y
    expanded = (min_x, min_y, width, height) != (0, 0, original_width, original_height)
    for h in hotspots:
        h["x"] -= min_x
        h["y"] -= min_y
        if not (0 <= h["x"] < width and 0 <= h["y"] < height and h["width"] > 0 and h["height"] > 0):
            raise ValueError(f"Hotspot outside canvas: {h['id']}")
    relations = []
    if separate_edition:
        for sid, group in groups.items():
            parent = group.get(ED + "parentid")
            if parent in source_bindings:
                relations.append(dict(source_id=source_bindings[parent], target_id=source_bindings[sid],
                                      relation_type="CONTAINS", direction="forward"))
        for group in svg:
            if group.get(ED + "type") != "relation":
                continue
            a, b = group.get(ED + "fromid"), group.get(ED + "toid")
            if a in source_bindings and b in source_bindings:
                # Do not infer semantic direction from the SVG paint order.
                text = label(group)
                relations.append(dict(source_id=source_bindings[a], target_id=source_bindings[b],
                                      relation_type="SEMANTIC_LINK", direction="none",
                                      relation_text=text if text not in {"", "标签"} else None))
        by_id = {n["id"]: n for n in extra_nodes}
        for n in extra_nodes:
            parent = groups[n["source_id"]].get(ED + "parentid")
            n["parent_id"] = source_bindings.get(parent)
            chain, seen, current = [], set(), n
            while current:
                if current["id"] in seen:
                    raise ValueError("Cyclic original topic hierarchy")
                seen.add(current["id"])
                chain.append(current["label"])
                parent = groups[current["source_id"]].get(ED + "parentid")
                current = by_id.get(source_bindings.get(parent))
            n["path"] = " > ".join([entry["name"], *reversed(chain)])
    digest = hashlib.sha256(blob).hexdigest()
    data = dict(course_id=cid, name=entry["name"], width=width, height=height, hotspots=hotspots,
                root_id=entry["root_id"], main_nodes_mapped=len(main_mapped), main_nodes_total=len(main_ids),
                sha256=digest, source_file=path.relative_to(ROOT).as_posix(), file=f"{cid}-{digest[:12]}.svg",
                url=f"/api/graph/courses/{cid}/original.svg?v={digest[:12]}",
                extra_nodes=extra_nodes, source_relations=relations, separate_edition=separate_edition,
                mapping_methods=methods, unmapped_shapes=skipped, canvas_expanded=expanded,
                source_url=f"/api/graph/courses/{cid}/original.svg?source=true",
                original_viewbox=[0, 0, original_width, original_height])
    display_blob = blob
    if expanded:
        # Change only root canvas attributes; all original drawing elements stay byte-for-byte intact.
        header = re.search(rb"<svg\b[^>]*>", blob)
        if not header:
            raise ValueError("Missing SVG root header")
        updated = header.group()
        for key, value in [("width", str(width)), ("height", str(height)),
                           ("viewBox", f"{min_x} {min_y} {width} {height}")]:
            updated = re.sub(rb'(?<![\w:])'+key.encode()+rb'="[^"]*"', key.encode()+b'="'+value.encode()+b'"', updated)
        display_blob = blob[:header.start()] + updated + blob[header.end():]
    data["display_file"] = data["file"].replace(".svg", "-display.svg")
    data["display_sha256"] = hashlib.sha256(display_blob).hexdigest()
    if separate_edition:
        data["display_note"] = "当前显示你提供的数据库精简原图。"
    return data, blob, display_blob


def build(course_ids=None):
    manifest = read(PACKAGE / "manifest.json")
    sources = {normalized(p.stem): p for p in SOURCE.glob("*.svg")}
    pending, unavailable = [], []
    for entry in [*manifest["courses"], *manifest.get("overviews", [])]:
        if course_ids and entry["course_id"] not in course_ids:
            continue
        key = "数据库精简" if entry["name"] == "数据库" else entry["name"]
        path = sources.get(normalized(key))
        if path is None:
            unavailable.append(entry["course_id"])
            continue
        data, blob, display_blob = convert(entry, path)
        pending.append((data, blob, display_blob))
        print(f"{entry['course_id']} {entry['name']}: {len(data['hotspots'])} clickable; {data['main_nodes_mapped']}/{data['main_nodes_total']} original course nodes")
    # Validate the entire batch before publishing anything.
    DEST.mkdir(parents=True, exist_ok=True)
    for data, blob, display_blob in pending:
        (DEST / data["file"]).write_bytes(blob)
        (DEST / data["display_file"]).write_bytes(display_blob)
        (DEST / (data["display_file"] + ".gz")).write_bytes(gzip.compress(display_blob, compresslevel=6, mtime=0))
        dump(DEST / f"{data['course_id']}.json", data)
    if not course_ids:
        dump(DEST / "validation.json", dict(status="passed", maps=len(pending), unavailable=unavailable,
             matched_main_nodes=sum(d["main_nodes_mapped"] for d, _, _ in pending),
             clickable_areas=sum(len(d["hotspots"]) for d, _, _ in pending),
             canvas_expanded=[d["course_id"] for d, _, _ in pending if d["canvas_expanded"]],
             separate_editions=[d["course_id"] for d, _, _ in pending if d["separate_edition"]]))


if __name__ == "__main__":
    build()
