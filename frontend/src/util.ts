// Formatting helpers and catalog presentation metadata shared by all views.
import type { IssueCounts, Sev } from "./api";

export const nf = (v: unknown, d = 0): string => {
  if (v == null || v === "") return "—";
  const n = typeof v === "number" ? v : Number(v);
  return Number.isNaN(n) ? String(v) : n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
};
export const pct = (v: number | null | undefined, d = 1): string => (v == null ? "—" : `${nf(v * 100, d)}%`);
export const clip = (t: unknown, n = 26): string => {
  const s = String(t ?? "");
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
};
export const colIndex = (letters: string): number => letters.split("").reduce((a, c) => a * 26 + c.charCodeAt(0) - 64, 0);
export const colLetter = (n: number): string => {
  let s = "";
  while (n > 0) {
    const m = (n - 1) % 26;
    s = String.fromCharCode(65 + m) + s;
    n = Math.floor((n - 1) / 26);
  }
  return s;
};
export const splitCell = (cell: string): [string, number] => {
  const m = /^([A-Z]+)(\d+)$/.exec(cell);
  return m ? [m[1], Number(m[2])] : ["A", 1];
};
export const basename = (path: string | null | undefined): string => (path ?? "").split("/").pop() ?? "";

export const TYPE_META: Record<string, { color: string; short: string }> = {
  Asset: { color: "--type-asset", short: "Asset" },
  Unit: { color: "--type-unit", short: "Unit" },
  Zone: { color: "--type-zone", short: "Zone" },
  Well: { color: "--type-well", short: "Well" },
  EconomicLocation: { color: "--type-location", short: "Location" },
  EconomicCase: { color: "--type-case", short: "Case" },
  LeaseholdTract: { color: "--type-tract", short: "Tract" },
  Operator: { color: "--type-operator", short: "Operator" },
  County: { color: "--type-county", short: "County" },
  DevelopmentArea: { color: "--type-devarea", short: "Dev area" },
  BatteryCode: { color: "--type-battery", short: "Battery" },
  PricingFacility: { color: "--type-facility", short: "Facility" },
  ReportingScope: { color: "--type-scope", short: "Scope" },
  DocumentClaim: { color: "--type-claim", short: "Claim" },
};
export const TYPE_ORDER = Object.keys(TYPE_META);
export const typeColor = (t: string): string => `hsl(var(${TYPE_META[t]?.color ?? "--muted-text"}))`;
export const typeFill = (t: string, a: number): string => `hsl(var(${TYPE_META[t]?.color ?? "--muted-text"}) / ${a})`;
export const METHODS = ["source", "key", "spatial", "alias", "document", "crosswalk"];

export const SEVERITIES: Sev[] = ["blocking", "warning", "info"];
export const worst = (c: IssueCounts | undefined, allowed: Sev[] = SEVERITIES): Sev | null => SEVERITIES.find((s) => allowed.includes(s) && (c?.[s] ?? 0) > 0) ?? null;
export const issueTotal = (c: IssueCounts | undefined, allowed: Sev[] = SEVERITIES): number => allowed.reduce((sum, s) => sum + (c?.[s] ?? 0), 0);

export const ZONES = ["USS", "MSS", "JM", "LSS", "DEAN", "WCA", "WCB I", "WCB II", "WCC", "WCD", "STR / BND", "UP BRNT", "LR BRNT", "MSSP", "WDFD"];

/** Decision options per rule shown in the review pane (the reviewer can also type their own). */
export const DECISION_OPTIONS: Record<string, string[]> = {
  UNIT_ASSIGNMENT_CONFLICT: ["Use ComboCurve unit", "Use GIS unit", "Accept both", "Defer"],
  OWNERSHIP_VALUE_CONFLICT: ["Workbook governs", "GIS governs", "Accept both", "Defer"],
  VALUE_FIELD_CONFLICT: ["KY is PV-10", "MF is PV-10", "Ask seller", "Defer"],
  OPERATOR_ALIAS_CONFLICT: ["Operated", "Non-operated", "Ask seller", "Defer"],
  ZONE_ALIAS_MISSING: ["Map to LSS", "New bench", "Exclude from zone totals", "Defer"],
  CROSSWALK_MISSING: ["Supply crosswalk", "Mark unsupported", "Defer"],
  CLAIM_MISMATCH: ["Deck is rounded", "Deck is wrong", "Ask seller", "Defer"],
  UNMATCHED_KEY: ["Ignore rows", "Add wells", "Ask seller", "Defer"],
  FORMULA_CACHE_MISSING: ["Recalculate in Excel", "Ignore", "Defer"],
};

/** How a field mapping was proposed: header rule, value overlap with existing keys, keyword rule or model. */
export const methodLabel = (m: { method: string; rationale?: string; match_rate?: string | null }): string => {
  if (m.match_rate || m.rationale?.startsWith("value overlap")) return "value overlap";
  if (m.rationale?.startsWith("header rule")) return "header rule";
  if (m.method === "model") return "model proposal";
  if (m.method === "reviewer") return "reviewer";
  return "keyword rule";
};
