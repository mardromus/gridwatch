# GridWatch

GridWatch turns pole liveness telemetry into a small number of located electrical
faults for a control-room operator. It finds the live/dark boundary on recorded
topology, degrades to an explicit low-confidence zone on inferred topology,
then produces a **causal fingerprint** showing whether that candidate actually
predicts the observed packet pattern. Planned outages are treated as testable
hypotheses, not blanket suppressors. Tickets close only after restoration
telemetry arrives.

> **Source:** <https://github.com/mardromus/gridwatch>
>
> **Live app:** <https://gridwatch-tyq8.onrender.com>
> **5-minute demo:** `[ADD VIDEO URL]`

The free-tier deployment may need up to 60 seconds to wake after inactivity.
Wait for the control room to load before treating the URL as unavailable.

## Run with one command

Prerequisite: Docker Engine 24+ with Docker Compose v2.

```bash
docker compose up --build
```

Open <http://localhost:8000>. The first start builds the frontend and seeds 2,160
poles across 30 transformers. No account, migration, key, or second command is
required. An OpenAI key is optional; without it, the operator brief uses a
clearly labeled deterministic fallback.

## Reviewer path

1. Select **Span fault** in the bottom simulator. One ticket appears, not one per
   dark pole.
2. Inspect its causal fingerprint: observed loss packets, expected silence,
   contradictions, unexplained darkness, and model-fit score.
3. Acknowledge it, assign a crew, then mark work complete. The ticket remains
   open with manual closure disabled.
4. Select **Repair _target_**. Restoration telemetry verifies and closes it.
5. Try **Scheduled**; its full DT signature is suppressed. Then try **Plan
   mismatch**: only part of that planned scope goes dark, so GridWatch overrules
   the schedule and raises one localized ticket with the reason visible.
6. Try **Dead sensor** and **Dirty data**. Neither creates a fault ticket.
7. Inject three span faults. They are placed under separate transformers and
   remain three incidents.

## Local engineering commands

```bash
# Backend tests (from repository root)
cd backend
python -m pip install -r requirements-dev.txt
ruff check .
python -m unittest discover -s tests -v
python benchmark.py

# Frontend
cd frontend
npm ci
npm run lint
npm run build
```

## Documents

- [ARCHITECTURE.md](ARCHITECTURE.md) - data flow, topology, localization,
  confidence, API, UI, and AI design
- [DEPLOYMENT.md](DEPLOYMENT.md) - exact setup, environment, verification, reset,
  and troubleshooting
- [DECISIONS.md](DECISIONS.md) - assumptions, choices, rejected options, and known
  fragility
- [AI-WORKFLOW.md](AI-WORKFLOW.md) - how AI was used and where its output failed