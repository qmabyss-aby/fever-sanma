"""ブラウザ版を _site/ に組み立てる（GitHub Pages に置くもの一式）。

    python tools/build_web.py

web/ の HTML・JavaScript をそのまま写し、Python のコード（fever_sanma/）を
fever_sanma.zip にまとめる。ブラウザはこの zip を Pyodide の中に展開して読み込む。
tkinter 版の GUI はブラウザでは動かないので入れない。
"""

from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "_site"
EXCLUDE = {"gui.py", "human_cui.py"}


def build(site: Path = SITE) -> Path:
    if site.exists():
        shutil.rmtree(site)
    shutil.copytree(ROOT / "web", site, ignore=shutil.ignore_patterns("README.md", "*.sql"))
    with zipfile.ZipFile(site / "fever_sanma.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted((ROOT / "fever_sanma").rglob("*.py")):
            if path.name in EXCLUDE:
                continue
            archive.write(path, path.relative_to(ROOT).as_posix())
    return site


if __name__ == "__main__":
    out = build(Path(sys.argv[1]) if len(sys.argv) > 1 else SITE)
    print(f"built {out}")
