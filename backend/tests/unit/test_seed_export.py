"""Exporting a seed (spec 003, T007). The runner is injected, so no database or pg_dump is needed."""

from __future__ import annotations

import pytest

from pulse.seed import EXCLUDED_TABLES, Manifest, SeedError, export_seed


class FakeRun:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        out = argv[argv.index("-f") + 1]
        open(out, "wb").write(b"a dump")


def _export(tmp_path, run, outbound=0):
    return export_seed(dsn="postgresql://x/pulse", out=tmp_path / "seed.dump", revision="0010",
                       row_counts={"account": 5}, drafts={"model": "m", "llm": 1, "template": 2},
                       created="2026-10-18", outbound_enabled_tenants=outbound, run=run)


def test_the_dump_is_data_only_without_owners_and_leaves_out_secrets_and_live_state(tmp_path):
    run = FakeRun()
    _export(tmp_path, run)
    argv = run.calls[0]
    assert argv[0] == "pg_dump" and "-Fc" in argv and "--data-only" in argv and "--no-owner" in argv
    excluded = {argv[i + 1] for i, a in enumerate(argv) if a == "-T"}
    # sessions and login attempts are live state of whoever built it; the migration owns the schema version
    assert excluded == set(EXCLUDED_TABLES) and {"app_session", "login_attempt", "work_lease", "alembic_version"} <= excluded
    assert argv[-1] == "postgresql://x/pulse"


def test_a_manifest_beside_the_dump_describes_exactly_that_file(tmp_path):
    m = _export(tmp_path, FakeRun())
    side = Manifest.from_json((tmp_path / "seed.dump.json").read_text())
    assert side == m
    from pulse.seed import sha256_of
    assert m.sha256 == sha256_of(tmp_path / "seed.dump") and m.schema_revision == "0010"


def test_a_database_with_outbound_email_enabled_is_never_exported(tmp_path):
    run = FakeRun()
    with pytest.raises(SeedError, match="outbound"):
        _export(tmp_path, run, outbound=1)
    assert run.calls == []     # refused before pg_dump ran


def test_the_promoted_model_is_packed_beside_the_dump_and_covered_by_the_manifest(tmp_path):
    import json

    from pulse.seed import sha256_of
    arts = tmp_path / "artifacts"; arts.mkdir()
    (arts / "m-1.json").write_text(json.dumps({"version": "m-1", "trained_at": "2026-10-01", "promoted": True}))
    (arts / "m-1.pkl").write_bytes(b"model")
    m = export_seed(dsn="postgresql://x/pulse", out=tmp_path / "seed.dump", revision="0010", row_counts={}, drafts={},
                    created="2026-10-18", outbound_enabled_tenants=0, run=FakeRun(), artifacts_dir=arts)
    archive = tmp_path / "seed.dump.artifacts.tar.gz"
    assert archive.exists() and m.artifacts_sha256 == sha256_of(archive)
