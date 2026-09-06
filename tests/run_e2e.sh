#!/usr/bin/env bash
# End-to-end dry run on fictional data. Usage: tests/run_e2e.sh [workdir]
set -e
T=$(cd "$(dirname "$0")/.." && pwd); W=${1:-/tmp/idp_e2e}; rm -rf "$W"; mkdir -p "$W"
python3 "$T/tests/make_fixture.py" "$W" 2026-09-06
cd "$W"
python3 "$T/idp/parse_as.py" in/as.eml in/as_today.json
python3 "$T/idp/match.py" MISSING in/as_today.json in/wards.json in/ams.json out --date 06.09.2026 --roster in/roster.txt
cp "$T/tests/synth_fixture.py" synth.py
python3 "$T/idp/build.py" . "06 September 2026" --date 2026-09-06 --as-today in/as_today.json --ams in/ams.json | tail -3
grep -q "BUILD OK" <(python3 "$T/idp/build.py" . "06 September 2026" --date 2026-09-06 --as-today in/as_today.json --ams in/ams.json) && echo "E2E OK: $W"
