"""ブラウザ版を _site/ に組み立てる（GitHub Pages に置くもの一式）。

    python tools/build_web.py

web/ の HTML・JavaScript をそのまま写し、Python のコード（fever_sanma/）を
fever_sanma.zip にまとめる。ブラウザはこの zip を Pyodide の中に展開して読み込む。
tkinter 版の GUI はブラウザでは動かないので入れない。
"""

from __future__ import annotations

import json
import shutil
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "_site"
EXCLUDE = {"gui.py", "human_cui.py"}


def build(site: Path = SITE) -> Path:
    if site.exists():
        shutil.rmtree(site)
    shutil.copytree(ROOT / "web", site, ignore=shutil.ignore_patterns("README.md", "*.sql"))
    # GitHub Pages はファイルを最大10分キャッシュさせるので、公開し直した直後に古い
    # config.js などが読まれることがある。読み込む URL に版番号を付けて避ける。
    # 開いたままのページが新しい版に気づけるよう、同じ版番号を version.json にも書く。
    build_id = str(int(time.time()))
    index = site / "index.html"
    index.write_text(
        index.read_text(encoding="utf-8").replace("__BUILD__", build_id), encoding="utf-8"
    )
    (site / "version.json").write_text(json.dumps({"build": build_id}), encoding="utf-8")
    with zipfile.ZipFile(site / "fever_sanma.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted((ROOT / "fever_sanma").rglob("*.py")):
            if path.name in EXCLUDE:
                continue
            archive.write(path, path.relative_to(ROOT).as_posix())
    return site


if __name__ == "__main__":
    out = build(Path(sys.argv[1]) if len(sys.argv) > 1 else SITE)
    print(f"built {out}")
