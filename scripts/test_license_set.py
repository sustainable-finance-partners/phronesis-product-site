#!/usr/bin/env python3
"""The license set renders its signed strings exactly.

The Register License page (``site/license.html``), the license block in
``site/llms.txt`` and ``site/.well-known/agents.txt``, the crawl posture in
``site/robots.txt`` and the homepage record count carry counsel-approved and signed
strings. Each string is pinned in ``gates/license_strings.json`` with the source
document, the line it was extracted from, and sha256 digests of the extracted text and
of the whole source line. The strings are never retyped: ``--write-pin`` extracts them
from the source documents, and the tests below prove

  * each pinned string equals the text extracted from its source line, when the source
    workspace is on this machine (``PHRONESIS_WORKSPACE`` names its root; CI has no
    copy, so there the test is skipped and says so);
  * each pinned string still hashes to the digest recorded when it was extracted;
  * each pinned string appears, exactly, where it renders.

Run from anywhere: ``python3 scripts/test_license_set.py`` (the tests, exit 0 on pass)
or ``python3 scripts/test_license_set.py --write-pin`` (re-extract the pin from the
sources; needs ``PHRONESIS_WORKSPACE``). Standard library only.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import os
import re
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE = REPO_ROOT / "site"
PIN_PATH = REPO_ROOT / "gates" / "license_strings.json"
WORKSPACE_ENV = "PHRONESIS_WORKSPACE"

LICENSE_URL = "https://phronesisintel.com/license"
SCORECARD_URL = "https://api.phronesisintel.com/.well-known/scorecard.json"
#: The gate's marker for the homepage count (discovery_surface_consistency.py in the
#: app repo). The marker stays the span's LAST attribute and the digits stay the span's
#: direct text, so the gate's count regex matches the static render.
DA_COUNT_SOURCE_MARKER = 'data-source="scorecard.aggregate_stats.forecast_count"'
TRUST_SECTION_URL = "https://api.phronesisintel.com/trust#how-the-record-is-protected"

LICENSE_CLAUSE_IDS = tuple(f"license.p{n}" for n in range(1, 11))

#: Phrases of the retired "Training-protected" posture. None may remain on any
#: published file once the license's terms replace it (the claim-state census).
RETIRED_POSTURE_PHRASES = (
    "training-protected",
    "block ai training",
    "ai-train=no",
    "requires a license",
    "blocked pending a license",
    "training-class crawlers",
)

#: The eight training-crawler groups the retired posture disallowed.
RETIRED_TRAINING_AGENTS = (
    "GPTBot",
    "Google-Extended",
    "Applebot-Extended",
    "CCBot",
    "Bytespider",
    "meta-externalagent",
    "anthropic-ai",
    "cohere-ai",
)


# ── extraction (the pin is written from the sources, never typed) ────────────


def _source_lines(path: Path) -> list[str]:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"{path.name}: unexpected byte-order mark")
    return raw.decode("utf-8").split("\n")


def extract(line: str, how: dict[str, str]) -> str:
    """The string a pin row names, cut from one source line by its ``extract`` rule.

    ``blockquote``: the line is a Markdown blockquote line; the string is the line
    after its ``"> "`` prefix. ``quoted-after``: the string is the text between the
    first ``open`` delimiter after ``anchor`` and the next ``close`` delimiter.
    """
    kind = how["kind"]
    if kind == "blockquote":
        if not line.startswith("> "):
            raise ValueError(f"not a blockquote line: {line[:60]!r}")
        return line[2:]
    if kind == "quoted-after":
        at = line.find(how["anchor"])
        if at < 0:
            raise ValueError(f"anchor {how['anchor']!r} not on the line")
        start = line.find(how["open"], at + len(how["anchor"]))
        if start < 0:
            raise ValueError(f"no {how['open']!r} after the anchor")
        start += len(how["open"])
        end = line.find(how["close"], start)
        if end < 0:
            raise ValueError(f"no closing {how['close']!r}")
        return line[start:end]
    raise ValueError(f"unknown extract kind {kind!r}")


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_pin() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(PIN_PATH.read_text(encoding="utf-8"))
    return data


def pinned() -> dict[str, str]:
    """Pin id -> pinned text."""
    return {str(row["id"]): str(row["text"]) for row in load_pin()["strings"]}


def write_pin(workspace: Path) -> None:
    data = load_pin()
    for row in data["strings"]:
        lines = _source_lines(workspace / row["source"])
        line = lines[int(row["line"]) - 1]
        text = extract(line, row["extract"])
        row["text"] = text
        row["sha256"] = sha256(text)
        row["line_sha256"] = sha256(line)
    PIN_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


# ── rendering (Markdown inline marks to HTML; the words are never touched) ───

_MARK_RE = re.compile(r"\*\*(.+?)\*\*|`([^`]+)`")


def render_inline(text: str) -> str:
    """``**bold**`` -> ``<strong>``, ``code`` -> ``<code>``; every other byte is the
    source's, HTML-escaped (the license text carries no ``&``, ``<`` or ``>``)."""
    out: list[str] = []
    pos = 0
    for m in _MARK_RE.finditer(text):
        out.append(html.escape(text[pos : m.start()], quote=False))
        if m.group(1) is not None:
            out.append(f"<strong>{html.escape(m.group(1), quote=False)}</strong>")
        else:
            out.append(f"<code>{html.escape(m.group(2), quote=False)}</code>")
        pos = m.end()
    out.append(html.escape(text[pos:], quote=False))
    return "".join(out)


