#!/usr/bin/env python3
"""The homepage status strings render COO dispatch 809 §7 exactly, and the vertical
badges are register-derived.

* The byte copy of dispatch 809 (``tests/fixtures/dispatch_809_sources/``) still hashes
  to its recorded digest, and its README records the same bytes and digest.
* Every constant of ``status_copy_text`` is re-derived from that copy by an extraction
  independent of the generator's, and the module equals the generator's output.
* The P6 word is the one the code supports (``defined``), put into the signed sentence's
  one slot; every other byte of the sentence is 809's.
* The home page renders them: the register's label (``Live``), the primitive-status
  sentence, the thirteen badges in the register-derived forms, and one JSON-LD ``Offer``
  (the API, free reads; no mint offer while the price list shows every mint in build).
* ``scripts/refresh_count.py`` derives the badges offline from a fixture payload: the
  rows the register count is made over, by subject, refusing when they do not number
  ``forecast_count`` or the markup is not found once each.

Desk-only checks (skipped, and saying so, elsewhere): the OneDrive original is the
copy's bytes; with ``PHRONESIS_API_TREE`` (a clone of the app repository; revision
``PHRONESIS_API_REV``, default ``HEAD``) the subject map is the app's
``_VERTICAL_METADATA`` and the app registers no market-state MCP tool.

Run: ``python3 scripts/test_status_strings.py``. Standard library only.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen_status_copy_text as gen  # noqa: E402
import refresh_count  # noqa: E402
import status_copy_text as text  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE = REPO_ROOT / "site"
SOURCES = REPO_ROOT / "tests" / "fixtures" / "dispatch_809_sources"
D809 = SOURCES / "dispatch_809_20261106.md"
D809_BYTES = 15277
D809_SHA256 = "c7271feef01379d7cd103a4a56df0ebb4bef4fa50d30af5f098ed1daceed2ae0"
APPARATUS = Path(
    r"C:\Users\John Stinehour\OneDrive\Desktop\Sustainable Finance Partners"
    r"\Sustainable Finance Partners Business Apparatus\00_Operating_Model"
)
ORIGINAL_GLOB = "CCO_DISPATCH_809_*.md"
API_TREE_ENV = "PHRONESIS_API_TREE"
API_REV_ENV = "PHRONESIS_API_REV"
#: The visible hero line the JSON-LD Offer's description is taken from (no new copy).
HERO_READ_LINE = "Read the record free. Minting from $1"


def read_site(rel: str) -> str:
    """A published file as text with LF line ends (a Windows checkout writes CRLF)."""
    return (SITE / rel).read_bytes().decode("utf-8").replace("\r\n", "\n")


def source_line(number: int) -> str:
    return D809.read_bytes().decode("utf-8").split("\n")[number - 1]


def quoted(segment: str) -> list[str]:
    return re.findall(r'"([^"]+)"', segment)


class _Paragraphs(HTMLParser):
    """The text of every ``<p>`` on a page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.paragraphs: list[str] = []
        self._buf: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "p":
            self._buf = []

    def handle_data(self, data: str) -> None:
        if self._buf is not None:
            self._buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "p" and self._buf is not None:
            self.paragraphs.append("".join(self._buf))
            self._buf = None


