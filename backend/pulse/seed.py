"""The demo seed: a pre-built database a reviewer loads in minutes instead of building for 10 to 46 (spec 003).

``export_seed`` dumps a built demo database; ``load_seed`` restores it into a migrated, empty one. The seed is a
shortcut, never a replacement: ``bootstrap-demo`` and ``backfill`` still build the same estate from scratch.
All data in it is simulated (``@example.com`` addresses); it carries no credential and no owner information.
"""

from __future__ import annotations

import hashlib
import json
import tarfile
from contextlib import contextmanager, nullcontext
from dataclasses import asdict, dataclass, field
from pathlib import Path


class SeedError(Exception):
    """A seed that must not be loaded, or a load that did not reproduce what the manifest describes."""


@dataclass(frozen=True)
class Manifest:
    schema_revision: str            # the alembic revision the dump was taken at; a load needs a database at the same one
    sha256: str                     # of the dump file
    created: str                    # ISO date
    row_counts: dict[str, int]      # per table, to verify a load against
    drafts: dict = field(default_factory=dict)   # how drafts were written: model, date, llm and template counts
    artifacts_sha256: str = ""      # of <seed>.artifacts.tar.gz (the promoted model); empty when the seed carries none

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> Manifest:
        return cls(**json.loads(text))


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_file(path: Path, manifest: Manifest) -> None:
    actual = sha256_of(path)
    if actual != manifest.sha256:
        raise SeedError(f"the seed file does not match its manifest (sha256 {actual[:12]}… vs {manifest.sha256[:12]}…); "
                        "download it again")


def check_loadable(*, tenant_count: int, db_revision: str, manifest: Manifest, file: Path, overwrite: bool) -> None:
    """Raise ``SeedError`` unless the seed may be loaded. Called before anything is touched."""
    verify_file(file, manifest)
    if db_revision != manifest.schema_revision:
        raise SeedError(f"the database is at schema revision {db_revision} but the seed was dumped at "
                        f"{manifest.schema_revision}; migrate the database (or fetch the seed that matches this release)")
    if tenant_count and not overwrite:
        raise SeedError(f"the database already holds {tenant_count} tenant(s); loading would mix two demos. "
                        "Pass --overwrite to replace them with the seed")


# Never in a seed: the migration owns the schema version, and the rest is *live state of whoever built it* --
# a sign-in session or a login attempt from the publisher's machine must not exist on someone else's database.
EXCLUDED_TABLES = ("alembic_version", "app_session", "login_attempt", "work_lease")


def export_seed(*, dsn: str, out: Path, revision: str, row_counts: dict[str, int], drafts: dict, created: str,
                outbound_enabled_tenants: int, run, artifacts_dir: Path | None = None) -> Manifest:
    """Dump the data of a built demo database to ``out`` and write ``<out>.json`` describing exactly that file.

    Data only: the migrations create the schema, the roles and row-level security, so a seed can never smuggle a
    different one in. Refuses to run when any tenant can send real email: a seed must never ship in a sending state."""
    if outbound_enabled_tenants:
        raise SeedError(f"{outbound_enabled_tenants} tenant(s) have outbound email enabled; switch it off in Admin before "
                        "exporting -- a published seed must never be able to send mail")
    out = Path(out)
    argv = ["pg_dump", "-Fc", "--data-only", "--no-owner"]
    for table in EXCLUDED_TABLES:
        argv += ["-T", table]
    argv += ["-f", str(out), dsn]
    run(argv, check=True)
    archive_sha = ""
    if artifacts_dir is not None:
        archive_sha = pack_artifacts(artifacts_dir, out.with_name(out.name + ".artifacts.tar.gz")) or ""
    manifest = Manifest(schema_revision=revision, sha256=sha256_of(out), created=created, row_counts=row_counts,
                        drafts=drafts, artifacts_sha256=archive_sha)
    out.with_name(out.name + ".json").write_text(manifest.to_json())
    return manifest


