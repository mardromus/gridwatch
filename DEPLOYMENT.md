# Deployment

## Prerequisites

- Docker Engine 24 or newer
- Docker Compose plugin 2.24 or newer (`docker compose version`)
- 2 GB free RAM and 1 GB free disk for the first image build

No local Node.js, Python, database, migration tool, or API key is required.

## Start

```bash
git clone https://github.com/mardromus/gridwatch.git
cd gridwatch
docker compose up --build
```

Open <http://localhost:8000>. The terminal should show Uvicorn listening on
`0.0.0.0:8000`. The header should say **Telemetry online**, the network count
should be 2,160, and the map should show 30 transformer markers.

Verify without a browser:

```bash
curl http://localhost:8000/api/health
```

Expected shape:

```json
{"status":"ok","service":"gridwatch","seeded_poles":2160}
```

## Environment

Copying `.env.example` to `.env` is optional.

| Variable | Required | Safe default | Meaning |
|---|---|---|---|
| `PORT` | No | `8000` | host port mapped to container 8000 |
| `CORS_ORIGINS` | No | `http://localhost:8000` | comma-separated browser origins |
| `OPENAI_API_KEY` | No | empty | enables model-generated operator briefs |
| `OPENAI_MODEL` | No | `gpt-4.1-mini` | OpenAI-compatible chat model |
| `OPENAI_BASE_URL` | No | OpenAI v1 URL | alternate OpenAI-compatible endpoint |
| `GRIDWATCH_DB_PATH` | No | Compose sets `/data/gridwatch.db` | SQLite audit path for non-Compose runs |

Never commit `.env`. The no-key brief is a supported deterministic fallback, not
an error state.

## Manual verification

Run this smoke sequence on any machine with Docker before submitting:

```bash
docker compose up --build --detach --wait
curl http://localhost:8000/api/health
curl -X POST -H "Content-Type: application/json" \
	-d '{"kind":"span"}' http://localhost:8000/api/simulator/inject
curl http://localhost:8000/api/dashboard
docker compose down -v
```

The health response must report 2,160 seeded poles. The dashboard must show
exactly one active incident after the span injection.

## Reset

Reset the seeded demo from the circular-arrow button or:

```bash
curl -X POST http://localhost:8000/api/simulator/reset
```

Remove containers and durable audit data:

```bash
docker compose down -v
```

## Public deployment

`render.yaml` is a Docker web-service blueprint. Push the repository to GitHub,
create a Render Blueprint from it, and add `OPENAI_API_KEY` only if model-backed
briefs are wanted. Set the health check to `/api/health`. The service needs no
other managed dependency. The container honors Render's injected `PORT`.

The free Render blueprint intentionally stores SQLite under `/tmp`: audit data
and in-memory incidents reset after a spin-down, restart, or deploy, and the
startup seed restores a usable demo automatically. Local Docker Compose is the
durable mode because it mounts the `gridwatch-data` named volume.

Before submission, open the public URL in a private browser window, wait through
any free-tier cold start, inject and repair a span fault, and put the URL in
`README.md`.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `docker` is not recognized | Docker Desktop/Engine is absent or not on PATH | Install/start Docker, reopen the terminal, run `docker version` |
| `Bind for 0.0.0.0:8000 failed` | another local process owns port 8000 | set `PORT=8010` in `.env`, rerun, open port 8010 |
| frontend loads but API calls fail | stale image or incorrect origin | run `docker compose down`, rebuild; include the public origin in `CORS_ORIGINS` |
| map is gray but controls work | OpenStreetMap tiles are blocked/offline | allow `tile.openstreetmap.org`; API and list remain usable |
| first start appears stuck | Node and Python layers are building | wait for `Uvicorn running`; later starts use cached layers |
| brief says deterministic fallback | no key, model timeout, invalid model JSON | expected safe behavior; check key/base URL only if model mode is required |
| `httptools` fails on Windows ARM in a local venv | optional Uvicorn native extras lack a compatible wheel/toolchain | install plain `uvicorn`; the committed requirements already do this |
| SQLite is read-only | mounted data path is not writable | remove/recreate the Compose volume with `docker compose down -v` |
| free-tier service restarts and demo state disappears | Render free storage and the correlation projection are ephemeral | wait for the automatic seed, then rerun the scenario; use Compose when durable audit data is required |
| image scan reports new critical CVEs | a base tag moved or the vulnerability feed changed | rebuild against current patched images, review reachability, and pin a clean digest; do not suppress critical findings |

The Docker CLI was unavailable in the authoring environment, so the image file
was reviewed but not built there. The submission owner must complete the fresh
clone self-check before submitting; do not remove this note until that succeeds.