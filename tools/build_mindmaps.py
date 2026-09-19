"""Convert uploaded EMMX into a separate website package; never write to Neo4j.

The verified old export supplies stable IDs and classification of compressed,
floating and summary nodes. Text, notes and media are read from the new archives.
Unsupported binary-only archives are explicitly marked as compatibility copies.
"""
import hashlib
import json
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "知识导图"
BASE = ROOT / "unified_kg"
OUTPUT = ROOT / "web_mindmaps"


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def dump(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def items(data):
    return [*data["knowledge_nodes"], *data["floating_topics"]["roots"],
            *data["floating_topics"]["items"], *data["summary_blocks"],
            *data["summary_items"], *data["callouts"], *data["boundary_groups"],
            *data["structural_anchors"]]


def normalized(name):
    return re.sub(r"细节[和与]骨干-|[\s（）()]|2", "", name).lower()


class Archive:
    def __init__(self, path):
        self.path = path
        self.zip = zipfile.ZipFile(path)
        self.names = {}
        for info in self.zip.infolist():
            self.names[info.filename] = info.filename
            if not info.flag_bits & 0x800:
                try:
                    self.names[info.filename.encode("cp437").decode("utf-8")] = info.filename
                except UnicodeError:
                    pass
        self.xml = ET.fromstring(self.zip.read("page/page.xml")) if "page/page.xml" in self.names else None
        self.shapes = {s.get("ID"): s for s in self.xml.iter("Shape")} if self.xml is not None else {}
        self.refs = {}
        if self.xml is not None:
            rels = ET.fromstring(self.zip.read("rels/page_rels.xml"))
            self.refs = {r.get("Id"): posixpath.normpath(posixpath.join("page", r.get("Target")))
                         for r in rels.iter() if r.get("Id")}

    def media(self, rid):
        name = self.refs[rid]
        return name, self.zip.read(self.names[name])


def save_image(archive, rid, image_id, cid, owner, source_shape, **extra):
    name, blob = archive.media(rid)
    digest = hashlib.sha256(blob).hexdigest()
    suffix = Path(name).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}:
        raise ValueError(f"Unsupported image type: {name}")
    relative = f"media/{cid}/{digest}{suffix}"
    destination = OUTPUT / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        destination.write_bytes(blob)
    return dict(id=image_id, course_id=cid, source_id=source_shape, resource_id=rid,
                source_media_path=name, file=relative, file_size=len(blob), sha256=digest,
                owner_id=owner, **extra)


def blocks(shape, section, register):
    result = []
    for bi, block in enumerate(shape.findall(f"./{section}/TextBlock")):
        images = {i.get("IX"): i for i in block.findall("Image")}
        for paragraph in block.findall("./Text/pp"):
            pending = []

            def flush():
                text = "".join(pending).strip()
                if text:
                    result.append(dict(type="text", text=text))
                pending.clear()

            for span in paragraph:
                if span.get("MX") in images:
                    flush()
                    ref = images[span.get("MX")]
                    iid = register(ref.get("Name"), f"{section}:{bi}:{span.get('MX')}")
                    result.append(dict(type="image", image_id=iid))
                else:
                    pending.append("".join(span.itertext()))
            flush()
        # Some files declare images without a corresponding text placeholder.
        for ix, ref in images.items():
            iid = register(ref.get("Name"), f"{section}:{bi}:{ix}")
            if not any(b.get("image_id") == iid for b in result):
                result.append(dict(type="image", image_id=iid))
    return result


