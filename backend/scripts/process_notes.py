#!/usr/bin/env python3
"""
Sequential per-note annotation processor for Clinical Annotation Web.

Calls the /api/annotate/sequential/stream endpoint to process notes one at a time,
with per-note error resilience and incremental save to disk.

Requires the backend server to be running.

Usage:
    python backend/scripts/process_notes.py --session-id <ID>
    python backend/scripts/process_notes.py --session-id <ID> --skip-annotated
    python backend/scripts/process_notes.py --session-id <ID> --fast --dry-run
    python backend/scripts/process_notes.py --session-id <ID> --note-ids note1 note2
    python backend/scripts/process_notes.py --session-id <ID> --output-json results.json
"""

import argparse
import json
import sys
import time


def parse_args():
    parser = argparse.ArgumentParser(
        description="Sequential per-note annotation processor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --session-id abc123
  %(prog)s --session-id abc123 --skip-annotated
  %(prog)s --session-id abc123 --fast --dry-run
  %(prog)s --session-id abc123 --note-ids note1 note2 note3
  %(prog)s --session-id abc123 --prompt-types histology-int ageatdiagnosis-int
  %(prog)s --session-id abc123 --output-json results.json
  %(prog)s --session-id abc123 --api-url http://remote:8001
        """,
    )
    parser.add_argument("--session-id", required=True, help="Session ID to process")
    parser.add_argument("--note-ids", nargs="+", default=None, help="Specific note IDs (space-separated)")
    parser.add_argument("--prompt-types", nargs="+", default=None, help="Override prompt types (space-separated)")
    parser.add_argument("--skip-annotated", action="store_true", help="Skip notes that already have annotations")
    parser.add_argument("--fast", action="store_true", help="Use fast/condensed prompts")
    parser.add_argument("--fewshot-k", type=int, default=5, help="Number of few-shot examples (default: 5)")
    parser.add_argument("--no-fewshots", action="store_true", help="Disable few-shot examples")
    parser.add_argument("--dry-run", action="store_true", help="Show processing plan without executing")
    parser.add_argument("--api-url", default="http://localhost:8001", help="Backend base URL (default: http://localhost:8001)")
    parser.add_argument("--output-json", default=None, help="Write JSON summary report to file")
    return parser.parse_args()


def check_server(api_url):
    """Check if the backend server is reachable."""
    import requests
    try:
        resp = requests.get(f"{api_url}/api/server/status", timeout=5)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"ERROR: Cannot reach backend at {api_url}")
        print(f"  {e}")
        print(f"  Make sure the server is running: cd backend && uvicorn main:app --port 8001")
        sys.exit(1)


def get_session(api_url, session_id):
    """Fetch session data for dry-run display."""
    import requests
    resp = requests.get(f"{api_url}/api/sessions/{session_id}", timeout=10)
    if resp.status_code == 404:
        print(f"ERROR: Session not found: {session_id}")
        sys.exit(1)
    resp.raise_for_status()
    return resp.json()


def format_time(seconds):
    """Format seconds to human-readable string."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes}m {secs:.0f}s"


def run_dry_run(api_url, args):
    """Show what would be processed without executing."""
    session = get_session(api_url, args.session_id)

    notes = session.get("notes", [])
    annotations = session.get("annotations", {})
    prompt_types = args.prompt_types or session.get("prompt_types", [])

    if args.note_ids:
        requested_ids = set(args.note_ids)
        notes = [n for n in notes if n.get("note_id") in requested_ids]

    annotated_count = 0
    to_process = []
    for note in notes:
        note_id = note.get("note_id", "")
        existing = annotations.get(note_id, {})
        if args.skip_annotated and all(pt in existing for pt in prompt_types):
            annotated_count += 1
        else:
            to_process.append(note_id)

    print(f"\nSession: {args.session_id} ({session.get('name', 'unnamed')})")
    print(f"Notes: {len(notes)} total, {annotated_count} already annotated, {len(to_process)} to process")
    print(f"Prompts: {len(prompt_types)} types ({', '.join(prompt_types[:5])}{'...' if len(prompt_types) > 5 else ''})")
    print(f"Mode: {'fast' if args.fast else 'standard'}")
    print(f"Few-shots: {'disabled' if args.no_fewshots else f'k={args.fewshot_k}'}")

    if to_process:
        print(f"\nNotes to process:")
        for nid in to_process[:20]:
            print(f"  - {nid}")
        if len(to_process) > 20:
            print(f"  ... and {len(to_process) - 20} more")
    else:
        print("\nNothing to process (all notes already annotated).")


def process_stream(api_url, args):
    """Process notes via SSE streaming endpoint."""
    import requests

    # Build request body
    body = {
        "fewshot_k": args.fewshot_k,
        "use_fewshots": not args.no_fewshots,
        "fast_mode": args.fast,
        "skip_annotated": args.skip_annotated,
    }
    if args.note_ids:
        body["note_ids"] = args.note_ids
    if args.prompt_types:
        body["prompt_types"] = args.prompt_types

    url = f"{api_url}/api/annotate/sequential/stream"
    params = {"session_id": args.session_id}

    try:
        resp = requests.post(url, json=body, params=params, stream=True, timeout=None)
        if resp.status_code != 200:
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            print(f"ERROR: Server returned {resp.status_code}: {detail}")
            sys.exit(1)
    except requests.ConnectionError:
        print(f"ERROR: Cannot connect to {api_url}")
        sys.exit(1)

    # Parse SSE events
    results = []
    total_to_process = 0
    buffer = ""

    for chunk in resp.iter_content(chunk_size=None, decode_unicode=True):
        if not chunk:
            continue
        buffer += chunk
        while "\n\n" in buffer:
            event_str, buffer = buffer.split("\n\n", 1)
            event_type = None
            event_data = None

            for line in event_str.strip().split("\n"):
                if line.startswith("event:"):
                    event_type = line[len("event:"):].strip()
                elif line.startswith("data:"):
                    event_data = line[len("data:"):].strip()

            if not event_type or not event_data:
                continue

            try:
                data = json.loads(event_data)
            except json.JSONDecodeError:
                continue

            if event_type == "started":
                total_to_process = data.get("notes_to_process", 0)
                skipped = data.get("skipped", 0)
                total_notes = data.get("total_notes", 0)
                print(f"Notes: {total_notes} total, {skipped} skipped, {total_to_process} to process")
                print("-" * 52)

            elif event_type == "progress":
                note_id = data.get("note_id", "?")
                status = data.get("status", "?")
                completed = data.get("completed", 0)
                total = data.get("total", total_to_process)
                proc_time = data.get("processing_time_seconds", 0)

                if status == "success":
                    ann_count = data.get("annotations_count", 0)
                    status_str = f"OK  ({ann_count} prompts, {format_time(proc_time)})"
                elif status == "error":
                    err = data.get("error_message", "unknown error")
                    status_str = f"ERROR: {err}"
                else:
                    status_str = status

                width = len(str(total))
                print(f"[{completed:>{width}}/{total}] {note_id} {'.' * max(1, 40 - len(note_id))} {status_str}")
                results.append(data)

            elif event_type == "complete":
                return data

            elif event_type == "error":
                detail = data.get("detail", "Unknown error")
                print(f"\nERROR from server: {detail}")
                sys.exit(1)

    # If we get here without a complete event, try non-streaming fallback
    print("\nWARN: Stream ended without complete event. Trying non-streaming fallback...")
    return process_non_stream(api_url, args)


def process_non_stream(api_url, args):
    """Fallback: process via non-streaming endpoint."""
    import requests

    body = {
        "fewshot_k": args.fewshot_k,
        "use_fewshots": not args.no_fewshots,
        "fast_mode": args.fast,
        "skip_annotated": args.skip_annotated,
    }
    if args.note_ids:
        body["note_ids"] = args.note_ids
    if args.prompt_types:
        body["prompt_types"] = args.prompt_types

    url = f"{api_url}/api/annotate/sequential"
    params = {"session_id": args.session_id}

    print("Processing (non-streaming, please wait)...")
    resp = requests.post(url, json=body, params=params, timeout=None)
    if resp.status_code != 200:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        print(f"ERROR: Server returned {resp.status_code}: {detail}")
        sys.exit(1)

    return resp.json()


def main():
    args = parse_args()

    print("Sequential Note Processor - Clinical Annotation Web")
    print("=" * 52)

    # Check server
    status = check_server(args.api_url)
    vllm_status = status.get("vllm", {}).get("status", "unknown")
    print(f"Server: {args.api_url} | vLLM: {vllm_status}")

    # Dry run
    if args.dry_run:
        run_dry_run(args.api_url, args)
        return

    # Process
    print(f"Session: {args.session_id}")
    print(f"Mode: {'fast' if args.fast else 'standard'} | Skip annotated: {args.skip_annotated}")
    print("-" * 52)

    start_time = time.time()

    try:
        response = process_stream(args.api_url, args)
    except KeyboardInterrupt:
        elapsed = time.time() - start_time
        print(f"\n\nInterrupted after {format_time(elapsed)}.")
        print("Already-processed notes have been saved. Re-run with --skip-annotated to resume.")
        sys.exit(130)

    if response is None:
        print("ERROR: No response received")
        sys.exit(1)

    # Print summary
    print("=" * 52)
    processed = response.get("processed", 0)
    errors = response.get("errors", 0)
    skipped = response.get("skipped", 0)
    total_time = response.get("total_time_seconds", time.time() - start_time)
    total_notes = response.get("total_notes", 0)

    print(f"Summary: {processed}/{processed + errors} OK, {errors} error(s), {skipped} skipped | Total: {format_time(total_time)}")
    if processed > 0:
        print(f"Avg: {format_time(total_time / processed)}/note")

    # Write JSON report if requested
    if args.output_json:
        with open(args.output_json, "w") as f:
            json.dump(response, f, indent=2, default=str)
        print(f"Report saved to: {args.output_json}")

    # Exit code: 0 if all OK, 1 if any errors
    if errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
