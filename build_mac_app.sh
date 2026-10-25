#!/bin/sh
set -e
cd "$(dirname "$0")"
python3 -m pip install --user pyinstaller
python3 -m PyInstaller --noconfirm --clean --onefile --windowed --name ProofCheck --add-data 'index.html:.' --add-data 'assets:assets' server.py
printf '\nBuilt in dist/ProofCheck.app (unsigned; distribute only after signing/notarization).\n'
