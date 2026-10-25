#!/usr/bin/env python3
"""ProofCheck 1.1: local inspection + opt-in self-hosted report service.
Standard-library HTTP/SQLite, no external telemetry. See README for threat model.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote
import xml.etree.ElementTree as ET
import legacy_agent as legacy

ROOT = Path(__file__).resolve().parent

def default_data_dir():
    if sys.platform == 'win32':
        return Path(os.environ.get('APPDATA') or Path.home() / 'AppData' / 'Roaming') / 'ProofCheck'
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'ProofCheck'
    return Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share') / 'ProofCheck'

DB_PATH = Path(os.environ.get('PROOFCHECK_DB', str(default_data_dir() / 'proofcheck.sqlite3')))
MAX_REQUEST = 3 * 1024 * 1024
LOCK = threading.Lock()
MODES = ('desktop', 'web')
# Browser measurements are generated on a user's own device and are explicitly
# untrusted self-reports; they must never be presented as verified native tests.
RATE_BUCKETS = {}
RATE_LOCK = threading.Lock()

def rate_limited(identity, operation, limit, window):
    current = time.monotonic()
    key = (identity, operation)
    with RATE_LOCK:
        if len(RATE_BUCKETS) > 20000:
            for k, v in list(RATE_BUCKETS.items()):
                if v[1] <= current:
                    RATE_BUCKETS.pop(k, None)
        count, end = RATE_BUCKETS.get(key, (0, current + window))
        if current >= end:
            count, end = 0, current + window
        RATE_BUCKETS[key] = (count + 1, end)
        return count >= limit



def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def db():
    c = sqlite3.connect(DB_PATH, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA busy_timeout=15000')
    c.execute('PRAGMA foreign_keys=ON')
    return c


def initialize_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.executescript('''
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY, created TEXT NOT NULL, updated TEXT NOT NULL,
            data TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS evidence (
            id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            filename TEXT NOT NULL, mime TEXT NOT NULL, bytes INTEGER NOT NULL,
            sha256 TEXT NOT NULL, body BLOB NOT NULL, created TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS shares (
            token TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            created TEXT NOT NULL, expires REAL NOT NULL, snapshot TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_evidence_session ON evidence(session_id);
        CREATE INDEX IF NOT EXISTS idx_shares_session ON shares(session_id);
        ''')


def clean_label(s, limit=120):
    if not isinstance(s, str):
        return ''
    return ''.join(ch for ch in s[:limit] if ch.isprintable()).strip()


def valid_choice(v, options, default='not_tested'):
    return v if v in options else default


RESULTS = {'pass', 'fail', 'not_tested', 'unavailable', 'needs_review'}


def normalize_session(input_data):
    if not isinstance(input_data, dict):
        raise ValueError('Invalid session document')
    if len(json.dumps(input_data, ensure_ascii=False)) > 180_000:
        raise ValueError('Session too large')
    source = input_data.get('device') or {}
    if not isinstance(source, dict):
        source = {}
    device = {k: clean_label(source.get(k, ''), 200) for k in
              ('category', 'manufacturer', 'model', 'serial', 'nickname', 'seller', 'notes')}
    device['category'] = valid_choice(device['category'], {'laptop', 'mobile', 'desktop', 'tablet', 'other'}, 'other')
    checks = []
    for item in (input_data.get('checks') or [])[:120]:
        if not isinstance(item, dict):
            continue
        ident = clean_label(item.get('id'), 45)
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,45}', ident):
            continue
        checks.append({'id': ident, 'title': clean_label(item.get('title'), 120),
                       'status': valid_choice(item.get('status'), RESULTS),
                       'method': valid_choice(item.get('method'), {'user_confirmed', 'browser_measured', 'unavailable'}, 'user_confirmed'),
                       'details': clean_label(item.get('details'), 600),
                       'timestamp': clean_label(item.get('timestamp'), 45)})
    repairs = []
    for r in (input_data.get('repairs') or [])[:100]:
        if isinstance(r, dict):
            repairs.append({'part': clean_label(r.get('part'), 120),
                            'action': valid_choice(r.get('action'), {'repair', 'replace', 'unknown'}, 'unknown'),
                            'date': clean_label(r.get('date'), 20),
                            'provider': clean_label(r.get('provider'), 150),
                            'evidence': clean_label(r.get('evidence'), 400),
                            'notes': clean_label(r.get('notes'), 500), 'verified': False})
    browser = input_data.get('browser')
    if not isinstance(browser, dict):
        browser = {}
    browser = {k: clean_label(browser.get(k), 250) for k in ('platform', 'userAgent', 'screen', 'ram', 'battery', 'connection')}
    automated = input_data.get('automated')
    if not isinstance(automated, dict):
        automated = {}
    # Desktop automated values are stored only when supplied by server endpoint, not trusted when supplied by client.
    return {'device': device, 'checks': checks, 'repairs': repairs, 'browser': browser,
            'automated': {}, 'remarks': clean_label(input_data.get('remarks'), 3000)}


def redact_snapshot(session_data, evidence_meta):
    data = json.loads(json.dumps(session_data))
    data.setdefault('device', {})['serial'] = '[محجوب للخصوصية]'
    data['device']['notes'] = '[محجوب للخصوصية]'
    data['browser'] = {}
    data['device']['seller'] = '[محجوب للخصوصية]'
    data['automated'] = data.get('automated') or {}
    if 'device' in data['automated']:
        info = data['automated']['device']
        if isinstance(info, dict):
            info.pop('hostname', None)
            info.pop('serial_number', None)
            if isinstance(info.get('device_identity'), dict):
                info['device_identity'].pop('serial_number', None)
    # Evidence files aren't shared; hashes are integrity fingerprints of stored evidence, not proof of its authenticity.
    return {'app': 'ProofCheck', 'version': '1.1', 'created': now(), 'data': data,
            'evidence': evidence_meta, 'disclaimer': 'A test records only the stated measurement or observation. Replacement/originality of internal components is not established by these tests.'}


def get_evidence_meta(c, session_id):
    return [dict(id=r['id'], filename=r['filename'], mime=r['mime'], bytes=r['bytes'], sha256=r['sha256'], created=r['created'])
            for r in c.execute('SELECT id,filename,mime,bytes,sha256,created FROM evidence WHERE session_id=? ORDER BY created', (session_id,))]


def battery_detail():
    sysname = platform.system()
    if sysname == 'Linux':
        for path in Path('/sys/class/power_supply').glob('BAT*'):
            def val(k):
                try: return (path / k).read_text().strip()
                except OSError: return None
            design = val('energy_full_design') or val('charge_full_design')
            full = val('energy_full') or val('charge_full')
            current = val('capacity')
            return {'source': 'Linux sysfs', 'design_capacity': design, 'full_capacity': full,
                    'health_percent_estimate': round(100 * int(full) / int(design), 1) if full and design and int(design) else None,
                    'charge_percent': current, 'cycle_count': val('cycle_count'),
                    'note': 'OS-exposed values, not forensic validation'}
    if sysname == 'Darwin':
        try:
            raw = subprocess.run(['system_profiler', 'SPPowerDataType', '-json'], capture_output=True, text=True, timeout=12)
            data = json.loads(raw.stdout)
            return {'source': 'macOS system_profiler', 'data': data.get('SPPowerDataType', []),
                    'note': 'Reported by macOS; fields vary by model'}
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    if sysname == 'Windows':
        # Writes a temporary XML report and removes it; XML parsing is version dependent.
        path = None
        try:
            fd, path = tempfile.mkstemp(prefix='proofcheck_battery_', suffix='.xml')
            os.close(fd)
            run = subprocess.run(['powercfg', '/batteryreport', '/xml', '/output', path], capture_output=True, timeout=16)
            if run.returncode == 0:
                root = ET.parse(path).getroot()
                values = {}
                for node in root.iter():
                    tag = node.tag.rsplit('}', 1)[-1]
                    if tag.lower() in {'designcapacity', 'fullchargecapacity', 'cyclecount'} and node.text:
                        values[tag] = node.text.strip()
                design = next((v for k,v in values.items() if k.lower()=='designcapacity'), None)
                full = next((v for k,v in values.items() if k.lower()=='fullchargecapacity'), None)
                try: health = round(100 * int(full) / int(design), 1) if design and full and int(design) else None
                except ValueError: health = None
                return {'source': 'Windows powercfg /batteryreport', 'values': values,
                        'health_percent_estimate': health,
                        'note': 'Capacity values from OS battery reporting; may be unsupported/inaccurate for some hardware'}
        except (OSError, ValueError, ET.ParseError, subprocess.TimeoutExpired):
            pass
        finally:
            if path:
                try: os.remove(path)
                except OSError: pass
    return {'available': False, 'note': 'Battery design/full capacity is not exposed in a supported way on this system'}


def expanded_system_info():
    result = legacy.system_info()
    if platform.system() == 'Linux':
        ident = result.get('device_identity') or {}
        def read(p):
            try: return Path(p).read_text().strip()
            except OSError: return None
        ident['manufacturer'] = read('/sys/class/dmi/id/sys_vendor')
        ident['model'] = read('/sys/class/dmi/id/product_name')
        ident['serial_number'] = read('/sys/class/dmi/id/product_serial')
        result['device_identity'] = ident
    result['battery_detail'] = battery_detail()
    result['collected_at'] = now()
    result['measurement_scope'] = 'OS-reported telemetry and short benchmarks only; component originality is not authenticated'
    return result


def expanded_storage():
    s = legacy.storage_health()
    cmd = shutil.which('smartctl')
    if cmd:
        try:
            scan = subprocess.run([cmd, '--scan', '-j'], capture_output=True, text=True, timeout=8)
            details = []
            for item in json.loads(scan.stdout or '{}').get('devices', [])[:8]:
                name = item.get('name')
                if not isinstance(name, str) or not re.fullmatch(r'[/A-Za-z0-9_.\\-]+', name):
                    continue
                args = [cmd, '-H', '-j', name]
                if item.get('type'):
                    args += ['-d', item['type']]
                res = subprocess.run(args, capture_output=True, text=True, timeout=10)
                try:
                    obj = json.loads(res.stdout)
                    details.append({'device': name, 'smart_available': obj.get('smart_support'),
                                    'smart_status': obj.get('smart_status'),
                                    'exit_code': res.returncode,
                                    'note': 'SMART self-report; does not guarantee no hidden defects'})
                except ValueError:
                    details.append({'device': name, 'error': 'Unable to parse SMART results (permissions or compatibility)'})
            s['smartctl'] = details
        except (OSError, ValueError, subprocess.TimeoutExpired):
            s['smartctl'] = {'available': False, 'note': 'smartctl scan failed, possibly due to permission limits'}
    else:
        s['smartctl'] = {'available': False, 'note': 'Install smartmontools for optional SMART status; may require elevated privileges'}
    return s


class Handler(BaseHTTPRequestHandler):
    mode = 'desktop'
    def _security(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('X-Robots-Tag', 'noindex, nofollow, noarchive')
        self.send_header('Permissions-Policy', 'camera=(self), microphone=(self), geolocation=()')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'")
    def send_bytes(self, code, data, mime='application/json; charset=utf-8', extra=None):
        self.send_response(code)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self._security()
        if extra:
            for k,v in extra.items(): self.send_header(k, v)
        self.end_headers()
        try: self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError): pass
    def reply(self, code, payload):
        self.send_bytes(code, json.dumps(payload, ensure_ascii=False, separators=(',', ':'), default=str).encode('utf-8'))
    def err(self, code, reason):
        self.reply(code, {'error': reason})
    def _request_ok(self, write=False):
        if self.mode == 'desktop':
            host = self.headers.get('Host', '').split(':')[0].lower().strip('[]')
            if host not in {'127.0.0.1', 'localhost', '::1'}:
                self.err(403, 'Local service only')
                return False
        else:
            allowed = os.environ.get('PROOFCHECK_ALLOWED_HOSTS', '').split(',')
            allowed = [s.strip().lower() for s in allowed if s.strip()]
            if allowed and self.headers.get('Host', '').split(':')[0].lower() not in allowed:
                self.err(403, 'Unrecognized host')
                return False
        if write:
            if self.mode == 'web':
                # Caddy replaces X-Real-IP before proxying. Only enable trust
                # when direct access to the backend is blocked at the network.
                client = self.client_address[0]
                if os.environ.get('PROOFCHECK_TRUST_PROXY') == '1':
                    forwarded = self.headers.get('X-Real-IP', '')
                    if re.fullmatch(r'[A-Fa-f0-9.:]{2,45}', forwarded):
                        client = forwarded
                path = urlparse(self.path).path
                if path == '/api/sessions':
                    group, max_count = 'create', int(os.environ.get('PROOFCHECK_CREATE_PER_HOUR', '12'))
                elif path.endswith('/evidence'):
                    group, max_count = 'upload', 36
                else:
                    group, max_count = 'write', 180
                if rate_limited(client, group, max_count, 3600 if group == 'create' else 600):
                    self.err(429, 'Rate limit exceeded; try again later')
                    return False
            origin = self.headers.get('Origin', '')
            if origin:
                requested = urlparse(origin)
                host = self.headers.get('Host', '')
                if requested.netloc != host or requested.scheme not in {'http', 'https'}:
                    self.err(403, 'Cross-origin request blocked')
                    return False
        return True
    def _input(self):
        if self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
            raise ValueError('Expected application/json')
        length = int(self.headers.get('Content-Length', '-1'))
        if length < 0 or length > MAX_REQUEST: raise ValueError('Request size exceeds limit')
        return json.loads(self.rfile.read(length))
    def do_GET(self):
        if not self._request_ok(): return
        path = urlparse(self.path).path
        if path in {'/', '/index.html'}:
            return self.file('index.html', 'text/html; charset=utf-8')
        if path == '/assets/app.js': return self.file('assets/app.js', 'text/javascript; charset=utf-8')
        if path == '/assets/bench-worker.js': return self.file('assets/bench-worker.js', 'text/javascript; charset=utf-8')
        if path == '/assets/style.css': return self.file('assets/style.css', 'text/css; charset=utf-8')
        if path == '/assets/icon-192.png': return self.file('assets/icon-192.png', 'image/png')
        if path == '/assets/icon-512.png': return self.file('assets/icon-512.png', 'image/png')
        if path == '/manifest.webmanifest': return self.file('manifest.webmanifest', 'application/manifest+json; charset=utf-8')
        if path == '/sw.js': return self.file('sw.js', 'text/javascript; charset=utf-8')
        if path.startswith('/report/') and re.fullmatch(r'/report/[A-Za-z0-9_-]{20,100}', path):
            return self.file('index.html', 'text/html; charset=utf-8')
        if path in {'/api/status', '/healthz'}:
            return self.reply(200, {'ok': True, 'mode': self.mode, 'version': '1.1', 'time': now(),
                                    'local_inspector': self.mode == 'desktop'})
        if path == '/api/system' or path == '/api/storage' or path.startswith('/api/benchmark/'):
            if self.mode != 'desktop': return self.err(403, 'Local native inspection is unavailable in web mode')
            if path == '/api/system': return self.reply(200, expanded_system_info())
            if path == '/api/storage': return self.reply(200, expanded_storage())
            return self.err(405, 'Benchmarks require POST')
        m = re.fullmatch(r'/api/sessions/([A-Za-z0-9_-]{20,100})', path)
        if m:
            with db() as c:
                row = c.execute('SELECT id,created,updated,data FROM sessions WHERE id=?', (m[1],)).fetchone()
                if not row: return self.err(404, 'Session not found')
                return self.reply(200, {'session_id': row['id'], 'created': row['created'], 'updated': row['updated'],
                                        'data': json.loads(row['data']), 'evidence': get_evidence_meta(c, m[1])})
        m = re.fullmatch(r'/api/evidence/([A-Za-z0-9_-]{20,100})/([A-Za-z0-9_-]{20,100})', path)
        if m:
            with db() as c:
                r = c.execute('SELECT mime,body FROM evidence WHERE session_id=? AND id=?', (m[1],m[2])).fetchone()
                if not r: return self.err(404, 'Evidence not found')
                return self.send_bytes(200, r['body'], r['mime'], {'Content-Disposition':'inline'})
        m = re.fullmatch(r'/api/share/([A-Za-z0-9_-]{20,100})', path)
        if m:
            with db() as c:
                r = c.execute('SELECT snapshot,expires FROM shares WHERE token=?', (m[1],)).fetchone()
                if not r or r['expires'] < time.time(): return self.err(404, 'Link expired or revoked')
                return self.reply(200, json.loads(r['snapshot']))
        return self.err(404, 'Not found')
    def file(self, relative, mime):
        try: data = (ROOT / relative).read_bytes()
        except OSError: return self.err(500, 'Missing application file')
        self.send_bytes(200, data, mime)
    def do_POST(self):
        if not self._request_ok(write=True): return
        path = urlparse(self.path).path
        try: body = self._input()
        except (ValueError, OverflowError, json.JSONDecodeError) as e: return self.err(400, str(e))
        try: return self._post(path, body)
        except (ValueError, TypeError) as e: return self.err(400, str(e))
        except sqlite3.Error: return self.err(500, 'Database error')
    def _post(self, path, body):
        if not isinstance(body, dict): raise ValueError('Expected JSON object')
        if path == '/api/sessions':
            if not isinstance(body, dict): raise ValueError('Expected object')
            record = normalize_session(body.get('data', {}))
            token = secrets.token_urlsafe(32)
            ts = now()
            with db() as c:
                c.execute('INSERT INTO sessions VALUES (?,?,?,?)', (token,ts,ts,json.dumps(record, ensure_ascii=False)))
            return self.reply(201, {'session_id': token, 'created': ts, 'data': record})
        m = re.fullmatch(r'/api/sessions/([A-Za-z0-9_-]{20,100})', path)
        if m:
            record = normalize_session(body.get('data', {}))
            with db() as c:
                r = c.execute('SELECT data FROM sessions WHERE id=?', (m[1],)).fetchone()
                if not r: return self.err(404, 'Session not found')
                old = json.loads(r['data'])
                record['automated'] = old.get('automated', {})
                # Preserve OS-verified / benchmark fields when the UI saves unrelated edits.
                old_verified = {v.get('id'):v for v in old.get('checks', []) if v.get('method') in ('measured','os_reported')}
                new_ids = {v.get('id') for v in record['checks']}
                record['checks'] = [old_verified.get(v['id'],v) if v['id'] in old_verified else v for v in record['checks']]
                record['checks'].extend(v for ident,v in old_verified.items() if ident not in new_ids)
                c.execute('UPDATE sessions SET data=?,updated=? WHERE id=?', (json.dumps(record,ensure_ascii=False),now(),m[1]))
            return self.reply(200, {'ok': True})
        if path == '/api/benchmark':
            if self.mode != 'desktop': return self.err(403, 'Not allowed for a remote server')
            tests = body.get('tests', [])
            if not isinstance(tests, list) or not tests or len(tests)>3 or any(x not in {'cpu','memory','disk'} for x in tests):
                raise ValueError('Select cpu, memory, disk only')
            with LOCK:
                results = {}
                for t in dict.fromkeys(tests):
                    results[t] = {'cpu': legacy.cpu_benchmark, 'memory': legacy.memory_benchmark, 'disk': legacy.disk_benchmark}[t]()
                session_id=body.get('session_id')
                if session_id is not None:
                    if not isinstance(session_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{20,100}',session_id):
                        raise ValueError('Invalid session id')
                    with db() as c:
                        row = c.execute('SELECT data FROM sessions WHERE id=?', (session_id,)).fetchone()
                        if not row: return self.err(404,'Session not found')
                        saved = json.loads(row['data'])
                        checks = {v['id']:v for v in saved.get('checks', [])}
                        for kind, value in results.items():
                            details = (f"{value.get('elapsed_seconds')} seconds; {value.get('operations_per_second')} ops/sec"
                                       if kind=='cpu' else
                                       f"{value.get('bytes_tested')} bytes touched in {value.get('elapsed_seconds')} seconds"
                                       if kind=='memory' else
                                       f"write {value.get('write_mib_per_second')} MiB/s; read {value.get('read_mib_per_second')} MiB/s, temporary file {value.get('size_bytes')} bytes")
                            if value.get('error'): details = value['error']
                            checks[kind] = {'id':kind,'title':{'cpu':'فحص المعالج القصير','memory':'فحص RAM القصير','disk':'سرعة التخزين القصيرة'}[kind],
                                            'method':'measured','status':'needs_review' if value.get('error') else 'pass',
                                            'details':details[:600],'timestamp':now()}
                        saved['checks']=list(checks.values())
                        c.execute('UPDATE sessions SET data=?,updated=? WHERE id=?', (json.dumps(saved,ensure_ascii=False),now(),session_id))
            return self.reply(200, {'results':results, 'created_at':now(), 'method':'measured_microbenchmark'})
        m = re.fullmatch(r'/api/sessions/([A-Za-z0-9_-]{20,100})/automated', path)
        if m:
            if self.mode != 'desktop': return self.err(403, 'Automated results cannot be submitted from browser in web mode')
            allowed = {'device', 'storage', 'benchmarks'}
            field = body.get('field')
            if field not in allowed: raise ValueError('Invalid automated field')
            # Stronger: receive only a nonce corresponding to a previous run? All local desktop data still from caller.
            with db() as c:
                r = c.execute('SELECT data FROM sessions WHERE id=?', (m[1],)).fetchone()
                if not r: return self.err(404, 'Session not found')
                data = json.loads(r['data'])
                # Re-evaluate from OS, rather than trusting client JSON.
                if field == 'device': obj = expanded_system_info()
                elif field == 'storage': obj = expanded_storage()
                else: return self.err(403, 'Benchmarks are saved client-side as measured check details; do not upload spoofable claims')
                data.setdefault('automated', {})[field] = obj
                if field=='storage':
                    smart = obj.get('smartctl')
                    available = isinstance(smart,list) and len(smart)>0
                    desc = 'SMART information reported by smartctl; device status is not a guarantee' if available else 'SMART not available; consult the OS details'
                    item = {'id':'storage_health','title':'حالة التخزين وSMART','status':'needs_review' if available else 'unavailable',
                            'method':'os_reported' if available else 'unavailable','details':desc,'timestamp':now()}
                    checks={x['id']:x for x in data.get('checks',[])}
                    checks['storage_health']=item
                    data['checks']=list(checks.values())
                c.execute('UPDATE sessions SET data=?,updated=? WHERE id=?', (json.dumps(data, ensure_ascii=False),now(),m[1]))
            return self.reply(200, {'ok':True, 'field':field})
        m = re.fullmatch(r'/api/sessions/([A-Za-z0-9_-]{20,100})/evidence', path)
        if m:
            filename = clean_label(body.get('filename'), 120) or 'file'
            try: raw = base64.b64decode(body.get('data',''), validate=True)
            except (ValueError, TypeError): raise ValueError('Invalid base64 content')
            if len(raw) == 0 or len(raw) > 2 * 1024 * 1024:
                raise ValueError('Each evidence file must be 1 byte to 2 MiB')
            mime = None
            if raw[:8] == b'\x89PNG\r\n\x1a\n': mime='image/png'
            elif raw[:3] == b'\xff\xd8\xff': mime='image/jpeg'
            elif raw[:4] == b'RIFF' and raw[8:12] == b'WEBP': mime='image/webp'
            elif raw[:5] == b'%PDF-': mime='application/pdf'
            if not mime: raise ValueError('Only PNG, JPEG, WebP, and PDF evidence files are accepted')
            token = secrets.token_urlsafe(18)
            digest = hashlib.sha256(raw).hexdigest()
            with db() as c:
                if not c.execute('SELECT 1 FROM sessions WHERE id=?', (m[1],)).fetchone(): return self.err(404,'Session not found')
                count = c.execute('SELECT COUNT(*) AS n FROM evidence WHERE session_id=?', (m[1],)).fetchone()['n']
                if count>=30: return self.err(400, 'Maximum 30 evidence files per session')
                c.execute('INSERT INTO evidence VALUES (?,?,?,?,?,?,?,?)', (token,m[1],filename,mime,len(raw),digest,raw,now()))
            return self.reply(201, {'id':token, 'filename':filename, 'bytes':len(raw), 'mime':mime,'sha256':digest})
        m = re.fullmatch(r'/api/sessions/([A-Za-z0-9_-]{20,100})/share', path)
        if m:
            days = body.get('days',7)
            if isinstance(days, bool) or not isinstance(days, int) or days<1 or days>30: raise ValueError('Share duration: 1–30 days')
            with db() as c:
                row = c.execute('SELECT data FROM sessions WHERE id=?', (m[1],)).fetchone()
                if not row: return self.err(404,'Session not found')
                snapshot = redact_snapshot(json.loads(row['data']),get_evidence_meta(c,m[1]))
                token = secrets.token_urlsafe(32)
                expires = time.time() + days * 86400
                c.execute('INSERT INTO shares VALUES (?,?,?,?,?)',(token,m[1],now(),expires,json.dumps(snapshot,ensure_ascii=False)))
            return self.reply(201, {'token':token, 'path':'/report/'+token, 'expires_epoch':expires,
                                    'note':'Public only if you deploy the server on a public HTTPS domain. Local links stay local.'})
        return self.err(404, 'Not found')
    def do_DELETE(self):
        if not self._request_ok(write=True): return
        path = urlparse(self.path).path
        m = re.fullmatch(r'/api/sessions/([A-Za-z0-9_-]{20,100})/shares/([A-Za-z0-9_-]{20,100})',path)
        if m:
            with db() as c:
                n = c.execute('DELETE FROM shares WHERE session_id=? AND token=?',(m[1],m[2])).rowcount
            return self.reply(200 if n else 404, {'ok':bool(n)})
        m = re.fullmatch(r'/api/evidence/([A-Za-z0-9_-]{20,100})/([A-Za-z0-9_-]{20,100})',path)
        if m:
            with db() as c:
                n = c.execute('DELETE FROM evidence WHERE session_id=? AND id=?',(m[1],m[2])).rowcount
            return self.reply(200 if n else 404, {'ok':bool(n)})
        m = re.fullmatch(r'/api/sessions/([A-Za-z0-9_-]{20,100})',path)
        if m:
            with db() as c:
                n = c.execute('DELETE FROM sessions WHERE id=?',(m[1],)).rowcount
            return self.reply(200 if n else 404, {'ok':bool(n)})
        return self.err(404, 'Not found')
    def log_message(self, fmt, *args):
        if os.environ.get('PROOFCHECK_VERBOSE') == '1':
            print('[ProofCheck]', fmt % args)


def main(argv=None):
    p = argparse.ArgumentParser(description='ProofCheck hardware inspection and report server')
    p.add_argument('--mode', choices=MODES, default='desktop', help='desktop=local hardware, web=browser-only remote users')
    p.add_argument('--host', default=None)
    p.add_argument('--port', type=int, default=8765)
    p.add_argument('--no-browser', action='store_true')
    opts = p.parse_args(argv)
    if not (1 <= opts.port <= 65535): p.error('Invalid port')
    opts.host = opts.host or ('127.0.0.1' if opts.mode == 'desktop' else '0.0.0.0')
    if opts.mode == 'desktop' and opts.host not in {'127.0.0.1', '::1', 'localhost'}:
        p.error('Desktop inspector must only listen on localhost')
    if opts.mode == 'web' and opts.host not in {'127.0.0.1','::1','localhost','0.0.0.0'}:
        print('Warning: deploy behind TLS reverse proxy; public plain HTTP disables camera/mic in browsers')
    initialize_db()
    Handler.mode=opts.mode
    server = ThreadingHTTPServer((opts.host, opts.port), Handler)
    server.daemon_threads=True
    print(f'ProofCheck 1.1: http://127.0.0.1:{opts.port} | mode={opts.mode}')
    print('Use only devices you own or have permission to inspect. Ctrl+C to exit.')
    if opts.mode=='web': print('For remote mobiles: deploy behind HTTPS, configure backups/limits, do not expose this demo directly to the internet.')
    if not opts.no_browser and opts.mode=='desktop':
        import webbrowser
        webbrowser.open(f'http://127.0.0.1:{opts.port}')
    try: server.serve_forever()
    except KeyboardInterrupt: print('\nShutting down')
    finally: server.server_close()

if __name__ == '__main__': main()