class _LdJson(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.blocks: list[str] = []
        self._buf: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and dict(attrs).get("type") == "application/ld+json":
            self._buf = []

    def handle_data(self, data: str) -> None:
        if self._buf is not None:
            self._buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._buf is not None:
            self.blocks.append("".join(self._buf))
            self._buf = None


# ── the source and the generated module ──────────────────────────────────────


class SourceTests(unittest.TestCase):
    def test_the_copy_is_the_bytes_the_strings_were_cut_from(self) -> None:
        raw = D809.read_bytes()
        self.assertEqual(len(raw), D809_BYTES)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), D809_SHA256)
        self.assertNotIn(b"\r", raw)
        # The house pin (CRLF->LF, first 16) is the pin 809 was received under.
        self.assertEqual(
            hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()[:16],
            "c7271feef01379d7",
        )

    def test_the_readme_records_these_bytes(self) -> None:
        readme = (SOURCES / "README.md").read_text(encoding="utf-8")
        row = f"| `{D809.name}` |"
        self.assertEqual(readme.count(row), 1)
        line = next(x for x in readme.splitlines() if x.startswith(row))
        self.assertIn(f"| {D809_BYTES} | `{D809_SHA256}` |", line)

    def test_the_status_words_are_809_line_39s(self) -> None:
        line = source_line(39)
        segment = line.split("Three status words: ", 1)[1].split(
            " Verticals render", 1
        )[0]
        self.assertEqual(
            re.findall(r"\*\*([^*]+)\*\*", segment),
            [text.STATUS_LIVE, text.STATUS_DEFINED, text.STATUS_PLANNED],
        )

    def test_the_badge_forms_are_809_line_39s(self) -> None:
        tail = source_line(39).split("Verticals render **register-derived**: ", 1)[1]
        self.assertEqual(
            quoted(tail), [text.VERTICAL_RECORDS, text.VERTICAL_CATALOGUED]
        )

    def test_the_metric_label_is_809_line_41s(self) -> None:
        segment = source_line(41).split(":445 ", 1)[1].split(" \u00b7 ", 1)[0]
        self.assertEqual(quoted(segment), [text.METRIC_RETIRED, text.METRIC_LIVE])
        self.assertIn("if it labels the API/register", segment)

    def test_the_primitive_sentence_is_809_line_41s(self) -> None:
        segment = source_line(41).split(":572 ", 1)[1].split(" \u00b7 ", 1)[0]
        old, new = quoted(segment)
        self.assertTrue(old.startswith("P1, P2, P3, P6 live on production today"))
        self.assertEqual(new, text.PRIMITIVES_STATUS_SIGNED)

    def test_the_p6_word_fills_the_one_slot_and_nothing_else_moves(self) -> None:
        signed = text.PRIMITIVES_STATUS_SIGNED
        self.assertEqual(signed.count(text.P6_SLOT), 1)
        self.assertEqual(
            text.P6_SLOT, "{" + f"{text.STATUS_LIVE} | {text.STATUS_DEFINED}" + "}"
        )
        self.assertEqual(text.P6_STATUS, text.STATUS_DEFINED)
        before, after = signed.split(text.P6_SLOT)
        self.assertEqual(text.PRIMITIVES_STATUS, before + text.P6_STATUS + after)

    def test_the_module_is_the_generators_output(self) -> None:
        module = (REPO_ROOT / "scripts" / "status_copy_text.py").read_bytes()
        expected = gen.render(gen.constants(D809.read_bytes().decode("utf-8")))
        self.assertEqual(module.decode("utf-8").replace("\r\n", "\n"), expected)

    def test_a_rule_that_does_not_match_once_refuses(self) -> None:
        raw = D809.read_bytes().decode("utf-8")
        with self.assertRaises(gen.ExtractionError):
            gen.constants(raw.replace("Three status words: ", "Status words: ", 1))
        doubled = raw.replace(
            source_line(41), source_line(41) + "\n" + source_line(41), 1
        )
        with self.assertRaises(gen.ExtractionError):
            gen.constants(doubled)

    @unittest.skipUnless(
        APPARATUS.is_dir(), "the OneDrive original is on the desk only"
    )
    def test_the_original_is_the_copys_bytes(self) -> None:
        originals = sorted(APPARATUS.glob(ORIGINAL_GLOB))
        self.assertEqual(len(originals), 1, originals)
        self.assertEqual(
            hashlib.sha256(originals[0].read_bytes()).hexdigest(), D809_SHA256
        )


def _api_file(path: str) -> str:
    root = os.environ.get(API_TREE_ENV)
    if not root:
        raise unittest.SkipTest(
            f"{API_TREE_ENV} is not set: no clone of the app repository"
        )
    rev = os.environ.get(API_REV_ENV) or "HEAD"
    out = subprocess.run(
        ["git", "-C", root, "show", f"{rev}:{path}"], check=True, capture_output=True
    ).stdout
    return out.decode("utf-8")


