// Typed client for the FastAPI service (src/data_room_intelligence/service/api.py).
import { useEffect, useState } from "react";

export type Sev = "blocking" | "warning" | "info";
export type IssueCounts = Partial<Record<Sev, number>>;
export type Json = Record<string, unknown>;

export interface NodeCard { id: string; type: string; label: string; level?: number | null; issues: IssueCounts; props: Json; parents?: string[]; file?: string | null; locator?: string | null }
export interface EdgeView { id: string; source: string; target: string; kind: string; method: string; conflict: boolean; evidence: string | null; file: string | null; props: Json }
export interface Neighborhood { focus: string; depth: number; hub: boolean; capped: number; nodes: NodeCard[]; edges: EdgeView[] }
export interface SchemaLink { source: string; kind: string; target: string; method: string; count: number }
export interface SchemaView { types: { type: string; count: number; issues: IssueCounts }[]; links: SchemaLink[] }
export interface Fact { subject: string; measure: string; value: number; unit: string | null; zone: string | null; period: string | null; item: string | null; section?: string | null; case_id?: string | null; dataset_id?: string; file?: string; locator?: string; quality: string | null }
export interface Assertion { label: string; value: unknown; entity: string | null; file: string | null; locator: string | null }
export interface Decision { choice: string; reason: string; reviewer: string; decided_at?: string; scope?: string }
export interface Issue { issue_id: string; rule: string; severity: Sev; subject: string; qualifier: string | null; detail: string; blocks: string; assertions: Assertion[]; status: string; decision: Decision | null; subject_label?: string; subject_type?: string }
export interface PropertyDef { name: string; type: string; unit?: string | null; description?: string | null; required?: boolean }
export interface EntityTypeDef { name: string; id_prefix: string; key: string; description: string; properties: PropertyDef[]; standard?: string | null }
export interface RelationshipDef { name: string; source: string; target: string; method: string; build_rule: string; description?: string | null }
export interface MeasureDef { name: string; subject: string; unit: string; dimensions: string[]; description: string; sources: string[] }
export interface RuleDef { code: string; title: string; subject: string; check: string; severity: Sev; blocks: string }
export interface AliasTable { name?: string; status?: string; description?: string; entries?: Record<string, string | null>; [key: string]: unknown }
export interface Catalog { catalog_version: string; status: string; description?: string; entity_types: EntityTypeDef[]; relationship_types: RelationshipDef[]; measures: MeasureDef[]; rules: (RuleDef & { count: number })[]; aliases: Record<string, AliasTable>; counts: { entities: Record<string, number>; relationships: Record<string, number> } }
export interface Link { direction: "out" | "in"; kind: string; method: string; file: string | null; locator: string | null; props: Json; conflict: boolean; other: NodeCard }
export type Geometry =
  | { type: "Polygon"; coordinates: number[][][] }
  | { type: "MultiPolygon"; coordinates: number[][][][] }
  | { type: "LineString"; coordinates: number[][] }
  | { type: "MultiLineString"; coordinates: number[][][] }
  | { type: "Point"; coordinates: number[] };
