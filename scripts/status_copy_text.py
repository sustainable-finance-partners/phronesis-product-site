"""The homepage status strings, verbatim (GENERATED - never edit by hand).

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

__all__ = [
    "METRIC_LIVE",
    "METRIC_RETIRED",
    "P6_SLOT",
    "P6_STATUS",
    "PRIMITIVES_STATUS",
    "PRIMITIVES_STATUS_SIGNED",
    "STATUS_DEFINED",
    "STATUS_LIVE",
    "STATUS_PLANNED",
    "VERTICAL_CATALOGUED",
    "VERTICAL_RECORDS",
]

#: 809:39 - **live** (callable today)
STATUS_LIVE: Final[str] = "live"
#: 809:39 - **defined** (a published spec or taxonomy entry ...)
STATUS_DEFINED: Final[str] = "defined"
#: 809:39 - **planned**
STATUS_PLANNED: Final[str] = "planned"
#: 809:39 - Verticals render register-derived: "{n} records" where n > 0
VERTICAL_RECORDS: Final[str] = "{n} records"
#: 809:39 - ... else **"catalogued"**
VERTICAL_CATALOGUED: Final[str] = "catalogued"
#: 809:41 - the :445 label as served ("In production")
METRIC_RETIRED: Final[str] = "In production"
#: 809:41 - :445 ... -> *"Live"* if it labels the API/register
METRIC_LIVE: Final[str] = "Live"
#: 809:41 - the :572 sentence as signed, its P6 slot open
PRIMITIVES_STATUS_SIGNED: Final[str] = (
    "P3 live; P1 identity live, mandate verification planned; P2 honest-empty "
    "(UNRATED until the observation substrate ships); P6 {live | defined} ; P4 and "
    "P5 planned."
)
#: the slot in PRIMITIVES_STATUS_SIGNED the code decides
P6_SLOT: Final[str] = "{live | defined}"
#: the word the code supports for P6: STATUS_DEFINED, cut at 809:39
P6_STATUS: Final[str] = "defined"
#: the sentence the page renders: the signed one, P6_SLOT -> P6_STATUS
PRIMITIVES_STATUS: Final[str] = (
    "P3 live; P1 identity live, mandate verification planned; P2 honest-empty "
    "(UNRATED until the observation substrate ships); P6 defined ; P4 and P5 "
    "planned."
)
