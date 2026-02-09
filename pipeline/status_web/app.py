from fastapi.responses import StreamingResponse, JSONResponse
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
import streamlit as st
import requests
import time
import os
import json
from datetime import datetime

st.set_page_config(page_title='IDEA4RC data ingestion',
                   page_icon="LogoIDEA4RC-300x200.jpg", layout="wide")

# Persistent store for sessions (tasks are loaded from API /recent_tasks)

RECENT_PROCESSES_FILE = os.path.join(os.path.dirname(__file__), ".recent_processes.json")


def _load_recent_sessions():
    """Load recent NLP session IDs from file (persists across server restarts)."""
    if not os.path.isfile(RECENT_PROCESSES_FILE):
        return []
    try:
        with open(RECENT_PROCESSES_FILE, "r") as f:
            data = json.load(f)
            return data.get("sessions", [])
    except Exception:
        return []


def _save_recent_session(session_id: str):
    """Append a session ID to the file, keep last 5."""
    sessions = _load_recent_sessions()
    sessions = [s for s in sessions if s.get("id") != session_id]
    sessions.insert(0, {"id": session_id, "started_at": datetime.now().isoformat()})
    sessions = sessions[:5]
    os.makedirs(os.path.dirname(RECENT_PROCESSES_FILE) or ".", exist_ok=True)
    with open(RECENT_PROCESSES_FILE, "w") as f:
        json.dump({"sessions": sessions}, f, indent=2)


def _mark_session_continued(session_id: str, task_id: str):
    """Mark a session as continued (pipeline was run for it)."""
    sessions = _load_recent_sessions()
    for s in sessions:
        if s.get("id") == session_id:
            s["continued_task_id"] = task_id
            s["continued_at"] = datetime.now().isoformat()
            break
    os.makedirs(os.path.dirname(RECENT_PROCESSES_FILE) or ".", exist_ok=True)
    with open(RECENT_PROCESSES_FILE, "w") as f:
        json.dump({"sessions": sessions}, f, indent=2)


def _add_recent_process(store, proc_type: str, proc_id: str):
    """Record a new process (for session state / tasks use API)."""
    if proc_type == "session":
        _save_recent_session(proc_id)
    store["last_task_id"] = proc_id if proc_type == "task" else store.get("last_task_id")


@st.cache_resource
def _persistent_store():
    return {"last_task_id": None}


_store = _persistent_store()

st.title("IDEA4RC Data Ingestion")

ETL_HOST = os.getenv("ETL_HOST", "localhost:4001")
RESULTS_UI_HOST = os.getenv("RESULTS_UI_HOST", "localhost:5173")

# Define API host early so it's available to the "Last run" block
mode = os.getenv("API_HOST", "localhost:8010")

# NLP Backend/Frontend URLs for validation integration
NLP_BACKEND_URL = os.getenv("NLP_BACKEND_URL", "http://localhost:8001")
NLP_FRONTEND_URL = os.getenv("NLP_FRONTEND_URL", "http://localhost:3000")


def _api(path: str) -> str:
    return f"http://{mode}{path}"


st.write(
    """
    In this application you can run the data ingestion pipeline for the IDEA4RC project through the **validation system**.\n
    The pipeline consists of three main steps:\n
    1. **Text Processing**: Extracts and processes free text data from patient records.\n
    2. **Data Linking**: Links the processed text data with structured data from the database.\n
    3. **Quality Checks**: Performs quality checks on the linked data to ensure accuracy and completeness.\n
    **Use OPTION 1** to run the full process with NLP validation (create session, validate annotations, then continue pipeline).\n
    You can also run individual steps (linking only, quality checks only) or the ETL process as needed.\n
    """
)

# --- Last 5 processes (always visible, persisted across sessions) ---
st.markdown("### Last 5 processes")
with st.expander("How to validate an NLP session", expanded=False):
    st.markdown("""
    1. **Create NLP Session** (Option 1) – upload text and structured data, click "1. Create NLP Session".
    2. **Open Validation UI** – click the link next to your session (or go to the NLP frontend `/annotate/<session_id>`).
    3. **Review and correct** histology/topography annotations in the Validation UI.
    4. **Return here** and click **"3. Continue Pipeline"** (with the same structured file still in state). The pipeline will fetch your validated annotations and run Linking + Quality Checks.
    Once you continue, the session will show as **Continued** below and the new pipeline task will appear in the list.
    """)