export interface Interpret { node: NodeCard; aliases: string[]; links: Link[]; link_count: number; facts: Fact[]; fact_count: number; issues: Issue[]; geometry: Geometry[]; schema: EntityTypeDef; measures: MeasureDef[] }
export interface Counts { entities: number; entities_by_type: Record<string, number>; relationships: number; relationships_by_kind: Record<string, number>; facts: number; geometries: number; aliases: number; issues: number; issues_by_rule: Record<string, number> }
export interface Room { room_id: string; snapshot_id: string; status: string; catalog_version: string; rules_version: string; built_at: string; files: number; counts: Counts; name: string; open_issues: IssueCounts; decided_issues: number }
export interface SheetInfo { sheet: string; rows: number; columns: number; filled_cells: number; formula_cells: number; uncached_formulas: number }
export interface FileItem { file_id: string; path: string; kind: string; role: string | null; size_bytes: number; sha256: string; as_of: string | null; protection: string | null; bundle: string | null; sidecars: number; sheets: SheetInfo[]; pages: number | null; figures: number | null; claims: number | null; issues: Record<string, number>; incoming: boolean }
export interface Mapping { dataset_id: string; file: string; field_id: string; column: string; header: string; header_key: string; target: string; kind: string; transform: string | null; method: string; status: string; confidence: number; rationale: string; match_rate?: string | null; decided_by?: string }
export interface FieldSchema { field_id: string; dataset_id: string; column_ref: string; header_path: string[]; inferred_type: string; unit: string | null; scale: string | null; rows: number; null_rate: number; distinct_count: number; samples: unknown[]; formula_count: number; uncached_formula_count: number; candidate_key: boolean }
export interface DatasetSchema { dataset_id: string; file: string; kind: string; locator: string | null; header_rows: number[]; record_count: number; fields: FieldSchema[]; crs: string | null; notes: string[] }
export interface TableInfo { dataset_id: string; file_id: string; file: string; sheet: string; header_rows: number[]; headers: Record<string, string[]>; records: number; family: string; context: Json }
export interface Chart { chart_type: string; title: string | null; unit: string | null; series: { name: string; points: { x: string; y: number | null }[] }[]; notes?: string | null }
export interface Figure { id: string; page: number; polygon: number[]; image: string; crop: string; chart: Chart | null; status: string; model: string; seconds: number }
export interface DocPage { page: number; width: number; height: number; unit: string; image: string; lines: { content: string; polygon: number[] }[] }
export interface Claim { claim_id: string; label: string; value: number; unit: string | null; raw: string; page: number; polygon: number[] }
export interface DocumentData { file: string; file_id: string; source: string; model: string; api_version: string; pages: DocPage[]; paragraphs: { role: string | null; content: string; page: number; polygon: number[] }[]; tables: Json[]; figures: Figure[]; claims: Claim[] }
export interface ClaimCheck { check: string; computed: number | null; computed_from: string | null; entity: string }
export interface FileDetail { entry: FileItem; datasets: DatasetSchema[]; tables: Record<string, TableInfo>; mappings: Mapping[]; document: DocumentData | null; claim_checks: Record<string, ClaimCheck> }
export type CellValue = string | number | boolean | null;
export interface GridWindow { sheet: string; max_row: number; max_col: number; r0: number; r1: number; c0: number; c1: number; rows: CellValue[][]; formulas: number[][] }
export interface CellLineage { locator: string; value: CellValue; facts: Fact[]; links: { kind: string; source: string; target: string; method: string }[]; entities: NodeCard[]; mapping: Mapping | null; issues: Issue[] }
export interface Citation { file: string | null; locator: string | null; label: string }
export interface Action { type: "focus" | "inspect" | "review" | "document" | "view"; label: string; entity?: string; rule?: string; file_id?: string; page?: number; view?: string; mode?: string }
export interface OperationResult { operation: string; args: Json; data: Json; summary: string; citations: Citation[]; actions: Action[] }
export interface Answer { question: string; answer: string; mode: string; operations: { operation: string; args: Json }[]; results: { operation: string; data: Json; summary: string }[]; citations: Citation[]; actions: Action[]; seconds: number }
export interface RuleSummary extends RuleDef { open: number; decided: number }
export interface Health { status: string; offline: boolean; model: string | null; room_id: string }
export interface RebuildResult { snapshot_id: string; status: string; counts: Counts; file_id?: string; proposals?: Mapping[] }
export interface GeoFeature { type: "Feature"; properties: { entity: string | null; issues: IssueCounts; feature_id: string; [key: string]: unknown }; geometry: Geometry }
export interface GeoLayer { type: "FeatureCollection"; name: string; features: GeoFeature[] }

const cache = new Map<string, Promise<unknown>>();

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* keep status text */
    }
    throw new Error(`${response.status} ${detail}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  get<T>(url: string): Promise<T> {
    if (!cache.has(url)) {
      const pending = request<T>(url);
      cache.set(url, pending);
      pending.catch(() => cache.delete(url));
    }
    return cache.get(url) as Promise<T>;
  },
  post<T>(url: string, body?: unknown): Promise<T> {
    return request<T>(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) });
  },
  upload<T>(url: string, file: File): Promise<T> {
    const form = new FormData();
    form.append("file", file);
    return request<T>(url, { method: "POST", body: form });
  },
  invalidate(): void {
    cache.clear();
  },
};

export const q = (params: Record<string, string | number | boolean | null | undefined>): string =>
  Object.entries(params)
    .filter(([, v]) => v != null && v !== "")
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
    .join("&");

export function useFetch<T>(url: string | null, version: number): { data: T | null; error: string | null; loading: boolean } {
  const [state, setState] = useState<{ url: string | null; version: number; data: T | null; error: string | null }>({ url: null, version: -1, data: null, error: null });
  useEffect(() => {
    if (!url) return;
    let live = true;
    api.get<T>(url).then(
      (data) => live && setState({ url, version, data, error: null }),
      (error: Error) => live && setState({ url, version, data: null, error: error.message }),
    );
    return () => {
      live = false;
    };
  }, [url, version]);
  const current = state.url === url && state.version === version;
  return { data: state.url === url ? state.data : null, error: current ? state.error : null, loading: Boolean(url) && !current };
}
