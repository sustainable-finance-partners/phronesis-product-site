#!/usr/bin/env python3
"""Site gates for phronesis-product-site: what the host publishes, and vendor names.

The host (the Cloudflare Pages project ``phronesis-product-site``, build output
directory ``site``) publishes the folder ``site/`` and nothing else. Everything at
the repository root outside ``site/`` is repository-only: the operating pointer,
the README, the workflows, the gate configuration, this script and the skills
draft. A structural fix cannot regress by a forgotten ignore entry; these checks
keep the structure.

Commands:
  publish-folder  (CI) The root holds only the repository-only entries in
                  ``REPO_ONLY_ROOT``. ``site/`` holds none of the repository-only
                  names in ``NEVER_PUBLISHED``, at any depth. ``site/`` holds
                  ``index.html`` and ``404.html``: without a top-level 404.html,
                  Pages answers an unknown path with the homepage and a 200, so no
                  path could return 404.
  vendor-names    (CI) No vendor product name on a published file or the skills
                  draft, except inside a ratified string allow-listed for that
                  file (``gates/vendor_names.json``). Report-tier names are listed
                  on every run, ratified or not, and fail nothing.
  live-404        (desk, after the merge deploys) GET the repository-only paths on
                  the named hosts; every one must answer 404.

Every command runs its own self-test first, verdict included: a check that cannot
fail is not a check. Exit status: 0 pass, 1 fail, 2 usage error.
Standard library only; CI runs it with the runner's ``python3``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
PUBLISH_DIR = "site"
CONFIG = Path("gates") / "vendor_names.json"

#: Every entry allowed at the repository root. Anything else at the root is either
#: a public file in the wrong place (it would silently not be published) or a new
#: repository-only entry that has to be named here on purpose.
REPO_ONLY_ROOT = frozenset(
    {
        ".git",
        ".gitattributes",
        ".gitignore",
        ".github",
        "CLAUDE.md",
        "README.md",
        "gates",
        "scripts",
        "skills",
        PUBLISH_DIR,
    }
)

#: Tool caches a desk run leaves at the root (never committed, never published).
#: The root check passes over them so a local lint run does not turn it red.
LOCAL_ONLY_ROOT = frozenset(
    {
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "node_modules",
    }
)

#: Names that are never published: no file or directory under ``site/``, at any
#: depth, carries one of them (compared case-insensitively). The first four are
#: the ruled set (they must answer 404 on the host); the rest are repository
#: metadata.
NEVER_PUBLISHED = frozenset(
    {
        "claude.md",
        "readme.md",
        "skills",
        ".github",
        ".git",
        ".gitattributes",
        ".gitignore",
    }
)

#: Files the host needs at the top of the publish folder.
REQUIRED_IN_SITE = ("index.html", "404.html")

#: The repository-only paths the live check GETs: one per ruled class
#: (/CLAUDE.md, /README.md, /skills/*, /.github/*), each a file the repo carries.
LIVE_404_PATHS = (
    "/CLAUDE.md",
    "/README.md",
    "/skills/setup.md",
    "/.github/workflows/algo-protection-gate.yml",
)
LIVE_TIMEOUT_SECONDS = 10.0


# ── publish-folder ───────────────────────────────────────────────────────────


def publish_folder_failures(root: Path) -> list[str]:
    """Every way the tree at ``root`` breaks the publish-folder rule, one line each."""
    failures: list[str] = []
    site = root / PUBLISH_DIR
    if not site.is_dir():
        return [
            f"PUBLISH-FOLDER: {PUBLISH_DIR}/ is missing; the host publishes nothing"
        ]
    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if entry.name not in REPO_ONLY_ROOT | LOCAL_ONLY_ROOT:
            failures.append(
                f"PUBLISH-FOLDER[root]: {entry.name} sits at the repository root, which is "
                f"not published; a public file belongs in {PUBLISH_DIR}/, a repository-only "
                "entry is named in REPO_ONLY_ROOT"
            )
    for path in sorted(site.rglob("*")):
        if path.name.lower() in NEVER_PUBLISHED:
            rel = path.relative_to(root).as_posix()
            failures.append(
                f"PUBLISH-FOLDER[never-published]: {rel} is inside the publish folder; "
                "repository-only files stay at the root"
            )
    for name in REQUIRED_IN_SITE:
        if not (site / name).is_file():
            failures.append(
                f"PUBLISH-FOLDER[required]: {PUBLISH_DIR}/{name} is missing"
            )
    return failures


def _touch(root: Path, rel: str, text: str = "x\n") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _good_tree(root: Path) -> None:
    for rel in (
        "CLAUDE.md",
        "README.md",
        ".gitattributes",
        ".github/workflows/gate.yml",
        "gates/vendor_names.json",
        "scripts/site_gates.py",
        "skills/setup.md",
        "site/index.html",
        "site/404.html",
        "site/.well-known/agents.txt",
    ):
        _touch(root, rel)


#: (case, extra files on top of the good tree, file to delete, expected failures)
_PUBLISH_CASES: tuple[tuple[str, tuple[str, ...], str | None, int], ...] = (
    ("the good tree passes", (), None, 0),
    ("a public page left at the root", ("index.html",), None, 1),
    ("a desk lint cache at the root", (".ruff_cache/x",), None, 0),
    ("an operating pointer inside the publish folder", ("site/CLAUDE.md",), None, 1),
    ("a README one level down", ("site/docs/README.md",), None, 1),
    ("a lower-case readme", ("site/readme.md",), None, 1),
    ("a skills folder published", ("site/skills/setup.md",), None, 1),
    ("a workflow folder published", ("site/.github/workflows/gate.yml",), None, 1),
    ("no 404 page", (), "site/404.html", 1),
)


def publish_folder_report(root: Path) -> tuple[int, list[str]]:
    """The verdict on the tree at ``root`` (0 pass, 1 fail) and the lines that give it."""
    failures = publish_folder_failures(root)
    if failures:
        return 1, [
            f"PUBLISH-FOLDER: FAIL ({len(failures)})",
            *(f"  {line}" for line in failures),
        ]
    published = sum(1 for p in (root / PUBLISH_DIR).rglob("*") if p.is_file())
    kept = sorted(p.name for p in root.iterdir() if p.name != PUBLISH_DIR)
    return 0, [
        f"PUBLISH-FOLDER: OK ({published} files published from {PUBLISH_DIR}/; "
        f"repository-only at the root: {', '.join(kept)})"
    ]


def publish_folder_self_test() -> list[str]:
    """Run the check over seeded trees; return a line for every case that misbehaves.

    Each case checks both the failure lines and the verdict the command returns, so
    a verdict that ignores its failures cannot pass the self-test."""
    problems: list[str] = []
    for case, extra, delete, expected in _PUBLISH_CASES:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _good_tree(root)
            for rel in extra:
                _touch(root, rel)
            if delete is not None:
                (root / delete).unlink()
            got = publish_folder_failures(root)
            if len(got) != expected:
                problems.append(
                    f"{case}: expected {expected} failure(s), got {len(got)}: {got}"
                )
            verdict, _ = publish_folder_report(root)
            if verdict != (1 if expected else 0):
                problems.append(
                    f"{case}: expected exit {1 if expected else 0}, got {verdict}"
                )
    return problems


def cmd_publish_folder(root: Path) -> int:
    problems = publish_folder_self_test()
    if problems:
        print("PUBLISH-FOLDER SELF-TEST: FAIL")
        for line in problems:
            print(f"  {line}")
        return 1
    print(f"PUBLISH-FOLDER SELF-TEST: OK ({len(_PUBLISH_CASES)} seeded trees)")
    verdict, lines = publish_folder_report(root)
    for line in lines:
        print(line)
    return verdict


# ── vendor-names ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Name:
    text: str
    tier: str  # "fail" or "report"
    pattern: re.Pattern[str]


@dataclass(frozen=True)
class Allowed:
    file: str
    text: str
    source: str


@dataclass(frozen=True)
class VendorConfig:
    roots: tuple[str, ...]
    exclude: frozenset[str]
    names: tuple[Name, ...]
    allowlist: tuple[Allowed, ...]


@dataclass(frozen=True)
class Hit:
    file: str
    line: int
    name: Name
    found: str
    source: str | None  # the allowlist source when inside a ratified string


def name_pattern(text: str, any_case: bool) -> re.Pattern[str]:
    """A name as a whole word: no letter may touch either end ("ChatGPT-4o" and
    "openai_chatgpt" match; "cursor:" in CSS does not match "Cursor", which is
    exact-case). Words inside a name may be split by any run of white space."""
    body = r"\s+".join(re.escape(word) for word in text.split())
    return re.compile(
        r"(?<![A-Za-z])" + body + r"(?![A-Za-z])", re.IGNORECASE if any_case else 0
    )


def _strings(value: Any, where: str) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(v, str) and v.strip() for v in value
    ):
        raise ValueError(f"{where} must be a list of non-empty strings")
    return list(value)


def load_config(data: dict[str, Any]) -> VendorConfig:
    names: list[Name] = []
    for tier in ("fail", "report"):
        block = data.get(tier, {})
        if not isinstance(block, dict):
            raise ValueError(f"{tier} must be an object")
        for key, any_case in (("any_case", True), ("exact_case", False)):
            for text in _strings(block.get(key, []), f"{tier}.{key}"):
                names.append(Name(text, tier, name_pattern(text, any_case)))
    allowlist: list[Allowed] = []
    for i, row in enumerate(data.get("allowlist", [])):
        if not isinstance(row, dict):
            raise ValueError(f"allowlist[{i}] must be an object")
        values = [row.get(k) for k in ("file", "text", "source")]
        if not all(isinstance(v, str) and v.strip() for v in values):
            raise ValueError(f"allowlist[{i}] needs non-empty file, text and source")
        allowlist.append(Allowed(str(values[0]), str(values[1]), str(values[2])))
    scan = data.get("scan", {})
    return VendorConfig(
        roots=tuple(_strings(scan.get("roots", []), "scan.roots")),
        exclude=frozenset(_strings(scan.get("exclude", []), "scan.exclude")),
        names=tuple(names),
        allowlist=tuple(allowlist),
    )


def _text_files(root: Path, config: VendorConfig) -> Iterator[tuple[str, str]]:
    for top in config.roots:
        for path in sorted((root / top).rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if rel in config.exclude:
                continue
            try:
                yield rel, path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue  # a binary asset carries no copy


def _spans(text: str, needle: str) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    start = text.find(needle)
    while start != -1:
        out.append((start, start + len(needle)))
        start = text.find(needle, start + 1)
    return out


def scan_vendor_names(
    root: Path, config: VendorConfig
) -> tuple[list[Hit], list[str], int]:
    """(every hit, every allowlist problem, files scanned)."""
    hits: list[Hit] = []
    problems: list[str] = []
    by_file: dict[str, list[Allowed]] = {}
    for row in config.allowlist:
        by_file.setdefault(row.file, []).append(row)
        if not any(n.pattern.search(row.text) for n in config.names):
            problems.append(
                f"ALLOWLIST[no-name]: {row.file}: {row.text!r} names no listed vendor; "
                "an entry exists only to sanction a name"
            )
    scanned = 0
    seen_files: set[str] = set()
    for rel, text in _text_files(root, config):
        scanned += 1
        seen_files.add(rel)
        sanctioned: list[tuple[int, int, str]] = []
        for row in by_file.get(rel, []):
            spans = _spans(text, row.text)
            if not spans:
                problems.append(
                    f"ALLOWLIST[stale]: {rel}: {row.text!r} no longer occurs in the file; "
                    "the page changed or the entry is wrong"
                )
            sanctioned.extend((a, b, row.source) for a, b in spans)
        for name in config.names:
            for match in name.pattern.finditer(text):
                source = next(
                    (
                        s
                        for a, b, s in sanctioned
                        if a <= match.start() and match.end() <= b
                    ),
                    None,
                )
                line = text.count("\n", 0, match.start()) + 1
                hits.append(Hit(rel, line, name, match.group(0), source))
    for rel in sorted(set(by_file) - seen_files):
        problems.append(f"ALLOWLIST[no-file]: {rel} is not a scanned file")
    hits.sort(key=lambda h: (h.file, h.line, h.found))
    return hits, problems, scanned


#: Matcher probes: (text, name expected to match it, or None for "matches nothing").
_MATCH_PROBES: tuple[tuple[str, str | None], ...] = (
    ("Ask ChatGPT.", "ChatGPT"),
    ("CHATGPT", "ChatGPT"),
    ("chatgpt-4o", "ChatGPT"),
    ('"openai_chatgpt"', "ChatGPT"),
    ("GitHub Copilot", "Copilot"),
    ("in Cursor", "Cursor"),
    ("Codex CLI", "Codex"),
    ("Hugging  Face", "Hugging Face"),
    ("cursor: pointer;", None),
    ("a codex of rules", None),
    ("perplexity of a model", None),
    ("ChatGPTs", None),
    ("theChatGPT", None),
)

_SELF_TEST_CONFIG: dict[str, Any] = {
    "scan": {"roots": ["site", "skills"], "exclude": ["site/robots.txt"]},
    "fail": {
        "any_case": ["ChatGPT", "Copilot", "Hugging Face"],
        "exact_case": ["Cursor", "Codex", "Perplexity"],
    },
    "report": {"exact_case": ["Stripe"]},
    "allowlist": [
        {"file": "site/ok.html", "text": "Works in ChatGPT.", "source": "self-test"},
        {
            "file": "site/pay.html",
            "text": "Humans pay by card through Stripe.",
            "source": "self-test",
        },
    ],
}

#: (relative file, contents) for the seeded tree.
_SELF_TEST_FILES: tuple[tuple[str, str], ...] = (
    ("site/a.html", "<p>Ask ChatGPT.</p>\n"),
    ("site/b.html", "<p>Use Cursor or Codex.</p>\n"),
    ("site/c.html", '<p style="cursor: pointer">a codex of rules</p>\n'),
    ("site/d.json", '{"partner": "openai_chatgpt"}\n'),
    ("site/ok.html", "<p>Works in ChatGPT.</p>\n<p>ChatGPT again.</p>\n"),
    ("site/other.html", "<p>Works in ChatGPT.</p>\n"),
    ("site/pay.html", "<p>Humans pay by card through Stripe. Stripe (cards).</p>\n"),
    ("site/robots.txt", "User-agent: ChatGPT-User\n"),
    ("skills/setup.md", "Use Copilot.\n"),
)

#: What the scan of the seeded tree must find: unsanctioned fail-tier hits, the
#: sanctioned one, report-tier hits ratified and not.
_SELF_TEST_EXPECT = {
    "fail": 7,
    "sanctioned": 1,
    "report_ratified": 1,
    "report_unratified": 1,
}


def vendor_self_test(config: VendorConfig) -> list[str]:
    """The shipped names each match themselves; the seeded tree scans as expected."""
    problems: list[str] = []
    for name in config.names:
        probes = [name.text]
        if name.pattern.flags & re.IGNORECASE:
            probes += [name.text.upper(), name.text.lower()]
        for probe in probes:
            if not name.pattern.search(probe):
                problems.append(f"shipped name {name.text!r} does not match {probe!r}")
    test_config = load_config(_SELF_TEST_CONFIG)
    by_text = {n.text: n for n in test_config.names}
    for probe, expected in _MATCH_PROBES:
        matched = [n.text for n in test_config.names if n.pattern.search(probe)]
        want = [expected] if expected else []
        if matched != want:
            problems.append(f"probe {probe!r}: expected {want}, matched {matched}")
    if set(by_text) != {
        "ChatGPT",
        "Copilot",
        "Hugging Face",
        "Cursor",
        "Codex",
        "Perplexity",
        "Stripe",
    }:
        problems.append(f"self-test config loaded the wrong names: {sorted(by_text)}")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for rel, text in _SELF_TEST_FILES:
            _touch(root, rel, text)
        hits, allow_problems, _ = scan_vendor_names(root, test_config)
        got = {
            "fail": sum(1 for h in hits if h.name.tier == "fail" and h.source is None),
            "sanctioned": sum(
                1 for h in hits if h.name.tier == "fail" and h.source is not None
            ),
            "report_ratified": sum(
                1 for h in hits if h.name.tier == "report" and h.source
            ),
            "report_unratified": sum(
                1 for h in hits if h.name.tier == "report" and not h.source
            ),
        }
        if got != _SELF_TEST_EXPECT:
            problems.append(f"seeded tree: expected {_SELF_TEST_EXPECT}, got {got}")
        if allow_problems:
            problems.append(
                f"seeded tree: unexpected allowlist problems {allow_problems}"
            )
        # A stale entry and an entry that names no vendor are each a failure.
        stale = load_config(
            {
                **_SELF_TEST_CONFIG,
                "allowlist": [
                    {
                        "file": "site/a.html",
                        "text": "ChatGPT is not on the page.",
                        "source": "self-test",
                    },
                    {"file": "site/a.html", "text": "Ask", "source": "self-test"},
                    {
                        "file": "site/missing.html",
                        "text": "ChatGPT",
                        "source": "self-test",
                    },
                ],
            }
        )
        _, stale_problems, _ = scan_vendor_names(root, stale)
        kinds = sorted(p.split(":", 1)[0] for p in stale_problems)
        want_kinds = sorted(
            ["ALLOWLIST[stale]", "ALLOWLIST[no-name]", "ALLOWLIST[no-file]"]
        )
        if kinds != want_kinds:
            problems.append(f"allowlist checks: expected {want_kinds}, got {kinds}")
        # The verdict the command returns, not only the counts behind it: the seeded
        # tree carries unsanctioned fail-tier hits, and a stale allowlist fails.
        for case, case_config in (
            ("the seeded tree", test_config),
            ("a stale allowlist", stale),
        ):
            got_exit, _ = vendor_names_report(root, case_config, ())
            if got_exit != 1:
                problems.append(f"{case}: expected exit 1, got {got_exit}")
    with tempfile.TemporaryDirectory() as tmp:
        # A clean tree: a sanctioned fail-tier name, report-tier names ratified and
        # not, and an excluded crawler directive. It passes; it fails only when a
        # ratified source is named that lacks an allow-listed string.
        root = Path(tmp)
        for rel, text in _SELF_TEST_FILES:
            if rel in {"site/ok.html", "site/pay.html", "site/robots.txt"}:
                _touch(root, rel, text.split("\n")[0] + "\n")
        both = "Works in ChatGPT. Humans pay by card through Stripe."
        clean: tuple[tuple[str, tuple[tuple[str, str], ...], int], ...] = (
            ("a clean tree", (), 0),
            ("a clean tree, both strings ratified", (("ratified.md", both),), 0),
            (
                "a clean tree, one string not ratified",
                (("ratified.md", "Works in ChatGPT."),),
                1,
            ),
        )
        for case, corpora, want_exit in clean:
            got_exit, _ = vendor_names_report(root, test_config, corpora)
            if got_exit != want_exit:
                problems.append(f"{case}: expected exit {want_exit}, got {got_exit}")
    return problems


def _context(path: Path, line: int) -> str:
    text = path.read_text(encoding="utf-8").split("\n")[line - 1].strip()
    return text if len(text) <= 160 else text[:157] + "..."


def ratified_problems(
    config: VendorConfig, corpora: Sequence[tuple[str, str]]
) -> list[str]:
    """Every allowlist row whose string occurs verbatim in none of ``corpora``
    (each a source name and its text)."""
    names = ", ".join(name for name, _ in corpora)
    return [
        f"ALLOWLIST[not-ratified]: {row.file}: {row.text!r} does not occur verbatim "
        f"in any of {names}"
        for row in config.allowlist
        if not any(row.text in text for _, text in corpora)
    ]


def vendor_names_report(
    root: Path, config: VendorConfig, corpora: Sequence[tuple[str, str]]
) -> tuple[int, list[str]]:
    """The verdict on the tree at ``root`` (0 pass, 1 fail) and the lines that give
    it. ``corpora`` (source name, text) are the ratified copy files every allowlist
    string must occur in verbatim; empty in CI."""
    lines: list[str] = []
    hits, allow_problems, scanned = scan_vendor_names(root, config)
    if corpora:
        allow_problems += ratified_problems(config, corpora)
        names = ", ".join(name for name, _ in corpora)
        lines.append(
            f"  allowlist checked verbatim against {len(corpora)} ratified source file(s): {names}"
        )
    failing = [h for h in hits if h.name.tier == "fail" and h.source is None]
    for hit in hits:
        if hit.name.tier == "fail" and hit.source is None:
            state = "FAIL (not inside a ratified string allow-listed for this file)"
        elif hit.source is not None:
            state = f"inside a ratified string ({hit.source})"
        else:
            state = "REPORT ONLY: not inside an allow-listed ratified string"
        lines.append(
            f"  {hit.name.tier.upper():6} {hit.file}:{hit.line} {hit.found!r} -> {state}"
        )
        lines.append(f"         | {_context(root / hit.file, hit.line)}")
    lines.extend(f"  {line}" for line in allow_problems)
    report = [h for h in hits if h.name.tier == "report"]
    lines.append(
        f"VENDOR NAMES COMPARED: {scanned} files under {', '.join(config.roots)}; "
        f"fail-tier hits {sum(1 for h in hits if h.name.tier == 'fail')} "
        f"({len(failing)} unsanctioned); report-tier hits {len(report)} "
        f"({sum(1 for h in report if h.source)} inside ratified strings, "
        f"{sum(1 for h in report if not h.source)} not)"
    )
    if failing or allow_problems:
        lines.append(
            f"VENDOR-NAMES: FAIL ({len(failing)} hit(s), {len(allow_problems)} allowlist problem(s))"
        )
        return 1, lines
    lines.append("VENDOR-NAMES: OK")
    return 0, lines


def cmd_vendor_names(
    root: Path, config_path: Path, ratified_sources: Sequence[Path]
) -> int:
    try:
        config = load_config(json.loads(config_path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        print(f"VENDOR-NAMES: FAIL (config {config_path}: {exc})")
        return 1
    try:
        corpora = [(p.name, p.read_text(encoding="utf-8")) for p in ratified_sources]
    except (OSError, ValueError) as exc:
        print(f"VENDOR-NAMES: FAIL (ratified source: {exc})")
        return 1
    problems = vendor_self_test(config)
    if problems:
        print("VENDOR-NAMES SELF-TEST: FAIL")
        for line in problems:
            print(f"  {line}")
        return 1
    print(
        f"VENDOR-NAMES SELF-TEST: OK ({len(_MATCH_PROBES)} probes, "
        f"{len(config.names)} shipped names, seeded trees as expected)"
    )
    verdict, lines = vendor_names_report(root, config, corpora)
    for line in lines:
        print(line)
    return verdict


# ── live-404 ─────────────────────────────────────────────────────────────────


def _status(url: str) -> int:
    request = urllib.request.Request(
        url, headers={"User-Agent": "phronesis-site-gate/1.0"}
    )
    try:
        # S310: the URL is built from a host the operator names on the command line.
        with urllib.request.urlopen(request, timeout=LIVE_TIMEOUT_SECONDS) as response:  # noqa: S310
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except (urllib.error.URLError, OSError):
        return 0


def live_404_report(
    hosts: Iterable[str], fetch: Callable[[str], int] = _status
) -> tuple[int, list[str]]:
    """GET every repository-only path on every host with ``fetch`` (url -> status);
    the verdict (0 only when every GET answered 404) and the lines that give it."""
    lines: list[str] = []
    failed = 0
    total = 0
    for host in hosts:
        for path in LIVE_404_PATHS:
            url = f"https://{host}{path}"
            status = fetch(url)
            total += 1
            ok = status == 404
            failed += not ok
            lines.append(f"  {'ok  ' if ok else 'FAIL'} GET {url} -> {status}")
    if failed or not total:
        lines.append(f"LIVE-404: FAIL ({failed} of {total} did not answer 404)")
        return 1, lines
    lines.append(f"LIVE-404: OK ({total} of {total} answered 404)")
    return 0, lines


#: (case, the status one path answers on the second host; every other GET answers
#: 404, expected exit). A 404 is the only pass: a 200 is the file served or a soft
#: 404 (the homepage), a 0 an unreachable host, and a 403 or 410 is not the ruling.
_LIVE_CASES: tuple[tuple[str, int, int], ...] = (
    ("every path answers 404", 404, 0),
    ("a served file or a soft 404 (200)", 200, 1),
    ("an unreachable host (0)", 0, 1),
    ("a refused path (403)", 403, 1),
    ("a gone path (410)", 410, 1),
)


def live_404_self_test() -> list[str]:
    """The verdict over a fake fetch: every path on every host is asked for, and
    only an all-404 run passes. No network."""
    problems: list[str] = []
    hosts = ("one.test", "two.test")
    odd = f"https://two.test{LIVE_404_PATHS[-1]}"
    for case, status, want in _LIVE_CASES:
        asked: list[str] = []

        def fake(url: str, status: int = status, asked: list[str] = asked) -> int:
            asked.append(url)
            return status if url == odd else 404

        got, _ = live_404_report(hosts, fake)
        if got != want:
            problems.append(f"{case}: expected exit {want}, got {got}")
        if len(asked) != len(hosts) * len(LIVE_404_PATHS):
            problems.append(
                f"{case}: expected {len(hosts) * len(LIVE_404_PATHS)} GETs, got {len(asked)}"
            )
    if live_404_report((), lambda url: 404)[0] != 1:
        problems.append("no host named: expected exit 1")
    return problems


def cmd_live_404(hosts: Iterable[str]) -> int:
    problems = live_404_self_test()
    if problems:
        print("LIVE-404 SELF-TEST: FAIL")
        for line in problems:
            print(f"  {line}")
        return 1
    print(f"LIVE-404 SELF-TEST: OK ({len(_LIVE_CASES) + 1} cases, no network)")
    verdict, lines = live_404_report(hosts)
    for line in lines:
        print(line)
    return verdict


def main(argv: Sequence[str] | None = None) -> int:
    # The report quotes page text (section signs, dashes); a desk console or a log
    # redirect on Windows would otherwise write it in the ANSI code page.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="repository root")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("publish-folder", help="the host publishes site/ and nothing else")
    vendor = sub.add_parser(
        "vendor-names", help="vendor names only inside ratified strings"
    )
    vendor.add_argument(
        "--config", type=Path, default=None, help="default: gates/vendor_names.json"
    )
    vendor.add_argument(
        "--ratified-source",
        type=Path,
        action="append",
        default=[],
        help="desk only: a ratified copy file every allowlist string must occur in verbatim",
    )
    live = sub.add_parser("live-404", help="GET the repository-only paths on each host")
    live.add_argument("hosts", nargs="+", help="host names, e.g. phronesisintel.com")
    args = parser.parse_args(argv)
    root: Path = args.root.resolve()
    if args.command == "publish-folder":
        return cmd_publish_folder(root)
    if args.command == "vendor-names":
        return cmd_vendor_names(
            root, args.config or root / CONFIG, args.ratified_source
        )
    return cmd_live_404(args.hosts)


if __name__ == "__main__":
    sys.exit(main())
