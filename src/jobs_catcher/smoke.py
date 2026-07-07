from __future__ import annotations
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from .settings import Settings, load_settings
from .web import create_app

def main() -> int:
    env = load_settings()
    with TemporaryDirectory() as td:
        root = Path(td)
        settings = Settings(**{
            **env.__dict__,
            "database_url": f"sqlite:///{root / 'smoke.sqlite3'}",
            "data_dir": root / "data",
            "upload_dir": root / "uploads",
            "run_dir": root / "runs",
        })
        app = create_app(settings=settings)
        c = TestClient(app)
        assert c.get("/health/live").json()["status"] == "ok"
        ready = c.get("/health/ready").json()
        assert ready["status"] == "ready", ready
        r = c.post("/login", data={"login": "admin", "password": "admin"}, follow_redirects=False)
        assert r.status_code == 303
        print("smoke ok: health endpoints and bootstrap admin login")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
