"""Time the dashboard, the lists and the reports on the performance showroom
(SPEC §11: under 2 s at p95). Run after scripts/perf_seed.py:

    .venv/Scripts/python scripts/perf_check.py [repeats]

Calls go through the real app in-process (FastAPI TestClient) against the
local database; the HTTP hop of a deployment is not included.
"""

import logging
import statistics
import sys
import time
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import Settings
from app.main import create_app

TENANT = "33333333-3333-3333-3333-333333333333"
ENDPOINTS = [
    ("dashboard", "/api/v1/dashboard", {}),
    ("needs attention", "/api/v1/attention", {}),
    ("inventory (stock, page 1)", "/api/v1/vehicles", {"scope": "stock"}),
    ("inventory (all, by price)", "/api/v1/vehicles", {"scope": "all", "sort": "-price"}),
    ("inventory search", "/api/v1/vehicles", {"q": "Corolla"}),
    ("sales list", "/api/v1/sales", {}),
    ("journal (page 1)", "/api/v1/journal-entries", {}),
    ("customers", "/api/v1/customers", {}),
    ("P&L (one year)", "/api/v1/reports/profit-and-loss", {"date_from": "2025-09-01", "date_to": "2026-10-31"}),
    ("trial balance", "/api/v1/reports/trial-balance", {}),
    ("inventory aging", "/api/v1/reports/inventory-aging", {}),
    (
        "vehicle profit (one year)",
        "/api/v1/reports/vehicle-profit",
        {"date_from": "2025-09-01", "date_to": "2026-10-31"},
    ),
]


def main(repeats: int) -> None:
    logging.disable(logging.INFO)
    env_file = Path(__file__).resolve().parents[1] / ".env"
    settings = Settings(_env_file=env_file, environment="testing")  # type: ignore[call-arg]
    token = httpx.post(
        f"{settings.supabase_url}/auth/v1/token",
        params={"grant_type": "password"},
        headers={"apikey": _publishable(env_file)},
        json={"email": "perf@sayyara.example", "password": "Demo-Pass-2026"},
        timeout=10,
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}", "X-Tenant-Id": TENANT}
    print(f"{'endpoint':32} {'p50 ms':>8} {'p95 ms':>8} {'max ms':>8}")
    worst = 0.0
    with TestClient(create_app(settings)) as client:
        for name, path, params in ENDPOINTS:
            client.get(path, params=params, headers=headers)  # warm up
            times = []
            for _ in range(repeats):
                started = time.perf_counter()
                response = client.get(path, params=params, headers=headers)
                times.append((time.perf_counter() - started) * 1000)
                response.raise_for_status()
            times.sort()
            p95 = times[max(0, int(len(times) * 0.95) - 1)]
            worst = max(worst, p95)
            print(f"{name:32} {statistics.median(times):8.0f} {p95:8.0f} {times[-1]:8.0f}")
    print(f"worst p95: {worst:.0f} ms - {'OK' if worst < 2000 else 'TOO SLOW'} (target < 2000 ms)")


def _publishable(env_file: Path) -> str:
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("SUPABASE_PUBLISHABLE_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("SUPABASE_PUBLISHABLE_KEY missing in .env")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 20)
