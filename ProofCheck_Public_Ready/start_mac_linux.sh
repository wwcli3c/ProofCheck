#!/usr/bin/env sh
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then
  python3 server.py --mode desktop
else
  echo 'Python 3.10+ required.'
  exit 1
fi
