import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

try:
    from azure.data.tables import TableServiceClient
except ImportError:  # pragma: no cover - only used when the optional Azure dependency is absent
    TableServiceClient = None


app = FastAPI(title="SmokeMonitor", version="1.0.0")
database_path = Path(os.getenv("DATABASE_PATH", "/data/smokemonitor.db"))
webhook_token = os.getenv("SMOKEMONITOR_TOKEN", "local-monitor-token")
storage_connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
storage_table_name = os.getenv("AZURE_STORAGE_TABLE", "smoketestruns")


class TestResult(BaseModel):
    job: str = Field(min_length=1, max_length=200)
    build: str = Field(min_length=1, max_length=100)
    status: str = Field(pattern="^(SUCCESS|FAILURE|UNSTABLE|ABORTED)$")
    attempt: int = Field(ge=1, le=10)
    base_url: str = Field(min_length=1, max_length=500)
    build_url: str | None = Field(default=None, max_length=500)
    duration_ms: int | None = Field(default=None, ge=0)
    total: int = Field(default=0, ge=0)
    passed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    skipped: int = Field(default=0, ge=0)
    failed_tests: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    junit_xml: str | None = Field(default=None, max_length=2_000_000)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_junit(result: TestResult) -> TestResult:
    if not result.junit_xml:
        return result
    try:
        root = ElementTree.fromstring(result.junit_xml)
    except ElementTree.ParseError as error:
        raise HTTPException(status_code=422, detail=f"Invalid JUnit XML: {error}") from error

    suites = [root] if root.tag == "testsuite" else list(root.findall(".//testsuite"))
    cases = list(root.findall(".//testcase"))
    failed_tests = []
    for case in cases:
        failure = case.find("failure")
        if failure is None:
            failure = case.find("error")
        if failure is not None:
            failed_tests.append(
                {
                    "name": case.attrib.get("name", "unknown"),
                    "classname": case.attrib.get("classname", ""),
                    "message": failure.attrib.get("message", failure.text or ""),
                }
            )
    totals = {
        "total": sum(int(s.attrib.get("tests", len(cases))) for s in suites),
        "failed": sum(int(s.attrib.get("failures", len(failed_tests))) for s in suites),
        "skipped": sum(int(s.attrib.get("skipped", 0)) for s in suites),
    }
    return result.model_copy(
        update={
            "total": totals["total"],
            "failed": totals["failed"],
            "skipped": totals["skipped"],
            "passed": max(0, totals["total"] - totals["failed"] - totals["skipped"]),
            "failed_tests": failed_tests,
            "junit_xml": None,
        }
    )


def sqlite_connection() -> sqlite3.Connection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(database_path)
    db.row_factory = sqlite3.Row
    db.execute(
        """CREATE TABLE IF NOT EXISTS test_results (
            id TEXT PRIMARY KEY, job TEXT NOT NULL, build TEXT NOT NULL,
            status TEXT NOT NULL, attempt INTEGER NOT NULL, base_url TEXT NOT NULL,
            build_url TEXT, duration_ms INTEGER, total INTEGER NOT NULL,
            passed INTEGER NOT NULL, failed INTEGER NOT NULL, skipped INTEGER NOT NULL,
            failed_tests TEXT NOT NULL, created_at TEXT NOT NULL
        )"""
    )
    columns = {row["name"] for row in db.execute("PRAGMA table_info(test_results)")}
    for name, definition in (
        ("id", "TEXT"),
        ("build_url", "TEXT"),
        ("duration_ms", "INTEGER"),
        ("total", "INTEGER NOT NULL DEFAULT 0"),
        ("passed", "INTEGER NOT NULL DEFAULT 0"),
        ("failed", "INTEGER NOT NULL DEFAULT 0"),
        ("skipped", "INTEGER NOT NULL DEFAULT 0"),
    ):
        if name not in columns:
            db.execute(f"ALTER TABLE test_results ADD COLUMN {name} {definition}")
    db.commit()
    return db


