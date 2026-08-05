# Decisions

Newest first. Dates use the latest build date, 2026-08-05.

## Preserve operator map control

**Chose:** focus the map once when the selected incident changes, then leave pan
and zoom under operator control across polling refreshes. The focused DT shows
only local live and no-device context, while the priority queue ranks open work
by affected poles. **Rejected:** refocusing on every refreshed incident object
and rendering every live pole network-wide. The former steals control every 2.5
seconds; the latter obscures the outage boundary and slows map scanning.

## Add a causal proof, not another opaque score

**Chose:** compare each candidate's predicted downstream telemetry with actual
loss packets, silence, fresh live contradictions, and darkness outside the
model. **Rejected:** showing only localization confidence or adding an ML anomaly
score. Confidence says how trustworthy the topology is; causal fit says whether
the candidate explains this event. Keeping them separate is more useful and
more defensible than blending both into one impressive-looking percentage.

## Let telemetry overrule the schedule feed

**Chose:** suppress only when observed darkness resembles the full planned scope;
escalate partial patterns as planned-window mismatches. **Rejected:** treating
the feed as gospel and ignoring it entirely. The former can hide real faults
during cancelled or late work; the latter causes predictable false alarms.

## Persist audit, keep correlation in memory

**Chose:** SQLite append-only telemetry plus incident snapshots; graph state in
one FastAPI process. **Rejected:** PostgreSQL, Redis, and a broker in the demo.
The smaller stack protects the one-command gate and handles the measured load.
It does not replay state after restart, which is explicitly fragile. Production
would move the same idempotent consumer behind MQTT/Kafka and PostgreSQL.

## Group fragmented inferred boundaries

**Chose:** one low-confidence DT-zone incident when imperfect geographic
topology creates several frontiers from one correlated outage. **Rejected:** one
ticket per inferred frontier and silently selecting the nearest candidate. The
first creates alert fatigue; the second presents invented precision. The cost is
that two real simultaneous faults under one unknown DT can be grouped.

## Deterministic localization, LLM communication

**Chose:** graph logic for faults and a schema-validated multilingual operator
brief for AI. **Rejected:** LLM localization, root-cause guessing, and automatic
workflow actions. Language is where variability helps; location and closure are
safety-relevant facts. Model failure falls back to deterministic text.

## Receipt time for correlation

**Chose:** sequence numbers for per-device order, a ten-minute stale cutoff, and
server receipt time across devices. **Rejected:** comparing device clocks. The
stated 90-second skew makes cross-device timestamp order unreliable. The cutoff
could reject a legitimate outage reported after a long communications failure;
that event remains an audit concern rather than current state.

## Infer topology geographically, but label it

**Chose:** nearest upstream pole within 120 m, constrained by distance from the
DT. **Rejected:** pretending parent links exist, using a pure minimum-spanning
tree, and DT-only localization everywhere. The heuristic ships value today and
keeps an explicit `inferred` provenance. A pole survey remains the real fix.

## Poll every 2.5 seconds

**Chose:** HTTP polling. **Rejected:** WebSockets. Polling meets a 120-second SLA,
recovers cleanly from free-tier cold starts, and avoids proxy upgrade failures.
At many simultaneous operators I would use server-sent events.

## Single container

**Chose:** multi-stage frontend build served by FastAPI. **Rejected:** separate
frontend/backend services. A separate CDN is sensible later, but one image makes
the acceptance command and public deployment harder to break.

## Assumptions

- A DT has at least two independent LT roots before the system labels a
  transformer fault; one root is ambiguous with a first-span fault.
- Restoration is verified at 80% of instrumented affected poles with no fresh
  dark evidence. Uninstrumented poles cannot directly vote.
- Scheduled scopes are known before matching telemetry enters the batch. A
  normalized full-scope packet coverage of 65% counts as schedule-aligned.
- One subdivision is one process/partition. State does not cross subdivisions.
- PIN code falls back from the first dark pole to its live anchor. The synthetic
  export includes valid values on 97% of poles; hosted geocoding is not required.
- Simulator loss-message success is deterministic at approximately 70% so demos
  and tests are reproducible; physical affected state remains separate.

## Known wrong or fragile

- Docker was not available in the authoring environment; fresh-clone Compose
  verification remains mandatory before submission.
- The frontend build uses Chainguard Node and the runtime uses Python Alpine;
  both are clean in the local registry scan, but the built image still needs a
  fresh scan on a Docker-capable machine before submission.
- Correlation state and simulations do not replay from SQLite after restart.
- Scheduled-outage partial-pattern mismatches are detected, but cancellation,
  late starts, and overruns are not reconciled against SCADA switch state.
- A completely silent outage cannot meet two minutes without a dying packet.
- Geographic inference is not accuracy-calibrated against surveyed ground truth.
- OSM tiles require internet access and have no bundled offline fallback.
- The model-backed Kannada/Hindi quality was not evaluated by a native speaker.
- The public Render demo exists, but the five-minute submission video still
  needs to be recorded and linked.

## With two more weeks

1. Implement event replay and PostgreSQL-backed projections, then kill processes
   during integration tests to prove recovery.
2. Compare inferred edges with a held-out surveyed set and calibrate confidence
   from measured precision rather than fixed product thresholds.
3. Add a heartbeat deadline worker for silent firmware 1.2 devices, requiring
   corroboration from neighboring branches before alerting.
4. Reconcile planned outages with SCADA switch state and an operator-visible
   "planned but not observed" exception.
5. Run k6/Locust tests through Docker, collect p50/p95/p99, and test 30 logical
   subdivision partitions.
6. Observe control-room users on a night shift and revise information density,
   language, and acknowledgement flow.