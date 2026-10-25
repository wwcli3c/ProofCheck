#!/usr/bin/env python3
"""Consistent backup of a live ProofCheck SQLite database. Keep output encrypted/private."""
import os
from pathlib import Path
import sqlite3
import sys

if len(sys.argv) != 2:
    print('Usage: python tools/backup_db.py /secure-backups/proofcheck-YYYYMMDD.sqlite3')
    sys.exit(2)
source = Path(os.getenv('PROOFCHECK_DB', str(Path.home() / '.local/share/ProofCheck/proofcheck.sqlite3')))
target = Path(sys.argv[1]).resolve()
if not source.is_file() or target == source.resolve():
    sys.exit('Source not found or target equals source')
target.parent.mkdir(parents=True, exist_ok=True)
with sqlite3.connect(source.as_posix()) as original, sqlite3.connect(target.as_posix()) as copy:
    original.backup(copy)
print(f'Backup saved: {target} ({target.stat().st_size} bytes). Encrypt before uploading or moving it.')
