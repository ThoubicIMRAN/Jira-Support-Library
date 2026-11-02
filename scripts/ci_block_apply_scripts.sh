#!/usr/bin/env bash
# CI guard (H1): fail the build if source-rewriting APPLY scripts or large
# base64 blobs are committed. These hide code from review and can overwrite
# production sources when imported.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

FAILED=0

# 1) Block *_APPLY.py / *APPLY*.py outside scripts/ and tests/
while IFS= read -r f; do
  [ -z "$f" ] && continue
  echo "ERROR: APPLY script must not be committed: $f"
  FAILED=1
done <<EOF
$(find . -type f \( -name '*_APPLY.py' -o -name '*APPLY*.py' \) \
  ! -path './.git/*' ! -path './scripts/*' ! -path './tests/*' 2>/dev/null || true)
EOF

# 2) Block known rewrite script names
for name in SYNC_LATEST_APPLY.py DIALOG_SAFETY_APPLY.py CI_FIX_DIALOG.py PHASE1_APPLY.py; do
  found=$(find . -name "$name" ! -path './.git/*' 2>/dev/null || true)
  if [ -n "$found" ]; then
    echo "ERROR: Forbidden rewrite script present: $found"
    FAILED=1
  fi
done

# 3) Flag large base64 payloads embedded in .py files (> 8 KB continuous)
while IFS= read -r f; do
  [ -z "$f" ] && continue
  if python3 -c "
import re, sys
path = sys.argv[1]
try:
    text = open(path, encoding='utf-8', errors='ignore').read()
except Exception:
    sys.exit(0)
for m in re.finditer(r'[A-Za-z0-9+/]{8000,}={0,2}', text):
    print(f'ERROR: large base64 blob in {path} (len={len(m.group(0))})')
    sys.exit(1)
sys.exit(0)
" "$f"; then
    :
  else
    FAILED=1
  fi
done <<EOF
$(find . -type f -name '*.py' ! -path './.git/*' ! -path './.venv/*' 2>/dev/null || true)
EOF

if [ "$FAILED" -ne 0 ]; then
  echo ""
  echo "ci_block_apply_scripts: failed. Remove APPLY/SYNC rewrite scripts and base64 source dumps."
  echo "Source changes must be normal commits, not self-modifying payloads."
  exit 1
fi

echo "ci_block_apply_scripts: OK"
exit 0
