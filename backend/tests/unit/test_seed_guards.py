"""When a seed may be loaded (spec 003, T005). Every refusal happens before anything is modified."""

from __future__ import annotations

import pytest

from pulse.seed import Manifest, SeedError, check_loadable, sha256_of


def _file(tmp_path, data=b"demo"):
    f = tmp_path / "seed.dump"
    f.write_bytes(data)
    return f


def _manifest(f, revision="0010"):
    return Manifest(schema_revision=revision, sha256=sha256_of(f), created="2026-10-18", row_counts={"account": 1})


def test_an_empty_migrated_database_at_the_seeds_revision_may_be_loaded(tmp_path):
    f = _file(tmp_path)
    check_loadable(tenant_count=0, db_revision="0010", manifest=_manifest(f), file=f, overwrite=False)


def test_a_database_that_already_holds_tenants_is_refused_and_the_message_names_the_flag(tmp_path):
    f = _file(tmp_path)
    with pytest.raises(SeedError, match="--overwrite"):
        check_loadable(tenant_count=3, db_revision="0010", manifest=_manifest(f), file=f, overwrite=False)


def test_overwrite_allows_a_database_that_holds_tenants(tmp_path):
    f = _file(tmp_path)
    check_loadable(tenant_count=3, db_revision="0010", manifest=_manifest(f), file=f, overwrite=True)


def test_a_schema_revision_mismatch_is_refused_even_with_overwrite_and_names_both_revisions(tmp_path):
    f = _file(tmp_path)
    with pytest.raises(SeedError, match=r"0009.*0010|0010.*0009"):
        check_loadable(tenant_count=0, db_revision="0009", manifest=_manifest(f, "0010"), file=f, overwrite=True)


def test_a_file_that_does_not_match_its_checksum_is_refused(tmp_path):
    f = _file(tmp_path)
    m = _manifest(f)
    f.write_bytes(b"something else")
    with pytest.raises(SeedError, match="sha256"):
        check_loadable(tenant_count=0, db_revision="0010", manifest=m, file=f, overwrite=False)