class AppCodeTests(unittest.TestCase):
    """Desk-only: the subject map and the P6 word against the app's code."""

    def test_the_subject_map_is_the_apps_vertical_metadata(self) -> None:
        route = _api_file("mcp_server/discovery/route.py")
        block = route.split("_VERTICAL_METADATA: tuple[dict[str, Any], ...] = (", 1)[1]
        block = block.split("\n)\n", 1)[0]
        pairs = re.findall(
            r'"id": "V(\d+)",.*?"subject": "([a-z_]+)"', block, flags=re.S
        )
        app = [(f"V#{n}", subject) for n, subject in pairs]
        self.assertEqual(app, list(refresh_count.VERTICAL_SUBJECTS[1:]))
        self.assertEqual(refresh_count.VERTICAL_SUBJECTS[0], ("V#0", None))

    def test_the_app_registers_no_market_state_tool(self) -> None:
        hermes = _api_file("mcp_server/hermes_mcp.py")
        tools = re.findall(r'@mcp\.tool\(\s*name="([a-z_]+)"', hermes)
        self.assertIn("forecast_submit", tools)
        self.assertIn("query_scorecard", tools)
        for name in tools:
            for word in ("market", "telemetry", "state"):
                with self.subTest(tool=name, word=word):
                    self.assertNotIn(word, name)

    def test_the_subject_map_is_the_one_the_verticals_page_dates_use(self) -> None:
        # test_license_set.VERTICAL_SUBJECTS (803 ruling 9: a record's vertical is
        # value.intake_payload.subject) dates /verticals; the badges use the same map.
        import test_license_set

        theirs = {
            f"V#{k[1:]}": v for k, v in test_license_set.VERTICAL_SUBJECTS.items()
        }
        ours = {v: s for v, s in refresh_count.VERTICAL_SUBJECTS if s is not None}
        self.assertEqual(ours, theirs)


# ── the home page ─────────────────────────────────────────────────────────────


class HomepageTests(unittest.TestCase):
    home: str

    @classmethod
    def setUpClass(cls) -> None:
        cls.home = read_site("index.html")

    def test_the_register_label_is_live(self) -> None:
        self.assertEqual(
            self.home.count(
                f'<span class="metric-value">{text.METRIC_LIVE}</span>\n'
                '          <span class="metric-label">Market Memory v1</span>'
            ),
            1,
        )
        self.assertNotIn(text.METRIC_RETIRED.casefold(), self.home.casefold())

    def test_the_primitive_status_sentence_is_809s_with_p6_decided(self) -> None:
        parser = _Paragraphs()
        parser.feed(self.home)
        self.assertEqual(parser.paragraphs.count(text.PRIMITIVES_STATUS), 1)
        self.assertNotIn(text.P6_SLOT, self.home)
        self.assertNotIn("live on production", self.home.casefold())

    def _badges(self) -> list[re.Match[str]]:
        return list(refresh_count.BADGE_RE.finditer(self.home))

    def test_thirteen_badges_in_order_each_in_a_register_derived_form(self) -> None:
        badges = self._badges()
        self.assertEqual(
            [m.group(4) for m in badges],
            [v for v, _ in refresh_count.VERTICAL_SUBJECTS],
        )
        self.assertEqual(self.home.count(refresh_count.BADGE_MARK), 13)
        records = re.compile(
            re.escape(text.VERTICAL_RECORDS).replace(r"\{n\}", r"([1-9]\d*)")
        )
        for m in badges:
            with self.subTest(vertical=m.group(4)):
                if m.group(2) == refresh_count.CATALOGUED_CLASS:
                    self.assertEqual(m.group(6), text.VERTICAL_CATALOGUED)
                else:
                    self.assertEqual(m.group(2), refresh_count.RECORDS_CLASS)
                    self.assertIsNotNone(records.fullmatch(m.group(6)))
        self.assertEqual(
            badges[0].group(6), text.VERTICAL_CATALOGUED
        )  # V#0: no subject

    def test_the_badges_count_no_more_than_the_register(self) -> None:
        span = refresh_count.SPAN_RE.search(self.home)
        assert span is not None
        listed = refresh_count.LIST_RE.search(self.home)
        assert listed is not None
        self.assertEqual(listed.group(2), span.group(2))  # one as-of for both
        total = sum(
            int(m.group(6).split()[0])
            for m in self._badges()
            if m.group(2) == refresh_count.RECORDS_CLASS
        )
        self.assertLessEqual(total, int(span.group(4)))

    def test_the_badge_classes_are_styled(self) -> None:
        for css in (refresh_count.RECORDS_CLASS, refresh_count.CATALOGUED_CLASS):
            with self.subTest(css=css):
                self.assertEqual(self.home.count(f".vertical-status.{css} {{"), 1)

    def _ld(self) -> list[dict[str, Any]]:
        parser = _LdJson()
        parser.feed(self.home)
        return [json.loads(block) for block in parser.blocks]

    def test_one_offer_remains_the_api_with_free_reads(self) -> None:
        blocks = self._ld()
        services = [b for b in blocks if b.get("@type") == "Service"]
        self.assertEqual(len(services), 1)
        service = services[0]
        self.assertNotIn("hasOfferCatalog", service)
        offer = service["offers"]
        self.assertEqual(offer["@type"], "Offer")
        self.assertEqual(offer["name"], "Phronesis API")
        self.assertEqual(offer["url"], "https://api.phronesisintel.com")
        pricing = json.loads(read_site("pricing.json"))
        self.assertEqual(offer["priceCurrency"], pricing["currency"])
        free_reads = [
            row
            for row in pricing["agent_schedule"]
            if row["request"].startswith("read_") and row.get("availability") == "live"
        ]
        self.assertEqual(
            [str(row["price_usd"]) for row in free_reads], [offer["price"]]
        )
        # The description is the page's own hero line, not new copy.
        self.assertTrue(HERO_READ_LINE.startswith(offer["description"]))
        self.assertIn(HERO_READ_LINE, self.home)
        self.assertNotIn("LIVE.", json.dumps(blocks))

    def test_no_mint_offer_while_the_price_list_shows_minting_in_build(self) -> None:
        pricing = json.loads(read_site("pricing.json"))
        mints = [
            r for r in pricing["agent_schedule"] if r["request"].startswith("mint_")
        ]
        self.assertTrue(mints)
        live = [r["request"] for r in mints if r.get("availability") == "live"]
        # 809 §7: "minting where the price list shows it live". If this fails, a mint
        # row went live: the API Offer gains it (and this test its expectation).
        self.assertEqual(live, [])
        for tier in pricing["tiers"]:
            avail = tier.get("includes", {}).get(
                "mints_standard_per_month_availability"
            )
            with self.subTest(tier=tier["id"]):
                self.assertIn(avail, (None, "in_build"))


