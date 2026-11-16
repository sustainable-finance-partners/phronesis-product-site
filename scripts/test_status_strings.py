#!/usr/bin/env python3
"""The homepage status strings render COO dispatches 809 §7 and 810 §4 exactly, and the
vertical badges are register-derived.

* The byte copy of dispatch 809 (``tests/fixtures/dispatch_809_sources/``) still hashes
  to its recorded digest, and its README records the same bytes and digest.
* Every constant of ``status_copy_text`` is re-derived from that copy by an extraction
  independent of the generator's, and the module equals the generator's output.
* The P6 word is the one the code supports (``defined``). The signed sentence's P6 piece
  is 810's re-signed ``P6 defined;``, and every other byte of the sentence is 809's.
* The byte copy of dispatch 810 (``tests/fixtures/dispatch_810_sources/``) hashes to its
  digest, and the four strings its line 25 signs are re-derived from it: the "series live"
  badge, the singular "1 record", the re-signed P6 piece and the P6 card's description.
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
SOURCES_810 = REPO_ROOT / "tests" / "fixtures" / "dispatch_810_sources"
D810 = SOURCES_810 / "dispatch_810_20261106.md"
D810_BYTES = 9288
D810_SHA256 = "6812b2b25843eef76f5388a67ed21a71ba51c418b3f5ad386a19dbe3a8794361"
ORIGINAL_GLOB_810 = "CCO_DISPATCH_810_*.md"
API_TREE_ENV = "PHRONESIS_API_TREE"
API_REV_ENV = "PHRONESIS_API_REV"
#: The visible hero line the JSON-LD Offer's description is taken from (no new copy).
HERO_READ_LINE = "Read the record free. Minting from $1"


def read_site(rel: str) -> str:
    """A published file as text with LF line ends (a Windows checkout writes CRLF)."""
    return (SITE / rel).read_bytes().decode("utf-8").replace("\r\n", "\n")


def source_line(number: int) -> str:
    return D809.read_bytes().decode("utf-8").split("\n")[number - 1]


def source_line_810(number: int) -> str:
    return D810.read_bytes().decode("utf-8").split("\n")[number - 1]


def _both_sources() -> tuple[str, str]:
    return D809.read_bytes().decode("utf-8"), D810.read_bytes().decode("utf-8")


#: (constant, its lettered item in 810 line 25, the item's one quoted string).
ITEMS_810: tuple[tuple[str, str], ...] = (
    ("VERTICAL_SERIES_LIVE", "(a)"),
    ("VERTICAL_RECORD_ONE", "(b)"),
    ("P6_RESIGNED", "(c)"),
    ("P6_CARD_DESCRIPTION", "(e)"),
)


def item_810(letter: str) -> str:
    """The text of one lettered item of 810 line 25, up to the next item."""
    line = source_line_810(25)
    start = line.index(f" {letter} ") + len(letter) + 2
    nxt = [line.find(f" ({c}) ", start) for c in "abcdef"]
    ends = [i for i in nxt if i > start]
    return line[start : min(ends)] if ends else line[start:]


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

    def test_the_p6_piece_is_810s_and_nothing_else_moves(self) -> None:
        signed = text.PRIMITIVES_STATUS_SIGNED
        self.assertEqual(signed.count(text.P6_SLOT), 1)
        self.assertEqual(
            text.P6_SLOT, "{" + f"{text.STATUS_LIVE} | {text.STATUS_DEFINED}" + "}"
        )
        self.assertEqual(text.P6_STATUS, text.STATUS_DEFINED)
        # 809 signed "P6 {live | defined} ;"; 810 re-signs the piece "P6 defined;".
        piece = f"P6 {text.P6_SLOT} ;"
        self.assertEqual(signed.count(piece), 1)
        self.assertEqual(text.P6_RESIGNED, f"P6 {text.P6_STATUS};")
        before, after = signed.split(piece)
        self.assertEqual(text.PRIMITIVES_STATUS, before + text.P6_RESIGNED + after)
        self.assertNotIn(" ;", text.PRIMITIVES_STATUS)

    def test_the_module_is_the_generators_output(self) -> None:
        module = (REPO_ROOT / "scripts" / "status_copy_text.py").read_bytes()
        expected = gen.render(gen.constants(*_both_sources()))
        self.assertEqual(module.decode("utf-8").replace("\r\n", "\n"), expected)

    def test_a_rule_that_does_not_match_once_refuses(self) -> None:
        raw, raw_810 = _both_sources()
        with self.assertRaises(gen.ExtractionError):
            gen.constants(raw.replace("Three status words: ", "Status words: ", 1), raw_810)
        doubled = raw.replace(
            source_line(41), source_line(41) + "\n" + source_line(41), 1
        )
        with self.assertRaises(gen.ExtractionError):
            gen.constants(doubled, raw_810)
        line = source_line_810(25)
        for name, broken in {
            "810 line doubled": raw_810.replace(line, line + "\n" + line, 1),
            "a third badge renamed": raw_810.replace(
                '**"series live"** —', '**"series-live"** —', 1
            ),
            "the three words out of order": raw_810.replace(
                '"series live" · "catalogued"*', '"catalogued" · "series live"*', 1
            ),
            "a singular that is not the plural's": raw_810.replace(
                '*"1 record"*', '*"1 recorded"*', 1
            ),
            "a P6 piece that is not P6 <word>;": raw_810.replace(
                '*"P6 defined;"***', '*"P6 live;"***', 1
            ),
        }.items():
            with self.subTest(case=name):
                self.assertNotEqual(broken, raw_810)
                with self.assertRaises(gen.ExtractionError):
                    gen.constants(raw, broken)

    def test_the_810_copy_is_the_bytes_the_strings_were_cut_from(self) -> None:
        raw = D810.read_bytes()
        self.assertEqual(len(raw), D810_BYTES)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), D810_SHA256)
        self.assertNotIn(b"\r", raw)
        self.assertEqual(
            hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()[:16],
            "6812b2b25843eef7",
        )
        readme = (SOURCES_810 / "README.md").read_text(encoding="utf-8")
        row = f"| `{D810.name}` |"
        self.assertEqual(readme.count(row), 1)
        line = next(x for x in readme.splitlines() if x.startswith(row))
        self.assertIn(f"| {D810_BYTES} | `{D810_SHA256}` |", line)

    def test_the_810_strings_are_line_25s(self) -> None:
        self.assertTrue(source_line_810(25).startswith("- **Product site #45 (after #44):**"))
        for name, letter in ITEMS_810:
            with self.subTest(constant=name):
                found = quoted(item_810(letter).split("—", 1)[0] if letter == "(a)" else item_810(letter))
                self.assertEqual(found[0], getattr(text, name))
        # The three words, in 810's order, are 809's two forms with the new one between.
        words = quoted(item_810("(a)").split("the three words: ", 1)[1])
        self.assertEqual(
            words,
            [text.VERTICAL_RECORDS, text.VERTICAL_SERIES_LIVE, text.VERTICAL_CATALOGUED],
        )

    @unittest.skipUnless(
        APPARATUS.is_dir(), "the OneDrive original is on the desk only"
    )
    def test_the_810_original_is_the_copys_bytes(self) -> None:
        originals = sorted(APPARATUS.glob(ORIGINAL_GLOB_810))
        self.assertEqual(len(originals), 1, originals)
        self.assertEqual(
            hashlib.sha256(originals[0].read_bytes()).hexdigest(), D810_SHA256
        )

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
        self.assertNotIn("P6 defined ;", self.home)  # 809's bytes, re-signed by 810
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
                elif m.group(2) == refresh_count.SERIES_LIVE_CLASS:
                    self.assertEqual(m.group(6), text.VERTICAL_SERIES_LIVE)
                    self.assertIn(m.group(4), ("V#1", "V#2"))  # agents.txt's SERIES-LIVE
                else:
                    self.assertEqual(m.group(2), refresh_count.RECORDS_CLASS)
                    if m.group(6) != text.VERTICAL_RECORD_ONE:
                        self.assertIsNotNone(records.fullmatch(m.group(6)))
                        self.assertNotEqual(m.group(6), text.VERTICAL_RECORDS.replace("{n}", "1"))
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
        for css in (
            refresh_count.RECORDS_CLASS,
            refresh_count.SERIES_LIVE_CLASS,
            refresh_count.CATALOGUED_CLASS,
        ):
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


class StatusRuleResidueTests(unittest.TestCase):
    """809 7's general rule on what the first round missed, and the /verticals deletions."""

    def test_p6_is_defined_in_agents_txt_not_live(self) -> None:
        lines = read_site(".well-known/agents.txt").split("\n")
        self.assertEqual(
            lines.count(f"Primitive: P6=Market-State-Telemetry {text.STATUS_DEFINED}"), 1
        )
        self.assertFalse([ln for ln in lines if ln.startswith("Primitive: P6=") and "LIVE" in ln])

    def test_v0_takes_the_catalogued_token_not_live(self) -> None:
        lines = read_site(".well-known/agents.txt").split("\n")
        v0 = [ln for ln in lines if ln.startswith("Vertical: V0=")]
        self.assertEqual(len(v0), 1)
        self.assertTrue(v0[0].endswith(" meta-vertical CATALOGUED"), v0)
        self.assertNotIn("LIVE", v0[0])

    def test_healthcare_carries_no_hipaa_safe_harbor_claim(self) -> None:
        agents = read_site(".well-known/agents.txt")
        self.assertEqual(agents.split("\n").count("Vertical: V3=Healthcare CATALOGUED"), 1)
        home = read_site("index.html")
        self.assertEqual(
            home.count(
                '<span class="vertical-name">Healthcare</span>'
                '<span class="vertical-status records" data-vertical="V#3">'
            ),
            1,
        )
        self.assertNotIn("HIPAA Safe Harbor", home)
        self.assertNotIn("HIPAA Safe Harbor", agents)

    def test_agentic_commerce_lists_only_p1_and_p3_live_and_p6_defined(self) -> None:
        service = json.loads(read_site(".well-known/agentic-commerce.json"))["service"]
        self.assertEqual(
            service["primitives_live"],
            ["p1-identity-and-mandate", "p3-forecast-and-evidence"],
        )
        self.assertEqual(service["primitives_defined"], ["p6-market-state-telemetry"])
        self.assertEqual(
            service["primitives_planned"],
            ["p4-coordination-and-negotiation", "p5-outcome-conditional"],
        )

    def test_the_p6_card_carries_810s_description(self) -> None:
        home = read_site("index.html")
        card = home.split('<span class="p-prefix">P6</span>', 1)[1].split("</div>", 1)[0]
        self.assertEqual(
            card,
            "\n        <h3>Market-State Telemetry</h3>\n"
            f"        <p>{text.P6_CARD_DESCRIPTION}</p>\n      ",
        )
        self.assertNotIn("microstructure feed", home)

    def test_the_p6_card_is_styled_defined_not_as_a_live_card(self) -> None:
        home = read_site("index.html")
        self.assertEqual(
            home.count(
                '<div class="primitive-card defined">\n        <span class="p-prefix">P6</span>'
            ),
            1,
        )
        self.assertEqual(home.count(".primitive-card.defined .p-prefix::after {"), 1)
        self.assertIn('content: " · defined";', home)

    def test_verticals_page_has_no_first_archetype_minted_claim(self) -> None:
        page = read_site("verticals.html")
        self.assertNotIn("archetype minted", page)
        for kept in (
            '<span class="archetype-id">H1</span> US disease incidence per 100k by demographic '
            "and region (e.g., Type 2 diabetes)</li>",
            '<span class="archetype-id">C1</span> SpaceX IPO probability by Q4 2027 '
            "(52% canonical p50)</li>",
            '<span class="archetype-id">R1</span> Humanoid robot industry deployment cadence by '
            "region and customer-segment</li>",
        ):
            with self.subTest(kept=kept):
                self.assertEqual(page.count(kept), 1)