def table_client():
    if not storage_connection_string or TableServiceClient is None:
        return None
    service = TableServiceClient.from_connection_string(storage_connection_string)
    service.create_table_if_not_exists(storage_table_name)
    return service.get_table_client(storage_table_name)


def entity_from_result(result: TestResult, run_id: str) -> dict[str, Any]:
    return {
        "PartitionKey": "runs",
        "RowKey": run_id,
        "run_id": run_id,
        "job": result.job,
        "build": result.build,
        "status": result.status,
        "attempt": result.attempt,
        "base_url": result.base_url,
        "build_url": result.build_url or "",
        "duration_ms": result.duration_ms or 0,
        "total": result.total,
        "passed": result.passed,
        "failed": result.failed,
        "skipped": result.skipped,
        "failed_tests": json.dumps(result.failed_tests),
        "created_at": now(),
    }


def normalize_entity(entity: dict[str, Any]) -> dict[str, Any]:
    result = dict(entity)
    result["failed_tests"] = json.loads(result.get("failed_tests", "[]"))
    for field in ("attempt", "duration_ms", "total", "passed", "failed", "skipped"):
        result[field] = int(result.get(field, 0) or 0)
    return result


def save_result(result: TestResult) -> str:
    run_id = str(uuid.uuid4())
    entity = entity_from_result(result, run_id)
    table = table_client()
    if table is not None:
        table.create_entity(entity)
        return run_id
    with sqlite_connection() as db:
        db.execute(
            """INSERT INTO test_results
            (id, job, build, status, attempt, base_url, build_url, duration_ms,
             total, passed, failed, skipped, failed_tests, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                result.job,
                result.build,
                result.status,
                result.attempt,
                result.base_url,
                result.build_url,
                result.duration_ms,
                result.total,
                result.passed,
                result.failed,
                result.skipped,
                json.dumps(result.failed_tests),
                entity["created_at"],
            ),
        )
    return run_id


def list_results(limit: int = 50) -> list[dict[str, Any]]:
    table = table_client()
    if table is not None:
        entities = [normalize_entity(entity) for entity in table.query_entities("PartitionKey eq 'runs'")]
        return sorted(entities, key=lambda item: item["created_at"], reverse=True)[:limit]
    with sqlite_connection() as db:
        rows = db.execute(
            "SELECT id AS run_id, job, build, status, attempt, base_url, build_url, "
            "duration_ms, total, passed, failed, skipped, failed_tests, created_at "
            "FROM test_results ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [normalize_entity(dict(row)) for row in rows]


def require_token(token: str | None) -> None:
    if token != webhook_token:
        raise HTTPException(status_code=401, detail="Invalid SmokeMonitor token")


@app.get("/health")
def health() -> dict[str, str]:
    backend = "azure-table" if storage_connection_string else "sqlite"
    return {"status": "ok", "service": "smokemonitor", "version": "1.0.0", "backend": backend}


@app.post("/api/results", status_code=201)
def receive_result(result: TestResult, x_smokemonitor_token: str | None = Header(default=None)):
    require_token(x_smokemonitor_token)
    result = parse_junit(result)
    run_id = save_result(result)
    return {"accepted": True, "run_id": run_id}


@app.get("/api/runs")
def runs(limit: int = 50) -> dict[str, Any]:
    safe_limit = max(1, min(limit, 200))
    items = list_results(safe_limit)
    return {"runs": items, "count": len(items)}


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str) -> dict[str, Any]:
    item = next((item for item in list_results(200) if item["run_id"] == run_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return item


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    items = list_results(50)
    success = sum(item["status"] == "SUCCESS" for item in items)
    failures = sum(item["status"] == "FAILURE" for item in items)
    cards = "".join(
        f"""<article class="result {escape(item["status"].lower())}">
        <div class="top"><strong>{escape(item["job"])}</strong><span>{escape(item["status"])}</span></div>
        <h2>Build #{escape(item["build"])}</h2>
        <p>{item["passed"]}/{item["total"]} passed · attempt {item["attempt"]}</p>
        <p><a href="/runs/{escape(item["run_id"])}">View run details</a> ·
        <a href="{escape(item["base_url"], quote=True)}">application</a></p>
        <small>{escape(item["created_at"])}</small></article>"""
        for item in items
    )
    empty = '<div class="empty">No test runs yet. POST a Jenkins result to populate this dashboard.</div>'
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport"
    content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="30">
    <title>SmokeMonitor</title><style>
    :root{{font-family:Inter,system-ui,sans-serif;color:#14213d;background:#f6f8fc}}
    *{{box-sizing:border-box}}body{{margin:0}}header{{padding:28px 7%;background:#14213d;color:#fff}}
    header strong{{letter-spacing:.08em}}main{{max-width:1100px;margin:42px auto;padding:0 24px}}
    .eyebrow{{color:#4776e6;text-transform:uppercase;font-size:12px;font-weight:800;letter-spacing:.12em}}
    h1{{font-size:48px;margin:12px 0}}.lead{{color:#64748b;font-size:18px}}
    .summary{{display:flex;gap:14px;flex-wrap:wrap;margin:25px 0}}.metric{{background:#fff;border:1px solid #e5eaf2;border-radius:12px;padding:14px 20px}}
    .metric strong{{font-size:25px;display:block}}.results{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:18px;margin-top:30px}}
    .result,.empty{{background:#fff;border:1px solid #e5eaf2;border-radius:16px;padding:22px;box-shadow:0 12px 32px #263b650d}}
    .top{{display:flex;justify-content:space-between;gap:12px}}.top span{{font-weight:800;font-size:12px}}
    .success .top span{{color:#17834b}}.failure .top span{{color:#cb3a3a}}.unstable .top span{{color:#b7791f}}
    h2{{margin:22px 0 8px}}p,small{{color:#64748b}}a{{color:#4776e6;text-decoration:none}}
    </style></head><body><header><strong>SMOKEMONITOR / QUALITY SIGNALS</strong></header>
    <main><div class="eyebrow">Live test operations</div><h1>Know what broke.</h1>
    <p class="lead">Durable build health, retries, and failure evidence in one place.</p>
    <section class="summary"><div class="metric"><strong>{len(items)}</strong> recent runs</div>
    <div class="metric"><strong>{success}</strong> successful</div><div class="metric"><strong>{failures}</strong> failed</div></section>
    <section class="results">{cards or empty}</section></main></body></html>"""


@app.get("/runs/{run_id}", response_class=HTMLResponse)
def run_page(run_id: str) -> str:
    item = run_detail(run_id)
    failures = "".join(
        f"<li><strong>{escape(str(test.get('name', 'unknown')))}</strong> "
        f"{escape(str(test.get('message', '')))}</li>" for test in item["failed_tests"]
    )
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Run {escape(run_id)}</title>
    <style>body{{font-family:system-ui;max-width:900px;margin:40px auto;padding:0 20px;color:#14213d}}
    a{{color:#4776e6}}.card{{border:1px solid #e5eaf2;border-radius:14px;padding:22px;margin:20px 0}}
    dt{{font-weight:700;margin-top:12px}}dd{{margin:3px 0;color:#64748b}}li{{margin:10px 0}}</style></head>
    <body><p><a href="/">&larr; all runs</a></p><h1>{escape(item["job"])} / build {escape(item["build"])}</h1>
    <div class="card"><dl><dt>Status</dt><dd>{escape(item["status"])}</dd>
    <dt>Attempt</dt><dd>{item["attempt"]}</dd><dt>Tests</dt><dd>{item["passed"]} passed, {item["failed"]} failed, {item["skipped"]} skipped</dd>
    <dt>Created</dt><dd>{escape(item["created_at"])}</dd></dl></div>
    <div class="card"><h2>Failed tests</h2><ul>{failures or "<li>No failed tests.</li>"}</ul></div></body></html>"""
