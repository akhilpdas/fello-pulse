"""T215 (FR-021): the new auth/mail/LLM settings exist with safe defaults, and secrets never
appear when the settings object is printed or logged.

Names the production change that makes it fail: the new fields on ``pulse.config.Settings``
(``SecretStr`` for ``smtp_password`` and ``llm_api_key``), and removal of the unused hard-coded
``auth_secret`` default.
"""

from __future__ import annotations

from pulse.config import Settings


def test_defaults_are_safe():
    s = Settings(_env_file=None)
    assert s.session_hours == 12
    assert (s.login_max_failures, s.login_window_seconds) == (5, 300)
    assert s.cookie_secure is False  # dev over http; docs say set true behind https
    assert s.smtp_host is None and s.smtp_port == 587 and s.smtp_starttls is True
    assert s.llm_enabled is False and s.llm_api_key is None and s.smtp_password is None
    assert s.llm_model == "claude-sonnet-5-5"


def test_secrets_never_appear_in_repr_or_str_or_dump():
    s = Settings(smtp_password="hunter2-smtp", llm_api_key="sk-ant-secret-key", _env_file=None)
    for rendered in (repr(s), str(s), str(s.model_dump()), s.model_dump_json()):
        assert "hunter2-smtp" not in rendered
        assert "sk-ant-secret-key" not in rendered
    # ...but the code that needs them can still get them, explicitly.
    assert s.smtp_password.get_secret_value() == "hunter2-smtp"
    assert s.llm_api_key.get_secret_value() == "sk-ant-secret-key"


def test_there_is_no_hardcoded_default_secret():
    assert not hasattr(Settings(_env_file=None), "auth_secret")