# Load from API (tasks persist in backend DB) and from file (NLP sessions)
recent_tasks = []
try:
    resp = requests.get(_api("/recent_tasks"), params={"limit": 5}, timeout=5)
    if resp.status_code == 200:
        recent_tasks = resp.json().get("tasks", [])
except Exception:
    pass

recent_sessions = _load_recent_sessions()

# Build combined list: sessions first (awaiting or continued), then tasks, max 5
combined = []
for s in recent_sessions[:5]:
    sid = s.get("id") if isinstance(s, dict) else s
    if sid and sid not in [c["id"] for c in combined]:
        combined.append({
            "type": "session",
            "id": sid,
            "started_at": s.get("started_at") if isinstance(s, dict) else None,
            "continued_task_id": s.get("continued_task_id") if isinstance(s, dict) else None,
            "continued_at": s.get("continued_at") if isinstance(s, dict) else None,
        })
for t in recent_tasks:
    tid = t.get("task_id") if isinstance(t, dict) else t
    if tid and tid not in [c["id"] for c in combined] and len(combined) < 5:
        combined.append({
            "type": "task",
            "id": tid,
            "step": t.get("step"),
            "progress": t.get("progress"),
            "started_at": t.get("started_at"),
        })

if combined:
    for i, proc in enumerate(combined[:5]):
        proc_type = proc.get("type", "task")
        proc_id = proc.get("id", "")
        if not proc_id:
            continue
        def _fmt_ts(ts):
            """Format ISO timestamp for display."""
            if not ts:
                return None
            try:
                if "T" in str(ts):
                    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                else:
                    dt = datetime.strptime(str(ts)[:19], "%Y-%m-%d %H:%M:%S")
                return dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                return str(ts)[:16] if ts else None

        with st.container():
            cols = st.columns([3, 2, 1, 1])
            with cols[0]:
                if proc_type == "session":
                    continued_task_id = proc.get("continued_task_id")
                    label = "NLP Session (continued)" if continued_task_id else "NLP Session (awaiting validation)"
                    st.write(f"**{label}:** `{proc_id}`")
                    run_ts = _fmt_ts(proc.get("continued_at") or proc.get("started_at"))
                    if run_ts:
                        st.caption(f"Run: {run_ts}")
                else:
                    st.write(f"**Task:** `{proc_id}`")
                    run_ts = _fmt_ts(proc.get("started_at"))
                    if run_ts:
                        st.caption(f"Run: {run_ts}")
            with cols[1]:
                if proc_type == "session":
                    continued_task_id = proc.get("continued_task_id")
                    if continued_task_id:
                        st.write("**Status:** Continued")
                        st.caption(f"Pipeline task: `{continued_task_id}` — use **Check Pipeline Status** below to view progress and download results.")
                    else:
                        st.write("**Status:** Awaiting validation")
                        st.markdown(f"[Open Validation UI]({NLP_FRONTEND_URL}/annotate/{proc_id})")
                else:
                    try:
                        resp = requests.get(_api(f"/status/{proc_id}"), timeout=5)
                        if resp.status_code == 200:
                            s = resp.json()
                            st.write(f"**Status:** {s['step']} ({s['progress']}%)")
                        else:
                            st.warning("Status unavailable")
                    except Exception:
                        st.warning("Backend not reachable")
            with cols[2]:
                if proc_type == "session":
                    manage_key = f"manage_{proc_id}"
                    if manage_key not in st.session_state:
                        st.session_state[manage_key] = False
                    if st.button("Manage", key=f"btn_manage_{i}_{proc_id[:8]}"):
                        st.session_state[manage_key] = not st.session_state[manage_key]
                        st.rerun()
                elif proc_type == "task" and st.button("Cancel", key=f"cancel_{i}_{proc_id[:8]}"):
                    try:
                        r = requests.post(_api(f"/cancel/{proc_id}"), timeout=5)
                        st.success(r.json().get("message", "Cancellation requested.")) if r.status_code == 200 else st.error(r.json().get("detail", "Cancel failed."))
                    except Exception as e:
                        st.error(f"Cancel failed: {e}")
            with cols[3]:
                if proc_type == "task" and st.button("Kill", key=f"kill_{i}_{proc_id[:8]}"):
                    try:
                        r = requests.post(_api(f"/kill/{proc_id}"), timeout=5)
                        st.success(r.json().get("message", "Force kill sent.")) if r.status_code == 200 else st.error(r.json().get("detail", "Kill failed."))
                    except Exception as e:
                        st.error(f"Kill failed: {e}")

            # --- Manage panel for sessions ---
            if proc_type == "session" and st.session_state.get(f"manage_{proc_id}", False):
                with st.container(border=True):
                    st.markdown(f"#### Manage Session `{proc_id[:8]}...`")
                    session_data = None
                    try:
                        s_resp = requests.get(f"{NLP_BACKEND_URL}/api/sessions/{proc_id}", timeout=10)
                        if s_resp.status_code == 200:
                            session_data = s_resp.json()
                    except Exception:
                        st.error("Could not fetch session data from NLP backend.")

                    if session_data:
                        # Session name editor
                        new_name = st.text_input(
                            "Session Name",
                            value=session_data.get("name", ""),
                            key=f"name_input_{proc_id[:8]}"
                        )

                        st.caption("To manage prompt types and report-type mapping, use the **Manage** button in the Validation UI.")

                        # Save button
                        if st.button("Save Changes", key=f"save_manage_{proc_id[:8]}"):
                            patch_body = {}
                            if new_name != session_data.get("name", ""):
                                patch_body["name"] = new_name
                            if patch_body:
                                try:
                                    patch_resp = requests.patch(
                                        f"{NLP_BACKEND_URL}/api/sessions/{proc_id}",
                                        json=patch_body,
                                        timeout=10
                                    )
                                    if patch_resp.status_code == 200:
                                        st.success("Session updated successfully.")
                                        st.rerun()
                                    else:
                                        st.error(f"Failed to update session: {patch_resp.text}")
                                except Exception as e:
                                    st.error(f"Failed to connect to NLP backend: {e}")
                            else:
                                st.info("No changes to save.")
                    else:
                        st.warning("Could not load session data. Is the NLP backend running?")

            st.divider()
    if st.button("Refresh Status", key="refresh_last_status"):
        st.rerun()
