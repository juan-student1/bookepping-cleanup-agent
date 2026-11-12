"""API: rebuild bank reconciliation in the background + per-statement table."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import apps.api.main as main
from src.use_cases.reconcile_statements import RebuildReport

WID = "00000000-0000-0000-0000-000000000001"


class _FakeUseCase:
    async def rebuild(self, _wid):
        return RebuildReport(
            statements=2, read=2, with_balances=2, links_repaired=45, reconciled=1, differences=1
        )

    async def statements(self, _wid):
        return [
            {"status": "reconciled", "chain_ok": True},
            {"status": "difference", "chain_ok": False},
            {"status": "no_balances", "chain_ok": None},
        ]


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(main, "ReconcileStatementsUseCase", _FakeUseCase)
    main._REBUILDS.clear()
    return TestClient(main.app)


def test_rebuild_runs_in_background_and_reports(client: TestClient) -> None:
    assert client.get("/api/reconciliation/rebuild", params={"workspace_id": WID}).json() == {
        "status": "idle"
    }
    started = client.post("/api/reconciliation/rebuild", params={"workspace_id": WID})
    assert started.status_code == 200
    status = client.get("/api/reconciliation/rebuild", params={"workspace_id": WID}).json()
    assert status["status"] == "done"
    assert status["report"]["links_repaired"] == 45


def test_statements_table_summary(client: TestClient) -> None:
    body = client.get("/api/reconciliation/statements", params={"workspace_id": WID}).json()
    assert body["summary"] == {
        "statements": 3,
        "reconciled": 1,
        "differences": 1,
        "no_balances": 1,
        "chain_breaks": 1,
    }
