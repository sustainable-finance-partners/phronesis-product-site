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
  * each pinned string appears, exactly, where it renders, and nothing stands beside the
    license on its surfaces: the license page's whole frame (nothing before ``<html>``,
    between ``</head>`` and ``<body>`` or after ``</body>``), its head (``/security``'s
    but its title, description and canonical lines), the words its CSS can place, its
    ``<main>`` and the body chrome around it; the license sections of llms.txt and
    agents.txt with their ordered headings and the section directly above each; and
    the whole robots.txt, line for line;
  * the agents.txt P1 primitive line is the signed 782 §1.2 token (pin ``782.P1``, cut
    from the dispatch line after its arrow), and no other published line carries that
    token shape.

The machine-readable declaration on this host (``site/license.xml``, the RSL 1.0
document robots.txt names, and the aipref ``Content-Usage`` robots rule) is tested
against the API's own flag-ON render, pinned in the same file under ``api_render`` with
its repository, path and the file's git blob id (content, not a commit).
``scripts/refresh_count.py`` (the pre-merge refresh of the homepage count) is tested
here offline against a fixture payload.

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
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import refresh_count  # noqa: E402  (the sibling script; isolated mode drops its directory)

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE = REPO_ROOT / "site"
PIN_PATH = REPO_ROOT / "gates" / "license_strings.json"
WORKSPACE_ENV = "PHRONESIS_WORKSPACE"
#: A clone of the app repository (sustainable-finance-partners/phronesis). Optional:
#: without it the source-line check of the ``api_render`` fixture is skipped and says
#: so. With it, the check requires the pinned blob at the clone's checked-out commit
#: (``HEAD``), or at the revision ``PHRONESIS_API_REV`` names (for example
#: ``origin/main``), and reads the file only through git.
API_TREE_ENV = "PHRONESIS_API_TREE"
API_REV_ENV = "PHRONESIS_API_REV"

LICENSE_URL = "https://phronesisintel.com/license"
#: The RSL 1.0 document for this host's content; robots.txt names it (RSL 1.0 §4.4).
RSL_DOCUMENT_URL = "https://phronesisintel.com/license.xml"
RSL_NAMESPACE = "https://rslstandard.org/rsl"
RSL_MEDIA_TYPE = "application/rsl+xml"
#: RSL 1.0 §3.2 / §3.2.1: ``max-age`` is "a positive integer number of days" a client may
#: treat the document and its association as authoritative (default 30). One day keeps a
#: change to the declaration (License clause 2(e)) binding within a day.
RSL_MAX_AGE_DAYS = "1"
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


def license_main(strings: dict[str, str]) -> str:
    """The license page's whole ``<main>``: the heading, the S.2 version line, and the ten
    clauses in their bold/code structure. Nothing else."""
    clauses = "\n\n".join(f"    <p>{render_inline(strings[pin])}</p>" for pin in LICENSE_CLAUSE_IDS)
    heading = html.escape(heading_text(strings["license.heading"]), quote=False)
    return (
        '<main id="main">\n'
        "\n"
        '<section style="background: var(--gradient-hero); '
        'padding: var(--space-16) 0 var(--space-8) 0;">\n'
        '  <div class="container-narrow">\n'
        f"    <h1>{heading}</h1>\n"
        f'    <p class="effective">{html.escape(strings["S.2.license"], quote=False)}</p>\n'
        "  </div>\n"
        "</section>\n"
        "\n"
        '<section style="padding: var(--space-12) 0;">\n'
        '  <div class="container-narrow policy">\n'
        "\n"
        f"{clauses}\n"
        "\n"
        "  </div>\n"
        "</section>\n"
        "\n"
        "</main>"
    )


def api_fixture() -> dict[str, Any]:
    """The API's flag-ON render (``api_render`` in the pin file)."""
    data: dict[str, Any] = load_pin()["api_render"]
    return data


def api_rendered() -> dict[str, Any]:
    rendered: dict[str, Any] = api_fixture()["rendered"]
    return rendered


def git_blob_id(content: bytes) -> str:
    """The git object id of a file's bytes (``git hash-object``): its content, not a commit."""
    return hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest()


def _git(tree: str, *args: str) -> bytes:
    return subprocess.run(["git", "-C", tree, *args], check=True, capture_output=True).stdout