def convert_course(entry, path):
    data = read(BASE / entry["file"])
    cid = entry["course_id"]
    archive = Archive(path)
    data["meta"].update(source_file=path.relative_to(ROOT).as_posix(),
                        source_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    if archive.xml is None:
        binary = archive.zip.read("mmpage/page.bin")
        if not all(n["label"].encode("utf-8") in binary for n in data["knowledge_nodes"]):
            raise ValueError(f"Binary archive no longer matches compatibility data: {path}")
        if data["images"]:
            raise ValueError("Binary archive with images needs a supported export")
        data["meta"].update(conversion_status="compatibility_copy", conversion_note=
            "此文件采用新版 EMMX 格式，当前显示已核对知识点文字的兼容导图；新版层级尚未完整解析。")
        archive.zip.close()
        return data

    by_source = {str(n["source_id"]): n for n in items(data)}
    missing = set(by_source) - archive.shapes.keys()
    if missing:
        raise ValueError(f"Source IDs changed: {cid} {missing}")
    # Reuse established compressed-node IDs only while source hierarchy agrees.
    main_sources = {str(n["source_id"]) for n in data["knowledge_nodes"]}
    for item in data["knowledge_nodes"]:
        expected = item.get("parent_id")
        source = archive.shapes[str(item["source_id"])]
        seen = set()
        while True:
            parent = source.find("./LevelData/Super")
            sid = parent.get("V") if parent is not None else None
            if not sid or sid == "0":
                actual = None
                break
            if sid in seen:
                raise ValueError(f"Cyclic source hierarchy: {cid}:{sid}")
            seen.add(sid)
            if sid in main_sources:
                actual = by_source[sid]["id"]
                break
            source = archive.shapes[sid]
        if expected != actual:
            raise ValueError(f"Hierarchy changed for {item['id']}: {expected} -> {actual}")
    images = {}
    for old in data["images"]:
        current = save_image(archive, old["resource_id"], old["id"], cid,
                             old.get("owner_id"), old["source_id"], placement="shape")
        if old["sha256"] != current["sha256"]:
            raise ValueError(f"Original image changed: {old['id']}")
        images[old["id"]] = dict(old, **current)
    rels = {r["source_shape_id"]: r for r in data["semantic_relations"]}
    for sid, shape in archive.shapes.items():
        item = by_source.get(sid)
        relation = rels.get(sid)
        if item is None and relation is None:
            if shape.findall(".//TextBlock/Image"):
                raise ValueError(f"Unmapped image owner: {cid}:{sid}")
            continue
        owner = item["id"] if item else relation["source_id"]

        def register(rid, location):
            iid = f"{cid}:INLINE:{sid}:{location}"
            if iid not in images:
                images[iid] = save_image(archive, rid, iid, cid, owner, sid,
                                         placement=location.split(":")[0].lower())
            return iid

        title = blocks(shape, "Text", register)
        notes = blocks(shape, "Note", register)
        if item is not None:
            label = "\n".join(b["text"] for b in title if b["type"] == "text")
            if label and item["entity_type"] != "course_root":
                item["label"] = label
            elif not label and any(b["type"] == "image" for b in title):
                item["label"] = "图示说明"
            item["content_blocks"] = title
            item["note_blocks"] = notes
            item["note_text"] = "\n".join(b["text"] for b in notes if b["type"] == "text")
        elif title or notes:
            relation["content_blocks"] = title + notes

    by_id = {n["id"]: n for n in items(data)}
    for n in by_id.values():
        n["image_ids"] = [i["id"] for i in images.values() if i.get("owner_id") == n["id"]]

    def refresh(tree, prefix):
        for t in tree:
            n = by_id[t["id"]]
            n["path"] = " > ".join([*prefix, n["label"]])
            t.update(label=n["label"], image_ids=n["image_ids"])
            refresh(t.get("children", []), [*prefix, n["label"]])
    refresh(data["main_tree"], [])
    for r in data["semantic_relations"]:
        r["source_label"] = by_id[r["source_id"]]["label"]
        r["target_label"] = by_id[r["target_id"]]["label"]
    data["images"] = list(images.values())
    data["meta"].update(conversion_status="converted", image_count=len(images))
    archive.zip.close()
    return data


def convert_overview(path, cid):
    archive = Archive(path)
    nodes, relations = [], []
    for sid, s in archive.shapes.items():
        label = "\n".join("".join(t.itertext()) for t in s.findall("./Text/TextBlock/Text")).strip()
        if s.get("Type") in {"RelatConnector", "MMConnector"} or not label:
            continue
        layout = {k: float(s.find(f"./Transform/{tag}").get("V"))
                  for k, tag in [("x", "CX"), ("y", "CY"), ("width", "Width"), ("height", "Height")]}
        nodes.append(dict(id=f"{cid}:K:{sid}", source_id=sid, label=path.stem if label == "中心主题" else label,
                          entity_type="overview_node", layout=layout, image_ids=[]))
    index = {n["source_id"]: n for n in nodes}
    for sid, s in archive.shapes.items():
        if s.get("Type") != "RelatConnector":
            continue
        c = s.find("./ConnectMap")
        if c is None or c.get("From") not in index or c.get("To") not in index:
            raise ValueError(f"Unresolved overview relationship: {path}:{sid}")
        a, b = index[c.get("From")], index[c.get("To")]
        arrows = [s.find(f"./ShapeFormat/LineFormat/{tag}") for tag in ("BeginArrow", "EndArrow")]
        start, end = [a is not None and a.get("ID", "0") != "0" for a in arrows]
        direction = "both" if start and end else "backward" if start else "forward" if end else "none"
        text = "".join("".join(t.itertext()) for t in s.findall("./Text/TextBlock/Text")).strip()
        relations.append(dict(id=f"{cid}:R:{sid}", source_id=a["id"], target_id=b["id"],
                              source_label=a["label"], target_label=b["label"],
                              relation_text=None if text in {"", "标签"} else text, direction=direction))
    archive.zip.close()
    return dict(meta=dict(course_id=cid, course_name=path.stem, map_kind="overview", conversion_status="converted",
                          source_file=path.relative_to(ROOT).as_posix()),
                knowledge_nodes=nodes, main_tree=[dict(nodes[0], children=[])],
                hierarchy_relations=[], semantic_relations=relations, floating_topics=dict(roots=[], items=[]),
                summary_blocks=[], summary_items=[], callouts=[], structural_anchors=[], boundary_groups=[], images=[])


def build():
    manifest = read(BASE / "manifest.json")
    used, entries, overviews = set(), [], []
    for entry in manifest["courses"]:
        matches = [p for p in SOURCE.glob("*.emmx") if normalized(p.stem) == normalized(entry["name"])]
        if len(matches) != 1:
            raise ValueError(f"Expected one source for {entry['name']}: {matches}")
        path = matches[0]
        used.add(path)
        data = convert_course(entry, path)
        dump(OUTPUT / entry["file"], data)
        entries.append(dict(entry, source_file=data["meta"]["source_file"], images=len(data["images"]),
                            conversion_status=data["meta"]["conversion_status"]))
    for number, path in enumerate(sorted(set(SOURCE.glob("*.emmx")) - used), 1):
        cid = f"M{number:02}"
        data = convert_overview(path, cid)
        filename = f"overviews/{cid}.json"
        dump(OUTPUT / filename, data)
        overviews.append(dict(course_id=cid, name=path.stem, file=filename, root_id=data["main_tree"][0]["id"],
                              source_file=data["meta"]["source_file"], images=0, knowledge_nodes=len(data["knowledge_nodes"])))
    result = dict(schema_version="web-mindmaps-1", courses=entries, overviews=overviews,
                  media_base_relative_to_manifest=".", statistics=dict(courses=len(entries), overviews=len(overviews),
                  images=sum(e["images"] for e in entries)),
                  conversion_notes=["高等数学暂用文字匹配校验后的旧结构，其他25门课正文、备注和图片由新EMMX读取。",
                                    "此数据包仅供网页导图，未修改Neo4j或问答图谱。"])
    dump(OUTPUT / "manifest.json", result)
    print(json.dumps(result["statistics"], ensure_ascii=False))


if __name__ == "__main__":
    build()
