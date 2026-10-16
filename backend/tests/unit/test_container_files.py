"""T289 (FR-031, FR-033, FR-034): static checks on the container definitions.

**These files have never been run.** Docker is not installed on the machine this was built on, so everything here is
verified by reading the files, not by building them. The test exists so that the properties that can be checked
without a container runtime do not rot: dependency ordering, healthchecks, no secrets or data baked into an image,
a non-root user, data kept in volumes, and the honest "unverified" label in the documentation.

Names the production change that makes it fail: the container files and the label do not exist yet.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
COMPOSE = ROOT / "docker-compose.yml"
BACKEND = ROOT / "infra" / "docker" / "backend.Dockerfile"
FRONTEND = ROOT / "infra" / "docker" / "frontend.Dockerfile"
IGNORE = ROOT / ".dockerignore"

def _compose() -> dict:
    return yaml.safe_load(COMPOSE.read_text())


def test_the_stack_has_the_four_services_the_system_needs():
    assert {"db", "api", "worker", "web"} <= set(_compose()["services"])


def test_the_database_has_a_healthcheck_and_a_named_volume_and_is_not_exposed_to_the_network():
    db = _compose()["services"]["db"]
    assert "healthcheck" in db
    assert any(str(v).split(":")[0] in _compose().get("volumes", {}) for v in db["volumes"]), "data must live in a named volume"
    for port in db.get("ports", []):
        assert str(port).startswith("127.0.0.1:"), f"database published beyond localhost: {port}"


def test_everything_waits_for_what_it_needs_to_be_healthy():
    s = _compose()["services"]
    for name in ("api", "worker"):
        assert s[name]["depends_on"]["db"]["condition"] == "service_healthy", name
    assert "healthcheck" in s["api"]
    assert s["worker"]["depends_on"]["api"]["condition"] == "service_healthy"  # one place runs migrations: the api
    assert s["web"]["depends_on"]["api"]["condition"] == "service_healthy"


def test_the_worker_runs_the_unattended_loop():
    cmd = _compose()["services"]["worker"]["command"]
    assert "pulse.cli" in " ".join(cmd) and "serve" in cmd


def test_no_password_or_key_is_a_literal_in_the_compose_file():
    for line in COMPOSE.read_text().splitlines():
        key = line.split(":", 1)[0]  # the setting's *name*; a URL value may mention a variable without being a secret
        if re.search(r"(PASSWORD|_KEY|SECRET)", key, re.I) and ":" in line and not line.strip().startswith("#"):
            value = line.split(":", 1)[1].strip().strip("\"'")
            if value:
                assert re.fullmatch(r"\$\{[A-Z0-9_]+(:-[^}]*)?\}", value) or value.startswith("$"), \
                    f"a credential is written literally: {line.strip()}"


def test_dockerfiles_exist_and_bake_in_no_secrets_or_data():
    for f in (BACKEND, FRONTEND):
        assert f.exists(), f
        text = f.read_text()
        assert not re.search(r"^\s*COPY\s+.*\b(data|artifacts)\b", text, re.M), f"{f.name} copies generated data/models"
        assert not re.search(r"^\s*COPY\s+.*\.env|\.demo-credentials", text, re.M), f"{f.name} copies a secrets file"
        assert not re.search(r"^\s*(ENV|ARG)\s+\S*(PASSWORD|SECRET|API_KEY)\S*\s*=?\s*\S+", text, re.M | re.I), \
            f"{f.name} sets a credential"


def test_the_backend_image_is_multistage_and_runs_as_a_non_root_user():
    text = BACKEND.read_text()
    assert len(re.findall(r"^FROM\s", text, re.M)) >= 2, "single-stage build ships the compiler and caches"
    assert re.search(r"^USER\s+(?!root)\S+", text, re.M), "the process must not run as root"


def test_the_build_context_excludes_what_must_never_enter_an_image():
    ignored = IGNORE.read_text()
    for must in ("data", "artifacts", ".env", ".demo-credentials", ".venv", "node_modules", ".git"):
        assert must in ignored, f".dockerignore does not exclude {must}"


def test_the_entrypoint_waits_for_the_database_and_migrates_only_for_the_api():
    ep = (ROOT / "infra" / "docker" / "entrypoint.sh").read_text()
    assert "alembic" in ep and "upgrade head" in ep and "MIGRATE" in ep


def test_the_documents_say_exactly_what_was_verified_about_the_containers_and_what_was_not():
    """The containers were built and run on 2026-10-17 (Colima, Apple-silicon, linux/arm64). Documents must say *that*, and
    name what was not checked -- not keep calling it unverified, and not claim more than was done."""
    readme = (ROOT / "README.md").read_text()
    section = readme[readme.index("## Containers"):readme.index("## Layout")]
    for evidence in ("Colima", "arm64", "bootstrap-demo", "browser"):
        assert evidence in section, f"README's Containers section does not mention {evidence}"
    assert re.search(r"amd64.*not|not.*amd64", section, re.I | re.S), "must say the amd64 build was not checked"
    for stale in ("never been built", "never built", "UNVERIFIED", "Docker is not installed"):
        assert stale not in section, f"stale claim in README Containers section: {stale!r}"
    for doc in ("docs/SOLUTION_BRIEF.md", "docs/DECK.md"):  # current-state documents must not say "never built"
        text = (ROOT / doc).read_text()
        assert "never built" not in text and "never been built" not in text, doc
    handoff = (ROOT / "HANDOFF.md").read_text()  # dated history is kept, but must carry the superseding section
    assert "Containers verified (2026-10-17)" in handoff and "supersedes every earlier" in handoff
