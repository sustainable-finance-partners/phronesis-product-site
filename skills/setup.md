# Phronesis Skills — Setup

A curl-able setup guide for wiring Phronesis forecasting into an agent runtime — Claude Code, Cursor, Codex, or the Vercel Skills CLI. Phronesis exposes co-equal MCP and REST transports; this guide uses the public surfaces (no auth) for discovery and the JWT-gated Decision API for forecasts.

Production base URL: `https://phronesis-jrstinehour.replit.app`

## 1. Install the Skills

**Claude Code:**

```
/plugin marketplace add sustainable-finance-partners/skills
```

**Vercel Skills CLI:**

```
npx skills add sustainable-finance-partners/skills
```

This installs one Skill per vertical (`phronesis-energy-forecasting`, `phronesis-quantum-forecasting`, …) plus a cross-product Skill. Each Skill teaches the agent the vertical's archetypes and how to call the endpoints below.

## 2. Discover the surface (no auth)

```
curl -s https://phronesis-jrstinehour.replit.app/v1/catalog
curl -s https://phronesis-jrstinehour.replit.app/v1/pricing
curl -s https://phronesis-jrstinehour.replit.app/v1/substrate/completeness
```

`/v1/catalog` lists the 12 verticals and their live archetypes. `/v1/pricing` lists the tier surface. `/v1/substrate/completeness` attests the 12-vertical-deep substrate.

## 3. Wire the MCP server

Add the Phronesis MCP server to your agent's MCP configuration:

```
https://phronesis-jrstinehour.replit.app/mcp
```

The MCP and REST transports are co-equal — either reaches the same governed forecast surface.

## 4. Request a forecast (JWT-gated)

`POST /v1/decision/forecast` returns a canonical decision-forecast: point forecast + p10/p50/p90 uncertainty band + assumptions + alternatives + sensitivity + counterfactuals + sources + cost attestation + an `audit_trail_id`.

```
curl -s -X POST https://phronesis-jrstinehour.replit.app/v1/decision/forecast \
  -H "Authorization: Bearer $PHRONESIS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{ "point_forecast": {...}, "uncertainty_band": {...}, "assumptions": [...] }'
```

A JWT is issued at onboarding — see `/v1/onboarding/disclosure`.

## 5. Verify a forecast (no auth)

```
curl -s https://phronesis-jrstinehour.replit.app/v1/trust/receipt/<forecast_id>
curl -s https://phronesis-jrstinehour.replit.app/calibration/leaderboard
```

The Trust Receipt returns the Themis rules applied + cost attestation + audit trail for a forecast. The calibration leaderboard reports per-vertical empirical accuracy scored against held-out ground truth — benchmark before you trust.

## 6. Setup prompt

Paste this to your agent after installing the Skills:

> Use the Phronesis Skills to forecast in the energy-transition verticals. Discover the surface via `/v1/catalog`, request structured forecasts via `POST /v1/decision/forecast`, and always verify a forecast via its Trust Receipt and the calibration leaderboard before acting on it. Agents trust evidence, not claims.
