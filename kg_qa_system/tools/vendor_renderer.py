"""Download pinned browser assets from npm, checking the registry integrity hash."""
import base64
import hashlib
import io
import json
from pathlib import Path
import tarfile
import sys
import urllib.request

DEST = Path(__file__).resolve().parents[1] / "static" / "vendor"
PACKAGES = {
    "markdown-it": ("15.0.2", ["dist/browser/markdown-it.umd.min.js", "LICENSE"]),
    "dompurify": ("3.4.15", ["dist/purify.min.js", "LICENSE"]),
    "katex": ("0.18.7", ["dist/katex.min.js", "dist/katex.min.css", "dist/fonts/", "LICENSE"]),
    "markdown-it-texmath": ("1.0.0", ["texmath.js", "license.txt"]),
    "@highlightjs/cdn-assets": ("11.12.0", ["highlight.min.js", "styles/github.min.css", "LICENSE"]),
}


def main():
    manifest_file = DEST / "manifest.json"
    manifest = json.loads(manifest_file.read_text()) if manifest_file.exists() else {}
    for name, (version, wanted) in PACKAGES.items():
        if len(sys.argv) > 1 and name not in sys.argv[1:]:
            continue
        with urllib.request.urlopen(f"https://registry.npmjs.org/{name}/{version}", timeout=40) as response:
            package = json.load(response)
        dist = package["dist"]
        with urllib.request.urlopen(dist["tarball"], timeout=60) as response:
            payload = response.read()
        algorithm, expected = dist["integrity"].split("-", 1)
        actual = base64.b64encode(hashlib.new(algorithm, payload).digest()).decode()
        if actual != expected:
            raise ValueError(f"Integrity mismatch: {name}")
        folder = DEST / ("highlightjs" if name.startswith("@highlightjs") else name)
        count = 0
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
            for member in archive.getmembers():
                relative = member.name.removeprefix("package/")
                if not member.isfile() or not any(relative == item or (item.endswith("/") and relative.startswith(item)) for item in wanted):
                    continue
                target = (folder / relative).resolve()
                if not target.is_relative_to(folder.resolve()):
                    raise ValueError("Unsafe archive path")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.extractfile(member).read())
                count += 1
        manifest[name] = {"version": version, "integrity": dist["integrity"], "source": dist["tarball"]}
        missing = [item for item in wanted if not (folder / item).exists()]
        if missing:
            raise ValueError(f"Missing assets: {name}: {missing}")
        print(f"{name} {version}: {count} files")
    (DEST / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
