from __future__ import annotations
from dataclasses import dataclass, field

STATUSES = {"queued", "running", "searching", "fetching_details", "prescoring", "codex_scoring", "importing", "completed", "failed", "cancelled"}
ACTIVE_STATUSES = {"queued", "running", "searching", "fetching_details", "prescoring", "codex_scoring", "importing"}

def validate_schedule(interval_days: int) -> None:
    if interval_days < 1: raise ValueError("minimum schedule interval is one day")

@dataclass
class JobQueue:
    jobs: dict[int, dict] = field(default_factory=dict)
    _next: int = 1
    def enqueue(self, user_id: int, job_type: str, payload: dict) -> int:
        if job_type == "scheduled_search":
            for jid, job in self.jobs.items():
                if job["user_id"] == user_id and job["type"] == job_type and job["status"] in {"queued", "running", "searching", "fetching_details", "prescoring", "codex_scoring", "importing"}:
                    return jid
        jid = self._next; self._next += 1
        self.jobs[jid] = {"id": jid, "user_id": user_id, "type": job_type, "payload": dict(payload), "status": "queued", "heartbeat": payload.get("heartbeat", 0), "attempts": 0}
        return jid
    def recover_stale(self, now: int, stale_after_seconds: int = 900) -> int:
        n=0
        for job in self.jobs.values():
            if job["status"] in ACTIVE_STATUSES - {"queued"} and now - job.get("heartbeat", 0) > stale_after_seconds:
                job["status"] = "queued"; job["attempts"] += 1; n += 1
        return n


class PersistentJobQueue:
    def __init__(self, db_path: str) -> None:
        import sqlite3, threading
        self._lock = threading.Lock()
        self.db_path = db_path
        self.db = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, type TEXT NOT NULL, status TEXT NOT NULL, heartbeat INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0, active_key TEXT UNIQUE)")
    def enqueue(self, user_id: int, job_type: str, payload: dict) -> int:
        active_key = f"{user_id}:{job_type}" if job_type == "scheduled_search" else None
        with self._lock, self.db:
            if active_key:
                row = self.db.execute("SELECT id FROM jobs WHERE active_key=? AND status IN ('queued','running','searching','fetching_details','prescoring','codex_scoring','importing')", (active_key,)).fetchone()
                if row: return int(row[0])
            try:
                cur = self.db.execute("INSERT INTO jobs(user_id,type,status,heartbeat,active_key) VALUES(?,?,?,?,?)", (user_id, job_type, "queued", int(payload.get("heartbeat", 0)), active_key))
                return int(cur.lastrowid)
            except Exception:
                if active_key:
                    row = self.db.execute("SELECT id FROM jobs WHERE active_key=?", (active_key,)).fetchone()
                    if row: return int(row[0])
                raise
    def recover_stale(self, now: int, stale_after_seconds: int = 900) -> int:
        with self._lock, self.db:
            cur = self.db.execute("UPDATE jobs SET status='queued', attempts=attempts+1 WHERE status IN ('running','searching','fetching_details','prescoring','codex_scoring','importing') AND ? - heartbeat > ?", (now, stale_after_seconds))
            return int(cur.rowcount)
    def get(self, job_id: int) -> dict:
        row = self.db.execute("SELECT id,user_id,type,status,heartbeat,attempts FROM jobs WHERE id=?", (job_id,)).fetchone()
        return {"id":row[0],"user_id":row[1],"type":row[2],"status":row[3],"heartbeat":row[4],"attempts":row[5]}
    def set_status(self, job_id: int, status: str, heartbeat: int = 0) -> None:
        with self._lock, self.db:
            self.db.execute("UPDATE jobs SET status=?, heartbeat=? WHERE id=?", (status, heartbeat, job_id))
