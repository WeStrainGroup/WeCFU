"""Release privacy/resource contract; also audits already-built archives.

Run: python tests/test_release_packaging.py dist/*.whl dist/*.tar.gz PATH.conda
This command reads archives without installing them or writing their contents.
"""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile
import zipfile

PUBLIC_JSON = {
    "wecfu/model_assets.json",
    "wecfu/server/fusion_filter_v2.json",
    "wecfu/server/product_fusion_v2.json",
    "wecfu/server/sam2_product_use.json",
    "wecfu/server/fusion_dino/configuration.json",
    "wecfu/server/fusion_dino/library-pins.json",
    "wecfu/server/fusion_dino/license-provenance.json",
    "wecfu/server/fusion_dino/loading-metadata.json",
    "wecfu/server/fusion_dino/runtime-contract.json",
}
REQUIRED_PRODUCT_FILES = {
    "wecfu/setup_models.py", "wecfu/runtime_paths.py", "wecfu/runtime_bootstrap.py", "wecfu/cli.py",
    "wecfu/server/app.py", "wecfu/server/web.py",
    "wecfu/server/sam_runtime.py", "wecfu/server/sam_worker.py",
    "wecfu/server/sam_warm_pool.py", "wecfu/experiments/segmentation.py",
    "wecfu/server/static/index.html", "wecfu/server/static/app.js",
    "wecfu/server/static/styles.css", "wecfu/server/static/i18n.js",
    "wecfu/server/static/param_controls.js", "wecfu/server/static/reference_controls.js",
    "wecfu/server/static/model_preview_controls.js", "wecfu/server/static/review_queue_controls.js",
    "wecfu/server/static/workflow_controls.js", "wecfu/server/static/default_batch.js",
    "wecfu/server/static/serial_batch.js",
}
SOURCE_TOP = {
    "pyproject.toml", "MANIFEST.in", "README.md", "README_HF.md", "INSTALL.md",
    "USAGE.md", "SHARE.md", "CHANGELOG.md", "LICENSE", "NOTICE",
    "THIRD_PARTY_NOTICES.md", "meta.yaml", "environment.yml", "Dockerfile",
    ".dockerignore", ".gitignore", "PKG-INFO", "setup.cfg",
}
PRIVATE_JSON_KEYS = {
    "person_id", "person_ids", "training_ids", "training_labels",
    "training_scope_images", "training_scope", "views_by_sha256",
    "source_fullfit_model_sha256", "source_fullfit_seal_sha256",
    "source_protocol_sha256", "source_manifest_sha256",
}
FORBIDDEN_SUFFIXES = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".tif", ".tiff",
    ".pt", ".pth", ".onnx", ".safetensors", ".npy", ".npz", ".pkl",
    ".csv", ".tsv", ".log", ".3mf",
}


def _public_package_path(name: str) -> bool:
    p = PurePosixPath(name)
    if name in PUBLIC_JSON:
        return True
    if p.suffix == ".py":
        return p.parent.as_posix() in {
            "wecfu", "wecfu/server", "wecfu/server/fusion_dino",
        } or name in {"wecfu/experiments/__init__.py", "wecfu/experiments/segmentation.py"}
    return p.parent.as_posix() == "wecfu/server/static" and p.suffix in {".html", ".js", ".css"}


def _assert_json_public(value):
    if isinstance(value, dict):
        assert not (set(value) & PRIVATE_JSON_KEYS), "Private research fields in public JSON"
        for child in value.values():
            _assert_json_public(child)
    elif isinstance(value, list):
        for child in value:
            _assert_json_public(child)


def assert_member(name: str, content: bytes, kind: str):
    path = PurePosixPath(name)
    assert not path.is_absolute() and ".." not in path.parts, f"Unsafe archive member: {name}"
    assert path.suffix.lower() not in FORBIDDEN_SUFFIXES, f"Binary data/weights in release: {name}"
    assert not set(path.parts) & {"data", ".git", ".env", "hardware", "docs", "__pycache__"}, name
    assert "internal_use" not in name and path.name != "fusion_source_views.json", name
    assert path.name != "direct_url.json", f"Local installation provenance must not be published: {name}"
    if name.startswith("wecfu/"):
        assert _public_package_path(name), f"Unapproved package resource: {name}"
    elif kind == "wheel" and ".dist-info/" in name:
        # Wheel metadata and explicitly carried license files only.
        tail = name.split(".dist-info/", 1)[1]
        assert tail in {"METADATA", "WHEEL", "RECORD", "entry_points.txt", "top_level.txt"} or tail.startswith("licenses/"), name
    elif kind == "conda" and name.startswith("info/"):
        assert path.suffix.lower() in {"", ".json", ".txt", ".md", ".py", ".sh", ".bat"}, name
    elif kind == "conda" and (name.startswith("python-scripts/") or ".dist-info/" in name):
        assert path.suffix.lower() in {"", ".txt", ".json", ".md", ".py"} or path.name in {"METADATA", "WHEEL", "RECORD"}, name
    elif kind == "sdist":
        assert name in SOURCE_TOP or (
            path.parent.as_posix() == "LICENSES" and path.suffix == ".txt"
        ) or (
            path.parent.as_posix() == "tests" and path.suffix in {".py", ".cjs"}
        ) or (
            path.parent.as_posix() == "wecfu.egg-info" and path.name in {
                "PKG-INFO", "SOURCES.txt", "dependency_links.txt", "entry_points.txt",
                "requires.txt", "top_level.txt", "not-zip-safe",
            }
        ), f"Unapproved source member: {name}"
    else:
        raise AssertionError(f"Unapproved release member: {name}")
    if name.endswith(".json") and name in PUBLIC_JSON:
        _assert_json_public(json.loads(content))
    # Do not reproduce a maintainer's home directory in any shipped text.
    assert not re.search(rb"/Users/[A-Za-z0-9_.-]+/", content), f"Private host path: {name}"


