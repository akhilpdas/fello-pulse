#!/usr/bin/env bash
# Can this database run Pulse as it is?  Usage:  bash infra/render/probe.sh "<the database's external URL>"
#
# Pulse's migration creates two database roles -- one that serves requests and cannot bypass row-level security, one for
# model training that can (BYPASSRLS, normally a superuser-only privilege) -- and loading the demo seed inserts rows into
# tables whose row-level security is FORCEd. A managed database that gives you one ordinary user may refuse all of that.
# This tries each step inside a transaction it rolls back, so it leaves nothing behind, and prints a verdict:
#   GO            works as it is                                     (exit 0)
#   NEEDS-CHANGES roles can be created but not a bypass role         (exit 2)  -> spec 003 task T023
#   NO-GO         cannot create roles at all                         (exit 3)  -> use Railway instead
set -u
URL="${1:?usage: probe.sh <postgres URL>}"
sql() { psql "$URL" -X -q -tA -v ON_ERROR_STOP=1 -c "$1" 2>&1; }

if ! info="$(sql "SELECT rolsuper, rolcreaterole, rolbypassrls, current_user FROM pg_roles WHERE rolname = current_user")"; then
  echo "could not connect: $info"; exit 1
fi
IFS='|' read -r is_super can_createrole has_bypass whoami <<<"$info"

try() { sql "BEGIN; $1; ROLLBACK;" >/dev/null 2>&1 && echo yes || echo no; }
create_role="$(try "CREATE ROLE pulse_probe_a LOGIN NOSUPERUSER NOBYPASSRLS")"
create_bypass="$(try "CREATE ROLE pulse_probe_b LOGIN NOSUPERUSER BYPASSRLS")"

echo "connected as:                         $whoami"
echo "superuser:                            $is_super"
echo "has BYPASSRLS itself:                 $has_bypass"
echo "can create an ordinary login role:    $create_role"
echo "can create a BYPASSRLS role:          $create_bypass"

if [ "$create_role" = no ]; then
  echo "NO-GO: this database user cannot create roles, which the migration needs. Use Railway (its Postgres gives a superuser)."
  exit 3
fi
if [ "$create_bypass" = yes ] && { [ "$is_super" = t ] || [ "$has_bypass" = t ]; }; then
  echo "GO: roles can be created and rows can be loaded past row-level security. The migration and the seed work as they are."
  exit 0
fi
echo "NEEDS-CHANGES: roles can be created, but not a bypass role, and this user cannot load rows past row-level security."
echo "  Pulse needs two small changes for this host (spec 003 T023): skip the training role, and lift FORCE ROW LEVEL SECURITY"
echo "  for the length of the seed load. Railway needs neither."
exit 2
