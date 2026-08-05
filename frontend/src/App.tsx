import {
  Activity,
  AlertTriangle,
  Bot,
  CalendarX2,
  Check,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  CircleDot,
  Clock3,
  FlaskConical,
  MapPin,
  Radio,
  RefreshCw,
  ShieldAlert,
  ScanSearch,
  Sparkles,
  Users,
  Wrench,
  X,
  Zap,
} from "lucide-react";
import { startTransition, useEffect, useState } from "react";
import { api } from "./api";
import { MapView } from "./MapView";
import type { Dashboard, Incident, NetworkMap, OperatorBrief } from "./types";

const SIMULATION_GROUPS = [
  {
    label: "Grid faults",
    tone: "faults",
    scenarios: [
      { kind: "span", label: "Span", icon: Zap },
      { kind: "dt", label: "DT", icon: CircleDot },
      { kind: "feeder", label: "Feeder", icon: Activity },
    ],
  },
  {
    label: "Exceptions",
    tone: "exceptions",
    scenarios: [
      { kind: "sensor_failure", label: "Dead sensor", icon: Radio },
      { kind: "scheduled_outage", label: "Scheduled", icon: Clock3 },
      { kind: "schedule_mismatch", label: "Plan mismatch", icon: CalendarX2 },
      { kind: "duplicate_noise", label: "Dirty data", icon: ShieldAlert },
    ],
  },
];