# ── the refresh, offline ──────────────────────────────────────────────────────


def _row(subject: str | None, record_class: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"intent": "x"}
    if subject is not None:
        payload["subject"] = subject
    row: dict[str, Any] = {"key": "FC-X", "value": {"intake_payload": payload}}
    if record_class is not None:
        row["record_class"] = record_class
    return row


def _payload(rows: list[dict[str, Any]], count: int | None = None) -> dict[str, Any]:
    counted = sum(1 for r in rows if r.get("record_class") in (None, "forecast"))
    return {
        "aggregate_stats": {"forecast_count": counted if count is None else count},
        "metadata": {"generated_at": "2026-11-06T04:11:20Z"},
        "forecasts": rows,
    }


#: Energy 3 (one of them a 809 §5 ``forecast`` row), climate 1, one intersection record,
#: a capability_test and a withdrawn row that no count includes.
ROWS: list[dict[str, Any]] = [
    _row("energy"),
    _row("energy"),
    _row("energy", "forecast"),
    _row("climate"),
    _row("intersection"),
    _row("energy", "capability_test"),
    _row("quantum", "withdrawn"),
]
TODAY = dt.date(2026, 11, 6)


class VerticalRefreshTests(unittest.TestCase):
    home: str

    @classmethod
    def setUpClass(cls) -> None:
        cls.home = read_site("index.html")

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.index = self.dir / "index.html"
        self.index.write_bytes(self.home.encode("utf-8"))
        no_network = mock.patch.object(
            refresh_count, "fetch", side_effect=AssertionError("network used in a test")
        )
        no_network.start()
        self.addCleanup(no_network.stop)

    def _texts(self, page: str) -> dict[str, tuple[str, str]]:
        return {
            m.group(4): (m.group(2), m.group(6))
            for m in refresh_count.BADGE_RE.finditer(page)
        }

    def test_the_subject_map_names_the_thirteen_badges_once(self) -> None:
        ids = [v for v, _ in refresh_count.VERTICAL_SUBJECTS]
        self.assertEqual(ids, [f"V#{n}" for n in range(13)])
        subjects = [s for _, s in refresh_count.VERTICAL_SUBJECTS if s is not None]
        self.assertEqual(len(subjects), len(set(subjects)), subjects)
        self.assertEqual(text.VERTICAL_RECORDS.count("{n}"), 1)

    def test_counts_the_rows_the_register_count_is_made_over_by_subject(self) -> None:
        per_badge, unmapped = refresh_count.vertical_counts(_payload(ROWS), 5)
        self.assertEqual(per_badge["V#1"], 3)
        self.assertEqual(per_badge["V#4"], 1)
        self.assertEqual(per_badge["V#12"], 0)  # the withdrawn row counts nowhere
        self.assertEqual(per_badge["V#0"], 0)
        self.assertEqual(unmapped, {"intersection": 1})
        self.assertEqual(sum(per_badge.values()) + sum(unmapped.values()), 5)

    def test_refuses_when_the_rows_do_not_number_the_count(self) -> None:
        cases: dict[str, tuple[Any, int]] = {
            "the count one more": (_payload(ROWS), 6),
            "the count one fewer": (_payload(ROWS), 4),
            "no forecasts": ({"aggregate_stats": {"forecast_count": 5}}, 5),
            "forecasts not a list": ({"forecasts": {"FC-X": {}}}, 5),
            "a row not an object": (
                {**_payload(ROWS), "forecasts": [*ROWS, "FC-Y"]},
                5,
            ),
        }
        for name, (data, total) in cases.items():
            with self.subTest(case=name):
                with self.assertRaises(refresh_count.Refused):
                    refresh_count.vertical_counts(data, total)
        # Through refresh: the payload's own forecast_count is the total.
        with self.assertRaises(refresh_count.Refused):
            refresh_count.refresh(self.index, _payload(ROWS, 6), TODAY, verticals=True)

    def test_rewrites_the_badges_and_the_lists_date_and_no_other_byte(self) -> None:
        lines = refresh_count.refresh(self.index, _payload(ROWS), TODAY, verticals=True)
        page = self.index.read_bytes().decode("utf-8")
        badges = self._texts(page)
        self.assertEqual(
            badges["V#1"], ("records", text.VERTICAL_RECORDS.replace("{n}", "3"))
        )
        self.assertEqual(
            badges["V#4"], ("records", text.VERTICAL_RECORDS.replace("{n}", "1"))
        )
        for vid in ("V#0", "V#2", "V#3", "V#12"):
            self.assertEqual(badges[vid], ("catalogued", text.VERTICAL_CATALOGUED))
        self.assertIn(
            "note: records whose subject names no vertical: intersection 1", lines
        )
        self.assertEqual(lines[-1], "index.html: written")

        # Outside the count span, the <time>, the list's opening tag and the badges,
        # every byte is the page's.
        def strip(p: str) -> str:
            for rx in (
                refresh_count.SPAN_RE,
                refresh_count.TIME_RE,
                refresh_count.LIST_RE,
                refresh_count.BADGE_RE,
            ):
                p = rx.sub("<X>", p)
            return p

        self.assertEqual(strip(page), strip(self.home))
        listed = refresh_count.LIST_RE.search(page)
        assert listed is not None
        self.assertEqual(listed.group(2), "2026-11-06")

    def test_a_refused_vertical_read_writes_nothing_not_even_the_count(self) -> None:
        with self.assertRaises(refresh_count.Refused):
            refresh_count.refresh(self.index, _payload(ROWS, 9), TODAY, verticals=True)
        self.assertEqual(self.index.read_bytes().decode("utf-8"), self.home)

    def test_refuses_when_the_list_or_a_badge_is_not_found_once(self) -> None:
        first = refresh_count.BADGE_RE.search(self.home)
        assert first is not None
        for name, page in {
            "list missing": self.home.replace('id="vertical-records" ', "", 1),
            "badge missing": self.home.replace(
                'data-vertical="V#7"', 'data-vertical="V#77"', 1
            ),
            "badge twice": self.home.replace(first.group(0), first.group(0) * 2, 1),
            "a bare badge": self.home.replace(
                "</ul>", '<span class="vertical-status live">Live</span></ul>', 1
            ),
        }.items():
            with self.subTest(case=name):
                self.index.write_bytes(page.encode("utf-8"))
                with self.assertRaises(refresh_count.Refused):
                    refresh_count.refresh(
                        self.index, _payload(ROWS), TODAY, verticals=True
                    )
                self.assertEqual(self.index.read_bytes().decode("utf-8"), page)

    def test_keeps_crlf_line_ends(self) -> None:
        self.index.write_bytes(self.home.replace("\n", "\r\n").encode("utf-8"))
        refresh_count.refresh(self.index, _payload(ROWS), TODAY, verticals=True)
        raw = self.index.read_bytes()
        self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"))

    def test_current_values_write_nothing(self) -> None:
        refresh_count.refresh(self.index, _payload(ROWS), TODAY, verticals=True)
        once = self.index.read_bytes()
        lines = refresh_count.refresh(self.index, _payload(ROWS), TODAY, verticals=True)
        self.assertEqual(lines[-1], "index.html: already current; nothing written")
        self.assertEqual(self.index.read_bytes(), once)

    def test_check_passes_a_current_page_and_one_behind_the_register(self) -> None:
        refresh_count.refresh(self.index, _payload(ROWS), TODAY, verticals=True)
        before = self.index.read_bytes()
        ok, lines = refresh_count.check(self.index, _payload(ROWS), TODAY)
        self.assertTrue(ok)
        self.assertEqual(
            lines, ["index.html: OK, current with the register as of 2026-11-06"]
        )
        ok, lines = refresh_count.check(
            self.index, _payload([*ROWS, _row("energy")]), TODAY
        )
        self.assertTrue(ok)
        self.assertIn("WARN V#1: the page states 3, the register 4", lines)
        self.assertIn("WARN forecast_count: the page states 5, the register 6", lines)
        self.assertEqual(self.index.read_bytes(), before)  # --check writes nothing

    def test_check_fails_a_page_above_the_register(self) -> None:
        refresh_count.refresh(self.index, _payload(ROWS), TODAY, verticals=True)
        # A badge edited by hand above its register count (the mutation the offline
        # page tests cannot see), and a register that lost a record.
        page = self.index.read_bytes().decode("utf-8")
        edited = page.replace(
            'data-vertical="V#4">' + text.VERTICAL_RECORDS.replace("{n}", "1"),
            'data-vertical="V#4">' + text.VERTICAL_RECORDS.replace("{n}", "2"),
            1,
        )
        self.assertNotEqual(edited, page)
        self.index.write_bytes(edited.encode("utf-8"))
        ok, lines = refresh_count.check(self.index, _payload(ROWS), TODAY)
        self.assertFalse(ok)
        self.assertEqual(lines[0], "OVERCLAIM V#4: the page states 2, the register 1")
        self.assertEqual(lines[-1], "index.html: FAIL (1 above the register)")
        self.index.write_bytes(page.encode("utf-8"))
        ok, lines = refresh_count.check(self.index, _payload(ROWS[1:]), TODAY)
        self.assertFalse(ok)
        self.assertIn(
            "OVERCLAIM forecast_count: the page states 5, the register 4", lines
        )
        self.assertIn("OVERCLAIM V#1: the page states 3, the register 2", lines)

    def test_check_refuses_a_badge_in_neither_form(self) -> None:
        refresh_count.refresh(self.index, _payload(ROWS), TODAY, verticals=True)
        page = self.index.read_bytes().decode("utf-8")
        for bad in ("three records", "3 record", ""):
            with self.subTest(text=bad):
                self.index.write_bytes(
                    page.replace(
                        'data-vertical="V#1">'
                        + text.VERTICAL_RECORDS.replace("{n}", "3"),
                        f'data-vertical="V#1">{bad}',
                        1,
                    ).encode("utf-8")
                )
                with self.assertRaises(refresh_count.Refused):
                    refresh_count.check(self.index, _payload(ROWS), TODAY)

    def test_the_command_line_check_exit_status(self) -> None:
        refresh_count.refresh(self.index, _payload(ROWS), TODAY, verticals=True)
        current = self.dir / "current.json"
        current.write_text(json.dumps(_payload(ROWS)), encoding="utf-8")
        lost = self.dir / "lost.json"
        lost.write_text(json.dumps(_payload(ROWS[1:])), encoding="utf-8")
        with (
            mock.patch.object(refresh_count, "INDEX", self.index),
            mock.patch("builtins.print"),
        ):
            codes = [
                refresh_count.main(
                    ["refresh_count.py", "--check", "--from-file", str(p)]
                )
                for p in (current, lost)
            ]
        self.assertEqual(codes, [0, 1])

    def test_the_command_line_refreshes_the_badges(self) -> None:
        source = self.dir / "scorecard.json"
        source.write_text(json.dumps(_payload(ROWS)), encoding="utf-8")
        out: list[str] = []
        with (
            mock.patch.object(refresh_count, "INDEX", self.index),
            mock.patch(
                "builtins.print",
                side_effect=lambda *a: out.append(" ".join(map(str, a))),
            ),
        ):
            rc = refresh_count.main(["refresh_count.py", "--from-file", str(source)])
        self.assertEqual(rc, 0)
        page = self.index.read_bytes().decode("utf-8")
        self.assertEqual(
            self._texts(page)["V#1"][1], text.VERTICAL_RECORDS.replace("{n}", "3")
        )
        self.assertTrue(any(line.startswith("V#1: ") for line in out))


def main(argv: list[str]) -> int:
    if argv[1:]:
        print(__doc__)
        return 2
    result = unittest.main(module=__name__, argv=[argv[0], "-v"], exit=False).result
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
