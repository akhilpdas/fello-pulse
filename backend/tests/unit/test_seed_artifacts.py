"""The promoted model travels with the seed (spec 003, T012 finding).

The trained model is a pair of files (``artifacts/m-*.json`` card and ``.pkl``), not database rows. A database restored
from a seed without them would have scores but no ``/model`` report and a worker that cannot cycle.
"""

from __future__ import annotations

import json
import tarfile

import pytest

from pulse.seed import SeedError, pack_artifacts, unpack_artifacts


def _card(directory, version, trained_at, promoted):
    (directory / f"{version}.json").write_text(json.dumps(
        {"version": version, "trained_at": trained_at, "promoted": promoted, "artifact_path": f"../artifacts/{version}.pkl"}))
    (directory / f"{version}.pkl").write_bytes(b"model " + version.encode())


def test_only_the_latest_promoted_model_is_packed(tmp_path):
    src = tmp_path / "artifacts"; src.mkdir()
    _card(src, "m-old", "2026-10-01", True)
    _card(src, "m-new", "2026-10-10", True)
    _card(src, "m-unpromoted", "2026-10-15", False)
    tar = tmp_path / "a.tar.gz"
    assert pack_artifacts(src, tar)
    with tarfile.open(tar) as t:
        assert sorted(t.getnames()) == ["m-new.json", "m-new.pkl"]


def test_nothing_is_packed_when_no_model_is_promoted(tmp_path):
    src = tmp_path / "artifacts"; src.mkdir()
    _card(src, "m-1", "2026-10-01", False)
    assert pack_artifacts(src, tmp_path / "a.tar.gz") is None


def test_unpacking_restores_the_two_files(tmp_path):
    src, dest = tmp_path / "artifacts", tmp_path / "out"
    src.mkdir(); dest.mkdir()
    _card(src, "m-new", "2026-10-10", True)
    tar = tmp_path / "a.tar.gz"
    pack_artifacts(src, tar)
    unpack_artifacts(tar, dest)
    assert (dest / "m-new.pkl").read_bytes() == b"model m-new" and json.loads((dest / "m-new.json").read_text())["promoted"]


def test_an_archive_that_tries_to_write_outside_the_folder_is_refused(tmp_path):
    evil = tmp_path / "evil.tar.gz"
    payload = tmp_path / "x"; payload.write_text("pwned")
    with tarfile.open(evil, "w:gz") as t:
        t.add(payload, arcname="../escaped.txt")
    dest = tmp_path / "out"; dest.mkdir()
    with pytest.raises(SeedError, match="outside"):
        unpack_artifacts(evil, dest)
    assert not (tmp_path / "escaped.txt").exists()