def strip_marks(text: str) -> str:
    """The words a reader sees: the source with its Markdown marks removed."""
    return _MARK_RE.sub(lambda m: m.group(1) if m.group(1) is not None else m.group(2), text)


def heading_text(heading: str) -> str:
    """The license heading's words (the source line is the heading set in bold)."""
    if not (heading.startswith("**") and heading.endswith("**")):
        raise ValueError(f"heading is not a bold line: {heading!r}")
    return heading[2:-2]


def llms_block(strings: dict[str, str]) -> str:
    """The llms.txt license section: the heading, License ¶1 and ¶2 verbatim, and the
    signed access line (S.1) directly below them."""
    return (
        f"## {heading_text(strings['license.heading'])}\n"
        f"{strings['license.p1']}\n"
        "\n"
        f"{strings['license.p2']}\n"
        "\n"
        f"{strings['S.1']}\n"
    )


def agents_block(strings: dict[str, str]) -> str:
    """The agents.txt license section, in the file's ``# --- section ---`` form."""
    return (
        f"# --- {heading_text(strings['license.heading'])} ---\n"
        f"# {strings['license.p1']}\n"
        f"# {strings['license.p2']}\n"
        f"# {strings['S.1']}\n"
    )


def count_label(template: str, n: int, date: str) -> str:
    if template.count("{n}") != 1 or template.count("{date}") != 1:
        raise ValueError(f"S.6 template must carry {{n}} and {{date}} once: {template!r}")
    return template.replace("{n}", str(n)).replace("{date}", date)


# ── reading the published files ──────────────────────────────────────────────


def read_site(rel: str) -> str:
    """A published file as text with LF line ends (a Windows checkout writes CRLF)."""
    return (SITE / rel).read_bytes().decode("utf-8").replace("\r\n", "\n")


class _TextOf(HTMLParser):
    """Collects the text of every element of one tag name, in document order."""

    def __init__(self, tag: str) -> None:
        super().__init__(convert_charrefs=True)
        self.tag = tag
        self.texts: list[str] = []
        self._depth = 0
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == self.tag:
            self._depth += 1
            if self._depth == 1:
                self._buf = []

    def handle_endtag(self, tag: str) -> None:
        if tag == self.tag and self._depth:
            self._depth -= 1
            if self._depth == 0:
                self.texts.append("".join(self._buf))

    def handle_data(self, data: str) -> None:
        if self._depth:
            self._buf.append(data)


def texts_of(markup: str, tag: str) -> list[str]:
    parser = _TextOf(tag)
    parser.feed(markup)
    parser.close()
    return parser.texts


def between(text: str, start: str, end: str) -> str:
    a = text.index(start)
    b = text.index(end, a)
    return text[a : b + len(end)]


def _footer(markup: str) -> str:
    return between(markup, '<footer class="site-footer">', "</footer>")


_COUNT_SPAN_RE = re.compile(
    r'<span class="metric-value" id="record-count" data-as-of="(\d{4}-\d{2}-\d{2})" '
    + re.escape(DA_COUNT_SOURCE_MARKER)
    + r">(\d+)</span>\s*"
    r'<span class="metric-label">(.*?)</span>',
    re.S,
)
#: The gate's count regex as it stands on the app repo's main (the marker last, the
#: digits the span's direct text). The static render must keep matching it.
_GATE_COUNT_RE = re.compile(re.escape(DA_COUNT_SOURCE_MARKER) + r">\s*(\d+)\s*<")


# ── the tests ────────────────────────────────────────────────────────────────


