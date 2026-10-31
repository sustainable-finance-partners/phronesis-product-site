#!/usr/bin/env python3
"""Refresh the homepage record count from the live scorecard, in place.

The homepage metric bar carries the count of records on the register as a static
number with its date (``site/index.html``): the span marked
``data-source="scorecard.aggregate_stats.forecast_count"`` holds the digits and a
``data-as-of`` date, and the label's ``<time>`` element repeats the date. The inline
script on the page refreshes both in the browser; this script refreshes the static
values, the ones crawlers and the parity gate read, right before a merge.

It reads ``https://api.phronesisintel.com/.well-known/scorecard.json`` and takes
``aggregate_stats.forecast_count`` (a non-negative integer) and the UTC date of
``metadata.generated_at`` (the same two fields, and the same rule, as the inline
script). It rewrites three values in ``site/index.html`` and no other byte: the span's
digits, its ``data-as-of``, and the ``<time>`` element's ``datetime`` and text. It
prints each old value and its new value.

It refuses, and leaves the file untouched, when the payload is not in that shape (an
outage envelope with an empty ``aggregate_stats`` included), when the date is not a
real date or is later than today (UTC), or when the markup is not found exactly once.

Usage:
  python3 scripts/refresh_count.py              # fetch, rewrite site/index.html
  python3 scripts/refresh_count.py --dry-run    # fetch, print, write nothing
  python3 scripts/refresh_count.py --from-file scorecard.json   # no network

Exit status: 0 written (or already current), 1 refused, 2 usage. Standard library only.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX = REPO_ROOT / "site" / "index.html"
SCORECARD_URL = "https://api.phronesisintel.com/.well-known/scorecard.json"
TIMEOUT_S = 20

#: The count span as the page renders it: the gate's marker last, the digits its text.
SPAN_RE = re.compile(
    r'(<span class="metric-value" id="record-count" data-as-of=")(\d{4}-\d{2}-\d{2})'
    r'(" data-source="scorecard\.aggregate_stats\.forecast_count">)(\d+)(</span>)'
)
#: The label's date element.
TIME_RE = re.compile(
    r'(<time id="record-count-as-of" datetime=")(\d{4}-\d{2}-\d{2})(">)'
    r"(\d{4}-\d{2}-\d{2})(</time>)"
)


class Refused(Exception):
    """The payload or the page is not in the expected shape; nothing is written."""


def fetch(url: str = SCORECARD_URL) -> Any:
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "phronesis-site-refresh-count"},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        return json.loads(resp.read().decode("utf-8"))


def read_payload(data: Any, today: dt.date) -> tuple[int, str]:
    """``(forecast_count, as-of date)`` from a scorecard payload, or :class:`Refused`."""
    if not isinstance(data, dict):
        raise Refused("the scorecard payload is not a JSON object")
    stats = data.get("aggregate_stats")
    if not isinstance(stats, dict) or "forecast_count" not in stats:
        raise Refused("aggregate_stats.forecast_count is absent (outage envelope?)")
    n = stats["forecast_count"]
    if isinstance(n, bool) or not isinstance(n, int) or n < 0:
        raise Refused(f"aggregate_stats.forecast_count is not a non-negative integer: {n!r}")
    meta = data.get("metadata")
    stamp = meta.get("generated_at") if isinstance(meta, dict) else None
    if not isinstance(stamp, str):
        raise Refused("metadata.generated_at is absent or not a string")
    day = stamp[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise Refused(f"metadata.generated_at does not start with a YYYY-MM-DD date: {stamp!r}")
    try:
        when = dt.date.fromisoformat(day)
    except ValueError:
        raise Refused(f"metadata.generated_at is not a real date: {stamp!r}") from None
    if when > today:
        raise Refused(f"the as-of date {day} is later than today ({today.isoformat()}, UTC)")
    return n, day


def rewrite(page: str, n: int, day: str) -> tuple[str, list[tuple[str, str, str]]]:
    """The page with the three values replaced, and ``(what, old, new)`` for each."""
    spans = list(SPAN_RE.finditer(page))
    times = list(TIME_RE.finditer(page))
    if len(spans) != 1:
        raise Refused(f"the count span occurs {len(spans)} times, not once")
    if len(times) != 1:
        raise Refused(f"the as-of <time> element occurs {len(times)} times, not once")
    span, time = spans[0], times[0]
    if time.group(2) != time.group(4):
        raise Refused("the <time> element's datetime and text disagree")
    changes = [
        ("forecast_count", span.group(4), str(n)),
        ("data-as-of", span.group(2), day),
        ("<time>", time.group(2), day),
    ]
    new_span = f"{span.group(1)}{day}{span.group(3)}{n}{span.group(5)}"
    new_time = f"{time.group(1)}{day}{time.group(3)}{day}{time.group(5)}"
    # Replace from the later match first so the earlier offsets stay valid.
    edits = sorted(
        [(span.start(), span.end(), new_span), (time.start(), time.end(), new_time)],
        reverse=True,
    )
    out = page
    for start, end, text in edits:
        out = out[:start] + text + out[end:]
    return out, changes


def refresh(index: Path, data: Any, today: dt.date, write: bool = True) -> list[str]:
    """Rewrite ``index`` from ``data``; return the printed lines. Raises :class:`Refused`."""
    n, day = read_payload(data, today)
    raw = index.read_bytes()
    page = raw.decode("utf-8")
    new_page, changes = rewrite(page, n, day)
    lines = [f"{what}: {old} -> {new}" for what, old, new in changes]
    if int(changes[0][1]) > n:
        lines.append(f"note: the live count ({n}) is below the static count ({changes[0][1]})")
    if new_page == page:
        lines.append(f"{index.name}: already current; nothing written")
    elif write:
        index.write_bytes(new_page.encode("utf-8"))
        lines.append(f"{index.name}: written")
    else:
        lines.append(f"{index.name}: dry run; nothing written")
    return lines


def main(argv: list[str]) -> int:
    args = argv[1:]
    write = True
    source: Path | None = None
    while args:
        arg = args.pop(0)
        if arg == "--dry-run":
            write = False
        elif arg == "--from-file" and args:
            source = Path(args.pop(0))
        else:
            print(__doc__)
            return 2
    today = dt.datetime.now(dt.timezone.utc).date()
    try:
        if source is not None:
            data = json.loads(source.read_text(encoding="utf-8"))
        else:
            data = fetch()
        lines = refresh(INDEX, data, today, write=write)
    except Refused as exc:
        print(f"REFUSED: {exc}; {INDEX.name} is unchanged")
        return 1
    except (OSError, ValueError) as exc:
        print(f"REFUSED: could not read the scorecard ({exc}); {INDEX.name} is unchanged")
        return 1
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