def rsl_terms_of(document: str) -> dict[str, Any]:
    """The usage permits and prohibits (token lists, in order), the payment type, the
    terms URL and the content url of a one-``<content>`` RSL document."""
    ns = f"{{{RSL_NAMESPACE}}}"
    root = ET.fromstring(document.encode("utf-8"))
    if root.tag != f"{ns}rsl":
        raise ValueError(f"root element is {root.tag!r}, not rsl in the RSL namespace")
    contents = root.findall(f"{ns}content")
    if len(contents) != 1:
        raise ValueError(f"{len(contents)} <content> elements, not one")
    content = contents[0]
    licenses = content.findall(f"{ns}license")
    if len(licenses) != 1:
        raise ValueError(f"{len(licenses)} <license> elements, not one")
    lic = licenses[0]
    payments = lic.findall(f"{ns}payment")
    terms = content.findall(f"{ns}terms")
    if len(payments) != 1 or len(terms) != 1:
        raise ValueError("not exactly one <payment> and one <terms>")
    return {
        "permits": [
            tok
            for el in lic.findall(f"{ns}permits")
            if el.get("type") == "usage"
            for tok in (el.text or "").split()
        ],
        "prohibits": [
            tok
            for el in lic.findall(f"{ns}prohibits")
            if el.get("type") == "usage"
            for tok in (el.text or "").split()
        ],
        "payment": payments[0].get("type"),
        "terms": terms[0].text,
        "url": content.get("url"),
    }


def robots_posture(strings: dict[str, str], content_usage: str) -> str:
    """The robots.txt crawl posture, from its header comment to the wildcard group's end:
    S.1, the global RSL ``License:`` record, the ruled Content-Signal and the API's aipref
    Content-Usage rule. No sentence without a source."""
    return (
        "# Phronesis crawl policy.\n"
        f"# {strings['S.1']}\n"
        "# Agents: start at /llms.txt and\n"
        "# https://api.phronesisintel.com/.well-known/mcp.json.\n"
        "\n"
        f"License: {RSL_DOCUMENT_URL}\n"
        "\n"
        "# Content Signals (contentsignals.org): AI training yes, AI input\n"
        "# (reference/grounding) yes, search indexing yes.\n"
        "User-agent: *\n"
        f"Content-Signal: {strings['A.content-signal']}\n"
        f"Content-Usage: {content_usage}\n"
        "Allow: /\n"
    )


def robots_txt(strings: dict[str, str], content_usage: str) -> str:
    """The whole robots.txt, line for line: the file's own header, the crawl posture
    (above), the sitemap record and the agent-discovery comments, as they stand. An
    unsourced line added anywhere (header, between the records, after the sitemap) fails."""
    return (
        "# robots.txt for phronesisintel.com (Phronesis product site)\n"
        "# Last updated: 2026-10-30\n"
        "#\n"
        + robots_posture(strings, content_usage)
        + "\n"
        "# Sitemaps\n"
        "Sitemap: https://phronesisintel.com/sitemap.xml\n"
        "\n"
        "# Agent discovery\n"
        "# The agents.txt file at /.well-known/agents.txt is the canonical agent manifest.\n"
        "# Machine-readable pricing at /pricing.json\n"
        "# OpenAPI spec at https://api.phronesisintel.com/.well-known/openapi.json\n"
        "# Markdown contract docs at /spec\n"
    )


def section_until(text: str, heading: str, next_prefix: str) -> str:
    """From ``heading`` (a whole line, exactly once in ``text``) up to the line that
    starts the next section (``next_prefix``), or the end of the text."""
    if text.count(heading) != 1:
        raise ValueError(f"{heading!r} occurs {text.count(heading)} times, not once")
    start = text.index(heading)
    end = text.find("\n" + next_prefix, start + len(heading) - 1)
    return text[start:] if end < 0 else text[start : end + 1]


def section_above(text: str, heading: str, prefix: str) -> str:
    """The section directly above ``heading`` (a whole line, exactly once in ``text``):
    from the last line before it that starts with ``prefix`` up to the heading."""
    if text.count(heading) != 1:
        raise ValueError(f"{heading!r} occurs {text.count(heading)} times, not once")
    at = text.index(heading)
    if at == 0 or text[at - 1] != "\n":
        raise ValueError(f"{heading!r} does not start a line below another section")
    return text[text.rfind("\n" + prefix, 0, at - 1) + 1 : at]


def llms_headings(strings: dict[str, str]) -> list[str]:
    """Every heading line of llms.txt (any level), in order. A heading added anywhere,
    one that would close the license section early included, fails."""
    return [
        "# Phronesis",
        "## One motion, proven first where the stakes are sharpest",
        "## Endpoints",
        "## Verification",
        "## Agent discovery",
        "## Integration",
        f"## {heading_text(strings['license.heading'])}",
        "## What's live vs forward (honest)",
    ]


def agents_headers(strings: dict[str, str]) -> list[str]:
    """Every ``# --- section ---`` header of agents.txt, in order."""
    return [
        "# --- What Phronesis is ---",
        "# --- Surfaces ---",
        "# --- Endpoints ---",
        f"# --- {heading_text(strings['license.heading'])} ---",
        "# --- Authentication ---",
        "# --- Substrate discipline (enforced at the code layer) ---",
        "# --- Pricing model ---",
        "# --- Verticals (twelve applied + V#0 meta-vertical) ---",
        "# --- Architecture (six primitives) ---",
        "# --- Substrate properties ---",
        "# --- Sister surfaces ---",
    ]


