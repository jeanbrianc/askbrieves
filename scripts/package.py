"""Build a reproducible, pure-Python Lambda artifact on any host (including M1)."""

import hashlib
import pathlib
import zipfile


def main():
    root = pathlib.Path(__file__).resolve().parents[1]
    build = root / "build"
    build.mkdir(exist_ok=True)
    path = build / "askbrieves.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        sources = list((root / "src" / "askbrieves").glob("*.py"))
        sources += [p for p in (root / "src" / "askbrieves" / "web").glob("*") if p.suffix in (".html", ".js", ".css", ".png")]
        for source in sorted(sources):
            entry = zipfile.ZipInfo(str(source.relative_to(root / "src")), date_time=(2026, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o644 << 16
            archive.writestr(entry, source.read_bytes())
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    (build / "sha256.txt").write_text(digest + "\n")
    print(f"{path.name} sha256={digest} bytes={path.stat().st_size}")


if __name__ == "__main__":
    main()
