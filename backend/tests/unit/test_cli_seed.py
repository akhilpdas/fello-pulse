"""The ``export-seed`` and ``load-seed`` commands exist and read the arguments the spec promises (spec 003, T011)."""

from __future__ import annotations

import pytest

from pulse.cli import build_parser


def test_export_seed_defaults_to_a_file_in_the_current_directory():
    args = build_parser().parse_args(["export-seed"])
    assert args.out == "seed.dump" and callable(args.fn)


def test_load_seed_needs_a_file_or_a_url():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["load-seed"])
    assert build_parser().parse_args(["load-seed", "--file", "seed.dump"]).file == "seed.dump"
    assert build_parser().parse_args(["load-seed", "--url", "https://example.invalid/seed.dump"]).url.endswith("seed.dump")


def test_overwrite_is_off_unless_asked_for():
    assert build_parser().parse_args(["load-seed", "--file", "s"]).overwrite is False
    assert build_parser().parse_args(["load-seed", "--file", "s", "--overwrite"]).overwrite is True