function formatTime(value: string) {
  return new Intl.DateTimeFormat("en-IN", { hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

function statusLabel(status: string) {
  return status.replaceAll("_", " ");
}

export default function App() {
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [network, setNetwork] = useState<NetworkMap | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [brief, setBrief] = useState<OperatorBrief | null>(null);
  const [language, setLanguage] = useState("English");
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [connectionState, setConnectionState] = useState<"connecting" | "online" | "unavailable">("connecting");
  const [scenarioOpen, setScenarioOpen] = useState(false);

  async function refresh(includeNetwork = false) {
    const [nextDashboard, nextNetwork] = await Promise.all([
      api.dashboard(),
      includeNetwork ? api.network() : Promise.resolve(null),
    ]);
    setConnectionState("online");
    startTransition(() => {
      setDashboard(nextDashboard);
      if (nextNetwork) setNetwork(nextNetwork);
      setSelectedId((current) =>
        nextDashboard.incidents.some((item) => item.incident_id === current)
          ? current
          : nextDashboard.incidents.find((item) => item.status !== "closed")?.incident_id ?? null,
      );
    });
  }

  useEffect(() => {
    const initialRefresh = window.setTimeout(
      () => void refresh(true).catch((error: Error) => {
        setConnectionState("unavailable");
        setMessage(error.message);
      }),
      0,
    );
    const interval = window.setInterval(
      () => void refresh().catch(() => setConnectionState("unavailable")),
      2_500,
    );
    return () => {
      window.clearTimeout(initialRefresh);
      window.clearInterval(interval);
    };
  }, []);

  const selected = dashboard?.incidents.find((incident) => incident.incident_id === selectedId) ?? null;
  const orderedIncidents = [...(dashboard?.incidents ?? [])].sort((left, right) => {
    const leftClosed = left.status === "closed";
    const rightClosed = right.status === "closed";
    if (leftClosed !== rightClosed) return leftClosed ? 1 : -1;
    if (!leftClosed && left.affected_households !== right.affected_households) {
      return right.affected_households - left.affected_households;
    }
    return Date.parse(right.detected_at) - Date.parse(left.detected_at);
  });
  const active = orderedIncidents.filter((incident) => incident.status !== "closed");
  const activeScenarioCount = dashboard?.simulations.filter((item) => !item.repaired).length ?? 0;

  async function run(label: string, action: () => Promise<unknown>, success: string, mapChanged = false) {
    setBusy(label);
    setMessage(null);
    try {
      await action();
      await refresh(mapChanged);
      setMessage(success);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Action failed");
    } finally {
      setBusy(null);
    }
  }

  async function generateBrief() {
    if (!selected) return;
    setBusy("brief");
    setBrief(null);
    try {
      setBrief(await api.brief(selected.incident_id, language));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Brief generation failed");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-block">
          <div className="brand-mark"><Zap size={20} strokeWidth={2.5} /></div>
          <div><strong>GRIDWATCH</strong><span>Karnataka distribution control</span></div>
        </div>
        <div className={`system-state ${connectionState}`}>
          <i />
          {connectionState === "online"
            ? "Telemetry online"
            : connectionState === "connecting"
              ? "Connecting telemetry"
              : "Telemetry unavailable"}
          <span> · 2.5s refresh</span>
        </div>
        <div className="shift-block"><span>Subdivision SD-07</span><strong>Night control · Bengaluru</strong></div>
      </header>

      <section className="status-strip">
        <div className={active.length ? "metric critical" : "metric clear"}>
          <span>Active incidents</span><strong>{dashboard?.summary.active_incidents ?? "—"}</strong>
        </div>
        <div className="metric"><span>Homes affected</span><strong>{dashboard?.summary.affected_households.toLocaleString("en-IN") ?? "—"}</strong></div>
        <div className="metric"><span>Devices reporting</span><strong>{dashboard?.summary.reporting_devices.toLocaleString("en-IN") ?? "—"}</strong></div>
        <div className="metric topology"><span>Topology inferred</span><strong>{dashboard?.summary.inferred_topology_pct ?? "—"}%</strong></div>
        <div className="metric ingest"><span>Messages accepted</span><strong>{dashboard?.summary.ingest.accepted.toLocaleString("en-IN") ?? "—"}</strong></div>
      </section>

      <main className="workspace">
        <aside className="incident-rail">
          <div className="panel-heading">
            <div><span className="eyebrow">Priority queue</span><h1>Incidents</h1></div>
            <span className="count-badge">{active.length} open</span>
          </div>
          <div className="incident-list">
            {orderedIncidents.length === 0 && (
              <div className="empty-state"><Check size={26} /><strong>No active faults</strong><span>Network telemetry is nominal.</span></div>
            )}
            {orderedIncidents.map((incident) => (
              <button
                className={`incident-row ${selectedId === incident.incident_id ? "selected" : ""} ${incident.status === "closed" ? "closed" : ""}`}
                key={incident.incident_id}
                onClick={() => { setSelectedId(incident.incident_id); setBrief(null); }}
              >
                <span className={`severity ${incident.confidence < 0.8 ? "uncertain" : ""}`}><AlertTriangle size={17} /></span>
                <span className="incident-copy">
                  <span className="incident-meta"><b>{incident.kind.toUpperCase()}</b> · {formatTime(incident.detected_at)}</span>
                  {incident.fingerprint.schedule_context === "mismatch" && <span className="plan-flag">PLAN MISMATCH</span>}
                  <strong>{incident.asset_id}</strong>
                  <span>PIN {incident.pincode ?? "unavailable"} · {incident.affected_households} homes · {incident.affected_poles} poles</span>
                  <span className="row-footer"><i className={`status-dot ${incident.status}`} />{statusLabel(incident.status)}<b>{Math.round(incident.confidence * 100)}%</b></span>
                </span>
                <ChevronRight size={17} />
              </button>
            ))}
          </div>
        </aside>

        <section className="map-region">
          <MapView network={network} incidents={dashboard?.incidents ?? []} selected={selected} onSelect={setSelectedId} />
        </section>

        <aside className={`detail-panel ${selected ? "open" : ""}`}>
          {selected ? (
            <IncidentDetail
              incident={selected}
              brief={brief}
              language={language}
              busy={busy}
              onLanguage={setLanguage}
              onBrief={() => void generateBrief()}
              onAction={(action, crew) => void run(action, () => api.transition(selected.incident_id, action, crew), `${action} recorded`)}
              onClose={() => setSelectedId(null)}
            />
          ) : (
            <div className="detail-empty"><MapPin size={26} /><span>Select an incident or inject a fault.</span></div>
          )}
        </aside>
      </main>

      <section className={`simulator-bar ${scenarioOpen ? "expanded" : "collapsed"}`}>
        <button
          className="sim-toggle"
          aria-expanded={scenarioOpen}
          title={scenarioOpen ? "Close scenario lab" : "Open scenario lab"}
          onClick={() => setScenarioOpen((open) => !open)}
        >
          <FlaskConical size={18} />
          <span className="sim-toggle-copy"><span className="eyebrow">Training sandbox</span><strong>Scenario lab</strong></span>
          <small className={activeScenarioCount ? "active" : ""}>
            {activeScenarioCount ? `${activeScenarioCount} active` : "Baseline"}
          </small>
          {scenarioOpen ? <ChevronDown size={17} /> : <ChevronUp size={17} />}
        </button>
        {scenarioOpen && (
          <>
            <div className="scenario-groups">
              {SIMULATION_GROUPS.map((group) => (
                <div className={`scenario-group ${group.tone}`} key={group.label}>
                  <span>{group.label}</span>
                  <div className="scenario-actions">
                    {group.scenarios.map(({ kind, label, icon: Icon }) => (
                      <button key={kind} title={`Inject ${label}`} disabled={Boolean(busy)} onClick={() => void run(kind, () => api.simulate(kind), `${label} injected`, true)}>
                        <Icon size={15} />{label}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
            <div className="repair-actions">
              {dashboard?.simulations.filter((item) => !item.repaired && !item.scheduled).slice(-2).map((simulation) => (
                <button className="repair" key={simulation.simulation_id} disabled={Boolean(busy)} onClick={() => void run(`repair-${simulation.simulation_id}`, () => api.repair(simulation.simulation_id), `${simulation.target_id} restored`, true)}>
                  <Wrench size={15} />Repair {simulation.target_id}
                </button>
              ))}
              <button className="icon-button" title="Reset simulation" disabled={Boolean(busy)} onClick={() => void run("reset", api.reset, "Simulation reset", true)}><RefreshCw size={17} /></button>
            </div>
          </>
        )}
      </section>

      {message && <div className="toast"><span>{message}</span><button title="Dismiss" onClick={() => setMessage(null)}><X size={15} /></button></div>}
    </div>
  );
}

interface DetailProps {
  incident: Incident;
  brief: OperatorBrief | null;
  language: string;
  busy: string | null;
  onLanguage: (language: string) => void;
  onBrief: () => void;
  onAction: (action: string, crew?: string) => void;
  onClose: () => void;
}

function IncidentDetail({ incident, brief, language, busy, onLanguage, onBrief, onAction, onClose }: DetailProps) {
  return (
    <>
      <div className="detail-head">
        <div><span className="eyebrow">{incident.incident_id}</span><h2>{incident.asset_id}</h2></div>
        <button className="icon-button" title="Close details" onClick={onClose}><X size={18} /></button>
      </div>
      <div className="location-line"><MapPin size={17} /><strong>PIN {incident.pincode ?? "unavailable"}</strong><span>{incident.lat.toFixed(5)}, {incident.lon.toFixed(5)}</span></div>
      <div className="impact-block">
        <div><span>Estimated impact</span><strong>{incident.affected_households}</strong><small>homes · {incident.affected_poles} poles</small></div>
        <div><span>Confidence</span><strong>{Math.round(incident.confidence * 100)}%</strong><small>{incident.confidence >= 0.8 ? "high" : "verify on map"}</small></div>
      </div>
      <div className="confidence-track"><i style={{ width: `${incident.confidence * 100}%` }} /></div>

      {incident.fingerprint.schedule_context === "mismatch" && (
        <div className="plan-mismatch">
          <CalendarX2 size={20} />
          <div>
            <strong>Planned outage contradicted</strong>
            <span>
              Only {Math.round((incident.fingerprint.schedule_coverage ?? 0) * 100)}% of the
              expected DT shutdown signature appeared. Treat this as an unplanned fault.
            </span>
          </div>
        </div>
      )}

      <section className="detail-section ai-section">
        <div className="section-title"><div><Bot size={17} /><h3>Dispatch brief</h3></div><select value={language} onChange={(event) => onLanguage(event.target.value)}><option>English</option><option>Kannada</option><option>Hindi</option></select></div>
        {!brief && (
          <div className="brief-preview">
            <strong>{incident.kind.toUpperCase()} fault · {incident.asset_id}</strong>
            <p>
              Estimated {incident.affected_households} homes affected across {incident.affected_poles}
              {" "}poles in PIN {incident.pincode ?? "unavailable"}. Localization confidence is {Math.round(incident.confidence * 100)}%.
            </p>
            <p className="brief-action">Review the highlighted impact corridor, acknowledge the incident, and dispatch only from the locked ticket facts.</p>
            <button className="ai-button" onClick={onBrief} disabled={Boolean(busy)}><Sparkles size={16} />{busy === "brief" ? "Generating…" : "Refine or translate"}</button>
            <small>Deterministic preview · model cannot change location or status</small>
          </div>
        )}
        {brief && (
          <div className="brief-output">
            <strong>{brief.headline}</strong><p>{brief.situation}</p>
            <ul>{brief.evidence.map((item) => <li key={item}>{item}</li>)}</ul>
            <p className="brief-action">{brief.recommended_action}</p>
            <small>{brief.mode.replaceAll("_", " ")} · facts locked</small>
          </div>
        )}
      </section>

      <section className="detail-section fingerprint-section">
        <div className="fingerprint-heading">
          <div><ScanSearch size={17} /><h3>Causal fingerprint</h3></div>
          <strong>{Math.round(incident.fingerprint.fit_score * 100)}% fit</strong>
        </div>
        <p className="fingerprint-verdict">{incident.fingerprint.verdict}</p>
        <div className="fingerprint-meter" aria-label="Telemetry evidence composition">
          <i
            className="observed"
            style={{ flex: Math.max(incident.fingerprint.observed_dark, 0.2) }}
            title="Observed power-loss packets"
          />
          <i
            className="silent"
            style={{ flex: Math.max(incident.fingerprint.silent_or_unknown, 0.2) }}
            title="Silent or unknown devices"
          />
          {(incident.fingerprint.live_contradictions + incident.fingerprint.unexplained_dark) > 0 && (
            <i
              className="contradiction"
              style={{
                flex: incident.fingerprint.live_contradictions + incident.fingerprint.unexplained_dark,
              }}
              title="Contradictory evidence"
            />
          )}
        </div>
        <div className="fingerprint-stats">
          <div><strong>{incident.fingerprint.observed_dark}</strong><span>loss packets</span></div>
          <div><strong>{incident.fingerprint.silent_or_unknown}</strong><span>silent / unknown</span></div>
          <div><strong>{incident.fingerprint.live_contradictions}</strong><span>live conflicts</span></div>
          <div><strong>{incident.fingerprint.unexplained_dark}</strong><span>outside model</span></div>
        </div>
        <p className="fingerprint-note">
          Expected about {incident.fingerprint.expected_loss_reports} dying packets from {incident.fingerprint.predicted_reporting} eligible downstream devices.
        </p>
      </section>

      <section className="detail-section">
        <h3>Why this location</h3>
        <ul className="evidence-list">{incident.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
      </section>

      <section className="detail-section workflow">
        <h3>Ticket workflow</h3>
        <div className="workflow-state"><i className={`status-dot ${incident.status}`} /><strong>{statusLabel(incident.status)}</strong>{incident.crew && <span>{incident.crew}</span>}</div>
        <div className="workflow-actions">
          {incident.status === "detected" && <button onClick={() => onAction("acknowledge")} disabled={Boolean(busy)}><Check size={16} />Acknowledge</button>}
          {incident.status === "acknowledged" && <button onClick={() => onAction("assign", "Crew 3 · Jayanagar")} disabled={Boolean(busy)}><Users size={16} />Assign crew</button>}
          {incident.status === "crew_assigned" && <button onClick={() => onAction("resolve")} disabled={Boolean(busy)}><Wrench size={16} />Mark work complete</button>}
        </div>
        {incident.status === "resolved" && <div className="awaiting"><Radio size={16} />Awaiting restoration telemetry. Manual closure is disabled.</div>}
        {incident.status === "closed" && <div className="verified"><Check size={16} />Verified automatically · {Math.round(incident.verification_ratio * 100)}% restored</div>}
      </section>

      <section className="detail-section timeline">
        <h3>Event trail</h3>
        {incident.timeline.map((entry) => <div key={`${entry.at}-${entry.event}`}><i /><span>{formatTime(entry.at)}</span><strong>{statusLabel(entry.event)}</strong><p>{entry.detail}</p></div>)}
      </section>
    </>
  );
}