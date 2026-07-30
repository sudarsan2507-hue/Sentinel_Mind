"""The audit log is the record judges and developers actually read."""

from __future__ import annotations

import json

from audit_log import AuditLog


def _verdict(status: str, explanation: str = "because") -> dict:
    return {"status": status, "explanation": explanation, "confidence": 0.9}


def test_records_entry(sample_event):
    log = AuditLog()

    entry = log.record(sample_event, _verdict("OK"))

    assert len(log) == 1
    assert entry["status"] == "OK"
    assert entry["event"] == sample_event
    assert entry["sequence"] == 0
    assert "recorded_at" in entry


def test_filters_anomalies_correctly(sample_event):
    log = AuditLog()
    log.record(sample_event, _verdict("OK"))
    log.record(sample_event, _verdict("ANOMALY", "hallucinated tool"))
    log.record(sample_event, _verdict("WARN"))
    log.record(sample_event, _verdict("ANOMALY", "goal drift"))

    anomalies = log.anomalies()

    assert len(anomalies) == 2
    assert all(e["status"] == "ANOMALY" for e in anomalies)
    assert log.filter("OK") == [e for e in log.all() if e["status"] == "OK"]


def test_exports_valid_json(sample_event):
    log = AuditLog()
    log.record(sample_event, _verdict("ANOMALY", "infinite loop detected"))

    parsed = json.loads(log.export())

    assert parsed["summary"]["total"] == 1
    assert parsed["summary"]["counts"]["ANOMALY"] == 1
    assert parsed["entries"][0]["verdict"]["explanation"] == "infinite loop detected"
    assert "exported_at" in parsed


def test_clears_log(sample_event):
    log = AuditLog()
    log.record(sample_event, _verdict("OK"))
    log.record(sample_event, _verdict("ANOMALY"))

    log.clear()

    assert len(log) == 0
    assert log.all() == []
    assert log.summary()["total"] == 0


def test_sequence_is_unique_under_concurrent_writers(sample_event):
    """Two threads write here now: the meta-agent worker and POST /replay.

    Sequence used to be read outside the lock, so two entries could take the
    same number. Ordering is what makes a replay reproducible, so a duplicate
    sequence quietly corrupts the record.
    """
    import threading

    log = AuditLog()

    def hammer():
        for _ in range(100):
            log.record(sample_event, _verdict("OK"))

    threads = [threading.Thread(target=hammer) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    sequences = [e["sequence"] for e in log.all()]
    assert len(sequences) == 400
    assert len(set(sequences)) == 400, "duplicate sequence numbers"


def test_clear_restarts_sequence_numbering(sample_event):
    log = AuditLog()
    log.record(sample_event, _verdict("OK"))
    log.clear()

    assert log.record(sample_event, _verdict("OK"))["sequence"] == 0


def test_handles_multiple_records(sample_event):
    log = AuditLog()
    for i in range(50):
        status = "ANOMALY" if i % 10 == 0 else "OK"
        log.record({**sample_event, "id": f"evt_{i:06d}"}, _verdict(status))

    summary = log.summary()

    assert summary["total"] == 50
    assert summary["counts"]["ANOMALY"] == 5
    assert summary["counts"]["OK"] == 45
    # Sequence numbers stay monotonic so the trace can be replayed in order.
    assert [e["sequence"] for e in log.all()] == list(range(50))