class PinTests(unittest.TestCase):
    def test_every_pin_still_hashes_to_its_recorded_digest(self) -> None:
        for row in load_pin()["strings"]:
            with self.subTest(pin=row["id"]):
                self.assertEqual(sha256(row["text"]), row["sha256"])

    def test_pins_equal_their_source_lines(self) -> None:
        root = os.environ.get(WORKSPACE_ENV)
        if not root:
            self.skipTest(f"{WORKSPACE_ENV} is not set: the source documents are not here")
        workspace = Path(root)
        for row in load_pin()["strings"]:
            with self.subTest(pin=row["id"]):
                line = _source_lines(workspace / row["source"])[int(row["line"]) - 1]
                self.assertEqual(sha256(line), row["line_sha256"], "the source line moved")
                self.assertEqual(extract(line, row["extract"]), row["text"])

    def test_the_pin_carries_the_ten_clauses_and_the_signed_strings(self) -> None:
        ids = set(pinned())
        for need in ("license.heading", *LICENSE_CLAUSE_IDS, "S.1", "S.2.license", "S.6"):
            with self.subTest(pin=need):
                self.assertIn(need, ids)
        self.assertIn("A.content-signal", ids)


class LicensePageTests(unittest.TestCase):
    page: str
    strings: dict[str, str]

    @classmethod
    def setUpClass(cls) -> None:
        cls.page = read_site("license.html")
        cls.strings = pinned()

    def test_heading_is_the_license_heading(self) -> None:
        self.assertEqual(texts_of(self.page, "h1"), [heading_text(self.strings["license.heading"])])
        self.assertIn(f"<title>{heading_text(self.strings['license.heading'])}</title>", self.page)

    def test_version_line_is_s2(self) -> None:
        line = self.strings["S.2.license"]
        self.assertIn(f'<p class="effective">{html.escape(line, quote=False)}</p>', self.page)

    def test_each_clause_renders_verbatim_and_in_order(self) -> None:
        last = -1
        for pin_id in LICENSE_CLAUSE_IDS:
            with self.subTest(clause=pin_id):
                rendered = f"<p>{render_inline(self.strings[pin_id])}</p>"
                at = self.page.find(rendered)
                self.assertGreater(at, last, "missing, or out of order")
                self.assertEqual(self.page.count(rendered), 1)
                last = at

    def test_the_words_a_reader_sees_are_the_sources_words(self) -> None:
        clauses = [strip_marks(self.strings[pin_id]) for pin_id in LICENSE_CLAUSE_IDS]
        section = between(self.page, '<div class="container-narrow policy">', "</div>")
        self.assertEqual(texts_of(section, "p"), clauses)

    def test_no_word_inside_or_beside_the_license(self) -> None:
        # The policy section holds the ten clauses and nothing else.
        section = between(self.page, '<div class="container-narrow policy">', "</div>")
        body = re.sub(r"<p>.*?</p>", "", section, flags=re.S)
        self.assertEqual(re.sub(r"<[^>]+>", "", body).strip(), "")

    def test_standard_header_and_footer(self) -> None:
        security = read_site("security.html")
        self.assertEqual(_footer(self.page), _footer(security))
        self.assertEqual(
            between(self.page, '<header class="site-header">', "</header>"),
            between(security, '<header class="site-header">', "</header>"),
        )

    def test_trademark_footer_line_unchanged(self) -> None:
        line = (
            "<p>PHRONESIS is a trademark of John Ross Stinehour, used under license by "
            "Sustainable Finance Partners, LLC.</p>"
        )
        self.assertEqual(self.page.count(line), 1)
        self.assertIn(line, _footer(read_site("index.html")))

    def test_canonical_url(self) -> None:
        self.assertIn(f'<link rel="canonical" href="{LICENSE_URL}">', self.page)

    def test_sitemap_lists_the_page(self) -> None:
        self.assertIn(f"<loc>{LICENSE_URL}</loc>", read_site("sitemap.xml"))


class MachineReadableTests(unittest.TestCase):
    strings: dict[str, str]

    @classmethod
    def setUpClass(cls) -> None:
        cls.strings = pinned()

    def test_llms_txt_carries_p1_p2_then_s1(self) -> None:
        self.assertEqual(read_site("llms.txt").count(llms_block(self.strings)), 1)

    def test_agents_txt_carries_p1_p2_then_s1(self) -> None:
        self.assertEqual(read_site(".well-known/agents.txt").count(agents_block(self.strings)), 1)

    def test_s1_carries_the_license_url(self) -> None:
        self.assertTrue(self.strings["S.1"].endswith(f"Terms: {LICENSE_URL}"))

    def test_robots_content_signal_is_the_ruled_signal(self) -> None:
        robots = read_site("robots.txt")
        signals = [ln for ln in robots.split("\n") if ln.startswith("Content-Signal:")]
        self.assertEqual(signals, [f"Content-Signal: {self.strings['A.content-signal']}"])

    def test_robots_has_no_training_disallow_groups(self) -> None:
        robots = read_site("robots.txt")
        agents = [
            ln.split(":", 1)[1].strip()
            for ln in robots.split("\n")
            if ln.lower().startswith("user-agent:")
        ]
        self.assertEqual(agents, ["*"])
        self.assertNotIn("Disallow:", robots)
        for name in RETIRED_TRAINING_AGENTS:
            with self.subTest(agent=name):
                self.assertNotIn(name, robots)

    def test_robots_header_states_s1(self) -> None:
        self.assertIn(f"\n# {self.strings['S.1']}\n", read_site("robots.txt"))

    def test_no_published_file_keeps_the_retired_posture(self) -> None:
        for path in sorted(SITE.rglob("*")):
            if not path.is_file():
                continue
            try:
                text = path.read_bytes().decode("utf-8").lower()
            except UnicodeDecodeError:
                continue
            for phrase in RETIRED_POSTURE_PHRASES:
                with self.subTest(file=path.relative_to(SITE).as_posix(), phrase=phrase):
                    self.assertNotIn(phrase, text)


