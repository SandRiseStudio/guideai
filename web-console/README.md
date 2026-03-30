# GuideAI Web Console

React + TypeScript + Vite front end for the GuideAI platform. Point it at a running GuideAI API (local OSS server, staging, or cloud).

## Prerequisites

- Node.js 20+ (matches CI)
- A GuideAI API instance (for example `uvicorn guideai.api:app --reload` from the repository root; default API port is often `8000` — set `VITE_API_BASE_URL` accordingly)

## Configuration

| Variable | Purpose |
|----------|---------|
| `VITE_API_BASE_URL` | Base URL for the GuideAI REST API (no trailing slash). Defaults to `http://localhost:8080` in code if unset — override to match your server (e.g. `http://localhost:8000`). |

Create `.env.local` in this directory (gitignored) for machine-specific values:

```bash
echo 'VITE_API_BASE_URL=http://localhost:8000' > .env.local
```

## Commands

```bash
npm install
npm run dev      # dev server with HMR
npm run build    # production bundle → dist/
npm run preview  # serve dist/ locally
npm run test     # Vitest
npm run lint     # ESLint
```

## Monorepo note

`@guideai/collab-client` is linked from [`../packages/collab-client`](../packages/collab-client). Clone the full repository and install from the repo root when working on both packages.
