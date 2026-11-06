#!/usr/bin/env python3
"""Refresh the homepage record count and vertical badges from the live scorecard.

The homepage metric bar carries the count of records on the register as a static
number with its date (``site/index.html``): the span marked
``data-source="scorecard.aggregate_stats.forecast_count"`` holds the digits and a
``data-as-of`` date, and the label's ``<time>`` element repeats the date. The inline
script on the page refreshes both in the browser; this script refreshes the static
values, the ones crawlers and the parity gate read, right before a merge (and, once the
owner sets it, as the Pages build command).

The vertical list carries one badge per vertical (V#0-V#12), register-derived (COO
dispatch 809 §7): ``"{n} records"`` where the register holds n > 0 records for the
vertical, else ``"catalogued"`` (both strings from ``status_copy_text``, generated from
809's bytes). n counts the records the register count is made over (the rows of
``forecasts`` whose ``record_class`` is absent or ``forecast``; their number must equal
``forecast_count``, or the script refuses) whose ``value.intake_payload.subject`` is the
vertical's subject (:data:`VERTICAL_SUBJECTS`). The list's ``data-as-of`` is the count's
date. A record whose subject names no vertical is counted on no badge and printed.

It reads ``https://api.phronesisintel.com/.well-known/scorecard.json`` and takes
``aggregate_stats.forecast_count`` (a non-negative integer), the UTC date of
``metadata.generated_at`` (the same two fields, and the same rule, as the inline
script) and ``forecasts``. It rewrites the span's digits, its ``data-as-of``, the
``<time>`` element's ``datetime`` and text, the vertical list's ``data-as-of`` and the
thirteen badges' class and text in ``site/index.html``, and no other byte. It prints
each old value and its new value.

It refuses, and leaves the file untouched, when the payload is not in that shape (an
outage envelope with an empty ``aggregate_stats`` included), when the date is not a
real date or is later than today (UTC), or when the markup is not found exactly once.

``--check`` writes nothing: it compares the static page with the live register and
fails when the page states a number above it (the count, or any badge) or an as-of
after it; a page behind the register passes with WARN lines (the CI fallback COO
dispatch 809 §9 names, for when no build command refreshes the page).

Usage:
  python3 scripts/refresh_count.py              # fetch, rewrite site/index.html
  python3 scripts/refresh_count.py --dry-run    # fetch, print, write nothing
  python3 scripts/refresh_count.py --check      # fetch, fail on an overclaim
  python3 scripts/refresh_count.py --from-file scorecard.json   # no network

Exit status: 0 written (or already current; with --check, no overclaim), 1 refused
(with --check, an overclaim), 2 usage. Standard library only.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:  # isolated mode (-I) drops the script's directory
    sys.path.insert(0, str(_HERE))

from status_copy_text import VERTICAL_CATALOGUED, VERTICAL_RECORDS  # noqa: E402

REPO_ROOT = _HERE.parent
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

#: The homepage's thirteen vertical badges, in page order, each with the register
#: subject its records carry (``value.intake_payload.subject``). The subjects are the
#: app's canonical vertical tokens, ``mcp_server/discovery/route.py``
#: ``_VERTICAL_METADATA`` at ``bda96164`` (V1 line 146, V2 165, V3 187, V4 205, V5 224,
#: V6 242, V7 260, V8 278, V9 296, V10 316, V11 336, V12 356). V#0, the meta-vertical,
#: has no subject there: no record names it, so its badge is always the catalogued one.
VERTICAL_SUBJECTS: tuple[tuple[str, str | None], ...] = (
    ("V#0", None),
    ("V#1", "energy"),
    ("V#2", "compute"),
    ("V#3", "healthcare"),
    ("V#4", "climate"),
    ("V#5", "regulatory"),
    ("V#6", "supply_chain"),
    ("V#7", "space"),
    ("V#8", "robotics"),
    ("V#9", "ai_agi"),
    ("V#10", "physics_materials"),
    ("V#11", "longevity"),
    ("V#12", "quantum"),
)
#: The ``record_class`` values the register count is made over: absent (today's rows)
#: and ``forecast`` (809 §5); ``capability_test`` and ``withdrawn`` leave every count.
COUNTED_CLASSES: tuple[str | None, ...] = (None, "forecast")
#: The two badge forms, by the CSS class each carries on the page.
RECORDS_CLASS = "records"
CATALOGUED_CLASS = "catalogued"

#: The vertical list's opening tag: its as-of date, and the source the badges read.
LIST_RE = re.compile(
    r'(<ul class="vertical-list" id="vertical-records" data-as-of=")'
    r'(\d{4}-\d{2}-\d{2})(" data-source="scorecard\.forecasts\.subject">)'
)
#: One badge: its class, its vertical, its text.
BADGE_RE = re.compile(
    r'(<span class="vertical-status )(records|catalogued)(" data-vertical=")'
    r'(V#\d+)(">)([^<]*)(</span>)'
)
#: Every badge on the page carries this, whatever its form.
BADGE_MARK = 'class="vertical-status '


class Refused(Exception):
    """The payload or the page is not in the expected shape; nothing is written."""


def fetch(url: str = SCORECARD_URL) -> Any:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "phronesis-site-refresh-count",
        },
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
        raise Refused(
            f"aggregate_stats.forecast_count is not a non-negative integer: {n!r}"
        )
    meta = data.get("metadata")
    stamp = meta.get("generated_at") if isinstance(meta, dict) else None
    if not isinstance(stamp, str):
        raise Refused("metadata.generated_at is absent or not a string")
    day = stamp[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise Refused(
            f"metadata.generated_at does not start with a YYYY-MM-DD date: {stamp!r}"
        )
    try:
        when = dt.date.fromisoformat(day)
    except ValueError:
        raise Refused(f"metadata.generated_at is not a real date: {stamp!r}") from None
    if when > today:
        raise Refused(
            f"the as-of date {day} is later than today ({today.isoformat()}, UTC)"
        )
    return n, day


def vertical_counts(data: Any, total: int) -> tuple[dict[str, int], dict[str, int]]:
    """``(records per badge, records per subject that names no vertical)``.

    The rows counted are the ones ``forecast_count`` is made over; their number must be
    ``total``, so a class the count leaves out cannot enter a badge (and a class it
    keeps cannot leave one) without the script refusing.
    """
    rows = data.get("forecasts") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise Refused("forecasts is absent or not a list")
    by_subject: dict[str, int] = {}
    counted = 0
    for row in rows:
        if not isinstance(row, dict):
            raise Refused("a forecasts entry is not a JSON object")
        if row.get("record_class") not in COUNTED_CLASSES:
            continue
        counted += 1
        value = row.get("value")
        payload = value.get("intake_payload") if isinstance(value, dict) else None
        subject = payload.get("subject") if isinstance(payload, dict) else None
        key = subject if isinstance(subject, str) else "(no subject)"
        by_subject[key] = by_subject.get(key, 0) + 1
    if counted != total:
        raise Refused(
            f"the forecasts the count is made over number {counted}, "
            f"not forecast_count {total}"
        )
    known = {subject for _, subject in VERTICAL_SUBJECTS if subject is not None}
    per_badge = {
        vid: (by_subject.get(subject, 0) if subject is not None else 0)
        for vid, subject in VERTICAL_SUBJECTS
    }
    unmapped = {s: n for s, n in sorted(by_subject.items()) if s not in known}
    return per_badge, unmapped


def badge(n: int) -> tuple[str, str]:
    """``(css class, text)`` of a badge for a vertical with ``n`` records."""
    if VERTICAL_RECORDS.count("{n}") != 1:
        raise Refused(f"the records form {VERTICAL_RECORDS!r} does not carry one {{n}}")
    if n > 0:
        return RECORDS_CLASS, VERTICAL_RECORDS.replace("{n}", str(n))
    return CATALOGUED_CLASS, VERTICAL_CATALOGUED


def rewrite(page: str, n: int, day: str) -> tuple[str, list[tuple[str, str, str]]]:
    """The page with the three count values replaced, and ``(what, old, new)`` each."""
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
    return _splice(page, [(span, new_span), (time, new_time)]), changes


def rewrite_verticals(
    page: str, per_badge: Mapping[str, int], day: str
) -> tuple[str, list[tuple[str, str, str]]]:
    """The page with the list's as-of and the thirteen badges replaced, and the changes."""
    lists = list(LIST_RE.finditer(page))
    if len(lists) != 1:
        raise Refused(f"the vertical list occurs {len(lists)} times, not once")
    badges = list(BADGE_RE.finditer(page))
    found = [m.group(4) for m in badges]
    wanted = [vid for vid, _ in VERTICAL_SUBJECTS]
    if found != wanted or page.count(BADGE_MARK) != len(wanted):
        raise Refused(
            f"the vertical badges are {found} ({page.count(BADGE_MARK)} marked), "
            f"not {wanted} once each"
        )
    (opening,) = lists
    edits = [(opening, f"{opening.group(1)}{day}{opening.group(3)}")]
    changes = [("vertical data-as-of", opening.group(2), day)]
    for m in badges:
        css, text = badge(per_badge[m.group(4)])
        old = m.group(6)
        edits.append(
            (
                m,
                f"{m.group(1)}{css}{m.group(3)}{m.group(4)}{m.group(5)}{text}{m.group(7)}",
            )
        )
        if old != text or m.group(2) != css:
            changes.append((m.group(4), old, text))
    return _splice(page, edits), changes


