#!/usr/bin/env bash
# Fresh-container bootstrap: clone the toolkit and create the work tree. Usage: bash bootstrap.sh <repo_url> [/tmp/idp]
set -e
REPO=${1:?repo url}; W=${2:-/tmp/idp}
mkdir -p "$W/in" "$W/out"
rm -rf "$W/toolkit"; git clone -q --depth 1 "$REPO" "$W/toolkit"
python3 -c "import docx, openpyxl" && echo "python deps ok"
ls "$W/toolkit/idp"/*.py | xargs -n1 basename | tr '\n' ' '; echo
echo "toolkit commit: $(git -C "$W/toolkit" rev-parse --short HEAD)"