#: The llms.txt section directly above the license heading, whole, as it stands: a
#: sentence placed in it, or just above the license heading, fails.
LLMS_SECTION_ABOVE_LICENSE = (
    "## Integration\n"
    "\n"
    "- [API contract spec](https://phronesisintel.com/spec): the Hermes contract-v1 "
    "response shapes.\n"
    "- [OpenAPI](https://api.phronesisintel.com/.well-known/openapi.json): OpenAPI 3.1 spec.\n"
    "\n"
)
#: The agents.txt section directly above the license header, whole, as it stands.
AGENTS_SECTION_ABOVE_LICENSE = (
    "# --- Endpoints ---\n"
    "MCP: https://api.phronesisintel.com/mcp\n"
    "REST: https://api.phronesisintel.com\n"
    "Scorecard-JSON: https://api.phronesisintel.com/scorecard.json\n"
    "Bench-JSON: https://api.phronesisintel.com/.well-known/bench.json\n"
    "\n"
)

#: The agents.txt P1 token shape 782 §1.2 flips (case-sensitive: the JSON slug form
#: ``p1-identity-and-mandate`` is another shape, listed in the PR's census, not flipped).
P1_TOKEN_SHAPE = "Identity-and-Mandate"
#: The 782 §1.2 dispatch line: the token it replaces sits in the backtick span after this
#: anchor; the signed replacement (pin ``782.P1``) in the span after the line's one arrow.
P1_REPLACED_EXTRACT = {
    "kind": "quoted-after",
    "anchor": "editing for S.1:**",
    "open": "`",
    "close": "`",
}

#: The license page's frame: its bytes outside the ``<head>…</head>`` and
#: ``<body>…</body>`` spans. An HTML parser puts markup found before ``<html>`` or
#: between ``</head>`` and ``<body>`` into the rendered body, so nothing may sit there,
#: or after ``</body>``.
PAGE_FRAME = '<!DOCTYPE html>\n<html lang="en">\nHEAD\nBODY\n</html>\n'


def page_frame(page: str) -> str:
    """``page`` with its one ``<head>…</head>`` span replaced by ``HEAD`` and its one
    ``<body>…</body>`` span by ``BODY``."""
    for tag in ("<head>", "</head>", "<body>", "</body>"):
        if page.count(tag) != 1:
            raise ValueError(f"{tag} occurs {page.count(tag)} times, not once")
    head_start, head_end = page.index("<head>"), page.index("</head>") + len("</head>")
    body_start, body_end = page.index("<body>"), page.index("</body>") + len("</body>")
    if not head_start < head_end <= body_start < body_end:
        raise ValueError("<head> and <body> are not two spans in document order")
    return page[:head_start] + "HEAD" + page[head_end:body_start] + "BODY" + page[body_end:]


#: A CSS ``content`` declaration (generated content; property names are ASCII
#: case-insensitive). Words placed by CSS render on the page as if written there.
_CSS_CONTENT_RE = re.compile(r"(?<![\w-])content\s*:\s*[^;}]*", re.I)


