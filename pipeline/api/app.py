import asyncio
import io
import logging
import sqlite3
import uuid
import tempfile
from sqlalchemy import create_engine
import functools
import pandas as pd
import numpy as np
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from link_service.linking_service import link_rows
from nlp.process_texts import process_texts
from quality_checks.quality_check import quality_check, crosstab_external_user
from quality_checks.fill_metadata import run_fill_metadata
import os
import json
import datetime as _dt
from typing import Dict
import multiprocessing as mp
import signal
import time as _time
import queue as _queue
import traceback
import psutil
import mimetypes
import csv
from pathlib import Path
import requests

# Keep status/logs separate from large result tables to avoid locks
STATUS_DB = "pipeline_status.db"
RESULTS_DB = "pipeline_results.db"

# NLP Backend configuration for integration with validation UI
NLP_BACKEND_URL = os.getenv("NLP_BACKEND_URL", "http://localhost:8001")

# Initialize FastAPI app
app = FastAPI()

# Add CORS for Streamlit frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- cancellation support ---


class CancelledError(Exception):
    pass


CANCEL_EVENTS: Dict[str, asyncio.Event] = {}
# Store both PID and the Process object for proper cleanup
PROCESS_PIDS: Dict[str, tuple[int, mp.Process]] = {}


def create_cancel_event(task_id: str):
    CANCEL_EVENTS[task_id] = asyncio.Event()


def request_cancel(task_id: str) -> bool:
    ev = CANCEL_EVENTS.get(task_id)
    if not ev:
        return False
    ev.set()
    return True


def is_cancelled(task_id: str) -> bool:
    ev = CANCEL_EVENTS.get(task_id)
    return bool(ev and ev.is_set())


def check_cancelled_or_raise(task_id: str):
    if is_cancelled(task_id):
        raise CancelledError(f"Task {task_id} cancelled by user")


def _register_process(task_id: str, pid: int, process: mp.Process):
    """Register the subprocess PID and Process object for cleanup."""
    PROCESS_PIDS[task_id] = (pid, process)


def _clear_process(task_id: str):
    """Remove and ensure the process is properly joined/reaped."""
    info = PROCESS_PIDS.pop(task_id, None)
    if info:
        _, proc = info
        # Give it a chance to exit cleanly
        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=1.0)
        # Force kill if still alive
        if proc.is_alive():
            proc.kill()
            proc.join(timeout=0.5)
        # Final join to reap zombie
        try:
            proc.join(timeout=0.1)
        except Exception:
            pass


def _kill_task_process(task_id: str, force: bool = False, timeout: float = 2.0) -> bool:
    """
    Kill only the task's subprocess and its descendants, not the API server.
    Uses psutil to find child processes without killing the parent worker.
    """
    info = PROCESS_PIDS.get(task_id)
    if not info:
        return False

    pid, proc = info

    try:
        parent = psutil.Process(pid)
        # Collect all descendants (children of the subprocess)
        children = parent.children(recursive=True)
        processes_to_kill = [parent] + children
    except psutil.NoSuchProcess:
        _clear_process(task_id)
        return True
    except Exception as e:
        print(f"[WARN] Error collecting process tree for task {task_id}: {e}")
        _clear_process(task_id)
        return False

    # Send SIGTERM (or SIGKILL if force=True)
    sig = signal.SIGKILL if force else signal.SIGTERM
    for p in processes_to_kill:
        try:
            p.send_signal(sig)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    if not force:
        # Wait for graceful shutdown
        t0 = _time.time()
        while _time.time() - t0 < timeout:
            try:
                parent = psutil.Process(pid)
                if not parent.is_running():
                    break
                _time.sleep(0.1)
            except psutil.NoSuchProcess:
                break

        # Escalate to SIGKILL if still alive
        try:
            parent = psutil.Process(pid)
            if parent.is_running():
                for p in [parent] + parent.children(recursive=True):
                    try:
                        p.kill()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
        except psutil.NoSuchProcess:
            pass

    # Wait for the multiprocessing.Process to actually exit and be reaped
    proc.join(timeout=1.0)
    if proc.is_alive():
        proc.kill()
        proc.join(timeout=0.5)

    _clear_process(task_id)
    return True


# NEW: top-level child target so it's picklable under spawn
def _subproc_child(q: mp.Queue, target, args, kwargs):
    try:
        # Create a new session so we can cleanly kill this subtree later
        if hasattr(os, "setsid"):
            os.setsid()
    except Exception:
        pass
    try:
        res = target(*args, **kwargs)
        q.put(("ok", res))
    except Exception:
        q.put(("err", traceback.format_exc()))


def _run_in_subprocess(task_id: str, target, *args, **kwargs):
    """
    Run target(*args, **kwargs) in a separate process so we can kill it without affecting the API.
    Returns target's result (pickleable) or raises CancelledError/Exception.
    """
    q: mp.Queue = mp.Queue()
    p = mp.Process(
        target=_subproc_child,
        args=(q, target, args, kwargs),
        daemon=False,  # Change to False so we control cleanup
    )
    p.start()
    _register_process(task_id, p.pid, p)  # Store both PID and Process

    result = None
    try:
        while p.is_alive():
            if is_cancelled(task_id):
                _kill_task_process(task_id, force=False)
                raise CancelledError(f"Task {task_id} cancelled")

            try:
                status, payload = q.get(timeout=0.2)
                if status == "ok":
                    result = payload
                else:
                    raise RuntimeError(payload)
                break
            except _queue.Empty:
                pass

        if result is None and not q.empty():
            status, payload = q.get_nowait()
            if status == "ok":
                result = payload
            else:
                raise RuntimeError(payload)

        # Wait for process to finish normally
        p.join(timeout=1.0)

    finally:
        # Ensure cleanup even on exception
        _clear_process(task_id)

    return result


