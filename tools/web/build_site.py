"""做網站資料夾：只把白名單上的檔案複製出去。

GitHub Actions 部署網站時用（.github/workflows/pages.yml）。照片、文件、測試都不會出去。

用法（在專案根目錄）：
    python tools/web/build_site.py --dest _site
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# 網站上的路徑 → 專案裡的來源（None：空檔）
SITE: dict[str, str | None] = {
    "index.html": "prototype/index.html",
    "lamps.js": "prototype/lamps.js",
    "webalign.js": "prototype/webalign.js",
    "models/moge-2-s-fp16.onnx": "prototype/models/moge-2-s-fp16.onnx",
    "models/LICENSE-MoGe.txt": "prototype/models/LICENSE-MoGe.txt",
    "README.md": "tools/web/README.md",
    ".nojekyll": None,  # 叫 GitHub Pages 原封不動地給檔案
}


def stage(root: Path, dest: Path) -> None:
    """把白名單上的檔案複製到 dest；dest 裡不在白名單上的舊檔案刪掉（.git 不動）。"""
    _check_sources(root)
    dest.mkdir(parents=True, exist_ok=True)
    _remove_stale(dest)
    for name, src in SITE.items():
        target = dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if src:
            shutil.copyfile(root / src, target)
        else:
            target.write_bytes(b"")


def _check_sources(root: Path) -> None:
    for src in (root / s for s in SITE.values() if s):
        if not src.is_file():
            hint = "先執行 tools/autoalign/export_onnx.py" if src.suffix == ".onnx" else ""
            raise FileNotFoundError(f"找不到 {src}。{hint}")


def _remove_stale(dest: Path) -> None:
    for old in dest.rglob("*"):
        rel = old.relative_to(dest)
        if old.is_file() and ".git" not in rel.parts and rel.as_posix() not in SITE:
            old.unlink()


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dest", type=Path, required=True, help="網站資料夾放哪裡，例如 _site")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows 中文版終端機預設 cp950
    stage(root, args.dest)
    print(f"網站檔案放好了：{args.dest}（{len(SITE)} 個）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
