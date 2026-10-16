#!/usr/bin/env python3
"""Site gates for phronesis-product-site: what the host publishes, vendor names, and
internal names on public pages.

The host (the Cloudflare Pages project ``phronesis-product-site``, build output
directory ``site``) publishes the folder ``site/`` and nothing else. Everything at
the repository root outside ``site/`` is repository-only: the operating pointer,
the README, the workflows, the gate configuration and this script. The skills setup
guide is public by design (ADR-0034, §15.10.767 §R8.2): it lives at
``site/skills/setup.md`` and is served at the stable path ``/skills/setup``. A
structural fix cannot regress by a forgotten ignore entry; these checks keep the
structure.

Commands:
  publish-folder  (CI) The root holds only the repository-only entries in
                  ``REPO_ONLY_ROOT``. ``site/`` holds none of the repository-only
                  names in ``NEVER_PUBLISHED``, at any depth. ``site/`` holds
                  ``index.html`` and ``404.html`` (without a top-level 404.html,
                  Pages answers an unknown path with the homepage and a 200, so no
                  path could return 404) and the skills guide, and ``_redirects``
                  carries the rewrite that serves it at its stable path.
  vendor-names    (CI) No vendor product name on a published file, except inside
                  a ratified string allow-listed for that file
                  (``gates/vendor_names.json``). Report-tier names are listed on
                  every run, ratified or not, and fail nothing.
  taxonomy-leaks  (CI) No internal component name, governance reference, internal
                  rule or cluster number, or retired claim-state on a published
                  file (``gates/taxonomy_leaks.json``, §15.10.767 §S.4). A
                  fail-tier hit fails unless it lies inside a pending string listed
                  for that file (an occurrence with no ratified replacement yet,
                  printed on every run until Logos passes one); report-tier rules
                  list what is not yet ruled and fail nothing. Every rule carries
                  seeded fixtures that must fail it, and a recurrence floor held
                  in code (``RECURRENCE_FLOOR``) must fail the list whatever it
                  is edited to.
  live-404        (desk, after the merge deploys) GET the repository-only paths on
                  the named hosts (every one must answer 404) and the public stable
                  paths (every one must answer 200).

Every command runs its own self-test first, verdict included: a check that cannot
fail is not a check. Exit status: 0 pass, 1 fail, 2 usage error.
Standard library only; CI runs it with the runner's ``python3``.
"""

from __future__ import annotations

import argparse
import dataclasses
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
LEAK_CONFIG = Path("gates") / "taxonomy_leaks.json"

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
#: depth, carries one of them (compared case-insensitively). The first three are
#: the ruled set (/CLAUDE.md, /README.md and /.github/* must answer 404 on the
#: host); the rest are repository metadata. ``skills`` is not here: the setup
#: guide is public by design (ADR-0034).
NEVER_PUBLISHED = frozenset(
    {
        "claude.md",
        "readme.md",
        ".github",
        ".git",
        ".gitattributes",
        ".gitignore",
    }
)

#: Files the host needs inside the publish folder.
REQUIRED_IN_SITE = ("index.html", "404.html", "skills/setup.md")

#: ``site/_redirects`` rules that must be present, as (source, destination,
#: status): the skills guide is served at its stable path (§15.10.767 §R8.2).
REQUIRED_REWRITES: tuple[tuple[str, str, str], ...] = (
    ("/skills/setup", "/skills/setup.md", "200"),
)

#: The repository-only paths the live check GETs: one file per repository-only
#: root entry the repo carries (/CLAUDE.md, /README.md, /.github/* and every other
#: root file), each of which must answer 404.
LIVE_404_PATHS = (
    "/CLAUDE.md",
    "/README.md",
    "/.gitattributes",
    "/.github/workflows/algo-protection-gate.yml",
    "/gates/vendor_names.json",
    "/scripts/site_gates.py",
)
#: Root entries the live check has no path for: git's own metadata is never
#: pushed to the host, and the publish folder is what the host serves.
LIVE_404_UNPROBED = frozenset({".git", ".gitignore", PUBLISH_DIR})
#: The public stable paths the live check GETs; each must answer 200.
LIVE_200_PATHS = ("/skills/setup",)
LIVE_TIMEOUT_SECONDS = 10.0


# ── publish-folder ───────────────────────────────────────────────────────────


