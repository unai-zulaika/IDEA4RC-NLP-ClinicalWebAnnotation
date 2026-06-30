"""Render the enriched metrics dict to Markdown via Jinja2.

Strict-undefined: any missing field crashes loudly rather than producing silent
empty cells. This is what catches schema drift early.
"""
from __future__ import annotations

from pathlib import Path

import jinja2

DEFAULT_TEMPLATE_PATH = Path(__file__).parent / "templates" / "default.md.j2"

BUCKET_ORDER = ("reliable", "usable", "unreliable")


def _split_buckets(metrics: dict) -> dict[str, list[dict]]:
    """Group prompts into buckets, sorted alphabetically within each."""
    buckets: dict[str, list[dict]] = {b: [] for b in BUCKET_ORDER}
    for name, p in metrics["by_prompt"].items():
        bucket = p["bucket"]
        # Make a shallow copy with the name embedded so the template can reference it.
        record = dict(p)
        record["name"] = name
        buckets[bucket].append(record)
    for b in buckets:
        buckets[b].sort(key=lambda r: r["name"])
    return buckets


def render_markdown(metrics: dict, template_path: Path | None = None) -> str:
    """Render the enriched metrics (after classifier + sampler) to a Markdown string."""
    tpl_path = template_path or DEFAULT_TEMPLATE_PATH
    if not tpl_path.exists():
        raise FileNotFoundError(f"Template not found: {tpl_path}")

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(tpl_path.parent)),
        undefined=jinja2.StrictUndefined,
        autoescape=False,  # Markdown output; we manage escaping explicitly via macros
        # trim_blocks=False on purpose: we need newlines after inline {% endif %}
        # tags to land in the output between bullet rows.
        trim_blocks=False,
        lstrip_blocks=True,
    )
    template = env.get_template(tpl_path.name)

    context = {
        "center": metrics["center"],
        "generated_at": metrics["generated_at"],
        "session_id": metrics["session_id"],
        "totals": metrics["totals"],
        "summary_sentence": metrics["summary_sentence"],
        "bucket_counts": metrics["bucket_counts"],
        "buckets": _split_buckets(metrics),
    }
    return template.render(context)


def write_markdown(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