def generated_content(css: str) -> list[str]:
    """Every ``content:`` declaration in ``css``, whitespace-normalized, in order."""
    return [" ".join(m.split()) for m in _CSS_CONTENT_RE.findall(css)]


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
        self.assertIn("782.P1", ids)

    def test_the_p1_token_is_782s_replacement_on_its_source_line(self) -> None:
        # 782 §1.2 :13 names the token it replaces, then one arrow, then the signed
        # replacement. The pin is the replacement, cut from that line by its rule.
        row = next(r for r in load_pin()["strings"] if r["id"] == "782.P1")
        self.assertTrue(str(row["source"]).startswith("00_Operating_Model/CCO_DISPATCH_782_"))
        self.assertEqual((row["line"], row["extract"]["anchor"]), (13, "→ "))
        root = os.environ.get(WORKSPACE_ENV)
        if not root:
            self.skipTest(f"{WORKSPACE_ENV} is not set: the source documents are not here")
        line = _source_lines(Path(root) / row["source"])[int(row["line"]) - 1]
        self.assertEqual(sha256(line), row["line_sha256"], "the source line moved")
        self.assertEqual(extract(line, row["extract"]), row["text"])
        replaced = extract(line, P1_REPLACED_EXTRACT)
        self.assertEqual(line.count("→"), 1)
        self.assertLess(line.index(f"`{replaced}`"), line.index("→"))
        self.assertLess(line.index("→"), line.index(f"`{row['text']}`"))
        # The token it replaces is gone from agents.txt as a line.
        self.assertNotIn(replaced, read_site(".well-known/agents.txt").split("\n"))

    def test_the_api_fixture_still_hashes_to_its_recorded_digest(self) -> None:
        fixture = api_fixture()
        canonical = json.dumps(fixture["rendered"], ensure_ascii=False, sort_keys=True)
        self.assertEqual(sha256(canonical), fixture["rendered_sha256"])
        self.assertEqual(fixture["repo"], "sustainable-finance-partners/phronesis")
        self.assertEqual(fixture["path"], "mcp_server/legal/register_license.py")
        # The pin is the file's content (its git blob id), not a commit: the API pull
        # request is squash-merged, so no branch commit reaches main. read_from_commit
        # names where the blob was read, for information only.
        self.assertRegex(fixture["blob"], r"^[0-9a-f]{40}$")
        self.assertRegex(fixture["read_from_commit"], r"^[0-9a-f]{40}$")
        self.assertNotIn("commit", fixture)

    def test_the_api_fixture_parses_as_its_own_document(self) -> None:
        # The token fields are the parse of the pinned document, not a second copy.
        rendered = api_rendered()
        self.assertEqual(rsl_terms_of(rendered["rsl_document"]), {
            "permits": rendered["rsl_permits_usage"],
            "prohibits": rendered["rsl_prohibits_usage"],
            "payment": rendered["rsl_payment_type"],
            "terms": rendered["rsl_terms"],
            "url": rendered["rsl_content_url"],
        })

    def test_the_api_fixture_equals_its_source_lines(self) -> None:
        root = os.environ.get(API_TREE_ENV)
        if not root:
            self.skipTest(f"{API_TREE_ENV} is not set: no clone of the app repository here")
        rev = os.environ.get(API_REV_ENV) or "HEAD"
        fixture = api_fixture()
        # The pinned blob must be the file at the clone's checked-out commit (or at the
        # named revision): this holds on the API PR's branch and, after the squash
        # merge, on main. The file is read only through git, never from the work tree.
        found = _git(root, "rev-parse", "--verify", f"{rev}:{fixture['path']}")
        self.assertEqual(
            found.decode("ascii").strip(), fixture["blob"], f"{fixture['path']} at {rev}"
        )
        content = _git(root, "show", fixture["blob"])
        self.assertEqual(git_blob_id(content), fixture["blob"])
        lines = content.decode("utf-8").split("\n")
        for row in fixture["source_lines"]:
            with self.subTest(line=row["line"], value=row["for"]):
                line = lines[int(row["line"]) - 1]
                self.assertEqual(line, row["text"])
                self.assertEqual(sha256(line), row["line_sha256"])
        rendered = api_rendered()
        by_value = {str(row["for"]): str(row["text"]) for row in fixture["source_lines"]}
        usage = re.findall(r'"([^"]+)"', by_value["rsl_permits_usage (without training)"])
        usage += re.findall(r'"([^"]+)"', by_value["rsl_permits_usage (the training term)"])
        self.assertEqual(" ".join(usage).split(), rendered["rsl_permits_usage"])
        self.assertIn(f'url="{rendered["rsl_content_url"]}"', by_value["rsl_content_url"])
        self.assertIn(f'type="{rendered["rsl_payment_type"]}"', by_value["rsl_payment_type"])
        self.assertIn(f'"{rendered["rsl_terms"]}"', by_value["rsl_terms"])
        self.assertIn(rendered["content_usage"].replace("train-ai=y", "train-ai={train}"),
                      by_value["content_usage"])
        # The API renders max-age itself, in days (RSL 1.0 §3.2): the same one day.
        self.assertEqual(
            by_value["rsl_max_age (days)"], f"RSL_MAX_AGE_DAYS: Final[int] = {RSL_MAX_AGE_DAYS}"
        )
        self.assertIn(
            '<rsl xmlns="{_RSL_NAMESPACE}" max-age="{RSL_MAX_AGE_DAYS}">',
            by_value["rsl_max_age (the <rsl> element)"],
        )


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

    def test_main_holds_only_the_license(self) -> None:
        # 781 F: nothing inside or beside the counsel text. The whole <main> is the
        # heading, the S.2 line and the ten clauses, byte for byte; a sentence in the
        # hero, between the sections or after the clauses fails here.
        self.assertEqual(self.page.count("<main"), 1)
        self.assertEqual(between(self.page, "<main", "</main>"), license_main(self.strings))

    def test_body_outside_main_is_the_standard_chrome(self) -> None:
        # Outside <main> the body carries the site's skip link, header and footer only.
        security = read_site("security.html")
        body = between(self.page, "<body>", "</body>")
        header = between(self.page, '<header class="site-header">', "</header>")
        footer = _footer(self.page)
        main = between(self.page, "<main", "</main>")
        skip = '<a href="#main" class="skip-link">Skip to main content</a>'
        self.assertIn(skip, between(security, "<body>", "</body>"))
        skeleton = body.replace(header, "HEADER").replace(main, "MAIN").replace(footer, "FOOTER")
        self.assertEqual(
            skeleton, f"<body>\n\n{skip}\n\nHEADER\n\nMAIN\n\nFOOTER\n\n</body>"
        )
        self.assertTrue(self.page.endswith("</body>\n</html>\n"))

    def test_the_page_is_the_fixed_frame(self) -> None:
        # Nothing before <html>, between </head> and <body>, or after </body>: markup
        # there renders as the start of the body, outside every other check here.
        self.assertEqual(page_frame(self.page), PAGE_FRAME)

    def test_head_is_the_security_head_but_its_own_three_lines(self) -> None:
        # /security's head, byte for byte, except the title, the S.2 description and the
        # canonical: the same metas, links and inline <style>. A stylesheet link, a
        # script or a style rule added to this page alone fails here.
        heading = html.escape(heading_text(self.strings["license.heading"]), quote=False)
        description = html.escape(self.strings["S.2.license"], quote=True)
        expected = between(read_site("security.html"), "<head>", "</head>")
        for pattern, ours in (
            (r"<title>[^<]*</title>", f"<title>{heading}</title>"),
            (
                r'<meta name="description" content="[^"]*">',
                f'<meta name="description" content="{description}">',
            ),
            (
                r'<link rel="canonical" href="[^"]*">',
                f'<link rel="canonical" href="{LICENSE_URL}">',
            ),
        ):
            theirs = re.findall(pattern, expected)
            self.assertEqual(len(theirs), 1, pattern)
            expected = expected.replace(theirs[0], ours, 1)
        self.assertEqual(between(self.page, "<head>", "</head>"), expected)

    def test_css_places_no_words_on_the_page(self) -> None:
        # 781 F through CSS. The page's one <style> is /security's (the two pages share
        # it; the other pages carry their own), and the page's only generated content is
        # the logo glyph's empty string. The shared stylesheet's only generated content
        # is the routing-card arrow, a class this page does not use. Neither carries an
        # @import or a CSS escape (which could spell "content" another way).
        style_re = re.compile(r"<style\b[^>]*>(.*?)</style>", re.S | re.I)
        styles = style_re.findall(self.page)
        self.assertEqual(len(styles), 1)
        self.assertEqual(styles, style_re.findall(read_site("security.html")))
        self.assertEqual(generated_content(self.page), ["content:''"])
        sheet = read_site("styles.css")
        self.assertEqual(generated_content(sheet), ["content: '→'"])
        self.assertNotIn("routing-card", self.page)
        for css in (styles[0], sheet):
            self.assertNotIn("\\", css)
            self.assertNotIn("@import", css.lower())

    def test_meta_description_is_s2(self) -> None:
        description = html.escape(self.strings["S.2.license"], quote=True)
        self.assertEqual(
            re.findall(r'<meta name="description" content="([^"]*)">', self.page), [description]
        )

    def test_head_carries_no_other_words(self) -> None:
        # The head's only words are the <title> (the license heading) and the S.2 meta
        # description: no other meta, no script, no second title.
        head = between(self.page, "<head>", "</head>")
        description = html.escape(self.strings["S.2.license"], quote=True)
        self.assertEqual(
            re.findall(r"<meta\b[^>]*>", head),
            [
                '<meta charset="UTF-8">',
                '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
                f'<meta name="description" content="{description}">',
            ],
        )
        tags = set(re.findall(r"<([a-zA-Z][a-zA-Z0-9-]*)\b", head))
        self.assertEqual(tags, {"head", "meta", "title", "link", "style"})
        self.assertEqual(len(texts_of(head, "title")), 1)
        outside = re.sub(r"<style>.*?</style>|<title>.*?</title>|<[^>]+>", "", head, flags=re.S)
        self.assertEqual(outside.strip(), "")

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

    def test_llms_txt_license_section_is_exactly_the_block(self) -> None:
        # From the license heading to the next "## " heading: the block and its blank
        # separator line, nothing else (a line after S.1 fails here).
        heading = f"## {heading_text(self.strings['license.heading'])}\n"
        section = section_until(read_site("llms.txt"), heading, "## ")
        self.assertEqual(section, llms_block(self.strings) + "\n")

    def test_agents_txt_license_section_is_exactly_the_block(self) -> None:
        heading = f"# --- {heading_text(self.strings['license.heading'])} ---\n"
        section = section_until(read_site(".well-known/agents.txt"), heading, "# --- ")
        self.assertEqual(section, agents_block(self.strings) + "\n")

    def test_llms_txt_headings_are_these_in_order(self) -> None:
        # A heading of its own directly after S.1 would close the license section early;
        # with the heading list fixed, it fails here.
        lines = read_site("llms.txt").split("\n")
        self.assertEqual([ln for ln in lines if ln.startswith("#")], llms_headings(self.strings))

    def test_agents_txt_section_headers_are_these_in_order(self) -> None:
        lines = read_site(".well-known/agents.txt").split("\n")
        self.assertEqual(
            [ln for ln in lines if ln.startswith("# --- ")], agents_headers(self.strings)
        )

    def test_llms_txt_section_above_the_license_is_exactly_its_text(self) -> None:
        # The neighbour above: a sentence just above the license heading (or anywhere in
        # the section it closes) fails here.
        heading = f"## {heading_text(self.strings['license.heading'])}\n"
        above = section_above(read_site("llms.txt"), heading, "## ")
        self.assertEqual(above, LLMS_SECTION_ABOVE_LICENSE)

    def test_agents_txt_section_above_the_license_is_exactly_its_text(self) -> None:
        heading = f"# --- {heading_text(self.strings['license.heading'])} ---\n"
        above = section_above(read_site(".well-known/agents.txt"), heading, "# --- ")
        self.assertEqual(above, AGENTS_SECTION_ABOVE_LICENSE)

    def test_agents_txt_p1_primitive_is_the_signed_token(self) -> None:
        # 782 §1.2: one token. The six primitive lines stay P1..P6 in order, and P1's is
        # the pinned token, whole (P1 authentication live, mandate binding forward-state).
        lines = read_site(".well-known/agents.txt").split("\n")
        primitives = [ln for ln in lines if ln.startswith("Primitive:")]
        self.assertEqual(
            [ln.split("=", 1)[0] for ln in primitives], [f"Primitive: P{n}" for n in range(1, 7)]
        )
        self.assertEqual(primitives[0], self.strings["782.P1"])

    def test_robots_txt_is_exactly_the_expected_text(self) -> None:
        # All of robots.txt, line for line: the posture block below plus the file's own
        # header, sitemap and agent-discovery lines. A comment or directive added
        # anywhere fails here.
        self.assertEqual(
            read_site("robots.txt"), robots_txt(self.strings, api_rendered()["content_usage"])
        )

    def test_robots_posture_is_exactly_the_ruled_block(self) -> None:
        # The header comment, the RSL record and the wildcard group, byte for byte: the
        # S.1 line, the ruled Content-Signal, the API's Content-Usage. An unsourced line
        # (the old "All crawlers: welcome ..." sentence) fails here.
        robots = read_site("robots.txt")
        posture = robots_posture(self.strings, api_rendered()["content_usage"])
        self.assertEqual(between(robots, "# Phronesis crawl policy.\n", "Allow: /\n"), posture)
        self.assertNotIn("welcome", robots.lower())

    def test_robots_directives_are_exactly_these(self) -> None:
        robots = read_site("robots.txt")
        directives = [ln for ln in robots.split("\n") if ln.strip() and not ln.startswith("#")]
        self.assertEqual(
            directives,
            [
                f"License: {RSL_DOCUMENT_URL}",
                "User-agent: *",
                f"Content-Signal: {self.strings['A.content-signal']}",
                f"Content-Usage: {api_rendered()['content_usage']}",
                "Allow: /",
                "Sitemap: https://phronesisintel.com/sitemap.xml",
            ],
        )

    def test_robots_license_record_is_global_and_names_this_hosts_document(self) -> None:
        # RSL 1.0 §4.4: a License record outside any group applies to every client; the
        # value is an absolute URI resolving to an RSL document (site/license.xml).
        lines = read_site("robots.txt").split("\n")
        records = [i for i, ln in enumerate(lines) if ln.lower().startswith("license:")]
        groups = [i for i, ln in enumerate(lines) if ln.lower().startswith("user-agent:")]
        self.assertEqual([lines[i] for i in records], [f"License: {RSL_DOCUMENT_URL}"])
        self.assertLess(records[0], groups[0])
        self.assertEqual(RSL_DOCUMENT_URL, "https://phronesisintel.com/" + "license.xml")
        self.assertTrue((SITE / "license.xml").is_file())

    def test_robots_content_usage_is_the_apis_in_the_wildcard_group(self) -> None:
        # aipref attach-05 §3: a Content-Usage rule inside a group; no path = every path.
        lines = read_site("robots.txt").split("\n")
        rules = [i for i, ln in enumerate(lines) if ln.lower().startswith("content-usage:")]
        self.assertEqual(
            [lines[i] for i in rules], [f"Content-Usage: {api_rendered()['content_usage']}"]
        )
        wildcard = lines.index("User-agent: *")
        self.assertGreater(rules[0], wildcard)
        self.assertNotIn("", lines[wildcard : rules[0]])

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


