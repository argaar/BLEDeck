#!/usr/bin/env bash
# Unified test runner — Python (windows_app + simulator) + firmware native
# Unity tests. Continues past failures to give a complete picture; exits 0
# only if every suite passes.
set -uo pipefail

cd "$(dirname "$0")"

py_rc=0
pio_rc=0

echo "=== Python tests (windows_app + simulator) ==="
python -m pytest windows_app/tests/ simulator/tests/ -q || py_rc=$?

echo
echo "=== Firmware native tests (Unity) ==="
if command -v pio >/dev/null 2>&1; then
    pio test -e native -d firmware || pio_rc=$?
else
    echo "SKIP: PlatformIO CLI 'pio' not on PATH — install with 'pip install platformio'"
fi

echo
echo "=== Summary ==="
echo "Python   : exit code $py_rc"
echo "Firmware : exit code $pio_rc"

exit $(( py_rc != 0 ? py_rc : pio_rc ))