def _splice(page: str, edits: list[tuple[re.Match[str], str]]) -> str:
    # Replace from the last match first so the earlier offsets stay valid.
    out = page
    for match, text in sorted(edits, key=lambda e: e[0].start(), reverse=True):
        out = out[: match.start()] + text + out[match.end() :]
    return out


def refresh(
    index: Path, data: Any, today: dt.date, write: bool = True, verticals: bool = False
) -> list[str]:
    """Rewrite ``index`` from ``data``; return the printed lines. Raises :class:`Refused`.

    The count always; the vertical list too when ``verticals`` (the command line always
    passes it). Nothing is written unless every rewrite succeeds.
    """
    n, day = read_payload(data, today)
    raw = index.read_bytes()
    page = raw.decode("utf-8")
    new_page, changes = rewrite(page, n, day)
    lines = [f"{what}: {old} -> {new}" for what, old, new in changes]
    if int(changes[0][1]) > n:
        lines.append(
            f"note: the live count ({n}) is below the static count ({changes[0][1]})"
        )
    if verticals:
        per_badge, unmapped = vertical_counts(data, n)
        new_page, vchanges = rewrite_verticals(new_page, per_badge, day)
        lines += [f"{what}: {old} -> {new}" for what, old, new in vchanges]
        if unmapped:
            listed = ", ".join(f"{s} {k}" for s, k in unmapped.items())
            lines.append(f"note: records whose subject names no vertical: {listed}")
    if new_page == page:
        lines.append(f"{index.name}: already current; nothing written")
    elif write:
        index.write_bytes(new_page.encode("utf-8"))
        lines.append(f"{index.name}: written")
    else:
        lines.append(f"{index.name}: dry run; nothing written")
    return lines