#: ``/v1/catalog`` in its served shape: V1 and V2 SERIES_LIVE, every other CATALOGUED.
CATALOG: dict[str, Any] = {
    "verticals": [
        {"id": f"V{n}", "status": "SERIES_LIVE" if n in (1, 2) else "CATALOGUED"}
        for n in range(1, 14)
    ]
}


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
        self.assertEqual(badges["V#4"], ("records", text.VERTICAL_RECORD_ONE))
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
            'data-vertical="V#4">' + text.VERTICAL_RECORD_ONE,
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

    def test_series_live_shows_only_on_a_catalogued_series_with_no_record(self) -> None:
        refresh_count.refresh(
            self.index, _payload(ROWS), TODAY, verticals=True, catalog=CATALOG
        )
        badges = self._texts(self.index.read_bytes().decode("utf-8"))
        # V#2: SERIES_LIVE, no record. V#1: SERIES_LIVE with three: the count shows.
        self.assertEqual(badges["V#2"], ("series-live", text.VERTICAL_SERIES_LIVE))
        self.assertEqual(
            badges["V#1"], ("records", text.VERTICAL_RECORDS.replace("{n}", "3"))
        )
        for vid in ("V#0", "V#3", "V#12"):
            self.assertEqual(badges[vid], ("catalogued", text.VERTICAL_CATALOGUED))
        ok, lines = refresh_count.check(self.index, _payload(ROWS), TODAY, CATALOG)
        self.assertTrue(ok)
        self.assertEqual(
            lines, ["index.html: OK, current with the register as of 2026-11-06"]
        )

    def test_check_fails_series_live_the_catalog_does_not_list(self) -> None:
        refresh_count.refresh(
            self.index, _payload(ROWS), TODAY, verticals=True, catalog=CATALOG
        )
        demoted = {
            "verticals": [
                {**v, "status": "CATALOGUED"} if v["id"] == "V2" else v
                for v in CATALOG["verticals"]
            ]
        }
        for name, catalog in {"no catalog read": None, "V2 catalogued": demoted}.items():
            with self.subTest(case=name):
                ok, lines = refresh_count.check(self.index, _payload(ROWS), TODAY, catalog)
                self.assertFalse(ok)
                self.assertIn(
                    "OVERCLAIM V#2: the page states 'series live', "
                    "the catalog does not list it SERIES_LIVE",
                    lines,
                )
        # A catalogued badge on a series the catalog lists live is a page behind it.
        refresh_count.refresh(self.index, _payload(ROWS), TODAY, verticals=True)
        ok, lines = refresh_count.check(self.index, _payload(ROWS), TODAY, CATALOG)
        self.assertTrue(ok)
        self.assertIn(
            "WARN V#2: the page states 'catalogued', the catalog lists it SERIES_LIVE",
            lines,
        )

    def test_a_catalog_in_another_shape_refuses_and_writes_nothing(self) -> None:
        for name, catalog in {
            "not an object": [],
            "no verticals": {"series_live": 2},
            "a vertical with no id": {"verticals": [{"status": "SERIES_LIVE"}]},
            "a vertical with no status": {"verticals": [{"id": "V2"}]},
        }.items():
            with self.subTest(case=name):
                with self.assertRaises(refresh_count.Refused):
                    refresh_count.refresh(
                        self.index, _payload(ROWS), TODAY, verticals=True, catalog=catalog
                    )
                self.assertEqual(self.index.read_bytes().decode("utf-8"), self.home)

    def test_the_catalog_ids_are_the_badges_numbers(self) -> None:
        self.assertEqual(refresh_count.CATALOG_IDS["V#0"], None)
        for n in range(1, 13):
            self.assertEqual(refresh_count.CATALOG_IDS[f"V#{n}"], f"V{n}")

    def test_the_command_line_reads_a_catalog_file(self) -> None:
        source = self.dir / "scorecard.json"
        source.write_text(json.dumps(_payload(ROWS)), encoding="utf-8")
        catalog = self.dir / "catalog.json"
        catalog.write_text(json.dumps(CATALOG), encoding="utf-8")
        with (
            mock.patch.object(refresh_count, "INDEX", self.index),
            mock.patch("builtins.print"),
        ):
            rc = refresh_count.main(
                ["refresh_count.py", "--from-file", str(source), "--catalog-file", str(catalog)]
            )
            check_rc = refresh_count.main(
                ["refresh_count.py", "--check", "--from-file", str(source)]
            )
        self.assertEqual(rc, 0)
        self.assertEqual(
            self._texts(self.index.read_bytes().decode("utf-8"))["V#2"][1],
            text.VERTICAL_SERIES_LIVE,
        )
        self.assertEqual(check_rc, 1)  # no catalog read: the series-live badge is unsupported

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