class RslDocumentTests(unittest.TestCase):
    """``site/license.xml``: this host's RSL 1.0 declaration, the API's document byte for
    byte (its one-day ``max-age`` included); served as ``application/rsl+xml``
    (``site/_headers``)."""

    document: str
    strings: dict[str, str]

    @classmethod
    def setUpClass(cls) -> None:
        cls.document = read_site("license.xml")
        cls.strings = pinned()

    def test_the_document_is_the_apis_byte_for_byte(self) -> None:
        # The API renders max-age="1" itself, so this host serves its document unchanged.
        self.assertEqual(self.document, api_rendered()["rsl_document"])

    def test_permit_and_prohibit_tokens_equal_the_apis(self) -> None:
        site = rsl_terms_of(self.document)
        rendered = api_rendered()
        self.assertEqual(site["permits"], rendered["rsl_permits_usage"])
        self.assertEqual(site["prohibits"], rendered["rsl_prohibits_usage"])
        self.assertEqual(site["payment"], rendered["rsl_payment_type"])
        self.assertEqual(site["terms"], rendered["rsl_terms"])
        self.assertEqual(site["terms"], LICENSE_URL)

    def test_the_tokens_are_rsl_1_0_usage_tokens(self) -> None:
        # RSL-SPEC-1.0 (2025-12-10) usage vocabulary; ai-all is not used (wider than
        # License clause 2).
        vocabulary = {"all", "ai-all", "ai-train", "ai-input", "ai-index", "search"}
        site = rsl_terms_of(self.document)
        self.assertLessEqual(set(site["permits"]) | set(site["prohibits"]), vocabulary)
        self.assertNotIn("ai-all", site["permits"])
        self.assertNotIn("all", site["permits"])

    def test_max_age_is_one_day(self) -> None:
        for document in (self.document, api_rendered()["rsl_document"]):
            root = ET.fromstring(document.encode("utf-8"))
            self.assertEqual(root.tag, f"{{{RSL_NAMESPACE}}}rsl")
            self.assertEqual(root.get("max-age"), RSL_MAX_AGE_DAYS)

    def test_content_url_is_this_hosts_root_path(self) -> None:
        # RSL 1.0 §3.3: for a robots.txt association the url MUST be an RFC 9309 path;
        # the robots.txt of https://phronesisintel.com/ that names this document scopes
        # it to that origin, so "/" is every path of https://phronesisintel.com/.
        self.assertEqual(rsl_terms_of(self.document)["url"], "/")

    def test_the_comment_is_s2(self) -> None:
        self.assertEqual(
            re.findall(r"<!-- (.*?) -->", self.document), [self.strings["S.2.license"]]
        )

    def test_headers_serve_the_rsl_media_type(self) -> None:
        rules = read_site("_headers").split("\n")
        at = rules.index("/license.xml")
        self.assertEqual(rules[at + 1], f"  Content-Type: {RSL_MEDIA_TYPE}")


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


