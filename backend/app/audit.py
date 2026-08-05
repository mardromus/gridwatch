from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Any


class AuditStore:
    def __init__(self, path: str = ":memory:") -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.lock = RLock()
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS telemetry_events (
                event_key TEXT PRIMARY KEY,
                device_id TEXT NOT NULL,
                pole_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                device_ts TEXT NOT NULL,
                sequence_number INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_telemetry_pole_ts
                ON telemetry_events (pole_id, device_ts DESC);
            CREATE TABLE IF NOT EXISTS incident_snapshots (
                incident_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                asset_id TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        self.connection.commit()

    def record_telemetry(self, event_key: str, payload: dict[str, Any]) -> None:
        self.record_telemetry_batch([(event_key, payload)])

    def record_telemetry_batch(
        self, records: list[tuple[str, dict[str, Any]]]
    ) -> None:
        if not records:
            return
        with self.lock:
            self.connection.executemany(
                """
                INSERT OR IGNORE INTO telemetry_events
                    (event_key, device_id, pole_id, event_type, device_ts,
                     sequence_number, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        event_key,
                        payload["device_id"],
                        payload["pole_id"],
                        payload["event"],
                        payload["ts"],
                        payload["seq"],
                        json.dumps(payload, separators=(",", ":")),
                    )
                    for event_key, payload in records
                ],
            )
            self.connection.commit()

    def upsert_incident(self, snapshot: dict[str, Any]) -> None:
        with self.lock:
            self.connection.execute(
                """
                INSERT INTO incident_snapshots
                    (incident_id, status, asset_id, snapshot_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(incident_id) DO UPDATE SET
                    status = excluded.status,
                    asset_id = excluded.asset_id,
                    snapshot_json = excluded.snapshot_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    snapshot["incident_id"],
                    snapshot["status"],
                    snapshot["asset_id"],
                    json.dumps(snapshot, separators=(",", ":")),
                ),
            )
            self.connection.commit()

    def counts(self) -> dict[str, int]:
        with self.lock:
            telemetry = self.connection.execute("SELECT COUNT(*) FROM telemetry_events").fetchone()[
                0
            ]
            incidents = self.connection.execute(
                "SELECT COUNT(*) FROM incident_snapshots"
            ).fetchone()[0]
        return {"telemetry_events": telemetry, "incident_snapshots": incidents}

    def clear(self) -> None:
        with self.lock:
            self.connection.execute("DELETE FROM telemetry_events")
            self.connection.execute("DELETE FROM incident_snapshots")
            self.connection.commit()
    def close(self) -> None:
        with self.lock:
            self.connection.close()
