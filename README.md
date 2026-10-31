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
├── scripts/refresh_count.py         Rewrites the homepage count + as-of from the live scorecard (run before a merge)
├── gates/license_strings.json       Those strings, each pinned to its source line, + the API's RSL/aipref render
├── gates/vendor_names.json          Vendor names + the ratified strings allowed to carry them
├── gates/taxonomy_leaks.json        Internal names, governance references, retired claim-state (+ fixtures)
├── .github/workflows/               CI gates
├── CLAUDE.md                        Operating pointer
└── README.md                        This file
```

## Hosting

Cloudflare Pages project `phronesis-product-site` → custom domain `phronesisintel.com`
(root + `www`). Build settings: no build command; build output directory `site`. Domain
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
(`--dry-run` to print only). The
Hermes contract surface must allow CORS from `https://phronesisintel.com` origin
for the scorecard to render. If the browser console shows a CORS error post-deploy, the
mcp_server middleware needs the origin added to its allowlist (carry-item per Sprint 5.4
dispatch §AC-Phronesis-Site-2).

## Contributing

This is a static-content surface. No build step. Public files go under `site/`. Edits
land via PR; production deploys auto-trigger from `main` branch via Cloudflare Pages.