def _badge_count(match: re.Match[str]) -> int:
    """The number a badge states: 0 for the catalogued form, n for the records form."""
    if match.group(2) == CATALOGUED_CLASS and match.group(6) == VERTICAL_CATALOGUED:
        return 0
    head, tail = VERTICAL_RECORDS.split("{n}")
    stated = match.group(6)
    digits = (
        stated[len(head) : len(stated) - len(tail)] if tail else stated[len(head) :]
    )
    if (
        match.group(2) != RECORDS_CLASS
        or not stated.startswith(head)
        or not stated.endswith(tail)
        or not digits.isdigit()
    ):
        raise Refused(f"badge {match.group(4)} reads {stated!r}, in neither form")
    return int(digits)


def check(index: Path, data: Any, today: dt.date) -> tuple[bool, list[str]]:
    """``(no overclaim, lines)``: the static page against the live register.

    Every number the page states (the count and each badge) must be at most the live
    one, and its as-of no later than the live date; a page behind the register is a
    WARN line, never a failure (a refresh brings it current). Raises :class:`Refused`
    when the payload or the markup is not in the expected shape.
    """
    n, day = read_payload(data, today)
    per_badge, _ = vertical_counts(data, n)
    page = index.read_bytes().decode("utf-8")
    rewrite(page, n, day)  # the markup is found exactly once, or Refused
    rewrite_verticals(page, per_badge, day)
    span = SPAN_RE.search(page)
    assert span is not None  # rewrite() found it
    stated = [("forecast_count", int(span.group(4)), n)]
    stated += [
        (m.group(4), _badge_count(m), per_badge[m.group(4)])
        for m in BADGE_RE.finditer(page)
    ]
    over = [
        f"OVERCLAIM {what}: the page states {s}, the register {live}"
        for what, s, live in stated
        if s > live
    ]
    if span.group(2) > day:
        over.append(
            f"OVERCLAIM as-of: the page states {span.group(2)}, the register {day}"
        )
    behind = [
        f"WARN {what}: the page states {s}, the register {live}"
        for what, s, live in stated
        if s < live
    ]
    lines = over + behind
    if over:
        lines.append(f"{index.name}: FAIL ({len(over)} above the register)")
    elif behind:
        lines.append(
            f"{index.name}: OK, behind the register; a refresh brings it current"
        )
    else:
        lines.append(f"{index.name}: OK, current with the register as of {day}")
    return not over, lines


def main(argv: list[str]) -> int:
    args = argv[1:]
    write = True
    checking = False
    source: Path | None = None
    while args:
        arg = args.pop(0)
        if arg == "--dry-run":
            write = False
        elif arg == "--check":
            checking = True
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
        if checking:
            ok, lines = check(INDEX, data, today)
            for line in lines:
                print(line)
            return 0 if ok else 1
        lines = refresh(INDEX, data, today, write=write, verticals=True)
    except Refused as exc:
        print(f"REFUSED: {exc}; {INDEX.name} is unchanged")
        return 1
    except (OSError, ValueError) as exc:
        print(
            f"REFUSED: could not read the scorecard ({exc}); {INDEX.name} is unchanged"
        )
        return 1
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