async def run_quality_check_task(task_id: str, data_file: bytes, disease_type: str = "sarcoma"):
    """
    Background job: run quality_check on a single uploaded spreadsheet.
    Stores output so it can be fetched later via /results/{task_id}/quality_check.
    """
    task_logger = get_task_logger(task_id)
    try:
        update_status(task_id, "Initializing", 0)
        task_logger.info(
            "Quality-check task initialised for disease_type=%s.", disease_type)
        check_cancelled_or_raise(task_id)

        update_status(task_id, "Loading data", 10)
        # Support both Excel and CSV
        df: pd.DataFrame = await asyncio.to_thread(_read_uploaded_file, data_file)
        task_logger.info("File read into DataFrame (shape=%s).", df.shape)
        check_cancelled_or_raise(task_id)

        update_status(task_id, "Running quality check", 60)
        task_logger.info("Invoking quality_check() in isolated process.")
        # Run in separate process group
        qc_result = await asyncio.to_thread(_run_in_subprocess, task_id, quality_check, df, disease_type)
        check_cancelled_or_raise(task_id)

        final_df: pd.DataFrame | None = None
        if isinstance(qc_result, pd.DataFrame):
            final_df = qc_result
        elif isinstance(qc_result, tuple):
            for item in qc_result:
                if isinstance(item, pd.DataFrame):
                    final_df = item
                    break
        if final_df is None:
            task_logger.info(
                "quality_check returned no DataFrame. Using input as output.")
            final_df = df

        update_status(task_id, "Saving results", 90)
        await asyncio.to_thread(store_step_output, task_id, "quality_check", final_df)

        update_status(task_id, "Completed", 100, "Quality-check finished.")
        task_logger.info(
            "Quality-check task completed successfully (shape=%s).", final_df.shape)
    except CancelledError as exc:
        update_status(task_id, "Cancelled", 100, str(exc))
        task_logger.warning("Quality-check task cancelled.")
        return
    except Exception as exc:
        update_status(task_id, "Failed", 100, str(exc))
        task_logger.error("Quality-check task failed: %s", exc)
        raise
    finally:
        CANCEL_EVENTS.pop(task_id, None)


def _read_uploaded_file(file_bytes: bytes) -> pd.DataFrame:
    """
    Robustly load uploaded bytes as DataFrame:
    - If XLSX magic header (PK), read as Excel
    - Else read as CSV with delimiter sniffing and python engine
    """
    buf = io.BytesIO(file_bytes)

    # 1) XLSX detection by ZIP magic header
    try:
        if file_bytes[:2] == b"PK":
            return pd.read_excel(buf, engine="openpyxl", dtype=str)
    except Exception:
        # fall through to CSV logic
        pass

    # 2) CSV with delimiter sniffing
    try:
        # Let pandas detect delimiter using python engine
        buf.seek(0)
        return pd.read_csv(buf, sep=None, engine="python", dtype=str)
    except Exception:
        # Manual sniff as fallback
        try:
            sample = file_bytes[:4096].decode("utf-8", errors="ignore")
            dialect = csv.Sniffer().sniff(
                sample, delimiters=[",", ";", "\t", "|"])
            buf.seek(0)
            return pd.read_csv(buf, delimiter=dialect.delimiter, engine="python", dtype=str)
        except Exception as e:
            raise ValueError(
                f"Unable to parse uploaded file as Excel or CSV: {e}")


