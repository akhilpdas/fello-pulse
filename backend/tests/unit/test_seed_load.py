"""Loading a seed (spec 003, T009). Every side effect is injected, so the order and the refusals are what is tested."""

from __future__ import annotations

import pytest

from pulse.seed import Manifest, SeedError, load_seed, sha256_of


class Ports:
    """Records the order of side effects; ``counts`` is what the database reports after the restore."""

    def __init__(self, counts, tenants=0, revision="0010"):
        self.events, self.counts, self.tenants, self.revision = [], counts, tenants, revision

    def restore(self, dsn, file):
        self.events.append(("restore", dsn, str(file)))

    def truncate(self):
        self.events.append(("truncate",))

    def set_passwords(self, password):
        self.events.append(("passwords", password))

    def row_counts(self):
        return self.counts


def _setup(tmp_path, counts_after, tenants=0, revision="0010"):
    f = tmp_path / "seed.dump"
    f.write_bytes(b"demo")
    m = Manifest("0010", sha256_of(f), "2026-10-18", {"account": 5, "score": 9})
    return f, m, Ports(counts_after, tenants, revision)


def _load(f, m, p, overwrite=False, password="a-long-demo-passphrase"):
    return load_seed(file=f, manifest=m, dsn="postgresql://x/pulse", tenant_count=p.tenants, db_revision=p.revision,
                     overwrite=overwrite, demo_password=password, restore=p.restore, truncate=p.truncate,
                     set_passwords=p.set_passwords, row_counts=p.row_counts)


def test_a_clean_load_restores_then_sets_the_password_then_checks_the_counts(tmp_path):
    f, m, p = _setup(tmp_path, {"account": 5, "score": 9})
    _load(f, m, p)
    assert [e[0] for e in p.events] == ["restore", "passwords"]          # nothing to truncate on an empty database
    assert p.events[0] == ("restore", "postgresql://x/pulse", str(f))
    assert p.events[1] == ("passwords", "a-long-demo-passphrase")


def test_overwrite_empties_the_existing_data_first(tmp_path):
    f, m, p = _setup(tmp_path, {"account": 5, "score": 9}, tenants=3)
    _load(f, m, p, overwrite=True)
    assert [e[0] for e in p.events] == ["truncate", "restore", "passwords"]


def test_a_refused_load_touches_nothing(tmp_path):
    f, m, p = _setup(tmp_path, {}, tenants=3)
    with pytest.raises(SeedError, match="--overwrite"):
        _load(f, m, p)
    assert p.events == []


def test_a_restore_that_does_not_reproduce_the_manifest_counts_is_an_error(tmp_path):
    f, m, p = _setup(tmp_path, {"account": 5, "score": 7})
    with pytest.raises(SeedError, match="score"):
        _load(f, m, p)


def test_a_weak_password_is_refused_before_anything_is_touched(tmp_path):
    f, m, p = _setup(tmp_path, {"account": 5, "score": 9})
    with pytest.raises(SeedError, match="password"):
        _load(f, m, p, password="short")
    assert p.events == []


def _with_archive(tmp_path, tamper=False):
    import json

    from pulse.seed import pack_artifacts
    src = tmp_path / "src"; src.mkdir()
    (src / "m-1.json").write_text(json.dumps({"version": "m-1", "trained_at": "2026-10-01", "promoted": True}))
    (src / "m-1.pkl").write_bytes(b"model")
    f = tmp_path / "seed.dump"; f.write_bytes(b"demo")
    archive = tmp_path / "seed.dump.artifacts.tar.gz"
    digest = pack_artifacts(src, archive)
    if tamper:
        archive.write_bytes(archive.read_bytes() + b"x")
    return f, Manifest("0010", sha256_of(f), "2026-10-18", {"account": 5}, artifacts_sha256=digest)


def test_the_model_is_restored_beside_the_data(tmp_path):
    f, m = _with_archive(tmp_path)
    p, dest = Ports({"account": 5}), tmp_path / "artifacts"; dest.mkdir()
    load_seed(file=f, manifest=m, dsn="x", tenant_count=0, db_revision="0010", overwrite=False,
              demo_password="a-long-demo-passphrase", restore=p.restore, truncate=p.truncate, set_passwords=p.set_passwords,
              row_counts=p.row_counts, artifacts_dest=dest)
    assert (dest / "m-1.pkl").read_bytes() == b"model" and (dest / "m-1.json").exists()


def test_a_tampered_model_archive_is_refused_before_anything_is_touched(tmp_path):
    f, m = _with_archive(tmp_path, tamper=True)
    p, dest = Ports({"account": 5}), tmp_path / "artifacts"; dest.mkdir()
    with pytest.raises(SeedError, match="sha256"):
        load_seed(file=f, manifest=m, dsn="x", tenant_count=0, db_revision="0010", overwrite=False,
                  demo_password="a-long-demo-passphrase", restore=p.restore, truncate=p.truncate, set_passwords=p.set_passwords,
                  row_counts=p.row_counts, artifacts_dest=dest)
    assert p.events == [] and list(dest.iterdir()) == []


def test_settings_a_newer_client_writes_but_an_older_server_rejects_are_dropped_from_the_restore_script():
    # Debian's pg_restore 17 writes ``SET transaction_timeout`` even for a 16 server, which then refuses it (found by
    # loading a seed in Docker). Everything else in the script must pass through untouched.
    from pulse.seed import strip_unsupported_settings
    script = [b"SET statement_timeout = 0;\n", b"SET transaction_timeout = 0;\n", b"COPY public.account (id) FROM stdin;\n",
              b"SET transaction_timeout in a data row\n"]
    assert list(strip_unsupported_settings(script)) == [script[0], script[2], script[3]]