else:
    st.info("No processes yet. Start a task or create an NLP session to see it here.")

# Initialize session state
if "task_id" not in st.session_state:
    st.session_state.task_id = None

# ─── OPTION 1: Full Process with NLP Validation ─────────────────────────────
st.divider()
st.title("_OPTION 1_ :blue[Full process with NLP Validation]")

st.write("""
    Upload structured data and free texts. The system will create an NLP session
    that you can validate in the NLP UI before continuing with Linking and Quality Checks.

    **Recommended for data requiring manual validation of histology/topography codes.**
""")

# Session state for 1A workflow
if "nlp_session_id" not in st.session_state:
    st.session_state.nlp_session_id = None
if "structured_data_1a" not in st.session_state:
    st.session_state.structured_data_1a = None

disease_type_1a = st.selectbox(
    "Select disease type:",
    ["sarcoma", "head_and_neck"],
    key="disease_type_1a"
)

uploaded_structured_1a = st.file_uploader(
    "Upload structured data (Excel or CSV)",
    type=["xlsx", "csv"],
    key="structured_1a"
)
uploaded_text_1a = st.file_uploader(
    "Upload unstructured text (Excel or CSV)",
    type=["xlsx", "csv"],
    key="text_1a"
)

session_name_1a = st.text_input(
    "Session name (optional — defaults to Pipeline_timestamp)",
    value="",
    key="session_name_1a"
)

col1, col2 = st.columns(2)