class HomepageCountTests(unittest.TestCase):
    home: str
    strings: dict[str, str]

    @classmethod
    def setUpClass(cls) -> None:
        cls.home = read_site("index.html")
        cls.strings = pinned()

    def _match(self) -> re.Match[str]:
        m = _COUNT_SPAN_RE.search(self.home)
        assert m is not None, "the count span and its label are not in the ruled form"
        return m

    def test_one_count_span(self) -> None:
        self.assertEqual(self.home.count(DA_COUNT_SOURCE_MARKER), 1)
        self.assertEqual(len(_COUNT_SPAN_RE.findall(self.home)), 1)

    def test_as_of_is_a_real_date(self) -> None:
        dt.date.fromisoformat(self._match().group(1))

    def test_the_gate_regex_still_reads_the_static_count(self) -> None:
        gate = _GATE_COUNT_RE.search(self.home)
        assert gate is not None
        self.assertEqual(gate.group(1), self._match().group(2))

    def test_label_is_s6(self) -> None:
        m = self._match()
        as_of, n = m.group(1), int(m.group(2))
        self.assertEqual(
            m.group(3),
            "records on the register as of "
            f'<time id="record-count-as-of" datetime="{as_of}">{as_of}</time>',
        )
        metric = between(self.home, '<span class="metric-value" id="record-count"', "</div>")
        seen = " ".join(re.sub(r"<[^>]+>", " ", metric.split(">", 1)[1]).split())
        self.assertEqual(seen, count_label(self.strings["S.6"], n, as_of))

    def test_the_old_noun_is_gone(self) -> None:
        self.assertNotIn("Decision Assets on the ledger", self.home)

    def test_refresh_script_reads_the_cached_scorecard(self) -> None:
        scripts = re.findall(r"<script>(.*?)</script>", self.home, flags=re.S)
        refresh = [s for s in scripts if "record-count-as-of" in s]
        self.assertEqual(len(refresh), 1)
        body = refresh[0]
        self.assertIn(f"'{SCORECARD_URL}'", body)
        # The gate's marker stays on the span alone: one occurrence on the page.
        self.assertNotIn(DA_COUNT_SOURCE_MARKER, body)
        self.assertEqual(re.findall(r"https?://[^'\"\s)]+", body), [SCORECARD_URL])
        for needle in ("aggregate_stats", "forecast_count", "generated_at", "data-as-of"):
            with self.subTest(needle=needle):
                self.assertIn(needle, body)


class ClaimStateTests(unittest.TestCase):
    def test_oauth_connector_is_live_on_for_agents(self) -> None:
        page = read_site("for-agents.html")
        self.assertNotIn("<strong>In flight:</strong> the OAuth-consent connector path.", page)
        self.assertNotIn("OAuth-consent connect path = in flight", page)
        self.assertIn("OAuth-consent connect path = live", page)
        live = between(page, "<strong>Live:</strong>", "<strong>Forward (labeled):</strong>")
        self.assertIn("the OAuth-consent connector path", live)

    def test_security_links_the_trust_center_section(self) -> None:
        page = read_site("security.html")
        self.assertIn(f'<a href="{TRUST_SECTION_URL}">How the record is protected</a>', page)


def main(argv: list[str]) -> int:
    if argv[1:] == ["--write-pin"]:
        root = os.environ.get(WORKSPACE_ENV)
        if not root:
            print(f"--write-pin needs {WORKSPACE_ENV} (the source workspace root)")
            return 2
        write_pin(Path(root))
        print(f"wrote {PIN_PATH.relative_to(REPO_ROOT).as_posix()}")
        return 0
    if argv[1:]:
        print(__doc__)
        return 2
    result = unittest.main(module=__name__, argv=[argv[0], "-v"], exit=False).result
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
