"""Synthetic-only persistence candidate. Database writes require an authenticated owner."""
import csv
from datetime import date, datetime, timezone
import json
from uuid import UUID

VERSION = 'persistence-candidate-1'
BAT_VERSION = 'BAT-GR-23-demo-1.0'

class Conflict(ValueError):
    pass


def initialize(db):
    if 'center_id' not in {r[1] for r in db.execute('PRAGMA table_info(participant)')}:
        db.execute("ALTER TABLE participant ADD COLUMN center_id TEXT CHECK(center_id IN ('A','B','C'))")
    db.executescript('''
        CREATE TABLE IF NOT EXISTS response (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            participant_id TEXT NOT NULL REFERENCES participant(code),
            center_id TEXT NOT NULL CHECK(center_id IN ('A','B','C')),
            record_id TEXT NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('checkin','bat23')),
            logical_key TEXT NOT NULL,
            assessment_date TEXT NOT NULL,
            revision INTEGER NOT NULL,
            received_at_utc TEXT NOT NULL,
            payload TEXT NOT NULL,
            instrument_version TEXT NOT NULL,
            app_version TEXT NOT NULL,
            UNIQUE(participant_id, record_id),
            UNIQUE(participant_id, kind, logical_key, revision)
        );
    ''')


def validate(kind, body):
    fields = {'record_id','assessment_date','values'}
    if kind == 'bat23': fields.add('visit')
    if kind not in ('checkin','bat23') or set(body) != fields:
        raise ValueError('invalid_fields')
    if not isinstance(body['record_id'], str) or str(UUID(body['record_id'])) != body['record_id']:
        raise ValueError('invalid_id')
    raw_date = body['assessment_date']
    if not isinstance(raw_date, str) or date.fromisoformat(raw_date).isoformat() != raw_date:
        raise ValueError('invalid_date')
    values = body['values']
    if not isinstance(values,list) or len(values) != (3 if kind == 'checkin' else 23):
        raise ValueError('invalid_values')
    if any(v is not None and (type(v) is not int or not 1 <= v <= 5) for v in values):
        raise ValueError('invalid_values')
    if kind == 'checkin' and None in values:
        raise ValueError('incomplete_checkin')
    if kind == 'bat23' and body['visit'] not in ('T0','T4','T8'):
        raise ValueError('invalid_visit')
    return raw_date if kind == 'checkin' else body['visit']


def bat_scores(values):
    def mean(a): return None if None in a else sum(a)/len(a)
    return dict(answered=sum(v is not None for v in values), total=mean(values),
                exhaustion=mean(values[:8]), distance=mean(values[8:13]),
                cognitive=mean(values[13:18]), emotional=mean(values[18:]))


def save(db, code, kind, body):
    key = validate(kind, body)
    canonical = json.dumps(body,sort_keys=True,separators=(',',':'))
    # Serialize competing retries and revisions, including the check for existing ID.
    db.execute('BEGIN IMMEDIATE')
    center = db.execute('SELECT center_id FROM participant WHERE code=?',(code,)).fetchone()
    if not center or center[0] is None: raise Conflict('center_not_assigned')
    old = db.execute('SELECT kind,payload,revision,received_at_utc FROM response WHERE participant_id=? AND record_id=?',
                     (code,body['record_id'])).fetchone()
    if old:
        if old[0] != kind or old[1] != canonical: raise Conflict('record_id_conflict')
        return dict(duplicate=True,revision=old[2],received_at_utc=old[3])
    revision = db.execute('SELECT COALESCE(MAX(revision),0)+1 FROM response WHERE participant_id=? AND kind=? AND logical_key=?',
                          (code,kind,key)).fetchone()[0]
    at = datetime.now(timezone.utc).isoformat(timespec='microseconds')
    db.execute('''INSERT INTO response(participant_id,center_id,record_id,kind,logical_key,assessment_date,
                  revision,received_at_utc,payload,instrument_version,app_version) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
               (code,center[0],body['record_id'],kind,key,body['assessment_date'],revision,at,canonical,
                BAT_VERSION if kind=='bat23' else 'checkin-v1',VERSION))
    return dict(duplicate=False,revision=revision,received_at_utc=at)


def records(db, code):
    result=[]
    for row in db.execute('''SELECT r.kind,r.center_id,r.payload,r.revision,r.received_at_utc FROM response r
            WHERE r.participant_id=? AND NOT EXISTS (SELECT 1 FROM response n
            WHERE n.participant_id=r.participant_id AND n.kind=r.kind AND n.logical_key=r.logical_key
            AND n.revision>r.revision) ORDER BY r.sequence''',(code,)):
        kind,center,payload,revision,at=row
        data=json.loads(payload)
        result.append(dict(kind=kind,center_id=center,**data,revision=revision,received_at_utc=at,
                           scores=bat_scores(data['values']) if kind=='bat23' else None))
    return result


def export(db, stream):
    writer=csv.writer(stream)
    writer.writerow(['participant_id','center_id','record_id','kind','visit','assessment_date','revision',
                     'is_current','received_at_utc','instrument_version','app_version']+
                    [f'q{i:02}' for i in range(1,24)]+['bat_total','bat_exhaustion','bat_distance','bat_cognitive','bat_emotional'])
    for row in db.execute('''SELECT r.participant_id,r.center_id,r.record_id,r.kind,r.assessment_date,r.revision,
            NOT EXISTS(SELECT 1 FROM response n WHERE n.participant_id=r.participant_id AND n.kind=r.kind
              AND n.logical_key=r.logical_key AND n.revision>r.revision),
            r.received_at_utc,r.instrument_version,r.app_version,r.payload FROM response r ORDER BY r.sequence'''):
        pid,center,rid,kind,day,rev,current,at,iv,av,raw=row
        payload=json.loads(raw);values=payload['values']
        scores=bat_scores(values) if kind=='bat23' else {}
        writer.writerow([pid,center,rid,kind,payload.get('visit',''),day,rev,current,at,iv,av]+values+
                        ['']*(23-len(values))+[scores.get(k,'') for k in ('total','exhaustion','distance','cognitive','emotional')])
