#!/usr/bin/env python3
"""Generate ``scripts/status_copy_text.py`` from the byte copy of COO dispatch 809.

The homepage status strings are signed in dispatch 809 §7 (2026-11-06). They are never
retyped: this script cuts each one from its line of the byte copy in
``tests/fixtures/dispatch_809_sources/`` by a rule that must match exactly one line (and
exactly once in the file), and writes them into the generated module.

The one decision that is not a cut is the P6 word: 809 §7 leaves the slot
``{live | defined}`` for the code to decide. The app repository's ``origin/main``
(``bda96164``) serves no market-state telemetry: no MCP tool among those
``mcp_server/hermes_mcp.py`` registers (lines 76-508), no REST route, no path in the served
OpenAPI document. The only code that names P6 is a seed-question label
(``mcp_server/decision_asset/market_memory_cohort.py:55``). A published taxonomy entry
with no callable surface is "defined" (809 §7 line 39), so :data:`P6_STATUS` is the
extracted word ``defined``; the word itself is still cut from the source, never typed.

Usage:
  python3 scripts/gen_status_copy_text.py           # write the module
  python3 scripts/gen_status_copy_text.py --check   # exit 1 if the module differs

Standard library only.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "dispatch_809_sources"
    / "dispatch_809_20261106.md"
)
MODULE = REPO_ROOT / "scripts" / "status_copy_text.py"

#: (constant, the rule: the signed string inside its wrapper, its line in dispatch 809).
#: The ``**…**``, ``*"…"*`` and ``"…"`` wrappers are not copy and are stripped; every
#: byte inside them is kept.
RULES: tuple[tuple[str, str, int], ...] = (
    ("STATUS_LIVE", r"Three status words: \*\*([a-z]+)\*\* \(callable today\)", 39),
    (
        "STATUS_DEFINED",
        r"\*\*([a-z]+)\*\* \(a published spec or taxonomy entry with no callable surface\)",
        39,
    ),
    ("STATUS_PLANNED", r"· \*\*([a-z]+)\*\*\. Verticals render", 39),
    ("VERTICAL_RECORDS", r'render \*\*register-derived\*\*: "([^"]+)" where n > 0', 39),
    ("VERTICAL_CATALOGUED", r'where n > 0, else \*\*"([^"]+)"\*\*\.', 39),
    ("METRIC_RETIRED", r':445 "([^"]+)" → \*"', 41),
    ("METRIC_LIVE", r':445 "[^"]+" → \*"([^"]+)"\* if it labels the API/register', 41),
    (
        "PRIMITIVES_STATUS_SIGNED",
        r'P4 and P5 are planned" → \*"([^"]+)"\* with the P6 word from the code',
        41,
    ),
)

#: The slot in the signed primitive-status sentence: ``P6 {<word> | <word>}``.
SLOT_RE = re.compile(r"P6 (\{([a-z]+) \| ([a-z]+)\})")

#: Where each constant was cut, for the module's comments.
WHERE: dict[str, str] = {
    "STATUS_LIVE": "809:39 - **live** (callable today)",
    "STATUS_DEFINED": "809:39 - **defined** (a published spec or taxonomy entry ...)",
    "STATUS_PLANNED": "809:39 - **planned**",
    "VERTICAL_RECORDS": '809:39 - Verticals render register-derived: "{n} records" where n > 0',
    "VERTICAL_CATALOGUED": '809:39 - ... else **"catalogued"**',
    "METRIC_RETIRED": '809:41 - the :445 label as served ("In production")',
    "METRIC_LIVE": '809:41 - :445 ... -> *"Live"* if it labels the API/register',
    "PRIMITIVES_STATUS_SIGNED": "809:41 - the :572 sentence as signed, its P6 slot open",
}


class ExtractionError(Exception):
    """A rule did not match exactly one line, or the slot is not in the signed form."""


def extract(raw: str, rule: str) -> tuple[int, str]:
    """``(line number, string)`` for a rule that matches exactly one line, once."""
    hits = [
        (number, match.group(1))
        for number, line in enumerate(raw.split("\n"), start=1)
        if (match := re.search(rule, line))
    ]
    if len(hits) != 1 or len(re.findall(rule, raw)) != 1:
        raise ExtractionError(
            f"rule {rule!r} matched {len(hits)} lines, not exactly one"
        )
    return hits[0]


def constants(raw: str) -> dict[str, str]:
    """Every constant of the module, cut from ``raw`` (the dispatch's text)."""
    out: dict[str, str] = {}
    for name, rule, line in RULES:
        number, text = extract(raw, rule)
        if number != line:
            raise ExtractionError(f"{name}: found on line {number}, expected {line}")
        out[name] = text
    slot = SLOT_RE.search(out["PRIMITIVES_STATUS_SIGNED"])
    if slot is None or len(SLOT_RE.findall(out["PRIMITIVES_STATUS_SIGNED"])) != 1:
        raise ExtractionError("the signed sentence does not carry one P6 slot")
    options = (slot.group(2), slot.group(3))
    if options != (out["STATUS_LIVE"], out["STATUS_DEFINED"]):
        raise ExtractionError(
            f"the P6 slot offers {options}, not the live/defined words"
        )
    out["P6_SLOT"] = slot.group(1)
    # The code decides the word (module docstring): no callable surface -> "defined".
    out["P6_STATUS"] = out["STATUS_DEFINED"]
    out["PRIMITIVES_STATUS"] = out["PRIMITIVES_STATUS_SIGNED"].replace(
        out["P6_SLOT"], out["P6_STATUS"], 1
    )
    return out


def _literal(text: str) -> str:
    if '"' in text or "\\" in text or "\n" in text:
        raise ExtractionError(f"cannot write {text!r} as a plain double-quoted literal")
    return f'"{text}"'


def _assign(name: str, text: str) -> list[str]:
    one = f"{name}: Final[str] = {_literal(text)}"
    if len(one) <= 88:
        return [one]
    # Split at spaces into implicitly concatenated literals; every byte is kept.
    parts: list[str] = []
    current = ""
    for word in re.findall(r"\S+\s*", text):
        if current and len(current) + len(word) > 78:
            parts.append(current)
            current = ""
        current += word
    parts.append(current)
    if "".join(parts) != text:
        raise ExtractionError(f"{name}: the split lost bytes")
    return [f"{name}: Final[str] = (", *(f"    {_literal(p)}" for p in parts), ")"]


HEADER = '''"""The homepage status strings, verbatim (GENERATED - never edit by hand).

Extracted programmatically, never retyped, by ``scripts/gen_status_copy_text.py`` from the
byte copy ``tests/fixtures/dispatch_809_sources/dispatch_809_20261106.md`` of COO dispatch
809 (2026-11-06, pin ``c7271feef01379d7``), section 7:

* line 39 (the rule): the three status words ``STATUS_LIVE``, ``STATUS_DEFINED`` and
  ``STATUS_PLANNED``, and the two register-derived vertical badges ``VERTICAL_RECORDS``
  (``{n}`` is the vertical's count of records on the register) and
  ``VERTICAL_CATALOGUED``;
* line 41 (phronesisintel.com): the ``:445`` metric label as it was served
  (``METRIC_RETIRED``) and the word that replaces it where it labels the API/register
  (``METRIC_LIVE``); the ``:572`` primitive-status sentence as signed, its P6 slot open
  (``PRIMITIVES_STATUS_SIGNED``).

``PRIMITIVES_STATUS`` is the signed sentence with its one ``P6_SLOT`` replaced by
``P6_STATUS``, the word the code supports (``STATUS_DEFINED``: no callable market-state
surface on the app's ``origin/main``; see the generator's docstring). Every other byte is
809's. ``scripts/test_status_strings.py`` re-derives every constant and asserts equality.
"""

from __future__ import annotations

from typing import Final

'''

ORDER = (
    "STATUS_LIVE",
    "STATUS_DEFINED",
    "STATUS_PLANNED",
    "VERTICAL_RECORDS",
    "VERTICAL_CATALOGUED",
    "METRIC_RETIRED",
    "METRIC_LIVE",
    "PRIMITIVES_STATUS_SIGNED",
    "P6_SLOT",
    "P6_STATUS",
    "PRIMITIVES_STATUS",
)


def render(values: dict[str, str]) -> str:
    lines = [HEADER.rstrip("\n"), "", "__all__ = ["]
    lines += [f'    "{name}",' for name in sorted(ORDER)]
    lines += ["]", ""]
    for name in ORDER:
        if name in WHERE:
            lines.append(f"#: {WHERE[name]}")
        elif name == "P6_SLOT":
            lines.append("#: the slot in PRIMITIVES_STATUS_SIGNED the code decides")
        elif name == "P6_STATUS":
            lines.append(
                "#: the word the code supports for P6: STATUS_DEFINED, cut at 809:39"
            )
        else:
            lines.append(
                "#: the sentence the page renders: the signed one, P6_SLOT -> P6_STATUS"
            )
        lines += _assign(name, values[name])
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    args = argv[1:]
    if args not in ([], ["--check"]):
        print(__doc__)
        return 2
    raw = SOURCE.read_bytes().decode("utf-8")
    text = render(constants(raw))
    if args == ["--check"]:
        current = MODULE.read_bytes().decode("utf-8").replace("\r\n", "\n")
        if current != text:
            print(f"{MODULE.name}: differs from the generator's output; regenerate it")
            return 1
        print(f"{MODULE.name}: equals the generator's output")
        return 0
    MODULE.write_bytes(text.encode("utf-8"))
    print(f"{MODULE.name}: written ({len(ORDER)} constants)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