def _tar_members(stream, *, strip_root=False):
    with tarfile.open(fileobj=stream, mode="r|*") as archive:
        for member in archive:
            if member.isdir():
                continue
            assert member.isfile(), f"Links/special entries are not release files: {member.name}"
            name = member.name.split("/", 1)[1] if strip_root else member.name
            with archive.extractfile(member) as source:
                yield name, source.read()


def archive_members(path: Path):
    if path.name.endswith(".whl"):
        with zipfile.ZipFile(path) as archive:
            for row in archive.infolist():
                if not row.is_dir():
                    yield "wheel", row.filename, archive.read(row)
    elif path.name.endswith(".tar.gz"):
        with path.open("rb") as stream:
            for name, data in _tar_members(stream, strip_root=True):
                yield "sdist", name, data
    elif path.suffix == ".conda":
        import zstandard
        with zipfile.ZipFile(path) as outer:
            for archive_name in outer.namelist():
                if not archive_name.endswith(".tar.zst"):
                    continue
                with outer.open(archive_name) as compressed:
                    with zstandard.ZstdDecompressor().stream_reader(compressed) as stream:
                        for name, data in _tar_members(stream):
                            if name.startswith("site-packages/"):
                                name = name[len("site-packages/"):]
                            yield "conda", name, data
    else:
        raise AssertionError(f"Unsupported release archive: {path.name}")


def audit(path: Path):
    seen = set()
    for kind, name, content in archive_members(path):
        assert name not in seen, f"Repeated archive member: {name}"
        seen.add(name)
        assert_member(name, content, kind)
    missing = PUBLIC_JSON - seen
    assert not missing, f"Required runtime resources missing: {sorted(missing)}"
    for required in sorted(REQUIRED_PRODUCT_FILES):
        assert required in seen, f"Required product code missing: {required}"
    assert any(name.endswith("THIRD_PARTY_NOTICES.md") for name in seen), "Third-party notices missing"
    assert any(name.endswith("Apache-2.0.txt") for name in seen), "Apache license missing"
    return len(seen)


def test_rejects_photos_weights_research_and_unlisted_resources():
    import pytest
    for name in (
        "data/plate.jpg", "wecfu/server/sample.png", "wecfu/server/model.pth",
        "wecfu/server/fusion_source_views.json", "wecfu/server/sam2_internal_use.json",
        "wecfu/server/other.json", "docs/private-results.md", "hardware/model.3mf",
        "../escape.py", "wecfu/evaluation/runner.py",
        "wecfu-1.2.0.dist-info/direct_url.json",
    ):
        with pytest.raises(AssertionError):
            assert_member(name, b"{}", "sdist")


def test_public_json_cannot_carry_research_identities():
    import pytest
    with pytest.raises(AssertionError):
        assert_member("wecfu/server/fusion_filter_v2.json", b'{"model":{"person_id":"synthetic"}}', "wheel")
    assert_member("wecfu/server/fusion_filter_v2.json", b'{"model":{"coefficients":[0.1,0.2]}}', "wheel")


def test_public_runtime_resources_exist_and_are_sanitized():
    root = Path(__file__).resolve().parents[1]
    for name in PUBLIC_JSON:
        assert_member(name, (root / name).read_bytes(), "wheel")


def _synthetic_wheel(path, *, omit=()):
    with zipfile.ZipFile(path, "w") as out:
        for name in PUBLIC_JSON:
            out.writestr(name, "{}")
        for name in sorted(REQUIRED_PRODUCT_FILES - set(omit)):
            out.writestr(name, "synthetic product code")
        out.writestr("wecfu-1.2.0.dist-info/licenses/THIRD_PARTY_NOTICES.md", "test")
        out.writestr("wecfu-1.2.0.dist-info/licenses/LICENSES/Apache-2.0.txt", "test")


def test_built_archive_contract_detects_missing_runtime_and_private_files(tmp_path):
    import pytest
    wheel = tmp_path / "synthetic.whl"
    _synthetic_wheel(wheel)
    assert audit(wheel) > 0
    with zipfile.ZipFile(wheel, "a") as out:
        out.writestr("wecfu/server/leaked_photo.jpg", b"synthetic forbidden bytes")
    with pytest.raises(AssertionError):
        audit(wheel)
    with zipfile.ZipFile(wheel, "w") as out:
        out.writestr("wecfu/server/static/index.html", "")
    with pytest.raises(AssertionError, match="runtime resources missing"):
        audit(wheel)


def test_archive_rejects_missing_warm_or_batch_implementation(tmp_path):
    import pytest
    wheel = tmp_path / "synthetic.whl"
    for missing in (
        "wecfu/server/sam_warm_pool.py",
        "wecfu/server/static/default_batch.js",
        "wecfu/server/static/serial_batch.js",
    ):
        _synthetic_wheel(wheel, omit={missing})
        with pytest.raises(AssertionError, match="Required product code missing") as failure:
            audit(wheel)
        assert missing in str(failure.value)


def test_required_product_files_exist_in_release_source():
    root = Path(__file__).resolve().parents[1]
    for name in REQUIRED_PRODUCT_FILES:
        assert (root / name).is_file(), name


if __name__ == "__main__":
    if len(sys.argv) == 1:
        raise SystemExit("Pass built .whl, .tar.gz or .conda paths to audit")
    for argument in sys.argv[1:]:
        artifact = Path(argument)
        print(f"{artifact.name}: {audit(artifact)} members passed release privacy/resource checks")