@app.post("/run/quality_check")
async def quality_check_call(
    file: UploadFile = File(...),
    disease_type: str = "sarcoma",
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    task_id = str(uuid.uuid4())
    create_cancel_event(task_id)
    # NEW: create an initial status row so /status works immediately
    update_status(task_id, "Queued", 0, None)
    data_content = await file.read()

    # Start the task in the background
    background_tasks.add_task(run_quality_check_task,
                              task_id, data_content, disease_type)

    return {
        "task_id": task_id,
        "message": "quality_check started – poll /status/{task_id} for progress.",
    }


@app.post("/run/discoverability")
async def discoverability_call(
    file: UploadFile = File(...),
):
    # 1) Allocate task id and CREATE INITIAL STATUS ROW
    task_id = str(uuid.uuid4())
    # queued row so /status/{task_id} won’t 404
    update_status(task_id, "Queued", 0, None)
    create_cancel_event(task_id)

    # 2) Read upload bytes (fast) and start worker in the background
    payload = await file.read()

    async def _worker():
        try:
            await run_discoverability_task(task_id, payload)
        finally:
            CANCEL_EVENTS.pop(task_id, None)

    # fire-and-forget background task
    asyncio.create_task(_worker())

    # 3) Return immediately
    return {
        "task_id": task_id,
        "message": "discoverability started – poll /status/{task_id} for progress.",
    }


@app.get("/status/{task_id}")
def get_status(task_id: str):
    row = get_status_from_db(task_id)
    if not row:
        # Graceful default while background task starts
        return {"task_id": task_id, "step": "Queued", "progress": 0, "result": None, "is_running": True}
    return row


@app.get("/recent_tasks")
def get_recent_tasks(limit: int = 5):
    """Return the most recently started pipeline tasks, persisted across sessions."""
    tasks = get_recent_tasks_from_db(limit)
    return {"tasks": tasks}


async def run_discoverability_task(task_id: str, data_bytes: bytes):
    try:
        update_status(task_id, "Initializing", 5)
        df: pd.DataFrame = await asyncio.to_thread(_read_uploaded_file, data_bytes)
        update_status(task_id, "Computing discoverability", 70)
        out_file_json_path: str = await asyncio.to_thread(run_fill_metadata, df)
        # Store file path directly (NOT a table name)
        update_status(task_id, "Completed", 100, out_file_json_path)
    except Exception as exc:
        update_status(task_id, "Failed", 100, str(exc))
        raise
    finally:
        CANCEL_EVENTS.pop(task_id, None)


@app.post("/run/discoverability")
async def discoverability_call(file: UploadFile = File(...)):
    task_id = str(uuid.uuid4())
    # Create initial status row so /status polling works immediately
    update_status(task_id, "Queued", 0, None)
    create_cancel_event(task_id)
    payload = await file.read()

    async def _worker():
        await run_discoverability_task(task_id, payload)

    asyncio.create_task(_worker())
    return {"task_id": task_id, "message": "discoverability started"}


@app.get("/results/{task_id}/discoverability_json")
def get_discoverability_json(task_id: str):
    status = get_status_from_db(task_id)
    if not status:
        raise HTTPException(status_code=404, detail="Task ID not found")
    step = status.get("step")
    if step != "Completed":
        raise HTTPException(
            status_code=409, detail=f"Task not completed (step={step})")
    path = status.get("result")
    if not path:
        raise HTTPException(status_code=404, detail="No result path stored")
    if not os.path.isfile(path):
        raise HTTPException(
            status_code=404, detail=f"Result file not found: {path}")

    def _iterfile():
        with open(path, "rb") as f:
            while chunk := f.read(8192):
                yield chunk

    return StreamingResponse(
        _iterfile(),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{os.path.basename(path)}"'},
    )


async def run_link_rows_task(task_id: str, data_file: bytes, disease_type: str = "sarcoma"):
    """
    Background job: run link_rows on a single uploaded spreadsheet.
    The output is stored with store_step_output so it can be fetched later via
    /results/{task_id}/linked_data.
    """
    task_logger = get_task_logger(task_id)
    try:
        update_status(task_id, "Initializing", 0)
        task_logger.info(
            "Link-row task initialised for disease_type=%s.", disease_type)
        check_cancelled_or_raise(task_id)

        update_status(task_id, "Loading data", 10)
        df: pd.DataFrame = await asyncio.to_thread(_read_uploaded_file, data_file)
        task_logger.info("File read into DataFrame (shape=%s).", df.shape)
        check_cancelled_or_raise(task_id)

        update_status(task_id, "Linking rows", 60)
        task_logger.info("Invoking link_rows() in isolated process.")
        linked_df: pd.DataFrame = await asyncio.to_thread(_run_in_subprocess, task_id, link_rows, df)
        task_logger.info("link_rows complete (shape=%s).", linked_df.shape)
        check_cancelled_or_raise(task_id)

        await asyncio.to_thread(store_step_output, task_id, "linked_data", linked_df)

        update_status(task_id, "Completed", 100, "Link-rows finished.")
        task_logger.info("Link-row task completed successfully.")
    except CancelledError as exc:
        update_status(task_id, "Cancelled", 100, str(exc))
        task_logger.warning("Link-row task cancelled.")
        return
    except Exception as exc:
        update_status(task_id, "Failed", 100, str(exc))
        task_logger.error("Link-row task failed: %s", exc)
        raise
    finally:
        CANCEL_EVENTS.pop(task_id, None)


@app.post("/run/link_rows")
async def link_rows_call(
    file: UploadFile = File(...),
    disease_type: str = "sarcoma",
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    """
    Accepts a single Excel/CSV, runs only link_rows, and returns a task_id.
    Use /status/{task_id} to track progress and
    /results/{task_id}/linked_data to download the output CSV.
    """
    task_id = str(uuid.uuid4())
    create_cancel_event(task_id)
    # NEW: initial status
    update_status(task_id, "Queued", 0, None)
    data_content = await file.read()

    background_tasks.add_task(
        run_link_rows_task, task_id, data_content, disease_type)

    return {
        "task_id": task_id,
        "message": "link_rows started – poll /status/{task_id} for progress.",
    }


async def run_pipeline_task(task_id: str, data_file: bytes, text_file: bytes, disease_type: str = "sarcoma"):
    """Function to run the pipeline task asynchronously.
    """
    task_logger = get_task_logger(task_id)
    try:
        update_status(task_id, "Initializing", 0)
        task_logger.info(
            "Pipeline initialization started for disease_type=%s.", disease_type)
        check_cancelled_or_raise(task_id)

        update_status(task_id, "Loading data", 10)
        task_logger.info("Loading data from uploaded files.")
        excel_data: pd.DataFrame = await asyncio.to_thread(_read_uploaded_file, data_file)
        free_texts: pd.DataFrame = await asyncio.to_thread(_read_uploaded_file, text_file)
        check_cancelled_or_raise(task_id)

        def _call_process_texts_with_disease(ft, ex):
            return _call_process_texts(ft, ex, disease_type)

        # update_status(task_id, "Processing free texts", 30)
        # task_logger.info(
        #     "Processing free texts and structuring data in isolated process.")
        # # Use top-level wrapper instead of a local function (picklable under spawn)
        # # Create a wrapper that includes disease_type

        # process_result = await asyncio.to_thread(
        #     _run_in_subprocess, task_id, _call_process_texts_with_disease, free_texts, excel_data
        # )

        update_status(task_id, "Processing free texts", 30)
        task_logger.info(
            "Processing free texts and structuring data in isolated process.")

        # NEW: bind disease_type so the function is picklable and carries the selection
        process_with_disease = functools.partial(
            _call_process_texts, disease_type=disease_type)
        process_result = await asyncio.to_thread(
            _run_in_subprocess, task_id, process_with_disease, free_texts, excel_data
        )
        # Unpack the result (excel_data, llm_results)
        if isinstance(process_result, tuple) and len(process_result) == 2:
            structured_data, llm_results = process_result
            # Store LLM results as a separate downloadable step
            if llm_results is not None and not llm_results.empty:
                await asyncio.to_thread(store_step_output, task_id, "llm_annotations", llm_results)
                task_logger.info(
                    "LLM annotations saved (shape=%s).", llm_results.shape)
        else:
            # Backward compatibility
            structured_data = process_result

        await asyncio.to_thread(store_step_output, task_id, "processed_texts", structured_data)
        check_cancelled_or_raise(task_id)

        update_status(task_id, "Linking rows", 60)
        task_logger.info("Linking rows based on criteria in isolated process.")
        linked_data = await asyncio.to_thread(_run_in_subprocess, task_id, link_rows, structured_data)
        await asyncio.to_thread(store_step_output, task_id, "linked_data", linked_data)
        check_cancelled_or_raise(task_id)

        update_status(task_id, "Performing data quality checks", 90)
        task_logger.info("Performing data quality checks in isolated process.")
        await asyncio.to_thread(_run_in_subprocess, task_id, quality_check, linked_data, disease_type)
        final_data = linked_data
        await asyncio.to_thread(store_step_output, task_id, "quality_check", final_data)

        update_status(task_id, "Completed", 100,
                      result="Pipeline completed successfully!")
        task_logger.info("Pipeline completed successfully.")
    except CancelledError as e:
        update_status(task_id, "Cancelled", 100, result=str(e))
        task_logger.warning("Pipeline cancelled.")
        return
    except Exception as e:
        update_status(task_id, "Failed", 100, result=str(e))
        task_logger.error("Pipeline failed with error: %s", e)
        raise
    finally:
        CANCEL_EVENTS.pop(task_id, None)


@app.post("/pipeline")
async def start_pipeline(
    data_file: UploadFile = File(...),
    text_file: UploadFile = File(...),
    disease_type: str = "sarcoma",
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    """Starts the pipeline - accepts Excel or CSV files"""
    task_id = str(uuid.uuid4())
    create_cancel_event(task_id)
    # NEW: initial status
    update_status(task_id, "Queued", 0, None)
    data_content = await data_file.read()
    text_content = await text_file.read()

    # Add the task to the background
    background_tasks.add_task(
        run_pipeline_task, task_id, data_content, text_content, disease_type)

    return {
        "task_id": task_id,
        "message": "Pipeline started. Use /status/{task_id} to track progress.",
    }


@app.get("/status/{task_id}")
def get_status(task_id: str):
    row = get_status_from_db(task_id)
    if not row:
        # Graceful default while background task starts
        return {"task_id": task_id, "step": "Queued", "progress": 0, "result": None, "is_running": True}
    return row


@app.get("/logs/{task_id}")
async def get_logs(task_id: str):
    """
    Retrieve logs for a specific task.
    """
    conn = sqlite3.connect(STATUS_DB)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT timestamp, log_level, message
        FROM pipeline_logs
        WHERE task_id = ?
        ORDER BY timestamp
    """,
        (task_id,),
    )
    logs = [{"timestamp": row[0], "level": row[1], "message": row[2]}
            for row in cursor.fetchall()]
    conn.close()
    if not logs:
        raise HTTPException(
            status_code=404, detail="No logs found for the specified task.")
    return {"task_id": task_id, "logs": logs}


# Initialize SQLite database for logs
def init_logs_db():
    conn = sqlite3.connect(STATUS_DB)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS pipeline_logs (
            task_id TEXT,
            timestamp TEXT,
            log_level TEXT,
            message TEXT,
            FOREIGN KEY (task_id) REFERENCES pipeline_status (task_id)
        )
    """
    )
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.execute("PRAGMA busy_timeout=5000;")
    conn.commit()
    conn.close()


init_logs_db()


def log_message(task_id: str, log_level: str, message: str):
    """
    Save a log message to the database.
    """
    conn = sqlite3.connect(STATUS_DB, timeout=5)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO pipeline_logs (task_id, timestamp, log_level, message)
        VALUES (?, datetime('now'), ?, ?)
    """,
        (task_id, log_level, message),
    )
    conn.commit()
    conn.close()


# Configure standard Python logger
logger = logging.getLogger("pipeline")
logger.setLevel(logging.DEBUG)


# Log handler to save logs to the database
class DBLogHandler(logging.Handler):
    def __init__(self, task_id: str):
        super().__init__()
        self.task_id = task_id

    def emit(self, record):
        # Use formatted message to include args, avoid raw record.msg
        log_message(self.task_id, record.levelname, record.getMessage())


# Example: Add DBLogHandler to logger dynamically
def get_task_logger(task_id: str):
    task_logger = logging.getLogger(f"pipeline_{task_id}")
    task_logger.setLevel(logging.DEBUG)
    # Avoid adding duplicate handlers for the same task_id
    if not any(isinstance(h, DBLogHandler) and getattr(h, "task_id", None) == task_id for h in task_logger.handlers):
        task_logger.addHandler(DBLogHandler(task_id))
    # Prevent duplicate propagation to root loggers
    task_logger.propagate = False
    return task_logger


@app.post("/cancel/{task_id}")
def cancel_task(task_id: str):
    """
    Request cancellation of a running task by ID. Sends SIGTERM to the task subprocess only.
    """
    current = get_status_from_db(task_id)
    if not current:
        raise HTTPException(status_code=404, detail="Task ID not found.")
    update_status(task_id, "Cancelling", int(
        current.get("progress") or 0), current.get("result") or "")
    requested = request_cancel(task_id)
    _kill_task_process(task_id, force=False)
    return {"ok": bool(requested), "message": "Cancellation requested."}


@app.post("/kill/{task_id}")
def force_kill_task(task_id: str):
    """
    Force kill the task's subprocess (SIGKILL). Use if normal cancel doesn't work.
    """
    current = get_status_from_db(task_id)
    if not current:
        raise HTTPException(status_code=404, detail="Task ID not found.")
    request_cancel(task_id)
    killed = _kill_task_process(task_id, force=True)
    update_status(task_id, "Cancelled", 100,
                  "Force-killed by user" if killed else "Kill requested")
    return {"ok": bool(killed), "message": "Force kill sent."}


# Helper: top-level wrapper for process_texts (avoid local nested func)
def _call_process_texts(ft: pd.DataFrame, ex: pd.DataFrame, disease_type: str = "sarcoma"):
    try:
        # Updated to handle tuple return (excel_data, llm_results)
        result = process_texts(ft, ex, disease_type=disease_type)
        # If process_texts returns a tuple, return it; otherwise wrap in tuple
        if isinstance(result, tuple):
            return result
        else:
            # Backward compatibility if it returns only excel_data
            return (result, None)
    except TypeError:
        # Legacy signature fallback
        result = process_texts(ft, ex, None, None, None)
        # disease_type=disease_type)
        if isinstance(result, tuple):
            return result
        else:
            return (result, None)


def init_db():
    """Initialize SQLite database for pipeline status."""
    conn = sqlite3.connect(STATUS_DB)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS pipeline_status (
            task_id TEXT PRIMARY KEY,
            step TEXT,
            progress INTEGER,
            result TEXT
        )
    """
    )
    # Add started_at for "when did I run this" (migration for existing DBs)
    cursor.execute("PRAGMA table_info(pipeline_status)")
    columns = [row[1] for row in cursor.fetchall()]
    if "started_at" not in columns:
        cursor.execute("ALTER TABLE pipeline_status ADD COLUMN started_at TEXT")
    # Enable WAL so readers don't block on writers
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.execute("PRAGMA busy_timeout=5000;")
    conn.commit()
    conn.close()


init_db()


def _cell_to_sql_scalar(x):
    # None stays None
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None

    # Python datetime → ISO string
    if isinstance(x, (_dt.datetime, _dt.date, _dt.time)):
        # for dates with time keep full precision
        if isinstance(x, _dt.datetime):
            return x.strftime("%Y-%m-%d %H:%M:%S.%f")
        if isinstance(x, _dt.date):
            return x.strftime("%Y-%m-%d")
        return x.strftime("%H:%M:%S")

    # Pandas / NumPy datetimes
    if isinstance(x, (pd.Timestamp, np.datetime64)):
        ts = pd.to_datetime(x, errors="coerce")
        return None if pd.isna(ts) else ts.strftime("%Y-%m-%d %H:%M:%S.%f")

    # NumPy scalars → Python scalars
    if isinstance(x, np.generic):
        return x.item()

    # Lists / tuples / sets / dicts → JSON string (or join if you prefer)
    if isinstance(x, (list, tuple, set, dict)):
        try:
            return json.dumps(x, ensure_ascii=False)
        except Exception:
            return str(x)

    # bytes → utf8
    if isinstance(x, (bytes, bytearray)):
        try:
            return x.decode("utf-8")
        except Exception:
            return x.decode("latin-1", errors="ignore")

    return x


def sanitize_for_sqlite(df: pd.DataFrame) -> pd.DataFrame:
    # Normalize dtypes that often cause trouble
    df = df.copy()

    # Convert datetime64 columns to strings
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            df[c] = pd.to_datetime(df[c], errors="coerce").dt.strftime(
                "%Y-%m-%d %H:%M:%S.%f")

    # Map every cell to a SQL-safe scalar
    for c in df.columns:
        df[c] = df[c].map(_cell_to_sql_scalar)

    return df


def update_status(task_id: str, step: str, progress: int, result: str = ""):
    """
    Update the pipeline status in the database.
    started_at is set on first insert and preserved on updates.
    """
    conn = sqlite3.connect(STATUS_DB, timeout=5)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO pipeline_status (task_id, step, progress, result, started_at)
        VALUES (?, ?, ?, ?, COALESCE((SELECT started_at FROM pipeline_status WHERE task_id = ?), datetime('now')))
        ON CONFLICT(task_id) DO UPDATE SET step = excluded.step, progress = excluded.progress, result = excluded.result
    """,
        (task_id, step, progress, result or None, task_id),
    )
    conn.commit()
    conn.close()


def get_status_from_db(task_id: str):
    """
    Retrieve the pipeline status from the database.
    """
    conn = sqlite3.connect(STATUS_DB, timeout=5)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT step, progress, result FROM pipeline_status WHERE task_id = ?",
        (task_id,),
    )
    status = cursor.fetchone()
    conn.close()
    return (
        {"step": status[0], "progress": status[1], "result": status[2]}
        if status
        else None
    )


def get_recent_tasks_from_db(limit: int = 5):
    """
    Retrieve the most recently started tasks from the database (by insertion order).
    """
    conn = sqlite3.connect(STATUS_DB, timeout=5)
    cursor = conn.cursor()
    cursor.execute(
        """SELECT task_id, step, progress, result, started_at FROM pipeline_status
           ORDER BY rowid DESC LIMIT ?""",
        (limit,),
    )
    rows = cursor.fetchall()
    conn.close()
    return [
        {"task_id": r[0], "step": r[1], "progress": r[2], "result": r[3], "started_at": r[4]}
        for r in rows
    ]


# Example: define a placeholder for DB interactions
def store_step_output(task_id: str, step_name: str, data: pd.DataFrame):
    """
    Save data to the database after each pipeline step.
    """
    # Use a separate DB for bulky results to reduce contention with STATUS_DB
    engine = create_engine(
        f"sqlite:///{RESULTS_DB}",
        echo=False,
        future=True,
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    # Put results DB in WAL as well
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
        conn.exec_driver_sql("PRAGMA synchronous=NORMAL;")
        conn.exec_driver_sql("PRAGMA busy_timeout=5000;")

    data = sanitize_for_sqlite(data)
    data.to_sql(f"{task_id}_{step_name}", con=engine,
                if_exists="replace", index=False)  # type: ignore
    engine.dispose()


@app.post("/cancel/{task_id}")
def cancel_task(task_id: str):
    """
    Request cancellation of a running task by ID. Sends SIGTERM to the task subprocess only.
    """
    current = get_status_from_db(task_id)
    if not current:
        raise HTTPException(status_code=404, detail="Task ID not found.")
    update_status(task_id, "Cancelling", int(
        current.get("progress") or 0), current.get("result") or "")
    requested = request_cancel(task_id)
    _kill_task_process(task_id, force=False)
    return {"ok": bool(requested), "message": "Cancellation requested."}


@app.post("/kill/{task_id}")
def force_kill_task(task_id: str):
    """
    Force kill the task's subprocess (SIGKILL). Use if normal cancel doesn't work.
    """
    current = get_status_from_db(task_id)
    if not current:
        raise HTTPException(status_code=404, detail="Task ID not found.")
    request_cancel(task_id)
    killed = _kill_task_process(task_id, force=True)
    update_status(task_id, "Cancelled", 100,
                  "Force-killed by user" if killed else "Kill requested")
    return {"ok": bool(killed), "message": "Force kill sent."}


# NEW: discoverability task


async def run_discoverability_task(task_id: str, data_file: bytes):
    """
    Background job: run fill_metadata on the uploaded file and store output path in status.result.
    """
    task_logger = get_task_logger(task_id)
    try:
        # status row must exist already
        update_status(task_id, "Initializing", 5)
        task_logger.info("Discoverability task initialized.")

        # Parse file off the event loop
        update_status(task_id, "Loading data", 10)
        df: pd.DataFrame = await asyncio.to_thread(_read_uploaded_file, data_file)
        task_logger.info("File read into DataFrame (shape=%s).", df.shape)

        update_status(task_id, "Computing discoverability", 70)
        out_file_json_path: str = await asyncio.to_thread(run_fill_metadata, df)

        update_status(task_id, "Completed", 100, out_file_json_path)
        task_logger.info(
            "Discoverability completed. Output: %s", out_file_json_path)
    except Exception as exc:
        # Ensure a failure status is written even if not present
        try:
            update_status(task_id, "Failed", 100, str(exc))
        except Exception:
            pass
        task_logger.error("Discoverability task failed: %s", exc)
        raise


@app.post("/run/discoverability")
async def discoverability_call(
    file: UploadFile = File(...),
):
    # 1) Allocate task id and CREATE INITIAL STATUS ROW
    task_id = str(uuid.uuid4())
    # queued row so /status/{task_id} won’t 404
    update_status(task_id, "Queued", 0, None)
    create_cancel_event(task_id)

    # 2) Read upload bytes (fast) and start worker in the background
    payload = await file.read()

    async def _worker():
        try:
            await run_discoverability_task(task_id, payload)
        finally:
            CANCEL_EVENTS.pop(task_id, None)

    # fire-and-forget background task
    asyncio.create_task(_worker())

    # 3) Return immediately
    return {
        "task_id": task_id,
        "message": "discoverability started – poll /status/{task_id} for progress.",
    }


@app.get("/results/{task_id}/discoverability_json")
def get_discoverability_json(task_id: str):
    """
    Stream the filled metadata JSON for a completed discoverability task.
    """
    status = get_status_from_db(task_id)
    if not status:
        raise HTTPException(status_code=404, detail="Task ID not found.")
    if status["step"] != "Completed":
        raise HTTPException(status_code=409, detail="Task not completed yet.")
    path = status.get("result")
    if not path or not os.path.exists(path):
        raise HTTPException(
            status_code=404, detail="Discoverability output not found.")

    def _iterfile():
        with open(path, "rb") as f:
            while chunk := f.read(8192):
                yield chunk

    return StreamingResponse(
        _iterfile(),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{os.path.basename(path)}"'},
    )


# ─── NLP VALIDATION INTEGRATION ENDPOINTS ────────────────────────────────────

@app.post("/nlp/create_session")
async def create_nlp_session(
    text_file: UploadFile = File(...),
    session_name: str = "Pipeline Session",
    prompt_types: str = "histological-tipo-int,tumorsite-int"
):
    """Create NLP session for validation in external UI.

    This endpoint takes uploaded unstructured text data and creates a session
    in the NLP backend for manual validation of annotations.

    Args:
        text_file: CSV/Excel file with unstructured text data
        session_name: Name for the NLP session
        prompt_types: Comma-separated list of prompt types to use

    Returns:
        Session info including session_id for use in validation UI
    """
    # Read and parse the uploaded file
    file_bytes = await text_file.read()
    df = _read_uploaded_file(file_bytes)

    # If parsed as single column with semicolons, use "whole-line-quoted semicolon" parser
    # (e.g. patient_freetext_short.csv: each line is one quoted field, semicolon-separated inside)
    csv_data = []
    if df.shape[1] == 1:
        first_cell = str(df.iloc[0].iloc[0]) if len(df) > 0 else ""
        if ";" in str(df.columns[0]) or ";" in first_cell:
            try:
                text_content = file_bytes.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
                lines = [ln.strip() for ln in text_content.split("\n") if ln.strip()]
                if not lines:
                    raise ValueError("No lines")
                # Parse header: strip outer quotes, split by ;, unquote "" -> "
                header_line = lines[0]
                if header_line.startswith('"') and header_line.endswith('"'):
                    header_line = header_line[1:-1]
                header_reader = csv.reader(io.StringIO(header_line), delimiter=";", quotechar='"', doublequote=True)
                headers = [c.rstrip('"') for c in next(header_reader)]
                num_cols = len(headers)
                # Expected: text, date, p_id, note_id, report_type, (annotations)
                for idx, line in enumerate(lines[1:], start=0):
                    if not line.startswith('"') or not line.endswith('"'):
                        continue
                    inner = line[1:-1]
                    reader = csv.reader(io.StringIO(inner), delimiter=";", quotechar='"', doublequote=True)
                    parts = next(reader)
                    # If text field contained semicolons, we get more than num_cols parts: merge extra into text
                    if len(parts) > num_cols:
                        text = ";".join(parts[: len(parts) - (num_cols - 1)])
                        rest = [p.rstrip('"') for p in parts[len(parts) - (num_cols - 1) :]]
                    else:
                        text = parts[0] if parts else ""
                        rest = [p.rstrip('"') for p in (parts[1:] if len(parts) > 1 else [])]
                    row_dict = dict(zip(headers, [text] + rest))
                    # Normalize keys (strip quotes, lowercase)
                    row_dict = {str(k).strip().strip('"').lower(): v for k, v in row_dict.items()}
                    text_v = (row_dict.get("text") or "").strip()
                    date_v = (row_dict.get("date") or "").strip()
                    p_id_v = (row_dict.get("p_id") or "").strip()
                    note_id_v = (row_dict.get("note_id") or "").strip()
                    report_type_v = (row_dict.get("report_type") or "").strip()
                    if not text_v and not date_v and not note_id_v:
                        continue
                    csv_data.append({
                        "text": text_v or "",
                        "date": date_v or "",
                        "p_id": p_id_v or "",
                        "note_id": note_id_v or f"row_{idx}",
                        "report_type": report_type_v or "",
                    })
            except Exception:
                csv_data = []  # fall through to DataFrame path

    if not csv_data:
        # Normalize column names: strip whitespace/quotes, lowercase for matching
        def _norm_col(c):
            if c is None or (isinstance(c, float) and pd.isna(c)):
                return ""
            s = str(c).strip().strip('"').strip("'").lower()
            return s

        _col_map = {_norm_col(c): c for c in df.columns if _norm_col(c)}

        def _cell(row, *candidates):
            for cand in candidates:
                key = _col_map.get(cand.lower()) if isinstance(cand, str) else None
                if key is None and cand in row:
                    key = cand
                if key is not None and key in row.index:
                    v = row[key]
                    if v is None or (isinstance(v, float) and pd.isna(v)):
                        return ""
                    return str(v).strip()
            return ""

        for idx, row in df.iterrows():
            text = _cell(row, "text", "note_text", "content")
            date = _cell(row, "date")
            p_id = _cell(row, "p_id", "patient_id", "patient id")
            note_id = _cell(row, "note_id", "note id", "id")
            report_type = _cell(row, "report_type", "report type", "type")
            if not text and not date and not note_id:
                continue
            csv_data.append({
                "text": text or "",
                "date": date or "",
                "p_id": p_id or "",
                "note_id": note_id or f"row_{idx}",
                "report_type": report_type or "",
            })

    if not csv_data:
        raise HTTPException(
            status_code=400,
            detail=(
                "No valid note rows found. The file must contain columns for note text and identifiers. "
                "Expected column names (case-insensitive, with or without quotes): text, date, p_id, note_id, report_type. "
                "At least one row must have text or note_id."
            ),
        )

    # Create session via NLP backend
    try:
        response = requests.post(
            f"{NLP_BACKEND_URL}/api/sessions",
            json={
                "name": session_name,
                "csv_data": csv_data,
                "prompt_types": prompt_types.split(","),
                "evaluation_mode": "validation"
            },
            timeout=30
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create NLP session: {response.text}"
            )

        return response.json()

    except requests.exceptions.RequestException as e:
        raise HTTPException(
            status_code=503,
            detail=f"NLP backend unavailable: {str(e)}"
        )


@app.post("/pipeline/continue")
async def continue_pipeline_with_validated_data(
    structured_file: UploadFile = File(...),
    session_id: str = None,
    disease_type: str = "sarcoma",
    background_tasks: BackgroundTasks = BackgroundTasks()
):
    """Continue pipeline after NLP validation.

    This endpoint fetches validated NLP data from the NLP backend,
    merges it with structured data, and runs Linking + Quality Checks.

    Args:
        structured_file: CSV/Excel file with structured data
        session_id: NLP session ID to fetch validated annotations from
        disease_type: Disease type for quality checks (sarcoma or head_and_neck)

    Returns:
        Task ID for tracking pipeline progress
    """
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    task_id = str(uuid.uuid4())
    create_cancel_event(task_id)
    update_status(task_id, "Queued", 0, None)

    structured_content = await structured_file.read()

    background_tasks.add_task(
        run_continue_pipeline_task, task_id, structured_content, session_id, disease_type
    )

    return {"task_id": task_id, "message": "Pipeline continuation started"}


async def run_continue_pipeline_task(
    task_id: str,
    structured_bytes: bytes,
    session_id: str,
    disease_type: str
):
    """Background task: fetch validated NLP data and run Linking + QC.

    This function:
    1. Fetches validated annotations from the NLP backend
    2. Merges them with the structured data
    3. Runs the linking service
    4. Runs quality checks
    """
    task_logger = get_task_logger(task_id)
    try:
        update_status(task_id, "Fetching validated NLP data", 10)
        task_logger.info("Fetching validated annotations from NLP backend for session %s", session_id)

        # Fetch validated annotations from NLP backend
        try:
            nlp_response = requests.get(
                f"{NLP_BACKEND_URL}/api/sessions/{session_id}/export",
                timeout=60
            )
            if nlp_response.status_code != 200:
                raise Exception(f"Failed to fetch validated NLP data: {nlp_response.text}")

            nlp_df = pd.read_csv(io.StringIO(nlp_response.text))
            task_logger.info("Fetched NLP data with shape %s", nlp_df.shape)
        except requests.exceptions.RequestException as e:
            raise Exception(f"NLP backend unavailable: {str(e)}")

        check_cancelled_or_raise(task_id)

        update_status(task_id, "Loading structured data", 20)
        structured_df = _read_uploaded_file(structured_bytes)
        task_logger.info("Loaded structured data with shape %s", structured_df.shape)
        check_cancelled_or_raise(task_id)

        update_status(task_id, "Merging data", 30)
        task_logger.info("Merging structured data with validated NLP annotations")

        # Adjust NLP record_ids to continue from max record_id in structured data
        max_structured_record_id = 0
        if 'record_id' in structured_df.columns:
            try:
                max_structured_record_id = int(pd.to_numeric(structured_df['record_id'], errors='coerce').max())
                if pd.isna(max_structured_record_id):
                    max_structured_record_id = 0
            except (ValueError, TypeError):
                max_structured_record_id = 0

        if 'record_id' in nlp_df.columns and not nlp_df.empty:
            task_logger.info(f"Adjusting NLP record_ids (offset: {max_structured_record_id})")
            nlp_df['record_id'] = pd.to_numeric(nlp_df['record_id'], errors='coerce').fillna(0).astype(int) + max_structured_record_id

        # Ensure columns align properly for merge
        # Add missing columns to NLP data with empty values
        for col in structured_df.columns:
            if col not in nlp_df.columns:
                nlp_df[col] = ''

        # Add missing columns to structured data with empty values (in case NLP has extra)
        for col in nlp_df.columns:
            if col not in structured_df.columns:
                structured_df[col] = ''

        # Merge: append NLP data to structured data
        merged_df = pd.concat([structured_df, nlp_df], ignore_index=True)
        await asyncio.to_thread(store_step_output, task_id, "processed_texts", merged_df)
        task_logger.info("Merged data shape: %s", merged_df.shape)
        check_cancelled_or_raise(task_id)

        update_status(task_id, "Linking rows", 50)
        task_logger.info("Running linking service in isolated process")
        linked_df = await asyncio.to_thread(_run_in_subprocess, task_id, link_rows, merged_df)
        await asyncio.to_thread(store_step_output, task_id, "linked_data", linked_df)
        task_logger.info("Linked data shape: %s", linked_df.shape)
        check_cancelled_or_raise(task_id)

        update_status(task_id, "Running quality checks", 80)
        task_logger.info("Running quality checks in isolated process")
        await asyncio.to_thread(_run_in_subprocess, task_id, quality_check, linked_df, disease_type)
        await asyncio.to_thread(store_step_output, task_id, "quality_check", linked_df)
        check_cancelled_or_raise(task_id)

        update_status(task_id, "Completed", 100, "Pipeline completed with validated NLP data")
        task_logger.info("Pipeline continuation completed successfully")

    except CancelledError as e:
        update_status(task_id, "Cancelled", 100, str(e))
        task_logger.warning("Pipeline continuation cancelled")
        return
    except Exception as e:
        update_status(task_id, "Failed", 100, str(e))
        task_logger.error("Pipeline continuation failed: %s", e)
        raise
    finally:
        CANCEL_EVENTS.pop(task_id, None)


# NEW: results download endpoint (missing, used by status_web)
@app.get("/results/{task_id}/{step_name}")
def get_step_results_as_csv(task_id: str, step_name: str):
    """
    Fetch pipeline step data from the results database and return as a CSV file.
    """
    conn = None
    try:
        conn = sqlite3.connect(RESULTS_DB, timeout=5)
        conn.execute("PRAGMA busy_timeout=5000;")
        query = f'SELECT * FROM "{task_id}_{step_name}"'
        df: pd.DataFrame = pd.read_sql(query, conn)  # type: ignore

        if df.empty:
            raise HTTPException(
                status_code=404, detail="No data found for the specified task and step."
            )

        csv_data = io.BytesIO()
        df.to_csv(csv_data, index=False, encoding="utf-8")
        csv_data.seek(0)

        return StreamingResponse(
            csv_data,
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="{task_id}_{step_name}.csv"'
            },
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail="Not Found") from e
    finally:
        if conn is not None:
            conn.close()
