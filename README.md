# phronesis-product-site

Static source for [phronesisintel.com](https://phronesisintel.com) — Phronesis flagship platform marketing surface, operated by Sustainable Finance Partners, LLC.

For the SFP corporate parent site, see [sustainablefinancepartner.com](https://sustainablefinancepartner.com) (source: [`sfp-corporate-site`](https://github.com/sustainable-finance-partners/sfp-corporate-site)).

## Layout

```
.
├── index.html                       Home page
├── verticals.html                   Vertical coverage (V1–V8)
├── scorecard.html                   Live forecast scorecard (fetches phronesis-jrstinehour.replit.app/scorecard.json)
├── pricing.html                     Pricing tiers
├── spec.html                        For-agents technical surface (links to canonical /spec)
├── styles.css                       Shared design system (byte-identical with sfp-corporate-site)
├── manifest.json                    PWA manifest
├── favicon.svg
├── robots.txt
├── sitemap.xml
└── .well-known/
    ├── agents.txt                   Agent-discovery descriptor
    └── agentic-commerce.json        Agentic-commerce capabilities manifest
```

## Hosting

Cloudflare Pages → custom domain `phronesisintel.com` (root + `www`). Domain registered
at Cloudflare Registrar 2026-04-19 (3-yr auto-renew); DNS hosting at Cloudflare default.

## Live data dependency

`scorecard.html` fetches `https://phronesis-jrstinehour.replit.app/scorecard.json` on page
load. The Hermes contract surface must allow CORS from `https://phronesisintel.com` origin
for the scorecard to render. If the browser console shows a CORS error post-deploy, the
mcp_server middleware needs the origin added to its allowlist (carry-item per Sprint 5.4
dispatch §AC-Phronesis-Site-2).

## Contributing

This is a static-content surface. No build step. Edits land via PR; production deploys
auto-trigger from `main` branch via Cloudflare Pages.
