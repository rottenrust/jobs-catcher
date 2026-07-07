from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from jobs_catcher.queue import PersistentJobQueue

def test_persistent_queue_survives_restart_and_recovers_stale(tmp_path):
    db=tmp_path/'q.sqlite3'
    q=PersistentJobQueue(str(db)); jid=q.enqueue(1,'scheduled_search',{'heartbeat':0}); q.set_status(jid,'running',0)
    q2=PersistentJobQueue(str(db))
    assert q2.get(jid)['status']=='running'
    assert q2.recover_stale(1000)==1
    assert q2.get(jid)['status']=='queued' and q2.get(jid)['attempts']==1

def test_persistent_queue_one_active_search_under_concurrent_enqueue(tmp_path):
    q=PersistentJobQueue(str(tmp_path/'q.sqlite3'))
    with ThreadPoolExecutor(max_workers=4) as ex:
        ids=list(ex.map(lambda _: q.enqueue(7,'scheduled_search',{'heartbeat':1}), range(8)))
    assert len(set(ids)) == 1