class Ap2ClaimStateTests(unittest.TestCase):
    """COO 811 §4 with 810 §4's claim-state: no surface says an AP2 mandate is verified, is
    evidence, or authorizes layer 1. The API stores a presented mandate id as context only,
    its verification is not implemented, and it has no mandate parse or format error path,
    so the spec's auth category reads "JWT failure" (the code citations are in the CCO's
    handback to the COO; the API repository is private)."""

    def test_the_claim_state_is_810_line_26s(self) -> None:
        segment = source_line_810(26).split("an AP2 mandate is ", 1)[1]
        self.assertEqual(quoted(segment.split("*;", 1)[0] + "*")[0], text.AP2_CLAIM_STATE)

    def test_the_manifest_records_a_mandate_unverified(self) -> None:
        manifest = json.loads(read_site(".well-known/agentic-commerce.json"))
        auth = manifest["authentication"]
        self.assertEqual(auth["supported_methods"][0], {"ap2_mandate": "planned"})
        self.assertEqual(
            auth["agent_paths"]["path_a_autonomous_agent"]["description"],
            "Agents authenticate with an Authority Credential; an AP2 mandate is "
            f"{text.AP2_CLAIM_STATE} (Terms \u00a74.3).",
        )
        trust = manifest["trust_stack"]
        self.assertEqual(trust["layer_1_authorization"], "ap2_mandate_recorded_unverified")
        self.assertEqual(trust["layer_1_authorization_availability"], "planned")

    def test_agents_txt_says_the_same(self) -> None:
        agents = read_site(".well-known/agents.txt")
        self.assertEqual(agents.count(f"an AP2 mandate is {text.AP2_CLAIM_STATE} (Terms"), 1)

    def test_no_surface_says_a_mandate_is_evidence_or_verified(self) -> None:
        for rel in (".well-known/agentic-commerce.json", ".well-known/agents.txt", "spec.html"):
            page = read_site(rel)
            for gone in (
                "recorded as evidence of delegated authority",
                "ap2_mandate_verification",
                "MANDATE_INVALID_SIGNATURE",
                "signature verification failed",
                "(mandate or JWT failure)",
            ):
                with self.subTest(file=rel, text=gone):
                    self.assertNotIn(gone, page)
        self.assertEqual(read_site("spec.html").count("<code>auth</code> (JWT failure)"), 1)

    def test_the_spec_auth_line_states_the_claim_state(self) -> None:
        """COO 812 §1: of the four AP2 lines 811 listed, only the Auth line said a mandate is
        bound to the caller today; it takes the claim-state. The other three describe the
        flow as forward-state and stand."""
        spec = read_site("spec.html")
        self.assertEqual(spec.count(f"AP2 mandate: {text.AP2_CLAIM_STATE}.</div>"), 1)
        self.assertNotIn("delegated-authority evidence bound to the authenticated caller", spec)
        # LA-17 (W-A3 §7): the FORWARD-STATE request example, a text that told a reader
        # to call the closed forecast route, left the page; the Auth line's claim-state
        # and the Agentic-commerce heading stand.
        self.assertNotIn("FORWARD-STATE example", spec)
        self.assertEqual(spec.count("is <strong>FORWARD-STATE</strong>"), 1)


def main(argv: list[str]) -> int:
    if argv[1:]:
        print(__doc__)
        return 2
    result = unittest.main(module=__name__, argv=[argv[0], "-v"], exit=False).result
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
