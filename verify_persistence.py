"""HTTP, migration, restart and CSV checks using temporary synthetic data only."""
from concurrent.futures import ThreadPoolExecutor
import csv
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
from uuid import uuid4
ROOT=Path(__file__).resolve().parent

def check():
    with tempfile.TemporaryDirectory() as directory:
        db=Path(directory)/'synthetic.sqlite3'
        # Exercise migration from the previous schema, retaining an existing participant.
        with sqlite3.connect(db) as con:
            con.execute('CREATE TABLE participant(code TEXT PRIMARY KEY,access_hash TEXT UNIQUE NOT NULL)')
            con.execute("INSERT INTO participant VALUES('LEGACY-001','legacy-test-hash')")
        args=[sys.executable,str(ROOT/'server.py'),'--db',str(db)]
        def add(code,center):
            return subprocess.check_output(args+['add',code,'--center',center],text=True).strip()
        secret_a=add('SYNTH-A001','A');secret_b=add('SYNTH-B001','B');secret_c=add('SYNTH-C001','C')
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1]
        def start():
            p=subprocess.Popen(args+['serve','--port',str(port)],stdout=subprocess.PIPE,text=True,
                               env={**os.environ,'EVVARDIA_GUIDANCE_ENABLED':'0'})
            assert p.stdout.readline().strip()==f'http://127.0.0.1:{port}'
            return p
        def request(path,data=None,cookie='',owner='SYNTH-A001'):
            http=HTTPConnection('127.0.0.1',port,timeout=5)
            http.request('GET' if data is None else 'POST',path,None if data is None else json.dumps(data),
                         {'Origin':f'http://127.0.0.1:{port}','Content-Type':'application/json',
                          'Cookie':cookie,'X-Study-Participant':owner})
            r=http.getresponse();text=r.read().decode();token=r.getheader('Set-Cookie','').split(';')[0];http.close()
            return r.status,json.loads(text),token
        process=start()
        try:
            body=dict(record_id=str(uuid4()),assessment_date='2026-11-20',values=[2,4,3])
            assert request('/api/checkins',body)[0]==401
            ca=request('/login',{'access_code':secret_a})[2];cb=request('/login',{'access_code':secret_b})[2]
            cc=request('/login',{'access_code':secret_c})[2]
            assert request('/api/checkins',body,cb)[0]==403
            assert request('/api/checkins',{**body,'center_id':'B'},ca)[0]==400
            with ThreadPoolExecutor(max_workers=2) as pool:
                results=list(pool.map(lambda _:request('/api/checkins',body,ca),range(2)))
            assert sorted(r[0] for r in results)==[200,201]
            assert request('/api/checkins',{**body,'values':[5,4,3]},ca)[0]==409
            # Force a storage failure: HTTP must not claim a successful save.
            with sqlite3.connect(db) as con:
                con.execute("CREATE TRIGGER fail_test BEFORE INSERT ON response WHEN NEW.assessment_date='2026-11-21' BEGIN SELECT RAISE(ABORT,'synthetic storage failure'); END")
            assert request('/api/checkins',{**body,'record_id':str(uuid4()),'assessment_date':'2026-11-21'},ca)[0]==503
            with sqlite3.connect(db) as con:
                assert con.execute('SELECT count(*) FROM response').fetchone()[0]==1
                con.execute('DROP TRIGGER fail_test')
            revision={**body,'record_id':str(uuid4()),'values':[4,3,5]}
            assert request('/api/checkins',revision,ca)[1]['revision']==2
            assert request('/api/checkins',body,cb,'SYNTH-B001')[0]==201
            assert request('/api/checkins',body,cc,'SYNTH-C001')[0]==201
            own=request('/api/records',cookie=ca)[1]['records']
            assert len(own)==1 and own[0]['values']==[4,3,5] and own[0]['center_id']=='A'
            for bad in ([True,2,3],[1.0,2,3],[0,2,3],[None,2,3],[2,3]):
                assert request('/api/checkins',{**body,'record_id':str(uuid4()),'values':bad},ca)[0]==400
            bat=dict(record_id=str(uuid4()),assessment_date='2026-11-20',values=[1]*23,visit='T0')
            assert request('/api/bat',bat,ca)[0]==201
            bat5={**bat,'record_id':str(uuid4()),'values':[5]*23,'visit':'T4'}
            assert request('/api/bat',bat5,ca)[0]==201
            partial={**bat,'record_id':str(uuid4()),'values':[2]*8+[None]*15,'visit':'T8'}
            assert request('/api/bat',partial,ca)[0]==201
            own=request('/api/records',cookie=ca)[1]['records']
            scores={r['visit']:r['scores'] for r in own if r['kind']=='bat23'}
            assert scores['T0']['total']==1 and scores['T4']['total']==5
            assert scores['T8']['total'] is None and scores['T8']['exhaustion']==2
            assert request('/api/bat',{**bat,'record_id':str(uuid4()),'visit':'INVALID'},ca)[0]==400
            assert request('/api/records?participant_id=SYNTH-B001',cookie=ca)[0]==404
            process.terminate();process.wait(timeout=5);process=start()
            assert request('/api/records',cookie=ca)[1]['records']==own
            # Existing credentials still authenticate following restart.
            assert request('/login',{'access_code':secret_a})[0]==200
            assert request('/logout',{},ca)[0]==200
            assert request('/api/checkins',body,ca)[0]==401
            out=Path(directory)/'answers.csv'
            subprocess.run(args+['export-responses',str(out)],check=True)
            with out.open(encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
            assert len(rows)==7
            assert {r['center_id'] for r in rows}=={'A','B','C'}
            assert sum(r['kind']=='checkin' and r['is_current']=='1' for r in rows)==3
            assert [r for r in rows if r['kind']=='bat23' and r['visit']=='T8'][0]['bat_total']==''
            assert all('access_hash' not in r for r in rows)
            with sqlite3.connect(db) as con:
                assert con.execute("SELECT center_id FROM participant WHERE code='LEGACY-001'").fetchone()==(None,)
                assert con.execute('SELECT count(*) FROM response').fetchone()[0]==7
            print('PASS: legacy migration, A/B/C isolation, owner spoofing, concurrent retries, conflicts, revisions, validation, failed-write rejection, BAT complete/partial scoring, restart persistence, logout and CSV audit export.')
        finally:
            process.terminate();process.wait(timeout=5)

if __name__=='__main__':check()