def needs_rls_lift(session) -> bool:
    """True when this login is subject to FORCEd row-level security: neither a superuser nor BYPASSRLS (a managed
    database's login). Such a login sees no tenant rows without a tenant claim, so a bulk load cannot count or fix up
    what it restored."""
    from sqlalchemy import text
    return not session.execute(text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")).scalar()


@contextmanager
def rls_lifted(session):
    """Switch FORCE ROW LEVEL SECURITY off on the tables that have it, for the length of the load, then switch it back.
    An owner is exempt from row-level security that is not forced. ENABLE stays on throughout, so the request role
    (``pulse_app``, NOBYPASSRLS) is never unprotected. Committed on both sides because the restore is another connection."""
    from sqlalchemy import text
    tables = [r[0] for r in session.execute(text(
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relforcerowsecurity")).all()]
    for t in tables:
        session.execute(text(f'ALTER TABLE "{t}" NO FORCE ROW LEVEL SECURITY'))
    session.commit()
    try:
        yield tables
    finally:
        session.rollback()
        for t in tables:
            session.execute(text(f'ALTER TABLE "{t}" FORCE ROW LEVEL SECURITY'))
        session.commit()


def load_seed(*, file: Path, manifest: Manifest, dsn: str, tenant_count: int, db_revision: str, overwrite: bool,
              demo_password: str, restore, truncate, set_passwords, row_counts, artifacts_dest: Path | None = None,
              lift_rls=None) -> None:
    """Restore a seed into a migrated database. Order matters and every refusal happens before the first change:
    check -> (empty the old data if asked) -> restore -> set the password for the person loading -> verify the counts."""
    from pulse.auth.passwords import PasswordPolicyError, validate_password

    try:
        validate_password(demo_password, "demo@example.test")
    except PasswordPolicyError as exc:
        raise SeedError(f"demo password refused: {exc}") from exc
    check_loadable(tenant_count=tenant_count, db_revision=db_revision, manifest=manifest, file=file, overwrite=overwrite)
    archive = Path(file).with_name(Path(file).name + ".artifacts.tar.gz")
    if manifest.artifacts_sha256 and artifacts_dest is not None:
        if not archive.exists() or sha256_of(archive) != manifest.artifacts_sha256:
            raise SeedError("the model archive is missing or does not match the manifest's sha256; download the seed again")
    with (lift_rls() if lift_rls else nullcontext()):        # a login that is subject to forced row-level security (Render)
        if tenant_count:
            truncate()
        restore(dsn, file)
        # The seed carries the publisher's password hashes; nobody else knows that password. Replace every one.
        set_passwords(demo_password)
        got = row_counts()
    wrong = {t: (n, got.get(t)) for t, n in manifest.row_counts.items() if got.get(t) != n}
    if wrong:
        detail = ", ".join(f"{t}: expected {a}, found {b}" for t, (a, b) in wrong.items())
        raise SeedError(f"the restore did not reproduce the seed ({detail})")
    if manifest.artifacts_sha256 and artifacts_dest is not None:
        unpack_artifacts(archive, artifacts_dest)


def pack_artifacts(directory: Path, out: Path) -> str | None:
    """Archive the latest promoted model (its card and its pickle) and return the archive's sha256, or None if no model
    is promoted. The model is files, not rows: a seed without it has scores but no ``/model`` report and no worker."""
    directory = Path(directory)
    cards = []
    for p in directory.glob("*.json"):
        try:
            card = json.loads(p.read_text())
        except ValueError:
            continue
        if isinstance(card, dict) and card.get("promoted"):
            cards.append((card.get("trained_at", ""), p))
    if not cards:
        return None
    card_path = max(cards)[1]
    with tarfile.open(out, "w:gz") as tar:
        for member in (card_path, card_path.with_suffix(".pkl")):
            tar.add(member, arcname=member.name)
    return sha256_of(out)


def unpack_artifacts(archive: Path, dest: Path) -> None:
    """Extract a model archive, refusing any member that would land outside ``dest``."""
    dest = Path(dest).resolve()
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            target = (dest / member.name).resolve()
            if not member.isfile() or dest not in target.parents:
                raise SeedError(f"the model archive holds {member.name!r}, which is outside the artifacts folder; refusing it")
        for member in tar.getmembers():
            tar.extract(member, dest, filter="data")


_UNSUPPORTED = (b"SET transaction_timeout = ",)


def strip_unsupported_settings(lines):
    """Drop settings a newer ``pg_restore`` writes but an older server rejects. Debian's pg_restore 17 emits
    ``SET transaction_timeout`` even for a 16 server (found by loading a seed in Docker); restoring through a filter
    keeps the client's version independent of the server's, which differs across Docker, Railway and Render."""
    return (line for line in lines if not line.startswith(_UNSUPPORTED))


def restore_stream(dsn: str, file: Path) -> None:
    """``pg_restore --data-only`` -> filter -> ``psql`` in one transaction, streamed (no temporary SQL file)."""
    import subprocess

    src = subprocess.Popen(["pg_restore", "--data-only", "--no-owner", "-f", "-", str(file)], stdout=subprocess.PIPE)
    dst = subprocess.Popen(["psql", "-X", "-q", "-1", "-v", "ON_ERROR_STOP=1", dsn], stdin=subprocess.PIPE,
                           stdout=subprocess.DEVNULL)
    try:
        for line in strip_unsupported_settings(src.stdout):
            dst.stdin.write(line)
    except BrokenPipeError:      # psql stopped reading: its exit code below says why
        pass
    finally:
        if dst.stdin:
            dst.stdin.close()
    src_rc, dst_rc = src.wait(), dst.wait()
    if src_rc or dst_rc:
        raise SeedError(f"the restore failed (pg_restore exit {src_rc}, psql exit {dst_rc}); the database was left unchanged "
                        "because the load is one transaction")