with col1:
    create_session_disabled = not uploaded_text_1a
    if st.button("1. Create NLP Session", disabled=create_session_disabled, key="btn_create_nlp_session"):
        # Store structured data for later
        if uploaded_structured_1a:
            st.session_state.structured_data_1a = uploaded_structured_1a.getvalue()

        # Determine session name
        chosen_name = session_name_1a.strip() if session_name_1a.strip() else f"Pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # Create NLP session
        text_mime = "text/csv" if uploaded_text_1a.name.endswith('.csv') else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        files = {"text_file": (uploaded_text_1a.name, uploaded_text_1a.getvalue(), text_mime)}
        try:
            resp = requests.post(
                _api("/nlp/create_session"),
                files=files,
                params={"session_name": chosen_name},
                timeout=30
            )

            if resp.status_code == 200:
                session_data = resp.json()
                st.session_state.nlp_session_id = session_data["session_id"]
                _add_recent_process(_store, "session", st.session_state.nlp_session_id)
                # Auto-open the Manage panel for the new session
                st.session_state[f"manage_{st.session_state.nlp_session_id}"] = True
                st.success(f"NLP Session created: {st.session_state.nlp_session_id}")
                st.info("The **Manage** panel has been opened above — customize the session name and report-type mapping.")
            else:
                st.error(f"Failed to create session: {resp.text}")
        except requests.exceptions.RequestException as e:
            st.error(f"Failed to connect to API: {e}")

# Show validation link if session exists
if st.session_state.nlp_session_id:
    validation_url = f"{NLP_FRONTEND_URL}/annotate/{st.session_state.nlp_session_id}"
    st.markdown("### 2. Validate Annotations")
    st.markdown(f"[Open NLP Validation UI]({validation_url}) (opens in new tab)")
    st.info("Validate annotations (especially histology-topography), then return here to continue.")

with col2:
    continue_disabled = not (st.session_state.nlp_session_id and st.session_state.structured_data_1a)
    if st.button("3. Continue Pipeline", disabled=continue_disabled, key="btn_continue_pipeline"):
        # Continue pipeline with validated data
        files = {"structured_file": ("structured.csv", st.session_state.structured_data_1a)}
        try:
            resp = requests.post(
                _api("/pipeline/continue"),
                files=files,
                params={
                    "session_id": st.session_state.nlp_session_id,
                    "disease_type": disease_type_1a
                },
                timeout=30
            )

            if resp.status_code == 200:
                task_id = resp.json()["task_id"]
                st.session_state.task_id = task_id
                _add_recent_process(_store, "task", task_id)
                _mark_session_continued(st.session_state.nlp_session_id, task_id)
                st.success(f"Pipeline continued! Task ID: `{task_id}` — this session is no longer awaiting validation.")

                # Poll for completion
                bar = st.progress(0, text="Processing...")
                step = ""
                while step not in ("Completed", "Failed", "Cancelled"):
                    time.sleep(1)
                    status = requests.get(_api(f"/status/{task_id}"), timeout=5).json()
                    bar.progress(status["progress"], text=status["step"])
                    step = status["step"]
                bar.empty()

                if step == "Completed":
                    st.success("Pipeline completed! Use 'Check Pipeline Status' below to download results.")
                elif step == "Failed":
                    st.error(f"Pipeline failed: {status.get('result', 'Unknown error')}")
                else:
                    st.warning(f"Pipeline ended with status: {step}")
            else:
                st.error(f"Failed to continue pipeline: {resp.text}")
        except requests.exceptions.RequestException as e:
            st.error(f"Failed to connect to API: {e}")

# Reset button for Option 1 workflow
if st.session_state.nlp_session_id:
    if st.button("Reset Option 1 Workflow", key="btn_reset_1a"):
        st.session_state.nlp_session_id = None
        st.session_state.structured_data_1a = None
        st.rerun()


# ─── OPTION 2 : linking service only ───────────────────────────────────────────
st.divider()
st.title("_OPTION 2_ :blue[Run the linking service]")

# Disease type selector for linking
disease_type_link = st.selectbox(
    "Select disease type:",
    options=["sarcoma", "head_and_neck"],
    key="disease_type_link"
)

uploaded_linking_file = st.file_uploader(
    "Upload a file to run the linking service (Excel or CSV)",
    type=["xlsx", "csv"],
    key="linking_file_uploader",
)