#: A scorecard payload in the shape /.well-known/scorecard.json serves (the fields the
#: refresh reads, plus neighbours it must ignore). Offline: no test touches the network.
SCORECARD_FIXTURE: dict[str, Any] = {
    "status": "ok",
    "aggregate_stats": {"forecast_count": 45, "resolved_count": 0},
    "metadata": {"generated_at": "2026-10-30T04:54:10Z", "version": "fixture"},
}


class RefreshCountTests(unittest.TestCase):
    """``scripts/refresh_count.py`` against a copy of the homepage and a fixture payload."""

    home: str
    tmp: tempfile.TemporaryDirectory[str]
    index: Path

    @classmethod
    def setUpClass(cls) -> None:
        cls.home = read_site("index.html")

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.index = Path(self.tmp.name) / "index.html"
        self.index.write_bytes(self.home.encode("utf-8"))
        no_network = mock.patch.object(
            refresh_count, "fetch", side_effect=AssertionError("network used in a test")
        )
        no_network.start()
        self.addCleanup(no_network.stop)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _payload(self, **changes: Any) -> dict[str, Any]:
        data = json.loads(json.dumps(SCORECARD_FIXTURE))
        for key, value in changes.items():
            section, field = key.split("__")
            if value is None:
                data[section].pop(field, None)
            else:
                data[section][field] = value
        return dict(data)

    def _static(self, page: str) -> tuple[str, str, str, str]:
        m = _COUNT_SPAN_RE.search(page)
        assert m is not None
        t = re.search(r'<time id="record-count-as-of" datetime="([^"]+)">([^<]+)</time>', page)
        assert t is not None
        return m.group(2), m.group(1), t.group(1), t.group(2)

    def test_rewrites_the_three_values_and_no_other_byte(self) -> None:
        today = dt.date(2026, 10, 31)
        payload = self._payload(metadata__generated_at="2026-10-31T05:00:00Z")
        lines = refresh_count.refresh(self.index, payload, today)
        page = self.index.read_bytes().decode("utf-8")
        self.assertEqual(self._static(page), ("45", "2026-10-31", "2026-10-31", "2026-10-31"))
        n0, d0, _, _ = self._static(self.home)
        expected = self.home.replace(
            f'data-as-of="{d0}" {DA_COUNT_SOURCE_MARKER}>{n0}</span>',
            f'data-as-of="2026-10-31" {DA_COUNT_SOURCE_MARKER}>45</span>',
        ).replace(
            f'<time id="record-count-as-of" datetime="{d0}">{d0}</time>',
            '<time id="record-count-as-of" datetime="2026-10-31">2026-10-31</time>',
        )
        self.assertEqual(page, expected)
        self.assertEqual(
            lines,
            [
                f"forecast_count: {n0} -> 45",
                f"data-as-of: {d0} -> 2026-10-31",
                f"<time>: {d0} -> 2026-10-31",
                "index.html: written",
            ],
        )
        # The page still meets the homepage tests' form and the gate's regex.
        gate = _GATE_COUNT_RE.search(page)
        assert gate is not None
        self.assertEqual(gate.group(1), "45")

    def test_keeps_crlf_line_ends(self) -> None:
        self.index.write_bytes(self.home.replace("\n", "\r\n").encode("utf-8"))
        refresh_count.refresh(self.index, self._payload(), dt.date(2026, 10, 30))
        raw = self.index.read_bytes()
        self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"))
        self.assertEqual(self._static(raw.decode("utf-8"))[0], "45")

    def test_dry_run_writes_nothing(self) -> None:
        lines = refresh_count.refresh(self.index, self._payload(), dt.date(2026, 10, 30), write=False)
        self.assertEqual(self.index.read_bytes().decode("utf-8"), self.home)
        self.assertEqual(lines[-1], "index.html: dry run; nothing written")

    def test_current_values_write_nothing(self) -> None:
        n0, d0, _, _ = self._static(self.home)
        payload = self._payload(
            aggregate_stats__forecast_count=int(n0), metadata__generated_at=f"{d0}T00:00:00Z"
        )
        lines = refresh_count.refresh(self.index, payload, dt.date.fromisoformat(d0))
        self.assertEqual(lines[-1], "index.html: already current; nothing written")
        self.assertEqual(self.index.read_bytes().decode("utf-8"), self.home)

    def test_refuses_and_leaves_the_file_untouched(self) -> None:
        today = dt.date(2026, 10, 30)
        cases: dict[str, Any] = {
            "outage envelope": {"status": "insufficient_sample", "aggregate_stats": {}},
            "count absent": self._payload(aggregate_stats__forecast_count=None),
            "count a string": self._payload(aggregate_stats__forecast_count="45"),
            "count a bool": self._payload(aggregate_stats__forecast_count=True),
            "count negative": self._payload(aggregate_stats__forecast_count=-1),
            "count a float": self._payload(aggregate_stats__forecast_count=45.0),
            "no generated_at": self._payload(metadata__generated_at=None),
            "date unreadable": self._payload(metadata__generated_at="Oct 30 2026"),
            "date not real": self._payload(metadata__generated_at="2026-02-30T00:00:00Z"),
            "date in the future": self._payload(metadata__generated_at="2026-10-31T00:00:00Z"),
            "not an object": [45],
        }
        for name, payload in cases.items():
            with self.subTest(case=name):
                with self.assertRaises(refresh_count.Refused):
                    refresh_count.refresh(self.index, payload, today)
                self.assertEqual(self.index.read_bytes().decode("utf-8"), self.home)

    def test_refuses_when_the_markup_is_not_found_once(self) -> None:
        today = dt.date(2026, 10, 30)
        span = _COUNT_SPAN_RE.search(self.home)
        assert span is not None
        for name, page in {
            "span missing": self.home.replace('id="record-count" ', 'id="other" ', 1),
            "span twice": self.home.replace(span.group(0), span.group(0) * 2, 1),
            "time missing": self.home.replace('id="record-count-as-of"', 'id="other"', 1),
        }.items():
            with self.subTest(case=name):
                self.index.write_bytes(page.encode("utf-8"))
                with self.assertRaises(refresh_count.Refused):
                    refresh_count.refresh(self.index, self._payload(), today)
                self.assertEqual(self.index.read_bytes().decode("utf-8"), page)

    def test_the_command_line_reads_a_file_and_prints_old_to_new(self) -> None:
        source = Path(self.tmp.name) / "scorecard.json"
        source.write_text(json.dumps(SCORECARD_FIXTURE), encoding="utf-8")
        n0, d0, _, _ = self._static(self.home)
        out: list[str] = []
        with mock.patch.object(refresh_count, "INDEX", self.index), mock.patch(
            "builtins.print", side_effect=lambda *a: out.append(" ".join(map(str, a)))
        ):
            rc = refresh_count.main(["refresh_count.py", "--from-file", str(source)])
            bad = Path(self.tmp.name) / "outage.json"
            bad.write_text(json.dumps({"aggregate_stats": {}}), encoding="utf-8")
            rc_bad = refresh_count.main(["refresh_count.py", "--from-file", str(bad)])
            rc_usage = refresh_count.main(["refresh_count.py", "--nope"])
        self.assertEqual((rc, rc_bad, rc_usage), (0, 1, 2))
        self.assertIn(f"forecast_count: {n0} -> 45", out)
        self.assertIn(f"data-as-of: {d0} -> 2026-10-30", out)
        self.assertTrue(any(line.startswith("REFUSED: aggregate_stats") for line in out))
        self.assertEqual(self._static(self.index.read_bytes().decode("utf-8"))[0], "45")


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

    def test_no_other_published_line_carries_the_p1_token(self) -> None:
        # 782 §1.2's census rule: the token shape flips wherever this host publishes it.
        # It is published once: the agents.txt P1 line, which is the signed token.
        found: list[tuple[str, str]] = []
        for path in sorted(SITE.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(SITE).as_posix()
            try:
                text = read_site(rel)  # LF line ends, as every test here reads a file
            except UnicodeDecodeError:
                continue
            found += [(rel, ln) for ln in text.split("\n") if P1_TOKEN_SHAPE in ln]
        self.assertEqual(found, [(".well-known/agents.txt", pinned()["782.P1"])])


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
