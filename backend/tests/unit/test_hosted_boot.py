"""Turning what a hosting platform provides into what the application needs (spec 003, T018).

A managed database gives one URL, ``postgresql://owner:secret@host/db``. The application wants the ``psycopg`` driver
prefix for the owner (migrations, seed) and a second, restricted login -- ``pulse_app``, which cannot bypass row-level
security -- for everything that serves a request. Same host, same database, different user.
"""

from __future__ import annotations

from pulse.hosted_boot import app_url_from, normalise_owner_url


def test_a_plain_postgres_url_gets_the_driver_prefix():
    assert normalise_owner_url("postgresql://u:p@db.example:5432/pulse") == "postgresql+psycopg://u:p@db.example:5432/pulse"


def test_the_older_postgres_scheme_some_platforms_still_hand_out_is_accepted():
    assert normalise_owner_url("postgres://u:p@h/d") == "postgresql+psycopg://u:p@h/d"


def test_an_already_prefixed_url_is_left_alone():
    url = "postgresql+psycopg://u:p@h/d"
    assert normalise_owner_url(url) == url


def test_the_request_serving_login_is_pulse_app_on_the_same_host_and_database():
    assert app_url_from("postgresql+psycopg://owner:secret@db.example:5432/pulse") == \
        "postgresql+psycopg://pulse_app:pulse_app@db.example:5432/pulse"


def test_query_options_such_as_ssl_survive_the_swap():
    owner = "postgresql+psycopg://owner:secret@db.example/pulse?sslmode=require"
    assert app_url_from(owner) == "postgresql+psycopg://pulse_app:pulse_app@db.example/pulse?sslmode=require"


def test_a_socket_style_url_without_credentials_is_handled():
    assert app_url_from("postgresql+psycopg://pulse@/pulse?host=/tmp&port=5432") == \
        "postgresql+psycopg://pulse_app:pulse_app@/pulse?host=/tmp&port=5432"
