from __future__ import annotations
from fastapi.testclient import TestClient
from .web import create_app, Store

def main() -> int:
    app = create_app(Store())
    c = TestClient(app)
    assert c.get("/health/live").json()["status"] == "ok"
    assert c.get("/health/ready").json()["status"] == "ready"
    r = c.post("/login", data={"login": "admin", "password": "admin"}, follow_redirects=False)
    assert r.status_code == 303
    print("smoke ok: health endpoints and bootstrap admin login")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
