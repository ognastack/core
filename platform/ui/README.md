# OGNA platform UI

Web UI for the OGNA control plane, built from [ogna-fe-template](https://github.com/ognastack/ogna-fe-template). See [../README.md](../README.md) for what it does and how it's deployed.

```bash
npm ci
NEXT_PUBLIC_OGNA_URL=http://localhost:8000 npm run dev   # against a running platform stack
npm run build && npm run lint
```

- `src/lib/platform.ts`: typed client for the platform API (mirrors `api/app/models.py`)
- `src/app/protected/projects`: projects list, create panel, project detail
- `src/app/protected/account`: plan & usage, admin plan changes
- `src/components/page-shell.tsx`, `app-sidebar.tsx`, `status-badge.tsx`: layout pieces

In the stack the UI is served by the gateway at `/`, so API calls are same-origin (`window.location.origin`). `NEXT_PUBLIC_OGNA_URL` overrides that for local development.
