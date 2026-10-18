"""The seed's manifest and checksum (spec 003, T003).

A seed is only worth loading if it is the file the manifest describes, so the manifest carries the file's sha256, the
schema revision it was dumped from, per-table row counts to verify the load against, and how its drafts were written.
"""

from __future__ import annotations

import pytest

from pulse.seed import Manifest, SeedError, sha256_of, verify_file


def _manifest(sha="abc") -> Manifest:
    return Manifest(
        schema_revision="0010", sha256=sha, created="2026-10-18", row_counts={"account": 5000, "score": 36000},
        drafts={"model": "llama-3.3-70b-versatile", "date": "2026-10-18", "llm": 40, "template": 160},
    )


def test_the_manifest_round_trips_through_json():
    m = _manifest()
    assert Manifest.from_json(m.to_json()) == m


def test_a_file_matching_its_sha256_verifies(tmp_path):
    f = tmp_path / "seed.dump"
    f.write_bytes(b"demo data")
    verify_file(f, _manifest(sha256_of(f)))   # no exception


def test_a_changed_file_is_refused(tmp_path):
    f = tmp_path / "seed.dump"
    f.write_bytes(b"demo data")
    good = _manifest(sha256_of(f))
    f.write_bytes(b"demo data, tampered")
    with pytest.raises(SeedError, match="sha256"):
        verify_file(f, good)
