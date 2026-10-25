"""ProofCheck end-to-end API smoke/regression tests (unittest, standard library)."""
import base64
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server

class APITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        server.DB_PATH = Path(cls.temp.name)/'data.sqlite3'
        server.Handler.mode='desktop'
        server.initialize_db()
        cls.http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        cls.worker=threading.Thread(target=cls.http.serve_forever,daemon=True)
        cls.worker.start()
        cls.url=f'http://127.0.0.1:{cls.http.server_port}'
    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown();cls.http.server_close();cls.worker.join(2);cls.temp.cleanup()
    def req(self,path,data=None,method=None,origin=None):
        body=json.dumps(data).encode() if data is not None else None
        h={'Origin':origin} if origin else {}
        if data is not None:h['Content-Type']='application/json'
        try:
            r=urlopen(Request(self.url+path,data=body,method=method or ('POST' if data is not None else 'GET'),headers=h),timeout=12)
            return r.status,json.loads(r.read())
        except HTTPError as e:
            return e.code,json.loads(e.read())
    def test_01_health_and_html(self):
        c,d=self.req('/api/status');self.assertEqual(c,200);self.assertEqual(d['mode'],'desktop')
        with urlopen(self.url) as r:
            html=r.read().decode('utf-8');self.assertIn('ProofCheck',html);self.assertIn('فحوصات',html)
        with urlopen(self.url+'/assets/app.js') as r:self.assertIn(b'function dialog',r.read())
    def test_01_pwa_static_assets(self):
        import json
        for path, mime in [('/manifest.webmanifest','application/manifest+json'),('/sw.js','text/javascript'),('/assets/icon-192.png','image/png'),('/assets/icon-512.png','image/png')]:
            with urlopen(self.url+path) as r:
                self.assertEqual(r.status,200)
                self.assertIn(mime, r.headers.get('Content-Type',''))
                self.assertGreater(len(r.read()),20)
        with urlopen(self.url+'/manifest.webmanifest') as r:
            manifest=json.loads(r.read())
        self.assertEqual(manifest['short_name'],'ProofCheck')
    def test_02_session_report_evidence_revocation(self):
        c,d=self.req('/api/sessions',{'data':{'device':{'manufacturer':'TestBrand','model':'A1','serial':'SECRETSERIAL','seller':'Private Seller'},'repairs':[{'part':'screen','action':'replace','provider':'RepairShop'}]}})
        self.assertEqual(c,201);sid=d['session_id'];self.assertGreater(len(sid),20)
        c,d=self.req('/api/sessions/'+sid);self.assertEqual(c,200);self.assertEqual(d['data']['device']['serial'],'SECRETSERIAL')
        form={'data':d['data']};form['data']['checks']=[{'id':'screen','title':'Screen','status':'fail','method':'user_confirmed','details':'One line'}]
        c,_=self.req('/api/sessions/'+sid,form);self.assertEqual(c,200)
        fake_png=b'\x89PNG\r\n\x1a\n'+b'0'*100
        c,e=self.req(f'/api/sessions/{sid}/evidence',{'filename':'test.png','data':base64.b64encode(fake_png).decode()})
        self.assertEqual(c,201);self.assertEqual(e['sha256'],__import__('hashlib').sha256(fake_png).hexdigest());eid=e['id']
        c,d=self.req('/api/sessions/'+sid);self.assertEqual(len(d['evidence']),1)
        c,share=self.req(f'/api/sessions/{sid}/share',{'days':7});self.assertEqual(c,201)
        token=share['token'];self.assertTrue(share['path'].endswith(token))
        c,r=self.req('/api/share/'+token);self.assertEqual(c,200)
        self.assertEqual(r['data']['device']['serial'],'[محجوب للخصوصية]')
        self.assertEqual(r['data']['device']['seller'],'[محجوب للخصوصية]')
        self.assertEqual(r['data']['checks'][0]['status'],'fail')
        self.assertEqual(r['evidence'][0]['sha256'],e['sha256'])
        self.assertNotIn('body',r['evidence'][0])
        c,_=self.req(f'/api/sessions/{sid}/shares/{token}',method='DELETE');self.assertEqual(c,200)
        c,_=self.req('/api/share/'+token);self.assertEqual(c,404)
        c,_=self.req(f'/api/evidence/{sid}/{eid}',method='DELETE');self.assertEqual(c,200)
        c,_=self.req('/api/sessions/'+sid,method='DELETE');self.assertEqual(c,200)
        c,_=self.req('/api/sessions/'+sid);self.assertEqual(c,404)
    def test_03_invalid_input_and_csrf(self):
        code,_=self.req('/api/sessions',{'data':{'checks':[]}},origin='https://other-site.example');self.assertEqual(code,403)
        c,d=self.req('/api/sessions',{'data':{'device':{'category':'unknown'},'checks':[{'id':'x','status':'hacked'}]}})
        self.assertEqual(c,201);self.assertEqual(d['data']['device']['category'],'other');self.assertEqual(d['data']['checks'][0]['status'],'not_tested')
        sid=d['session_id']
        c,_=self.req(f'/api/sessions/{sid}/share',{'days':999});self.assertEqual(c,400)
        c,_=self.req(f'/api/sessions/{sid}/evidence',{'filename':'x.html','data':base64.b64encode(b'<script>bad</script>').decode()});self.assertEqual(c,400)
        c,_=self.req('/api/sessions/'+sid+'/automated',{'field':'device'});self.assertEqual(c,200)
        c,_=self.req('/api/sessions/'+sid+'/automated',{'field':'benchmarks'});self.assertEqual(c,403)
        c,_=self.req('/api/sessions/'+sid,method='DELETE');self.assertEqual(c,200)
    def test_04_cpu_memory_microbenchmarks(self):
        c,res=self.req('/api/benchmark',{'tests':['cpu','memory']});self.assertEqual(c,200)
        self.assertGreater(res['results']['cpu']['operations_per_second'],0)
        self.assertEqual(res['results']['memory']['bytes_tested'],8*1024*1024)
    def test_05_native_benchmark_is_server_measured(self):
        c,d=self.req('/api/sessions',{'data':{'checks':[{'id':'cpu','title':'CPU','method':'measured','status':'pass'}]}})
        sid=d['session_id']
        self.assertEqual(d['data']['checks'][0]['method'],'user_confirmed')
        c,r=self.req('/api/benchmark',{'tests':['cpu'],'session_id':sid})
        self.assertEqual(c,200)
        c,d=self.req('/api/sessions/'+sid)
        cpu=next(x for x in d['data']['checks'] if x['id']=='cpu')
        self.assertEqual(cpu['method'],'measured')
        previous=cpu['details']
        d['data']['checks']=[{'id':'cpu','title':'CPU','method':'measured','status':'fail','details':'fabricated'}]
        c,_=self.req('/api/sessions/'+sid,{'data':d['data']})
        self.assertEqual(c,200)
        c,d=self.req('/api/sessions/'+sid)
        cpu=next(x for x in d['data']['checks'] if x['id']=='cpu')
        self.assertEqual(cpu['status'],'pass')
        self.assertEqual(cpu['details'],previous)
        c,_=self.req('/api/sessions/'+sid,method='DELETE')
        self.assertEqual(c,200)
    def test_06_web_mode_isolated_sessions_and_browser_measurement(self):
        server.Handler.mode='web'
        try:
            with urlopen(self.url + '/assets/bench-worker.js') as response:
                self.assertEqual(response.status, 200)
                self.assertIn(b'Uint32Array', response.read())
            c, a = self.req('/api/sessions', {'data': {'device': {'model': 'OwnerA', 'serial': 'SECRET123'}, 'browser': {'userAgent': 'privateUA'}}})
            self.assertEqual(c, 201)
            c, b = self.req('/api/sessions', {'data': {'device': {'model': 'OwnerB'}}})
            self.assertEqual(c, 201)
            self.assertNotEqual(a['session_id'], b['session_id'])
            sid=a['session_id']
            c, owner=self.req('/api/sessions/'+sid)
            self.assertEqual(c,200)
            self.assertEqual(owner['data']['device']['model'],'OwnerA')
            owner['data']['checks']=[{'id':'cpu','title':'Browser CPU','status':'pass','method':'browser_measured','details':'Visitor browser benchmark'}]
            c,_=self.req('/api/sessions/'+sid,{'data':owner['data']})
            self.assertEqual(c,200)
            c,owner=self.req('/api/sessions/'+sid)
            self.assertEqual(owner['data']['checks'][0]['method'],'browser_measured')
            c,other=self.req('/api/sessions/'+b['session_id'])
            self.assertEqual(other['data']['device']['model'],'OwnerB')
            self.assertEqual(other['data']['checks'],[])
            c,link=self.req('/api/sessions/'+sid+'/share',{'days':1})
            self.assertEqual(c,201)
            c,report=self.req('/api/share/'+link['token'])
            self.assertEqual(report['data']['device']['serial'],'[محجوب للخصوصية]')
            self.assertEqual(report['data']['browser'], {})
            c,_=self.req('/api/system');self.assertEqual(c,403)
            c,_=self.req('/api/benchmark',{'tests':['cpu']});self.assertEqual(c,403)
        finally:
            server.Handler.mode='desktop'

    def test_07_web_rate_limiter(self):
        client='test-example-please-ignore'
        self.assertFalse(server.rate_limited(client,'create',2,3600))
        self.assertFalse(server.rate_limited(client,'create',2,3600))
        self.assertTrue(server.rate_limited(client,'create',2,3600))

    def test_05_web_mode_denies_host_inspection(self):
        server.Handler.mode='web'
        try:
            c,_=self.req('/api/system');self.assertEqual(c,403)
            c,_=self.req('/api/benchmark',{'tests':['cpu']});self.assertEqual(c,403)
            c,_=self.req('/api/sessions',{'data':{}});self.assertEqual(c,201)
        finally:
            server.Handler.mode='desktop'

if __name__=='__main__':unittest.main(verbosity=2)