def _rewrites(path: Path) -> set[tuple[str, ...]]:
    """The rules in a Pages ``_redirects`` file, each as its whitespace-split tokens."""
    if not path.is_file():
        return set()
    rules: set[tuple[str, ...]] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            rules.add(tuple(line.split()))
    return rules


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
    rules = _rewrites(site / "_redirects")
    for rule in REQUIRED_REWRITES:
        if rule not in rules:
            failures.append(
                f"PUBLISH-FOLDER[stable-path]: {PUBLISH_DIR}/_redirects lacks the rule "
                f"'{' '.join(rule)}'; {rule[0]} is a public stable path"
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
        "site/index.html",
        "site/404.html",
        "site/skills/setup.md",
        "site/.well-known/agents.txt",
    ):
        _touch(root, rel)
    _touch(
        root,
        "site/_redirects",
        "# comment\n/agents.txt /.well-known/agents.txt 301\n"
        + "".join(" ".join(rule) + "\n" for rule in REQUIRED_REWRITES),
    )


#: (case, extra files on top of the good tree, file to delete, expected failures).
#: An extra file is written as "x", so an extra ``site/_redirects`` replaces the
#: good tree's rules with none.
_PUBLISH_CASES: tuple[tuple[str, tuple[str, ...], str | None, int], ...] = (
    ("the good tree passes", (), None, 0),
    ("a public page left at the root", ("index.html",), None, 1),
    ("a desk lint cache at the root", (".ruff_cache/x",), None, 0),
    ("an operating pointer inside the publish folder", ("site/CLAUDE.md",), None, 1),
    ("a README one level down", ("site/docs/README.md",), None, 1),
    ("a lower-case readme", ("site/readme.md",), None, 1),
    ("the skills guide left at the root", ("skills/setup.md",), None, 1),
    ("a workflow folder published", ("site/.github/workflows/gate.yml",), None, 1),
    ("no 404 page", (), "site/404.html", 1),
    ("no skills guide in the publish folder", (), "site/skills/setup.md", 1),
    ("a _redirects without the stable-path rule", ("site/_redirects",), None, 1),
    ("no _redirects at all", (), "site/_redirects", 1),
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
        f"repository-only at the root: {', '.join(kept)}; stable paths: "
        f"{', '.join(rule[0] for rule in REQUIRED_REWRITES)})"
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


def _iter_text_files(
    root: Path, roots: Iterable[str], exclude: frozenset[str]
) -> Iterator[tuple[str, str]]:
    for top in roots:
        for path in sorted((root / top).rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if rel in exclude:
                continue
            try:
                yield rel, path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue  # a binary asset carries no copy


def _text_files(root: Path, config: VendorConfig) -> Iterator[tuple[str, str]]:
    return _iter_text_files(root, config.roots, config.exclude)


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
    "scan": {"roots": ["site"], "exclude": ["site/robots.txt"]},
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
    ("site/skills/setup.md", "Use Copilot.\n"),
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


# ── taxonomy-leaks ───────────────────────────────────────────────────────────
#
# §15.10.767 §S.2/§S.4: internal component names, governance references (lesson
# numbers, diligence names, internal document titles), internal rule and cluster
# numbers, and the retired claim-state ("12 of 12", bare "Live") never appear on a
# published file. The list is gates/taxonomy_leaks.json; this code holds the
# classes the dispatch put on it, so the list can grow and cannot silently shrink.

#: Rule ids the shipped list must carry (§15.10.767 §S.4; the reader test of
#: 2026-10-16 §4). A config without one of them fails the self-test.
REQUIRED_LEAK_RULES = frozenset(
    {
        "codename-themis",
        "codename-hygieia",
        "codename-mnemosyne",
        "codename-hermes",
        "codename-plutus",
        "governance-lesson-number",
        "governance-diligence-name",
        "governance-pricing-strategy",
        "rule-id-number",
        "rule-cluster-number",
        "claim-12-of-12",
        "claim-all-twelve-live",
        "claim-bare-live-badge",
        "claim-live-on-production",
        "claim-vertical-line-live",
    }
)

#: Published files a recurrence of a page-wide entry is seeded into (review of
#: §15.10.767 §S.4): the pages the reader test read, the agent-facing files and
#: the now-public skills guide.
_RECURRENCE_FILES = (
    "site/index.html",
    "site/verticals.html",
    "site/llms.txt",
    "site/.well-known/agents.txt",
    "site/.well-known/agentic-commerce.json",
    "site/skills/setup.md",
)
#: What §15.10.767 §S.1-§S.4 removed and every marker of the shell list the gate
#: replaced, seeded alone into each of ``_RECURRENCE_FILES``.
_RECURRENCE_TEXTS = (
    # internal component names (§S.2)
    "Themis",
    "Hygieia",
    "Mnemosyne",
    "Hermes",
    "Plutus",
    # governance references, removed not mapped (§S.2; Copy Set §13 F)
    "per Lesson #28-COO-vendor BINDING extension",
    "Per Karpathy diligence Q7:",
    "Per Pricing_Strategy v1.2 compute tier",
    # internal rule and cluster numbers (§S.2)
    "#101.5",
    "cluster #99",
    # the retired claim-state (§S.1; Copy Set §13 E)
    "12 of 12",
    "All twelve applied verticals live on production today.",
    "12-VERTICAL-COMPLETE",
    # the nationality-framed exclusion (reader test §4.3)
    "Chinese quantum vendors PROHIBITED",
    # the shell list this gate replaced
    "Sacred Invariant",
    "sacred_invariants",
    "Pattern-32",
    "Pattern-43",
    "Pattern-50",
    "Pattern-65",
    "THEMIS-DA-",
    "Themis-DA-",
    "Mnemosyne ledger",
    "mnemosyne_ledger",
    "Plutus orchestration",
    "plutus_ring",
)
#: Recurrences of the entries that are scoped to one file.
_RECURRENCE_SCOPED = (
    ("site/verticals.html", '<span class="vertical-deep-status live">Live</span>'),
    ("site/verticals.html", '<span class="value">Live on production</span>'),
    ("site/.well-known/agents.txt", "Vertical: V4=Climate-Physical-Risk LIVE"),
    ("site/.well-known/agents.txt", "Vertical: V4=Climate-Physical-Risk Live"),
    (
        "site/.well-known/agents.txt",
        "Vertical: V13=General any-consequential-decision LIVE",
    ),
)
#: The recurrence floor, held in code so that no edit of the list can pass one
#: silently (a rule dropped, a tier turned to report, a scope moved, a file
#: excluded, a pattern weakened together with its own fixtures): each (published
#: file, text) is seeded alone into that file, and the shipped list must fail it
#: with a fail-tier hit there. The list may grow; it cannot shrink below this.
RECURRENCE_FLOOR: tuple[tuple[str, str], ...] = (
    tuple((rel, text) for text in _RECURRENCE_TEXTS for rel in _RECURRENCE_FILES)
    + _RECURRENCE_SCOPED
)

_REGEX_FLAGS = {"i": re.IGNORECASE, "m": re.MULTILINE}
_TIERS = ("fail", "report")


@dataclass(frozen=True)
class LeakRule:
    id: str
    tier: str  # "fail" or "report"
    pattern: re.Pattern[str]
    files: frozenset[str]  # empty: every scanned file
    why: str
    fixtures: tuple[str, ...]  # each must be found by this rule (seeded failing text)
    near_misses: tuple[str, ...]  # each must not be found by this rule

    def applies_to(self, rel: str) -> bool:
        return not self.files or rel in self.files

    def probe_file(self, roots: Sequence[str]) -> str:
        """Where the self-test seeds this rule's fixtures: its first scoped file, or
        a page in the first scan root."""
        return min(self.files) if self.files else f"{roots[0]}/seeded.html"


@dataclass(frozen=True)
class Pending:
    file: str
    rule: str
    text: str
    source: str


@dataclass(frozen=True)
class LeakConfig:
    roots: tuple[str, ...]
    exclude: frozenset[str]
    rules: tuple[LeakRule, ...]
    pending: tuple[Pending, ...]


@dataclass(frozen=True)
class LeakHit:
    file: str
    line: int
    rule: LeakRule
    found: str
    pending: Pending | None  # the pending row when inside one


def _text(row: dict[str, Any], key: str, where: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where}.{key} must be a non-empty string")
    return value


def _rule_pattern(row: dict[str, Any], where: str) -> re.Pattern[str]:
    has_word, has_regex = "word" in row, "regex" in row
    if has_word == has_regex:
        raise ValueError(f"{where} needs exactly one of word or regex")
    if has_word:
        any_case = row.get("any_case", True)
        if not isinstance(any_case, bool):
            raise ValueError(f"{where}.any_case must be true or false")
        return name_pattern(_text(row, "word", where), any_case)
    flags_text = row.get("flags", "")
    if not isinstance(flags_text, str) or set(flags_text) - set(_REGEX_FLAGS):
        raise ValueError(
            f"{where}.flags must be letters from {''.join(_REGEX_FLAGS)!r}"
        )
    flags = 0
    for letter in flags_text:
        flags |= _REGEX_FLAGS[letter]
    try:
        return re.compile(_text(row, "regex", where), flags)
    except re.error as exc:
        raise ValueError(f"{where}.regex does not compile: {exc}") from exc


def load_leak_config(data: dict[str, Any]) -> LeakConfig:
    scan = data.get("scan", {})
    if not isinstance(scan, dict):
        raise ValueError("scan must be an object")
    roots = tuple(_strings(scan.get("roots", []), "scan.roots"))
    if not roots:
        raise ValueError("scan.roots must name at least one folder")
    raw_rules = data.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        raise ValueError("rules must be a non-empty list")
    rules: list[LeakRule] = []
    for i, row in enumerate(raw_rules):
        where = f"rules[{i}]"
        if not isinstance(row, dict):
            raise ValueError(f"{where} must be an object")
        rule_id = _text(row, "id", where)
        where = f"rules[{i}] ({rule_id})"
        if any(r.id == rule_id for r in rules):
            raise ValueError(f"{where}: duplicate rule id")
        tier = row.get("tier")
        if tier not in _TIERS:
            raise ValueError(f"{where}.tier must be one of {_TIERS}")
        fixtures = tuple(_strings(row.get("fixtures"), f"{where}.fixtures"))
        if not fixtures:
            raise ValueError(f"{where}.fixtures must hold at least one seeded fixture")
        rules.append(
            LeakRule(
                id=rule_id,
                tier=str(tier),
                pattern=_rule_pattern(row, where),
                files=frozenset(_strings(row.get("files", []), f"{where}.files")),
                why=_text(row, "why", where),
                fixtures=fixtures,
                near_misses=tuple(
                    _strings(row.get("near_misses", []), f"{where}.near_misses")
                ),
            )
        )
    by_id = {r.id: r for r in rules}
    pending: list[Pending] = []
    raw_pending = data.get("pending", [])
    if not isinstance(raw_pending, list):
        raise ValueError("pending must be a list")
    for i, row in enumerate(raw_pending):
        where = f"pending[{i}]"
        if not isinstance(row, dict):
            raise ValueError(f"{where} must be an object")
        item = Pending(
            file=_text(row, "file", where),
            rule=_text(row, "rule", where),
            text=_text(row, "text", where),
            source=_text(row, "source", where),
        )
        if item.rule not in by_id:
            raise ValueError(f"{where}: rule {item.rule!r} is not a listed rule")
        if by_id[item.rule].tier != "fail":
            raise ValueError(
                f"{where}: rule {item.rule!r} is report-tier; only a fail-tier hit is held pending"
            )
        pending.append(item)
    return LeakConfig(
        roots=roots,
        exclude=frozenset(_strings(scan.get("exclude", []), "scan.exclude")),
        rules=tuple(rules),
        pending=tuple(pending),
    )


def scan_leaks(root: Path, config: LeakConfig) -> tuple[list[LeakHit], list[str], int]:
    """(every hit, every pending-list problem, files scanned)."""
    hits: list[LeakHit] = []
    problems: list[str] = []
    by_id = {r.id: r for r in config.rules}
    by_file: dict[str, list[Pending]] = {}
    for row in config.pending:
        by_file.setdefault(row.file, []).append(row)
        rule = by_id[row.rule]
        if not rule.pattern.search(row.text):
            problems.append(
                f"PENDING[no-match]: {row.file}: {row.text!r} holds nothing rule "
                f"{row.rule} finds; a pending row exists only to hold a hit"
            )
        if not rule.applies_to(row.file):
            problems.append(
                f"PENDING[out-of-scope]: {row.file}: rule {row.rule} does not scan this file"
            )
    scanned = 0
    seen_files: set[str] = set()
    for rel, text in _iter_text_files(root, config.roots, config.exclude):
        scanned += 1
        seen_files.add(rel)
        held: list[tuple[int, int, Pending]] = []
        for row in by_file.get(rel, []):
            spans = _spans(text, row.text)
            if not spans:
                problems.append(
                    f"PENDING[stale]: {rel}: {row.text!r} no longer occurs in the file; "
                    "the page changed (drop the row) or the row is wrong"
                )
            held.extend((a, b, row) for a, b in spans)
        for rule in config.rules:
            if not rule.applies_to(rel):
                continue
            for match in rule.pattern.finditer(text):
                hold = next(
                    (
                        row
                        for a, b, row in held
                        if row.rule == rule.id
                        and a <= match.start()
                        and match.end() <= b
                    ),
                    None,
                )
                line = text.count("\n", 0, match.start()) + 1
                hits.append(LeakHit(rel, line, rule, match.group(0), hold))
    for rel in sorted(set(by_file) - seen_files):
        problems.append(f"PENDING[no-file]: {rel} is not a scanned file")
    hits.sort(key=lambda h: (h.file, h.line, h.rule.id, h.found))
    return hits, problems, scanned


def leaks_report(root: Path, config: LeakConfig) -> tuple[int, list[str]]:
    """The verdict on the tree at ``root`` (0 pass, 1 fail) and the lines that give it."""
    lines: list[str] = []
    hits, problems, scanned = scan_leaks(root, config)
    failing = [h for h in hits if h.rule.tier == "fail" and h.pending is None]
    held = [h for h in hits if h.rule.tier == "fail" and h.pending is not None]
    report = [h for h in hits if h.rule.tier == "report"]
    for hit in hits:
        if hit.rule.tier == "report":
            tag, state = "REPORT ", f"not yet ruled: {hit.rule.why}"
        elif hit.pending is None:
            tag, state = "FAIL   ", hit.rule.why
        else:
            tag, state = (
                "PENDING",
                f"held until a ratified string replaces it ({hit.pending.source})",
            )
        lines.append(
            f"  {tag} {hit.file}:{hit.line} {hit.found!r} [{hit.rule.id}] -> {state}"
        )
        lines.append(f"          | {_context(root / hit.file, hit.line)}")
    lines.extend(f"  {line}" for line in problems)
    fail_rules = sum(1 for r in config.rules if r.tier == "fail")
    lines.append(
        f"TAXONOMY LEAKS COMPARED: {scanned} files under {', '.join(config.roots)}; "
        f"{len(config.rules)} rules ({fail_rules} fail, {len(config.rules) - fail_rules} report); "
        f"fail-tier hits {len(failing) + len(held)} ({len(failing)} unheld, "
        f"{len(held)} pending a ratified string); report-tier hits {len(report)}"
    )
    if failing or problems:
        lines.append(
            f"TAXONOMY-LEAKS: FAIL ({len(failing)} hit(s), {len(problems)} pending-list problem(s))"
        )
        return 1, lines
    lines.append("TAXONOMY-LEAKS: OK")
    return 0, lines


#: A small config for the pending-list mechanics (the shipped rules are proven by
#: their own fixtures).
_LEAK_SELF_TEST_CONFIG: dict[str, Any] = {
    "scan": {"roots": ["site"], "exclude": ["site/skip.txt"]},
    "rules": [
        {
            "id": "name",
            "tier": "fail",
            "word": "Themis",
            "why": "self-test",
            "fixtures": ["Themis"],
        },
        {
            "id": "badge",
            "tier": "fail",
            "regex": r">\s*Live\s*<",
            "flags": "i",
            "files": ["site/v.html"],
            "why": "self-test",
            "fixtures": ["<b>Live</b>"],
        },
        {
            "id": "seen",
            "tier": "report",
            "regex": r"\bLIVE\.",
            "why": "self-test",
            "fixtures": ["LIVE."],
        },
    ],
    "pending": [
        {
            "file": "site/a.html",
            "rule": "name",
            "text": "the Themis gate",
            "source": "self-test",
        }
    ],
}

#: (case, {file: contents}, pending rows replacing the config's or None, expected
#: exit, expected problem kinds).
_LEAK_CASES: tuple[
    tuple[str, dict[str, str], list[dict[str, str]] | None, int, tuple[str, ...]], ...
] = (
    (
        "a hit inside its pending string is held",
        {"site/a.html": "<p>the Themis gate</p>\n"},
        None,
        0,
        (),
    ),
    (
        "a second occurrence outside the pending string fails",
        {"site/a.html": "<p>the Themis gate</p>\n<p>Themis again</p>\n"},
        None,
        1,
        (),
    ),
    (
        "a pending string held in one file does not hold another",
        {"site/a.html": "the Themis gate\n", "site/b.html": "the Themis gate\n"},
        None,
        1,
        (),
    ),
    (
        "a stale pending row fails",
        {"site/a.html": "<p>nothing</p>\n"},
        None,
        1,
        ("PENDING[stale]",),
    ),
    (
        "a pending row that holds no hit fails",
        {"site/a.html": "the gate\n"},
        [{"file": "site/a.html", "rule": "name", "text": "the gate", "source": "t"}],
        1,
        ("PENDING[no-match]",),
    ),
    (
        "a pending row for a file not scanned fails",
        {"site/a.html": "x\n"},
        [{"file": "site/gone.html", "rule": "name", "text": "Themis", "source": "t"}],
        1,
        ("PENDING[no-file]",),
    ),
    (
        "a pending row outside its rule's files fails",
        {"site/a.html": "<b>Live</b>\n"},
        [
            {
                "file": "site/a.html",
                "rule": "badge",
                "text": "<b>Live</b>",
                "source": "t",
            }
        ],
        1,
        ("PENDING[out-of-scope]",),
    ),
    (
        "a pending row holds only its own rule's hits",
        {"site/v.html": "<p>Themis <b>Live</b></p>\n"},
        [
            {
                "file": "site/v.html",
                "rule": "name",
                "text": "Themis <b>Live</b>",
                "source": "t",
            }
        ],
        1,
        (),
    ),
    ("a scoped rule fires in its file", {"site/v.html": "<b>Live</b>\n"}, [], 1, ()),
    (
        "a scoped rule is silent elsewhere",
        {"site/index.html": "<b>Live</b>\n"},
        [],
        0,
        (),
    ),
    ("a report-tier hit fails nothing", {"site/a.html": "Offer. LIVE.\n"}, [], 0, ()),
    ("an excluded file is not scanned", {"site/skip.txt": "Themis\n"}, [], 0, ()),
    ("a clean tree passes", {"site/a.html": "<p>the gate</p>\n"}, [], 0, ()),
)

#: Config rows the loader must refuse: (case, the mutation of the self-test config).
_LEAK_BAD_CONFIGS: tuple[tuple[str, dict[str, Any]], ...] = (
    # Each rule mutation clears the pending list, so the refusal comes from the
    # rule row itself and not from a pending row naming a rule that is gone.
    (
        "a rule without a fixture",
        {
            "rules": [
                {"id": "x", "tier": "fail", "word": "X", "why": "w", "fixtures": []}
            ],
            "pending": [],
        },
    ),
    (
        "a rule with both word and regex",
        {
            "rules": [
                {
                    "id": "x",
                    "tier": "fail",
                    "word": "X",
                    "regex": "X",
                    "why": "w",
                    "fixtures": ["X"],
                }
            ],
            "pending": [],
        },
    ),
    (
        "a duplicate rule id",
        {
            "rules": [
                {"id": "x", "tier": "fail", "word": "X", "why": "w", "fixtures": ["X"]},
                {"id": "x", "tier": "fail", "word": "Y", "why": "w", "fixtures": ["Y"]},
            ],
            "pending": [],
        },
    ),
    (
        "an unknown tier",
        {
            "rules": [
                {"id": "x", "tier": "warn", "word": "X", "why": "w", "fixtures": ["X"]}
            ],
            "pending": [],
        },
    ),
    ("no rules", {"rules": [], "pending": []}),
    (
        "a pending row on an unknown rule",
        {"pending": [{"file": "f", "rule": "nope", "text": "t", "source": "s"}]},
    ),
    (
        "a pending row on a report-tier rule",
        {"pending": [{"file": "f", "rule": "seen", "text": "LIVE.", "source": "s"}]},
    ),
)


def missing_leak_rules(config: LeakConfig) -> list[str]:
    """The required rule ids ``config`` does not carry."""
    return sorted(REQUIRED_LEAK_RULES - {r.id for r in config.rules})


def floor_failures(config: LeakConfig) -> list[str]:
    """Every recurrence of ``RECURRENCE_FLOOR`` the list ``config`` lets pass, one
    line each: seeded alone into its file (no pending rows, so any fail-tier hit
    fails the gate; the self-test's fixture runs prove that verdict), it must draw
    a fail-tier hit in that file."""
    bare = dataclasses.replace(config, pending=())
    out: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for rel, text in RECURRENCE_FLOOR:
            _touch(root, rel, text + "\n")
            hits, _, _ = scan_leaks(root, bare)
            (root / rel).unlink()  # one seeded file at a time
            if not any(h.file == rel and h.rule.tier == "fail" for h in hits):
                out.append(f"recurrence {text!r} in {rel} passes the list")
    return out


def leak_self_test(config: LeakConfig) -> tuple[list[str], int, int]:
    """(problems, seeded failing fixtures run, near misses run). The shipped list
    carries every required rule, and dropping any one of them is noticed; every
    shipped rule's fixtures fail the gate in a seeded tree (a report-tier fixture is
    found and fails nothing); every near miss is not found; a scoped rule is silent
    outside its files; the pending list holds only what it names; the loader
    refuses bad rows."""
    problems: list[str] = []
    missing = missing_leak_rules(config)
    if missing:
        problems.append(f"the shipped list lacks required rule(s): {missing}")
    for rule_id in sorted(REQUIRED_LEAK_RULES - set(missing)):
        thinned = dataclasses.replace(
            config, rules=tuple(r for r in config.rules if r.id != rule_id)
        )
        if rule_id not in missing_leak_rules(thinned):
            problems.append(f"dropping required rule {rule_id} goes unnoticed")
    problems.extend(floor_failures(config))
    # The floor can fail: with every rule turned report-tier, every recurrence
    # passes, and the floor names each one.
    silenced = dataclasses.replace(
        config,
        rules=tuple(dataclasses.replace(r, tier="report") for r in config.rules),
    )
    if len(floor_failures(silenced)) != len(RECURRENCE_FLOOR):
        problems.append("the recurrence floor passes a list whose rules fail nothing")
    bare = dataclasses.replace(config, pending=())
    fixtures_run = 0
    near_run = 0
    for rule in config.rules:
        probe = rule.probe_file(config.roots)
        for text in rule.fixtures:
            fixtures_run += 1
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                _touch(root, probe, text + "\n")
                hits, _, _ = scan_leaks(root, bare)
                verdict, _ = leaks_report(root, bare)
            if not any(h.rule.id == rule.id for h in hits):
                problems.append(f"{rule.id}: fixture {text!r} in {probe} is not found")
            want = 1 if rule.tier == "fail" else 0
            if verdict != want:
                problems.append(
                    f"{rule.id}: fixture {text!r} in {probe}: expected exit {want}, got {verdict}"
                )
        if rule.files:
            elsewhere = f"{config.roots[0]}/out-of-scope.html"
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                _touch(root, elsewhere, rule.fixtures[0] + "\n")
                hits, _, _ = scan_leaks(root, bare)
            if any(h.rule.id == rule.id for h in hits):
                problems.append(f"{rule.id}: fires outside its files ({elsewhere})")
        for text in rule.near_misses:
            near_run += 1
            if rule.pattern.search(text):
                problems.append(f"{rule.id}: near miss {text!r} is found")
    test_config = load_leak_config(_LEAK_SELF_TEST_CONFIG)
    for case, files, pending_rows, want_exit, want_kinds in _LEAK_CASES:
        case_config = test_config
        if pending_rows is not None:
            case_config = load_leak_config(
                {**_LEAK_SELF_TEST_CONFIG, "pending": pending_rows}
            )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _touch(root, "site/index.html", "<p>home</p>\n")
            for rel, text in files.items():
                _touch(root, rel, text)
            _, case_problems, _ = scan_leaks(root, case_config)
            verdict, _ = leaks_report(root, case_config)
        kinds = tuple(sorted(p.split(":", 1)[0] for p in case_problems))
        if verdict != want_exit or kinds != tuple(sorted(want_kinds)):
            problems.append(
                f"{case}: expected exit {want_exit} and {list(want_kinds)}, got {verdict} and {list(kinds)}"
            )
    for case, mutation in _LEAK_BAD_CONFIGS:
        try:
            load_leak_config({**_LEAK_SELF_TEST_CONFIG, **mutation})
        except ValueError:
            continue
        problems.append(f"the loader accepted {case}")
    return problems, fixtures_run, near_run


def cmd_taxonomy_leaks(root: Path, config_path: Path) -> int:
    try:
        config = load_leak_config(json.loads(config_path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        print(f"TAXONOMY-LEAKS: FAIL (config {config_path}: {exc})")
        return 1
    problems, fixtures_run, near_run = leak_self_test(config)
    if problems:
        print("TAXONOMY-LEAKS SELF-TEST: FAIL")
        for line in problems:
            print(f"  {line}")
        return 1
    print(
        f"TAXONOMY-LEAKS SELF-TEST: OK ({len(config.rules)} rules; {fixtures_run} seeded "
        f"fixtures each found, every fail-tier one failing the gate; {near_run} near "
        f"misses not found; {len(RECURRENCE_FLOOR)} code-held recurrences each "
        f"failing the gate; {len(_LEAK_CASES)} pending-list cases; "
        f"{len(_LEAK_BAD_CONFIGS)} refused configs)"
    )
    verdict, lines = leaks_report(root, config)
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


def _live_expectations() -> tuple[tuple[str, int], ...]:
    """Every (path, the one status that passes) the live check GETs on each host."""
    return tuple((p, 404) for p in LIVE_404_PATHS) + tuple(
        (p, 200) for p in LIVE_200_PATHS
    )


def live_404_report(
    hosts: Iterable[str], fetch: Callable[[str], int] = _status
) -> tuple[int, list[str]]:
    """GET every repository-only path and every public stable path on every host
    with ``fetch`` (url -> status); the verdict (0 only when every repository-only
    path answered 404 and every stable path 200) and the lines that give it."""
    lines: list[str] = []
    failed = 0
    total = 0
    for host in hosts:
        for path, want in _live_expectations():
            url = f"https://{host}{path}"
            status = fetch(url)
            total += 1
            ok = status == want
            failed += not ok
            lines.append(
                f"  {'ok  ' if ok else 'FAIL'} GET {url} -> {status} (must answer {want})"
            )
    if failed or not total:
        lines.append(f"LIVE-404: FAIL ({failed} of {total} did not answer as ruled)")
        return 1, lines
    lines.append(
        f"LIVE-404: OK ({total} of {total} answered as ruled: repository-only paths 404, "
        "stable paths 200)"
    )
    return 0, lines


#: (case, the status the second host's last repository-only path answers, the
#: status every stable path answers, expected exit). A 404 is the only pass for a
#: repository-only path: a 200 is the file served or a soft 404 (the homepage), a 0
#: an unreachable host, and a 403 or 410 is not the ruling. A stable path passes
#: only on a 200.
_LIVE_CASES: tuple[tuple[str, int, int, int], ...] = (
    ("every path answers as ruled", 404, 200, 0),
    ("a served file or a soft 404 (200)", 200, 200, 1),
    ("an unreachable host (0)", 0, 200, 1),
    ("a refused path (403)", 403, 200, 1),
    ("a gone path (410)", 410, 200, 1),
    ("the stable path not served (404)", 404, 404, 1),
)


def live_404_self_test(root: Path) -> list[str]:
    """The verdict over a fake fetch (every path on every host is asked for, and only
    a run that answers as ruled passes; no network), and the path lists against the
    tree at ``root``: one probe per repository-only root entry, each a file the repo
    carries, none under a public path."""
    problems: list[str] = []
    hosts = ("one.test", "two.test")
    odd = f"https://two.test{LIVE_404_PATHS[-1]}"
    stable = {f"https://{h}{p}" for h in hosts for p in LIVE_200_PATHS}
    for case, status, stable_status, want in _LIVE_CASES:
        asked: list[str] = []

        def fake(
            url: str,
            status: int = status,
            stable_status: int = stable_status,
            asked: list[str] = asked,
        ) -> int:
            asked.append(url)
            if url in stable:
                return stable_status
            return status if url == odd else 404

        got, _ = live_404_report(hosts, fake)
        if got != want:
            problems.append(f"{case}: expected exit {want}, got {got}")
        if len(asked) != len(hosts) * len(_live_expectations()):
            problems.append(
                f"{case}: expected {len(hosts) * len(_live_expectations())} GETs, got {len(asked)}"
            )
    if live_404_report((), lambda url: 404)[0] != 1:
        problems.append("no host named: expected exit 1")
    probed = {p.lstrip("/").split("/", 1)[0] for p in LIVE_404_PATHS}
    for entry in sorted(REPO_ONLY_ROOT - LIVE_404_UNPROBED - probed):
        problems.append(f"repository-only root entry {entry} has no live-404 path")
    for path in LIVE_404_PATHS:
        if not (root / path.lstrip("/")).is_file():
            problems.append(f"live-404 path {path} is not a file the repo carries")
        if path.lstrip("/").split("/", 1)[0] in {PUBLISH_DIR, "skills"}:
            problems.append(f"live-404 path {path} is a public path")
    return problems


def cmd_live_404(root: Path, hosts: Iterable[str]) -> int:
    problems = live_404_self_test(root)
    if problems:
        print("LIVE-404 SELF-TEST: FAIL")
        for line in problems:
            print(f"  {line}")
        return 1
    print(
        f"LIVE-404 SELF-TEST: OK ({len(_LIVE_CASES) + 1} cases, no network; "
        f"{len(LIVE_404_PATHS)} repository-only paths, {len(LIVE_200_PATHS)} stable path)"
    )
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
    leaks = sub.add_parser(
        "taxonomy-leaks",
        help="no internal names or retired claim-state on public files",
    )
    leaks.add_argument(
        "--config", type=Path, default=None, help="default: gates/taxonomy_leaks.json"
    )
    live = sub.add_parser(
        "live-404", help="GET the repository-only and stable paths on each host"
    )
    live.add_argument("hosts", nargs="+", help="host names, e.g. phronesisintel.com")
    args = parser.parse_args(argv)
    root: Path = args.root.resolve()
    if args.command == "publish-folder":
        return cmd_publish_folder(root)
    if args.command == "vendor-names":
        return cmd_vendor_names(
            root, args.config or root / CONFIG, args.ratified_source
        )
    if args.command == "taxonomy-leaks":
        return cmd_taxonomy_leaks(root, args.config or root / LEAK_CONFIG)
    return cmd_live_404(root, args.hosts)


if __name__ == "__main__":
    sys.exit(main())
