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
export const when = (iso: string | null | undefined): string => (iso ? new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "—");

/** Presentation of the base entity types. Types added to a project's model get a stable colour from their name. */
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
const hueOf = (name: string): number => [...name].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);
/** Colour expression for a type: a design token for base types, a hashed hue for project types. */
export const typeToken = (t: string): string => (TYPE_META[t] ? `var(${TYPE_META[t].color})` : `${hueOf(t)} 55% 50%`);
export const typeShort = (t: string): string => TYPE_META[t]?.short ?? t.replace(/([a-z])([A-Z])/g, "$1 $2");
export const typeColor = (t: string): string => `hsl(${typeToken(t)})`;
export const typeFill = (t: string, a: number): string => `hsl(${typeToken(t)} / ${a})`;
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
  UNMATCHED_LINK: ["Ignore rows", "Add the missing entities", "Ask seller", "Defer"],
  FORMULA_CACHE_MISSING: ["Recalculate in Excel", "Ignore", "Defer"],
};

/** Business wording for each rule: the question a decision answers and who usually owns it. */
export const RULE_LABELS: Record<string, { question: string; owner: string; policy: string[] }> = {
  UNIT_ASSIGNMENT_CONFLICT: { question: "Which unit does a well belong to when the economics file and the map disagree?", owner: "Land", policy: ["Use GIS unit", "Use ComboCurve unit"] },
  OWNERSHIP_VALUE_CONFLICT: { question: "Which working interest governs when the unit workbook and the map file disagree?", owner: "Land / Finance", policy: ["Workbook governs", "GIS governs"] },
  VALUE_FIELD_CONFLICT: { question: "Which of the two '10% Discount Cash Flow' columns is PV-10?", owner: "Finance", policy: ["KY is PV-10", "MF is PV-10"] },
  ZONE_ALIAS_MISSING: { question: "Which bench does a landing zone without an approved alias belong to?", owner: "Subsurface", policy: ["Exclude from zone totals"] },
  OPERATOR_ALIAS_CONFLICT: { question: "Is a seller-operated location that is tagged NON-OP operated or not?", owner: "Operations", policy: ["Operated", "Non-operated"] },
  CROSSWALK_MISSING: { question: "How do battery codes map to pricing facilities?", owner: "Marketing", policy: ["Mark unsupported"] },
  FORMULA_CACHE_MISSING: { question: "What to do with workbook formulas that have no saved value?", owner: "Finance", policy: ["Ignore"] },
  CLAIM_MISMATCH: { question: "Is a headline number in the seller's deck wrong, or just rounded?", owner: "Deal team", policy: ["Deck is rounded", "Deck is wrong"] },
  UNMATCHED_KEY: { question: "What to do with rows of a new file that name an entity the room does not have?", owner: "Data steward", policy: ["Ignore rows"] },
  UNMATCHED_LINK: { question: "What to do with rows of a new file that link to an entity the room does not have?", owner: "Data steward", policy: ["Ignore rows"] },
};

/** How a field mapping was proposed: header rule, value overlap with existing keys, keyword rule or model. */
export const methodLabel = (m: { method: string; rationale?: string; match_rate?: string | null }): string => {
  if (m.match_rate || m.rationale?.startsWith("value overlap")) return "value overlap";
  if (m.rationale?.startsWith("header rule")) return "header rule";
  if (m.method === "model") return "model proposal";
  if (m.method === "reviewer") return "reviewer";
  return "keyword rule";
};

export const STEPS: { id: "data" | "model" | "decisions" | "publish" | "ask"; label: string; hint: string }[] = [
  { id: "data", label: "Data", hint: "Files in the data room, what was read from them, and where every value comes from" },
  { id: "model", label: "Model", hint: "The project's model: proposed changes for new kinds of data, field mappings to approve, the dictionary and the graph" },
  { id: "decisions", label: "Decisions", hint: "Where the seller's files disagree; decide once per question or review the exceptions" },
  { id: "publish", label: "Publish", hint: "Snapshot status, what changed since the previous build, the publish gate and exports" },
  { id: "ask", label: "Ask", hint: "Explore the connected picture and ask questions answered from the data with citations" },
];
