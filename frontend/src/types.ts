export type TicketStatus =
  | "detected"
  | "acknowledged"
  | "crew_assigned"
  | "resolved"
  | "closed";

export interface TimelineEntry {
  at: string;
  event: string;
  detail: string;
}

export interface CausalFingerprint {
  predicted_reporting: number;
  observed_dark: number;
  silent_or_unknown: number;
  live_contradictions: number;
  unexplained_dark: number;
  expected_loss_reports: number;
  fit_score: number;
  verdict: string;
  schedule_context: "none" | "matched" | "mismatch";
  schedule_coverage: number | null;
}

export interface Incident {
  incident_id: string;
  kind: "span" | "transformer" | "feeder";
  asset_id: string;
  feeder_id: string;
  dt_id: string | null;
  upstream_pole_id: string | null;
  downstream_pole_id: string | null;
  candidate_path: string[];
  lat: number;
  lon: number;
  pincode: string | null;
  affected_poles: number;
  confidence: number;
  reasons: string[];
  status: TicketStatus;
  detected_at: string;
  crew: string | null;
  verification_ratio: number;
  fingerprint: CausalFingerprint;
  timeline: TimelineEntry[];
}

export interface Simulation {
  simulation_id: string;
  kind: string;
  target_id: string;
  affected_poles: number;
  started_at: string;
  scheduled: boolean;
  repaired: boolean;
  schedule_scope_id: string | null;
}

export interface Dashboard {
  summary: {
    active_incidents: number;
    affected_poles: number;
    network_poles: number;
    reporting_devices: number;
    inferred_topology_pct: number;
    ingest: { accepted: number; duplicates: number; stale: number; rejected: number };
  };
  incidents: Incident[];
  simulations: Simulation[];
}

export interface Pole {
  pole_id: string;
  lat: number;
  lon: number;
  feeder_id: string;
  dt_id: string;
  pincode: string | null;
  parent_pole_id: string | null;
  topology_source: "recorded" | "inferred";
  device_id: string | null;
  energized: boolean;
}

export interface Transformer {
  dt_id: string;
  feeder_id: string;
  lat: number;
  lon: number;
  capacity_kva: number;
  households_served: number;
}

export interface NetworkMap {
  poles: Pole[];
  transformers: Transformer[];
}

export interface OperatorBrief {
  headline: string;
  situation: string;
  evidence: string[];
  recommended_action: string;
  uncertainty: string;
  language: string;
  mode: string;
  estimated_cost_usd: number;
}