link_btn = st.button(
    "Execute Linking Service",
    key="btn_linking",
    disabled=uploaded_linking_file is None,
)
if link_btn:
    link_mime = "text/csv" if uploaded_linking_file.name.endswith(
        '.csv') else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    files = {
        "file": (
            uploaded_linking_file.name,
            uploaded_linking_file.getvalue(),
            link_mime,
        )
    }
    resp = requests.post(
        _api("/run/link_rows"),
        files=files,
        params={"disease_type": disease_type_link},
        timeout=30
    )

    if resp.status_code != 200:
        st.error(resp.json().get("detail", "Failed to start linking service."))
        st.stop()

    task_id = resp.json()["task_id"]
    st.session_state.task_id = task_id
    _add_recent_process(_store, "task", task_id)
    st.info(f"Task started (ID {task_id}). This usually finishes in 5-30 s…")

    # simple polling loop with a progress bar
    bar = st.progress(0, text="Linking rows…")
    step = ""
    while step not in ("Completed", "Failed", "Cancelled"):
        time.sleep(1)
        status = requests.get(_api(f"/status/{task_id}"), timeout=5).json()
        bar.progress(status["progress"], text=status["step"])
        step = status["step"]

    bar.empty()

    if step == "Failed":
        st.error(f"Linking failed: {status.get('result', 'no message')}")
        st.stop()

    result = requests.get(_api(f"/results/{task_id}/linked_data"), timeout=30)
    if result.status_code != 200:
        st.error(
            f"Finished but couldn't fetch result: "
            f"{result.json().get('detail', 'Unknown error')}"
        )
        st.stop()

    st.success("Linking service completed – download the CSV below:")
    st.download_button(
        label="Download Linking Service Result (CSV)",
        data=result.content,
        file_name=f"{task_id}_linked_data.csv",
        mime="text/csv",
    )

# ─── OPTION 3 : just quality checks ────────────────────────────────────────────
st.divider()
st.title("_OPTION 3_ :blue[Just quality checks]")

st.write("### Run Quality Check on a File")

# Disease type selector for quality check
disease_type_qc = st.selectbox(
    "Select disease type:",
    options=["sarcoma", "head_and_neck"],
    key="disease_type_qc"
)

uploaded_qc_file = st.file_uploader(
    "Upload a file to run quality check (Excel or CSV)", type=["xlsx", "csv"], key="qc_file_uploader"
)

qc_btn = st.button(
    "Execute Quality Check",
    key="btn_qc",
    disabled=uploaded_qc_file is None,
)
if qc_btn:
    qc_mime = "text/csv" if uploaded_qc_file.name.endswith(
        '.csv') else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    files = {
        "file": (
            uploaded_qc_file.name,
            uploaded_qc_file.getvalue(),
            qc_mime,
        )
    }
    resp = requests.post(
        _api("/run/quality_check"),
        files=files,
        params={"disease_type": disease_type_qc},
        timeout=30
    )

    if resp.status_code != 200:
        st.error(resp.json().get(
            "detail", "Failed to start quality check."))
        st.stop()

    task_id = resp.json()["task_id"]
    st.session_state.task_id = task_id
    _add_recent_process(_store, "task", task_id)
    st.info(
        f"Quality check started (ID {task_id}). This usually finishes in 30–60 s…")

    bar = st.progress(0, text="Running quality checks…")
    step = ""
    while step not in ("Completed", "Failed", "Cancelled"):
        time.sleep(1)
        status = requests.get(_api(f"/status/{task_id}"), timeout=5).json()
        bar.progress(status["progress"], text=status["step"])
        step = status["step"]

    bar.empty()

    if step == "Failed":
        st.error(f"Quality check failed: {status.get('result', 'no message')}")
        st.stop()

    result = requests.get(
        _api(f"/results/{task_id}/quality_check"), timeout=30)
    if result.status_code != 200:
        st.error(
            f"Finished but couldn't fetch result: "
            f"{result.json().get('detail', 'Unknown error')}"
        )
        st.stop()

    st.success("Quality check completed – download the CSV below:")
    st.download_button(
        label="Download Quality Check Result (CSV)",
        data=result.content,
        file_name=f"{task_id}_quality_check.csv",
        mime="text/csv",
    )

# SEE data quality

# Initialize state only once
if "data_quality_report" not in st.session_state:
    st.session_state.data_quality_report = False

# Button to toggle visibility
if st.button("See Data Quality Report"):
    st.session_state.data_quality_report = not st.session_state.data_quality_report

# Show report if toggled
if st.session_state.data_quality_report:
    st.markdown("## Data Report")
    st.components.v1.html(
        f"""
        <iframe src="http://{RESULTS_UI_HOST}/" width="100%" height="1000" style="border:none;"></iframe>
        """,
        height=1000
    )

