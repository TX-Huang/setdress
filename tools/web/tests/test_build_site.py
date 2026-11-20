"""放上網的檔案：只複製白名單上的，其他（照片、文件、測試）一律不出去。"""

from __future__ import annotations

from pathlib import Path

import pytest

from build_site import SITE, main, stage

MODEL = "prototype/models/moge-2-s-fp16.onnx"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """假的專案資料夾：網頁、燈具、對齊程式、模型，加上不能出去的東西。"""
    root = tmp_path / "Setdress"
    files = {
        "prototype/index.html": "<title>Setdress 原型</title>",
        "prototype/lamps.js": "// lamps",
        "prototype/catalog.js": "// catalog",  # 爬到的燈（docs/catalog.md 第 14 句）
        "prototype/erase.js": "// erase",  # 擦掉照片裡的東西（docs/erase.md）
        "prototype/models/mobile_sam_image_encoder.onnx": "onnx",
        "prototype/models/sam_mask_decoder_single.onnx": "onnx",
        "prototype/models/migan_pipeline_v2.onnx": "onnx",
        "prototype/models/LICENSE-MobileSAM.txt": "Apache License",
        "prototype/models/LICENSE-MI-GAN.txt": "MIT License",
        "prototype/webalign.js": "// align",
        MODEL: "onnx",
        "tools/web/README.md": "# Setdress 網頁版",
        "prototype/models/LICENSE-MoGe.txt": "MIT License",
        # 不能出去的
        "tools/autoalign/photos/S__1.jpg": "家裡的照片",
        "tools/autoalign/photos/ceilings.csv": "photo,ceiling_m",
        "docs/auto-align.md": "實拍照片的天花板高度",
        "prototype/tests/lamps.test.js": "// test",
    }
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    return root


def listing(folder: Path) -> set[str]:
    return {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}


def test_copies_exactly_the_site_files(project: Path, tmp_path: Path) -> None:
    dest = tmp_path / "site"
    stage(project, dest)
    assert listing(dest) == set(SITE)
    assert (dest / "index.html").read_text(encoding="utf-8") == "<title>Setdress 原型</title>"
    assert (dest / "models" / "moge-2-s-fp16.onnx").read_text(encoding="utf-8") == "onnx"


def test_never_copies_photos_docs_or_tests(project: Path, tmp_path: Path) -> None:
    dest = tmp_path / "site"
    stage(project, dest)
    for name in listing(dest):
        assert not name.endswith((".jpg", ".csv", ".test.js"))
        assert not name.startswith("docs/")


def test_removes_old_files_but_keeps_git(project: Path, tmp_path: Path) -> None:
    dest = tmp_path / "site"
    (dest / ".git").mkdir(parents=True)
    (dest / ".git" / "HEAD").write_text("ref: refs/heads/main", encoding="utf-8")
    (dest / "old.js").write_text("// 舊的", encoding="utf-8")
    stage(project, dest)
    assert not (dest / "old.js").exists()
    assert (dest / ".git" / "HEAD").exists()


def test_the_erase_tool_and_its_models_and_licenses_go_online() -> None:
    # docs/erase.md 第 7 句：模型放在網站上，第一次用才下載；授權檔一起放
    for name in (
        "erase.js",
        "models/mobile_sam_image_encoder.onnx",
        "models/sam_mask_decoder_single.onnx",
        "models/migan_pipeline_v2.onnx",
        "models/LICENSE-MobileSAM.txt",
        "models/LICENSE-MI-GAN.txt",
    ):
        assert name in SITE, name


def test_missing_model_stops_with_a_hint(project: Path, tmp_path: Path) -> None:
    (project / MODEL).unlink()
    with pytest.raises(FileNotFoundError, match=r"export_onnx\.py"):
        stage(project, tmp_path / "site")


def test_command_line_builds_the_site_folder(project: Path, tmp_path: Path) -> None:
    dest = tmp_path / "_site"
    assert main(["--dest", str(dest)], root=project) == 0
    assert listing(dest) == set(SITE)
