# phronesis-product-site

Static source for [phronesisintel.com](https://phronesisintel.com) — Phronesis flagship platform marketing surface, operated by Sustainable Finance Partners, LLC.

For the SFP corporate parent site, see [sustainablefinancepartner.com](https://sustainablefinancepartner.com) (source: [`sfp-corporate-site`](https://github.com/sustainable-finance-partners/sfp-corporate-site)).

## Layout

The host publishes `site/` and nothing else. Everything at the root is repository-only:
it is never served (CI fails a public file left at the root, or a repository-only name
inside `site/`).

```
.
├── site/                            PUBLISHED (Cloudflare Pages build output directory)
│   ├── index.html                   Home page
│   ├── verticals.html               Vertical coverage
│   ├── scorecard.html               Live forecast scorecard (fetches api.phronesisintel.com/scorecard.json)
│   ├── pricing.html, pricing.json   Pricing tiers (page + machine-readable)
│   ├── spec.html, for-agents.html   For-agents technical surfaces
│   ├── security.html, 404.html      Security page; the not-found page (needed for real 404s)
│   ├── license.html                 The Phronesis Register License (served at /license)
│   ├── license.xml                  Its RSL 1.0 declaration for this host (robots.txt License:; application/rsl+xml via _headers)
│   ├── llms.txt, evals.json         Agent-readable summaries
│   ├── styles.css                   Shared design system (byte-identical with sfp-corporate-site)
│   ├── manifest.json, favicon.svg, robots.txt, sitemap.xml
│   ├── _headers, _redirects         Pages header and redirect rules (not served)
│   ├── skills/setup.md              Skills setup guide: public by design (ADR-0034), served at /skills/setup
│   └── .well-known/                 agents.txt, agentic-commerce.json, agentic-verify.txt
├── scripts/site_gates.py            Publish-folder, vendor-name, taxonomy-leak and live-404 checks
├── scripts/test_license_set.py      The license set renders its signed strings exactly
├── scripts/refresh_count.py         Rewrites the homepage count, its as-of and the vertical badges from the live scorecard (run before a merge; --check fails on an overclaim)
├── scripts/status_copy_text.py      The homepage status strings (809 §7), GENERATED from the byte copy below
├── scripts/gen_status_copy_text.py  Generates it (--check: the module equals the generator's output)
├── scripts/test_status_strings.py   The homepage renders those strings; the badges are register-derived
├── tests/fixtures/dispatch_809_sources/  Byte copy of COO dispatch 809 + README (source path, bytes, SHA-256)
├── gates/license_strings.json       Those strings, each pinned to its source line, + the API's RSL/aipref render
├── gates/vendor_names.json          Vendor names + the ratified strings allowed to carry them
├── gates/taxonomy_leaks.json        Internal names, governance references, retired claim-state (+ fixtures)
├── .github/workflows/               CI gates
├── CLAUDE.md                        Operating pointer
└── README.md                        This file
```

## Hosting

Cloudflare Pages project `phronesis-product-site` → custom domain `phronesisintel.com`
(root + `www`). Build settings: build output directory `site`; no build command today.
COO dispatch 809 §9 names the build command `python3 scripts/refresh_count.py` (an owner
setting, Pages project → Settings → Builds, with a deploy hook fired at the end of each
API republish): once it is set, every deploy rewrites the homepage count and the vertical
badges from the live scorecard, and a refused read fails the build, so the last good
deploy stays up. Until then the static values are refreshed by hand before a merge, and
the `homepage-counts-not-above-the-register` CI job (`refresh_count.py --check`) fails a
PR whose page states more than the live register. Domain
registered at Cloudflare Registrar 2026-04-19 (3-yr auto-renew); DNS hosting at Cloudflare
default.

After a deploy, check from the desk that the repository-only paths (`/CLAUDE.md`,
`/README.md`, `/.github/*` and every other root file) answer 404 and that the stable
path `/skills/setup` answers 200:

```
python scripts/site_gates.py live-404 phronesisintel.com
```

## Live data dependency

`scorecard.html` fetches `https://api.phronesisintel.com/scorecard.json` on page
load. `index.html` refreshes its record count and as-of date from
`https://api.phronesisintel.com/.well-known/scorecard.json` (cached 300 s); the static
count and date are the fallback, and the app repo's parity gate reads them. To refresh
the static count, its `data-as-of` and the `<time>` element in one step (it prints each
old and new value, and refuses on an outage payload): `python3 scripts/refresh_count.py`
(`--dry-run` to print only; `--check` to compare without writing). The same run rewrites
the thirteen vertical badges (V#0–V#12), register-derived (COO dispatch 809 §7): "{n}
records" where the register holds n > 0 records whose `value.intake_payload.subject` is
the vertical's subject (the app's `mcp_server/discovery/route.py` `_VERTICAL_METADATA`),
else "catalogued"; the rows counted are the ones `forecast_count` is made over, and the
script refuses if their number differs. The badges have no in-browser refresh. The
Hermes contract surface must allow CORS from `https://phronesisintel.com` origin
for the scorecard to render. If the browser console shows a CORS error post-deploy, the
mcp_server middleware needs the origin added to its allowlist (carry-item per Sprint 5.4
dispatch §AC-Phronesis-Site-2).

## Contributing

This is a static-content surface. No build step today (see Hosting for the build command
809 §9 names). Public files go under `site/`. Edits land via PR; production deploys
auto-trigger from `main` branch via Cloudflare Pages. A signed string is never retyped:
it is cut from a byte copy of its source under `tests/fixtures/` into a generated
`*_copy_text.py` module, and a test pins it.