# ─── OPTION 4 : ETL ───────────────────────────────────────────────────────────
st.divider()
st.title("_OPTION 4_ :blue[Run ETL]")

st.write("### Run ETL on a File")

# Disease type selector for ETL
disease_type_etl = st.selectbox(
    "Select disease type:",
    options=["sarcoma", "head_and_neck"],
    key="disease_type_etl"
)

uploaded_etl_file = st.file_uploader(
    "Upload a file to run ETL", type=["xlsx", "csv"], key="etl_file_uploader"
)

etl_btn = st.button(
    "Execute ETL",
    key="btn_etl",
    disabled=uploaded_etl_file is None,
)
if etl_btn:
    files = {
        "dataFile": (
            uploaded_etl_file.name,
            uploaded_etl_file.getvalue(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }
    try:
        # Add disease_type parameter to ETL upload
        upload_response = requests.post(
            f"http://{ETL_HOST}/etl/upload",
            files=files,
            params={"disease_type": disease_type_etl}
        )
        if upload_response.status_code == 200:
            st.success("Final file successfully uploaded!")
        else:
            st.error(
                f"Upload failed with status code {upload_response.status_code}")
    except Exception as e:
        st.error(f"Upload failed: {e}")

    response = requests.post(
        f"http://{mode}/results/quality_check",
        files=files,
        params={"disease_type": disease_type_etl}
    )

    if response.status_code == 200:
        st.success("Quality check completed successfully. Download result below:")
        st.download_button(
            label="Download Quality Check Result",
            data=response.content,
            file_name=f"quality_check_result.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    else:
        st.error(f"Error: {response.json().get('detail', 'Unknown error')}")


# option 5: run discoverability
st.divider()
st.title("_OPTION 5_ :blue[Run Discoverability]")
st.write("### Run Discoverability on a File")
uploaded_discoverability_file = st.file_uploader(
    "Upload a file to run discoverability (Excel or CSV)", type=["xlsx", "csv"], key="discoverability_file_uploader"
)
discoverability_btn = st.button(
    "Execute Discoverability",
    key="btn_discoverability",
    disabled=uploaded_discoverability_file is None,
)
if discoverability_btn:
    discoverability_mime = "text/csv" if uploaded_discoverability_file.name.endswith(
        '.csv') else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    files = {
        "file": (
            uploaded_discoverability_file.name,
            uploaded_discoverability_file.getvalue(),
            discoverability_mime,
        )
    }
    resp = requests.post(_api("/run/discoverability"), files=files, timeout=10)
    if resp.status_code != 200:
        st.error(resp.text)
        st.stop()

    task_id = resp.json()["task_id"]
    _add_recent_process(_store, "task", task_id)
    bar = st.progress(0, text="Starting…")

    step = "Starting"
    progress = 0
    while step not in ("Completed", "Failed", "Cancelled"):
        time.sleep(1)
        try:
            st.write("")  # keep UI responsive
            r = requests.get(_api(f"/status/{task_id}"), timeout=5)
            if r.status_code != 200:
                # status row may not exist yet; keep waiting
                bar.progress(progress, text=step)
                continue
            status = r.json()
            step = status.get("step", step)
            progress = int(status.get("progress", progress or 0) or 0)
            bar.progress(progress, text=step)
        except requests.exceptions.RequestException:
            # transient network error; keep waiting
            bar.progress(progress, text=step)

    bar.empty()
    if step == "Completed":
        r = requests.get(
            _api(f"/results/{task_id}/discoverability_json"), timeout=30)
        if r.status_code == 200:
            st.success("Discoverability completed.")
            st.download_button("Download discoverability JSON", r.content,
                               file_name=f"{task_id}_discoverability.json",
                               mime="application/json")
        else:
            st.error(f"Finished but cannot fetch JSON: {r.text}")
    elif step == "Failed":
        st.error("Discoverability failed. See logs.")
    else:
        st.warning(f"Task ended with state: {step}")
# PIPELINE STATUS
st.divider()

# Check pipeline status section
st.write("### Check Pipeline Status")
task_id_input = st.text_input("Enter Task ID to check status:")

if st.button("Check Status"):
    if task_id_input:
        response = requests.get(f"http://{mode}/status/{task_id_input}")
        if response.status_code == 200:
            status = response.json()
            st.write(f"Step: {status['step']}")
            st.write(f"Progress: {status['progress']}%")
            if status["result"]:
                st.write(f"Result: {status['result']}")

            # New: stop-running button
            if status.get("is_running", False):
                if st.button("Stop this task"):
                    stop_resp = requests.post(
                        f"http://{mode}/cancel/{task_id_input}")
                    if stop_resp.status_code == 200:
                        st.info(stop_resp.json().get(
                            "message", "Cancellation requested."))
                    else:
                        try:
                            st.error(stop_resp.json().get(
                                "detail", "Unable to cancel task"))
                        except Exception:
                            st.error("Unable to cancel task")

            # Step 0: LLM annotations (raw)
            response_data_0 = requests.get(
                _api(f"/results/{task_id_input}/llm_annotations"), timeout=30)
            if response_data_0.status_code == 200:
                st.download_button(
                    label="Download LLM Annotations (Raw CSV)",
                    data=response_data_0.content,
                    file_name=f"{task_id_input}_llm_annotations.csv",
                    mime="text/csv",
                )
            else:
                st.info("LLM annotations not available yet (only for full pipeline)")

            # Step 1: Processed Texts (after regex extraction)
            response_data_1 = requests.get(
                _api(f"/results/{task_id_input}/processed_texts"), timeout=30)
            if response_data_1.status_code == 200:
                st.download_button(
                    label="Download CSV step 1 (Processed Texts)",
                    data=response_data_1.content,
                    file_name=f"{task_id_input}_processed_texts.csv",
                    mime="text/csv",
                )
            else:
                st.error(f"Error fetching file 1: {response_data_1.text}")

            response_data_2 = requests.get(
                _api(f"/results/{task_id_input}/linked_data"), timeout=30)
            if response_data_2.status_code == 200:
                st.download_button(
                    label="Download CSV step 2 (Linked Data)",
                    data=response_data_2.content,
                    file_name=f"{task_id_input}_linked_data.csv",
                    mime="text/csv",
                )
            else:
                st.error(f"Error fetching file 2: {response_data_2.text}")

            response_data_3 = requests.get(
                _api(f"/results/{task_id_input}/quality_check"), timeout=30)
            if response_data_3.status_code == 200:
                st.download_button(
                    label="Download CSV step 3 (Quality Check)",
                    data=response_data_3.content,
                    file_name=f"{task_id_input}_quality_check.csv",
                    mime="text/csv",
                )

                # Upload option if pipeline is completed
                if status["step"] == "Completed":
                    st.write(
                        "✅ Pipeline finished. You can now upload the final file.")
                    if st.button("Send Final File to Upload Endpoint"):
                        try:
                            files = {
                                'dataFile': (
                                    f'{task_id_input}_quality_check.csv',
                                    response_data_3.content,
                                    'text/csv'
                                )
                            }
                            upload_response = requests.post(
                                f"http://{ETL_HOST}/etl/upload", files=files)
                            if upload_response.status_code == 200:
                                st.success("Final file successfully uploaded!")
                            else:
                                st.error(
                                    f"Upload failed with status code {upload_response.status_code}")
                        except Exception as e:
                            st.error(f"Upload failed: {e}")
            else:
                st.error(f"Error fetching file 3: {response_data_3.text}")
        else:
            st.error(
                f"Error: {response.json().get('detail', 'Unknown error')}")
    else:
        st.warning("Please enter a valid Task ID.")

st.divider()

# Fetch logs section
st.write("### View Logs")
task_id_logs = st.text_input("Enter Task ID to view logs:")

if st.button("Fetch Logs"):
    if task_id_logs:
        try:
            response = requests.get(_api(f"/logs/{task_id_logs}"), timeout=10)
            if response.status_code == 200:
                logs = response.json()["logs"]
                st.write("### Logs:")
                for log in logs:
                    st.write(
                        f"[{log['timestamp']}] {log['level']}: {log['message']}")
            else:
                st.error(
                    f"Error: {response.json().get('detail', 'Task not found')}")
        except Exception as e:
            st.error(f"Logs fetch failed. Backend {mode} not reachable: {e}")
    else:
        st.warning("Please enter a valid Task ID.")


# Streamlit frontend only; no FastAPI server here
