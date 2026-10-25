# ProofCheck 1.1 — public web & optional desktop inspector

See **[START_HERE_AR.md](START_HERE_AR.md)** for complete Arabic deploy instructions (Render, VPS/Docker/Caddy, Windows local). **README_AR.md** explains features and limitations.

## Test locally
```sh
python -m unittest discover -s tests -v
python server.py --mode web --port 8765 --no-browser
```
Open http://127.0.0.1:8765 (same computer only). For public users, deploy the repo via `render.yaml` to a paid always-on instance with persistent storage or use Docker Compose/Caddy and a domain on a reliable VPS.

Web browser tests run on the **visitor device**, not on the hosted server. Native hardware component attestation is not possible universally through a browser. No third-party telemetry is enabled. Store evidence in a trusted service with clear consent and appropriate privacy protections before production use.
