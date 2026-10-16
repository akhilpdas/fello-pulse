"""T293 (FR-032): ``pulse bootstrap-demo`` is the container path's equivalent of ``run_all.sh`` stages 4-8 --
generate (if there are no feeds), bootstrap tenants and users with a demo password, ingest, train, run one cycle --
and tells you how to sign in. The steps are monkeypatched here: this tests the *order, the password handling and
the output*, not the (separately tested) steps themselves.

Names the production change that makes it fail: ``pulse.cli.cmd_bootstrap_demo``.
"""

from __future__ import annotations

import argparse

import pulse.cli as cli


def _wire(monkeypatch, calls, feeds_exist):
    monkeypatch.setattr(cli, "_feeds_present", lambda feeds: feeds_exist)
    monkeypatch.setattr(cli, "_generate", lambda feeds, seed: calls.append(("generate", seed)))
    monkeypatch.setattr(cli, "cmd_bootstrap", lambda a: calls.append(("bootstrap", a.demo_password)) or 0)
    monkeypatch.setattr(cli, "cmd_ingest", lambda a: calls.append(("ingest", None)) or 0)
    monkeypatch.setattr(cli, "_train", lambda: calls.append(("train", None)))
    monkeypatch.setattr(cli, "cmd_cycle", lambda a: calls.append(("cycle", None)) or 0)
    monkeypatch.setattr(cli, "_operators", lambda: [("northwind", "csm00@northwind.example.com")])


def _args(**kw):
    return argparse.Namespace(**{"feeds": "../data/feeds", "seed": 20261015, "artifacts": "../artifacts",
                                 "demo_password": None, **kw})


def test_runs_every_stage_in_order_and_generates_only_when_there_are_no_feeds(monkeypatch, capsys):
    calls = []
    _wire(monkeypatch, calls, feeds_exist=False)
    assert cli.cmd_bootstrap_demo(_args(demo_password="a long demo passphrase")) == 0
    assert [c[0] for c in calls] == ["generate", "bootstrap", "ingest", "train", "cycle"]
    calls.clear()
    _wire(monkeypatch, calls, feeds_exist=True)
    cli.cmd_bootstrap_demo(_args(demo_password="a long demo passphrase"))
    assert [c[0] for c in calls] == ["bootstrap", "ingest", "train", "cycle"]


def test_a_password_is_generated_when_none_is_given_and_printed_once_with_the_sign_in(monkeypatch, capsys):
    calls = []
    _wire(monkeypatch, calls, feeds_exist=True)
    monkeypatch.delenv("PULSE_DEMO_PASSWORD", raising=False)
    cli.cmd_bootstrap_demo(_args())
    generated = dict(calls)["bootstrap"]
    assert generated and len(generated) >= 12
    out = capsys.readouterr().out
    assert generated in out and "northwind" in out and "csm00@northwind.example.com" in out and "5173" in out


def test_a_given_password_is_used_as_is_and_not_echoed(monkeypatch, capsys):
    calls = []
    _wire(monkeypatch, calls, feeds_exist=True)
    cli.cmd_bootstrap_demo(_args(demo_password="my own chosen passphrase"))
    assert dict(calls)["bootstrap"] == "my own chosen passphrase"
    assert "my own chosen passphrase" not in capsys.readouterr().out
