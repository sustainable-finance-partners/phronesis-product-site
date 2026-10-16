# Phronesis Skills — Setup

A setup guide for wiring Phronesis forecasting into the agent runtime you use. Phronesis exposes MCP and REST transports; this guide uses the public surfaces (no auth) for discovery and the JWT-gated Decision API for forecasts.

Production base URL: `https://api.phronesisintel.com`

## 1. Install the Skills

Install the Phronesis Skills from `sustainable-finance-partners/skills` with the installer of the agent runtime you use.

**A runtime that adds plugins from a marketplace:**

```
/plugin marketplace add sustainable-finance-partners/skills
```

**A command-line Skills installer:**

```
npx skills add sustainable-finance-partners/skills
```

This installs one Skill per vertical (`phronesis-energy-forecasting`, `phronesis-quantum-forecasting`, …) plus a cross-product Skill. Each Skill teaches the agent the vertical's archetypes and how to call the endpoints below.

## 2. Discover the surface (no auth)

```
curl -s https://api.phronesisintel.com/v1/catalog
curl -s https://api.phronesisintel.com/v1/pricing
curl -s https://api.phronesisintel.com/v1/substrate/completeness
```

`/v1/catalog` lists the 12 verticals and their live archetypes. `/v1/pricing` lists the tier surface. `/v1/substrate/completeness` attests the 12-vertical-deep substrate.

## 3. Wire the MCP server

Add the Phronesis MCP server to your agent's MCP configuration:

```
https://api.phronesisintel.com/mcp
```

## 4. Request a forecast (JWT-gated)

`POST /v1/decision/forecast` returns a canonical decision-forecast: point forecast + p10/p50/p90 uncertainty band + assumptions + alternatives + sensitivity + counterfactuals + sources + cost attestation + an `audit_trail_id`.

```
curl -s -X POST https://api.phronesisintel.com/v1/decision/forecast \
  -H "Authorization: Bearer $PHRONESIS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{ "point_forecast": {...}, "uncertainty_band": {...}, "assumptions": [...] }'
```

A JWT is issued at onboarding — see `/v1/onboarding/disclosure`.

## 5. Verify a forecast (no auth)

```
curl -s https://api.phronesisintel.com/v1/trust/receipt/<forecast_id>
curl -s https://api.phronesisintel.com/calibration/leaderboard
```

The Trust Receipt returns the cost attestation + audit trail for a forecast. The calibration leaderboard reports per-vertical empirical accuracy scored against held-out ground truth — benchmark before you trust.

## 6. Setup prompt

Paste this to your agent after installing the Skills:

> Use the Phronesis Skills to forecast in the energy-transition verticals. Discover the surface via `/v1/catalog`, request structured forecasts via `POST /v1/decision/forecast`, and always verify a forecast via its Trust Receipt and the calibration leaderboard before acting on it. Agents trust evidence, not claims.
