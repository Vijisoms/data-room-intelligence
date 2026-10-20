// Explore: ontology graph (schema overview or entity neighborhood) with search, filters, quick card and inspector.
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, q, useFetch, type Catalog, type Neighborhood, type NodeCard, type SchemaView, type Sev } from "../api";
import { useApp } from "../store";
import { Dot, ErrorBox, Icon, Loading, SevChip, TypeTag } from "../ui";
import { METHODS, SEVERITIES, TYPE_ORDER, clip, issueTotal, nf, typeColor, typeFill, typeShort, worst } from "../util";

type Bounds = [number, number, number, number];

export function SearchBox({ onPick, placeholder = "Search units, wells, APIs, locations, zones…" }: { onPick: (node: NodeCard) => void; placeholder?: string }) {
  const [text, setText] = useState("");
  const [hits, setHits] = useState<NodeCard[]>([]);
  const [active, setActive] = useState(0);
  const [open, setOpen] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const value = text.trim();
    if (!value) {
      setHits([]);
      return;
    }
    const timer = window.setTimeout(() => {
      api.get<NodeCard[]>(`/api/graph/viz/search?${q({ q: value, limit: 40 })}`).then(
        (result) => {
          setHits(result);
          setActive(0);
          setOpen(true);
        },
        () => setHits([]),
      );
    }, 120);
    return () => window.clearTimeout(timer);
  }, [text]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "/" && !["INPUT", "TEXTAREA"].includes((document.activeElement as HTMLElement)?.tagName)) {
        event.preventDefault();
        input.current?.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);
  const groups = useMemo(() => {
    const map = new Map<string, NodeCard[]>();
    for (const hit of hits) {
      const list = map.get(hit.type) ?? [];
      if (list.length < 6) list.push(hit);
      map.set(hit.type, list);
    }
    return [...map.entries()];
  }, [hits]);
  const flat = groups.flatMap(([, list]) => list);
  const pick = (node: NodeCard) => {
    setText("");
    setOpen(false);
    onPick(node);
  };
  let index = -1;
  return (
    <div className="search">
      <Icon name="search" />
      <input
        ref={input}
        type="search"
        value={text}
        placeholder={placeholder}
        aria-label="Search entities"
        autoComplete="off"
        role="combobox"
        aria-expanded={open && flat.length > 0}
        aria-controls="suggest"
        onChange={(event) => setText(event.target.value)}
        onFocus={() => setOpen(true)}
        onBlur={() => window.setTimeout(() => setOpen(false), 120)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            setActive((a) => (a + (event.key === "ArrowDown" ? 1 : -1) + flat.length) % Math.max(flat.length, 1));
          }
          if (event.key === "Enter" && flat[active]) pick(flat[active]);
          if (event.key === "Escape") {
            setOpen(false);
            input.current?.blur();
          }
        }}
      />
      <kbd>/</kbd>
      {open && flat.length > 0 ? (
        <div className="suggest" id="suggest" role="listbox">
          {groups.map(([type, list]) => (
            <div key={type}>
              <div className="group">
                {typeShort(type)} · {hits.filter((h) => h.type === type).length}
              </div>
              {list.map((node) => {
                index += 1;
                const mine = index;
                return (
                  <button key={node.id} role="option" aria-selected={mine === active} onMouseDown={(event) => { event.preventDefault(); pick(node); }}>
                    <Dot color={typeColor(node.type)} />
                    <span className="label">
                      {node.label}
                      <span className="muted small">{`  ${node.id}`}</span>
                    </span>
                    {worst(node.issues) ? <SevChip sev={worst(node.issues) as Sev}>{nf(issueTotal(node.issues))}</SevChip> : null}
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function GraphCanvas({ bounds, fitKey, label, onBackground, overlays, children }: { bounds: Bounds; fitKey: string; label: string; onBackground: () => void; overlays: ReactNode; children: ReactNode }) {
  const svg = useRef<SVGSVGElement>(null);
  const root = useRef<SVGGElement>(null);
  const cam = useRef({ x: 0, y: 0, k: 1 });
  const drag = useRef<[number, number, number, number] | null>(null);
  const boundsRef = useRef(bounds);
  boundsRef.current = bounds;
  const apply = () => root.current?.setAttribute("transform", `translate(${cam.current.x},${cam.current.y}) scale(${cam.current.k})`);
  const fit = () => {
    const el = svg.current;
    if (!el) return;
    const b = boundsRef.current;
    const w = el.clientWidth || 1000;
    const h = el.clientHeight || 700;
    const k = Math.min(w / (b[2] - b[0]), h / (b[3] - b[1]), 1.6);
    cam.current = { k, x: w / 2 - (k * (b[0] + b[2])) / 2, y: h / 2 - (k * (b[1] + b[3])) / 2 };
    apply();
  };
  const zoomBy = (factor: number, px?: number, py?: number) => {
    const el = svg.current;
    if (!el) return;
    const x = px ?? el.clientWidth / 2;
    const y = py ?? el.clientHeight / 2;
    const c = cam.current;
    const k2 = Math.min(4, Math.max(0.15, c.k * factor));
    cam.current = { x: x - ((x - c.x) * k2) / c.k, y: y - ((y - c.y) * k2) / c.k, k: k2 };
    apply();
  };
  useLayoutEffect(fit, [fitKey]);
  useEffect(() => {
    const el = svg.current;
    if (!el) return;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const r = el.getBoundingClientRect();
      zoomBy(event.deltaY < 0 ? 1.12 : 1 / 1.12, event.clientX - r.left, event.clientY - r.top);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    let width = el.clientWidth;
    const observer = new ResizeObserver(() => {
      if (Math.abs(el.clientWidth - width) > 40) fit();
      width = el.clientWidth;
    });
    observer.observe(el);
    return () => {
      el.removeEventListener("wheel", onWheel);
      observer.disconnect();
    };
  }, []);
  useEffect(apply);
  return (
    <div className="canvas">
      <svg
        ref={svg}
        role="img"
        aria-label={label}
        onPointerDown={(event) => {
          if ((event.target as Element).closest(".node")) return;
          drag.current = [event.clientX, event.clientY, cam.current.x, cam.current.y];
          svg.current?.classList.add("panning");
          svg.current?.setPointerCapture(event.pointerId);
        }}
        onPointerMove={(event) => {
          const d = drag.current;
          if (!d) return;
          cam.current = { ...cam.current, x: d[2] + event.clientX - d[0], y: d[3] + event.clientY - d[1] };
          apply();
        }}
        onPointerUp={(event) => {
          const d = drag.current;
          if (d && Math.abs(event.clientX - d[0]) + Math.abs(event.clientY - d[1]) < 3) onBackground();
          drag.current = null;
          svg.current?.classList.remove("panning");
        }}
      >
        <g ref={root}>{children}</g>
      </svg>
      <div className="overlay zoom">
        <button className="icon-btn" aria-label="Zoom in" onClick={() => zoomBy(1.25)}><Icon name="plus" /></button>
        <button className="icon-btn" aria-label="Zoom out" onClick={() => zoomBy(0.8)}><Icon name="minus" /></button>
        <button className="icon-btn" aria-label="Fit to view" onClick={fit}><Icon name="fit" /></button>
      </div>
      {overlays}
    </div>
  );
}

function layoutNeighborhood(hood: Neighborhood): { pos: Map<string, [number, number]>; bounds: Bounds } {
  const order = (t: string) => TYPE_ORDER.indexOf(t);
  const pos = new Map<string, [number, number]>([[hood.focus, [0, 0]]]);
  const hop1 = hood.nodes.filter((n) => n.level === 1).sort((a, b) => order(a.type) - order(b.type) || a.label.localeCompare(b.label));
  const r1 = Math.max(170, (hop1.length * 62) / (2 * Math.PI));
  const angle = new Map<string, number>();
  hop1.forEach((n, i) => {
    const a = -Math.PI / 2 + (2 * Math.PI * i) / Math.max(hop1.length, 1);
    angle.set(n.id, a);
    pos.set(n.id, [r1 * Math.cos(a), r1 * Math.sin(a)]);
  });
  const hop2 = hood.nodes
    .filter((n) => n.level === 2)
    .map((n) => {
      const parents = (n.parents ?? []).filter((p) => angle.has(p));
      const x = parents.reduce((s, p) => s + Math.cos(angle.get(p) as number), 0);
      const y = parents.reduce((s, p) => s + Math.sin(angle.get(p) as number), 0);
      return [n.id, Math.atan2(y, x) + order(n.type) * 1e-3] as const;
    })
    .sort((a, b) => a[1] - b[1]);
  const r2 = Math.max(r1 + 170, (hop2.length * 40) / (2 * Math.PI));
  if (hop2.length) {
    const step = (2 * Math.PI) / hop2.length;
    const offset = hop2.reduce((s, [, a], i) => s + Math.atan2(Math.sin(a - i * step), Math.cos(a - i * step)), 0) / hop2.length;
    hop2.forEach(([id], i) => pos.set(id, [r2 * Math.cos(offset + i * step), r2 * Math.sin(offset + i * step)]));
  }
  const xs = [...pos.values()].map((p) => p[0]);
  const ys = [...pos.values()].map((p) => p[1]);
  return { pos, bounds: [Math.min(...xs) - 60, Math.min(...ys) - 40, Math.max(...xs) + 60, Math.max(...ys) + 50] };
}

const SCHEMA_POS: Record<string, [number, number]> = {
  EconomicCase: [-560, -150], Operator: [-560, 30], BatteryCode: [-560, 210], PricingFacility: [-860, 210], EconomicLocation: [-250, 30], Zone: [-250, 300],
  Well: [40, -190], Unit: [330, 30], LeaseholdTract: [330, -300], County: [620, -80], DevelopmentArea: [620, 140], Asset: [40, 330], ReportingScope: [330, 470], DocumentClaim: [-250, 520],
};

/** The box around the visible type nodes, so a project with few types fills the canvas instead of hugging a corner. */
function schemaBounds(points: [number, number][], extraRow: boolean): Bounds {
  if (!points.length) return [-1010, -380, 780, extraRow ? 810 : 610];
  const xs = points.map((p) => p[0]);
  const ys = points.map((p) => p[1]);
  return [Math.min(...xs) - 150, Math.min(...ys) - 100, Math.max(...xs) + 150, Math.max(...ys) + 90];
}

/** Positions for the schema graph: the base types have fixed places; types added to a project line up in a row below them. */
function schemaPositions(types: string[]): Record<string, [number, number]> {
  const extra = types.filter((t) => !SCHEMA_POS[t]);
  const positions = { ...SCHEMA_POS };
  extra.forEach((t, i) => { positions[t] = [-860 + i * 320, 720]; });
  return positions;
}

function NodeGlyph({ id, type, label, r, focus, selected, dim, nolabel, counts, severities, onSelect, onOpen, sub }: {
  id: string; type: string; label: string; r: number; focus?: boolean; selected?: boolean; dim?: boolean; nolabel?: boolean; counts: NodeCard["issues"]; severities: Sev[]; onSelect: () => void; onOpen: () => void; sub?: string;
}) {
  const sev = worst(counts, severities);
  const total = issueTotal(counts, severities);
  return (
    <g
      className={`node${focus ? " focus" : ""}${selected ? " selected" : ""}${dim ? " dim" : ""}${nolabel ? " nolabel" : ""}`}
      tabIndex={0}
      role="button"
      data-id={id}
      aria-label={`${typeShort(type)} ${label}${total ? `, ${total} issues` : ""}. Double-click or press Enter for details.`}
      onClick={(event) => { event.stopPropagation(); onSelect(); }}
      onDoubleClick={(event) => { event.stopPropagation(); onOpen(); }}
      onKeyDown={(event) => {
        if (event.key === "Enter") onOpen();
        if (event.key === " ") { event.preventDefault(); onSelect(); }
      }}
    >
      <circle className="ring" r={r + 4} fill="none" stroke="transparent" />
      <circle className="body" r={r} fill={typeFill(type, 0.25)} stroke={typeColor(type)} />
      {focus ? <circle r={r + 7} fill="none" stroke={typeColor(type)} strokeOpacity={0.45} strokeWidth={1.5} /> : null}
      {sub ? <text y={4} textAnchor="middle" style={{ fontSize: 12, fontWeight: 700 }}>{sub}</text> : null}
      {sev ? (
        <g className="badge" transform={`translate(${r * 0.8},${-r * 0.8})`}>
          <circle r={total > 99 ? 11 : 7.5} fill={`hsl(var(--${sev}))`} />
          <text style={total > 99 ? { fontSize: 9 } : undefined}>{total > 999 ? `${(total / 1000).toFixed(1)}k` : total}</text>
        </g>
      ) : null}
      <text y={r + 14} textAnchor="middle" style={sub ? { fontSize: 12.5 } : undefined}>{clip(label, focus ? 34 : sub ? 40 : 22)}</text>
    </g>
  );
}

function NeighborhoodGraph({ hood: data, legend: legendNode, onAsk }: { hood: Neighborhood; legend: ReactNode; onAsk: (node: NodeCard) => void }) {
  const { nav, patch, version, openEntity } = useApp();
  const { pos, bounds } = layoutNeighborhood(data);
  const byId = new Map(data.nodes.map((n) => [n.id, n]));
  const sel = nav.selected && byId.has(nav.selected) ? nav.selected : null;
  const adjacent = !sel || sel === data.focus ? null : new Set([sel, ...data.edges.filter((e) => e.source === sel || e.target === sel).flatMap((e) => [e.source, e.target])]);
  const hub = sel ?? data.focus;
  const kindCount: Record<string, number> = {};
  data.edges.forEach((e) => { if (e.source === hub || e.target === hub) kindCount[e.kind] = (kindCount[e.kind] ?? 0) + 1; });
  const labelled = new Set<string>();
  const showLabels = data.nodes.length <= 48;
  const viewIssues = data.nodes.reduce((s, n) => s + issueTotal(n.issues, nav.severities), 0);
  const selected = sel ? byId.get(sel) : null;
  return (
    <GraphCanvas
      bounds={bounds}
      fitKey={`${data.focus}-${data.depth}-${data.nodes.length}-${version}`}
      label={`Neighborhood of ${byId.get(data.focus)?.label ?? data.focus}`}
      onBackground={() => sel && patch({ selected: null })}
      overlays={
        <>
          <div className="overlay stats">
            {[[nf(data.nodes.length), "entities"], [nf(data.edges.length), "links"], [nf(viewIssues), "issues in view"], [nf(data.capped), "capped"], [data.hub ? "hub" : `${data.depth}-hop`, "depth"]].map(([v, l]) => (
              <div key={l}><b>{v}</b><span>{l}</span></div>
            ))}
          </div>
          {legendNode}
          <div className="overlay quick">
            {selected ? (
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <TypeTag type={selected.type} />
                  {worst(selected.issues) ? <SevChip sev={worst(selected.issues) as Sev}>{`${issueTotal(selected.issues)} open issue${issueTotal(selected.issues) > 1 ? "s" : ""}`}</SevChip> : <SevChip sev="ok">no issues</SevChip>}
                </div>
                <h4>{selected.label}</h4>
                <div className="mono muted" style={{ marginBottom: 6 }}>{selected.id}</div>
                <div className="kv">
                  {Object.entries(selected.props).filter(([, v]) => v != null && typeof v !== "object").slice(0, 5).map(([k, v]) => (
                    <span key={k} style={{ display: "contents" }}>
                      <span className="muted">{k}</span>
                      <span>{typeof v === "number" ? nf(v, Math.abs(v) < 10 && !Number.isInteger(v) ? 4 : Number.isInteger(v) ? 0 : 1) : clip(v, 40)}</span>
                    </span>
                  ))}
                </div>
                <div style={{ display: "flex", gap: 6, marginTop: 10, flexWrap: "wrap" }}>
                  <button className="btn primary" onClick={() => openEntity(selected.id)}>Details</button>
                  {selected.id !== data.focus ? <button className="btn" onClick={() => patch({ focus: selected.id })}><Icon name="focus" />Focus</button> : null}
                  <button className="btn" onClick={() => onAsk(selected)}><Icon name="spark" />Ask</button>
                </div>
                <div className="hint">Tip: double-click any node to open its inspector.</div>
              </div>
            ) : (
              <div>
                <h4>How to explore</h4>
                <div className="small muted">Search or click a node to select it; double-click (or Enter) for its properties, facts, sources, issues and schema. Red links mark source-vs-map disagreements; badges count open issues.{data.hub ? " This entity is a hub, so only direct links are shown." : ""}</div>
              </div>
            )}
          </div>
        </>
      }
    >
      <g>
        {data.edges.filter((e) => pos.has(e.source) && pos.has(e.target)).map((e) => {
          const [x1, y1] = pos.get(e.source) as [number, number];
          const [x2, y2] = pos.get(e.target) as [number, number];
          const dim = adjacent != null && !(adjacent.has(e.source) && adjacent.has(e.target));
          return (
            <line key={e.id} x1={x1} y1={y1} x2={x2} y2={y2} className={`edge m-${e.method}${e.conflict ? " conflict" : ""}${dim ? " dim" : ""}`}>
              <title>{`${byId.get(e.source)?.label} —${e.kind}→ ${byId.get(e.target)?.label}\nmethod: ${e.method}\nevidence: ${e.evidence ?? "—"}${e.props?.alias ? `\nalias: ${String(e.props.alias)}` : ""}`}</title>
            </line>
          );
        })}
      </g>
      <g>
        {data.edges.filter((e) => (e.source === hub || e.target === hub) && pos.has(e.source) && pos.has(e.target)).map((e) => {
          if (labelled.has(e.kind)) return null;
          labelled.add(e.kind);
          const [hx, hy] = pos.get(e.source === hub ? e.source : e.target) as [number, number];
          const [ox, oy] = pos.get(e.source === hub ? e.target : e.source) as [number, number];
          return <text key={`l-${e.kind}`} x={hx + (ox - hx) * 0.42} y={hy + (oy - hy) * 0.42 - 4} className="edge-label" textAnchor="middle">{`${e.kind}${kindCount[e.kind] > 1 ? ` ×${kindCount[e.kind]}` : ""}`}</text>;
        })}
      </g>
      <g>
        {data.nodes.map((n) => {
          const [x, y] = pos.get(n.id) ?? [0, 0];
          const level = n.level ?? 0;
          return (
            <g key={n.id} transform={`translate(${x},${y})`}>
              <NodeGlyph id={n.id} type={n.type} label={n.label} r={level === 0 ? 17 : level === 1 ? 11 : 8} focus={n.id === data.focus} selected={n.id === sel} dim={adjacent != null && !adjacent.has(n.id)} nolabel={!showLabels && level === 2 && n.id !== sel} counts={n.issues} severities={nav.severities} onSelect={() => patch({ selected: n.id })} onOpen={() => openEntity(n.id)} />
            </g>
          );
        })}
      </g>
    </GraphCanvas>
  );
}

export function Explore() {
  const { nav, patch, version, openDrawer, ask, room } = useApp();
  const schema = useFetch<SchemaView>("/api/graph/viz/schema", version);
  const catalog = useFetch<Catalog>("/api/catalog", version).data;
  // Base types with no entities yet (a project whose files do not cover them) are hidden from the schema graph unless asked for.
  const [showEmpty, setShowEmpty] = useState(false);
  const emptyTypes = schema.data?.types.filter((t) => t.count === 0).map((t) => t.type) ?? [];
  const typeList = (schema.data?.types.map((t) => t.type) ?? TYPE_ORDER).filter((t) => nav.mode === "neighborhood" || showEmpty || !emptyTypes.includes(t));
  const types = typeList.filter((t) => !nav.hiddenTypes.includes(t));
  const hoodUrl = nav.mode === "neighborhood" ? `/api/graph/viz/neighborhood?${q({ id: nav.focus, depth: nav.depth, types: types.join(","), methods: nav.methods.join(","), issues_only: nav.issuesOnly || null })}` : null;
  const hood = useFetch<Neighborhood>(hoodUrl, version);
  // The default focus is a well of the sample room; in another project it does not exist, so show the schema instead.
  useEffect(() => {
    if (nav.mode === "neighborhood" && hood.error?.startsWith("404")) patch({ mode: "schema" });
  }, [nav.mode, hood.error, patch]);
  const focusNode = hood.data?.nodes.find((n) => n.id === hood.data?.focus);
  const toggle = <T,>(list: T[], value: T): T[] => (list.includes(value) ? list.filter((v) => v !== value) : [...list, value]);
  const typeCounts: Record<string, number> = {};
  if (nav.mode === "neighborhood") hood.data?.nodes.forEach((n) => (typeCounts[n.type] = (typeCounts[n.type] ?? 0) + 1));
  else schema.data?.types.forEach((t) => (typeCounts[t.type] = t.count));

  const toolbar = (
    <div className="toolbar">
      <SearchBox onPick={(node) => patch({ focus: node.id, selected: node.id, mode: "neighborhood" })} />
      {nav.mode === "neighborhood" && focusNode ? (
        <span className="focus-chip">
          <span>Focus: </span>
          <TypeTag type={focusNode.type} />
          {clip(focusNode.label, 30)}
          <button aria-label="Clear focus and show the schema" onClick={() => patch({ mode: "schema" })}><Icon name="x" /></button>
        </span>
      ) : null}
      <div className="seg" role="group" aria-label="Graph mode">
        <button aria-pressed={nav.mode === "schema"} onClick={() => patch({ mode: "schema" })}>Schema</button>
        <button aria-pressed={nav.mode === "neighborhood"} onClick={() => patch({ mode: "neighborhood" })}>Neighborhood</button>
      </div>
      {nav.mode === "neighborhood" ? (
        <div className="seg" role="group" aria-label="Depth">
          {([1, 2] as const).map((d) => (
            <button key={d} aria-pressed={nav.depth === d} onClick={() => patch({ depth: d })}>{`${d} hop${d > 1 ? "s" : ""}`}</button>
          ))}
        </div>
      ) : null}
      <button className="chip" aria-pressed={nav.issuesOnly} onClick={() => patch({ issuesOnly: !nav.issuesOnly })}><Icon name="alert" />Issues only</button>
      {nav.mode === "schema" && emptyTypes.length ? <button className="chip" aria-pressed={showEmpty} onClick={() => setShowEmpty(!showEmpty)} title="Entity types of the base model that have no entities in this project">{`${showEmpty ? "Hide" : "Show"} ${emptyTypes.length} empty type${emptyTypes.length > 1 ? "s" : ""}`}</button> : null}
    </div>
  );
  const filters = (
    <div className="filters" role="toolbar" aria-label="Filters">
      <span className="lbl">Types</span>
      {typeList.map((t) => (
        <button key={t} className="chip" aria-pressed={!nav.hiddenTypes.includes(t)} onClick={() => patch({ hiddenTypes: toggle(nav.hiddenTypes, t) })}>
          <Dot color={typeColor(t)} />
          {typeShort(t)}
          <span className="n">{nf(typeCounts[t] ?? 0)}</span>
        </button>
      ))}
      <span className="lbl">Links</span>
      {METHODS.slice(0, 5).map((m) => (
        <button key={m} className="chip" aria-pressed={nav.methods.includes(m)} onClick={() => patch({ methods: toggle(nav.methods, m) })}>{m}</button>
      ))}
      <span className="lbl">Issues</span>
      {SEVERITIES.map((s) => (
        <button key={s} className="chip" aria-pressed={nav.severities.includes(s)} onClick={() => patch({ severities: toggle(nav.severities, s) })}>
          <Dot color={`hsl(var(--${s}))`} />
          {s}
        </button>
      ))}
    </div>
  );
  const legend = (
    <div className="overlay legend">
      <span><span className="line" />source</span>
      <span><span className="line" style={{ borderTopColor: "hsl(var(--primary))" }} />key match</span>
      <span><span className="line" style={{ borderTop: "2px dashed hsl(var(--type-well))" }} />spatial</span>
      <span><span className="line" style={{ borderTop: "2px dotted hsl(var(--type-zone))" }} />alias (proposed)</span>
      <span><span className="line" style={{ borderTopColor: "hsl(var(--blocking))" }} />conflicting link</span>
      <span className="muted">Double-click a node for details</span>
    </div>
  );

  let body: ReactNode;
  if (nav.mode === "neighborhood") {
    if (hood.error) body = <ErrorBox error={hood.error} />;
    else if (!hood.data) body = <Loading label="Loading neighborhood" />;
    else body = <NeighborhoodGraph hood={hood.data} legend={legend} onAsk={(node) => ask(`Tell me about ${node.label}`, node.id)} />;
  } else if (schema.error) body = <ErrorBox error={schema.error} />;
  else if (!schema.data) body = <Loading label="Loading schema" />;
  else {
    const data = schema.data;
    const visible = new Set(types);
    const agg = new Map<string, { source: string; kind: string; target: string; method: string; count: number }>();
    for (const link of data.links) {
      if (link.count && !nav.methods.includes(link.method)) continue;
      const key = `${link.source}|${link.kind}|${link.target}`;
      const current = agg.get(key);
      agg.set(key, current ? { ...current, count: current.count + link.count } : { ...link });
    }
    const counts = Object.fromEntries(data.types.map((t) => [t.type, t]));
    const positions = schemaPositions(data.types.map((t) => t.type));
    const extraRow = data.types.some((t) => !SCHEMA_POS[t.type]);
    const sel = nav.schemaType;
    const def = catalog?.entity_types.find((t) => t.name === sel);
    const exploreInstances = (type: string) => {
      const prefix = catalog?.entity_types.find((t) => t.name === type)?.id_prefix ?? type.toLowerCase();
      api.get<NodeCard[]>(`/api/graph/viz/search?${q({ q: `${prefix}:`, limit: 5 })}`).then((hits) => {
        const hit = hits.find((h) => h.type === type);
        if (hit) patch({ mode: "neighborhood", focus: hit.id, selected: hit.id });
      });
    };
    body = (
      <GraphCanvas
        bounds={schemaBounds(data.types.filter((t) => visible.has(t.type)).map((t) => positions[t.type]), extraRow)}
        fitKey={`schema-${version}-${extraRow}-${types.length}`}
        label="Ontology schema graph"
        onBackground={() => patch({ schemaType: null })}
        overlays={
          <>
            <div className="overlay stats">
              {[[nf(room?.counts.entities), "entities"], [nf(room?.counts.relationships), "links"], [String(data.types.filter((t) => t.count).length), "entity types"], [String(new Set(data.links.filter((l) => l.count).map((l) => l.kind)).size), "link types"], [nf(room?.counts.facts), "facts"]].map(([v, l]) => (
                <div key={l}><b>{v}</b><span>{l}</span></div>
              ))}
            </div>
            {legend}
            {sel && def ? (
              <div className="overlay quick">
                <TypeTag type={sel} />
                <h4>{`${sel} · ${nf(counts[sel]?.count ?? 0)}`}</h4>
                <div className="small">{def.description}</div>
                <div className="kv" style={{ marginTop: 6 }}>
                  <span className="muted">ID</span><span className="mono">{`${def.id_prefix}:<${def.key}>`}</span>
                  <span className="muted">Standard</span><span>{def.standard ?? "custom"}</span>
                  <span className="muted">Origin</span><span>{def.origin === "project" ? "added in this project" : "governed base model"}</span>
                </div>
                <div style={{ display: "flex", gap: 6, marginTop: 10, flexWrap: "wrap" }}>
                  <button className="btn primary" onClick={() => openDrawer({ kind: "type", name: sel })}>Schema details</button>
                  {counts[sel]?.count ? <button className="btn" onClick={() => exploreInstances(sel)}><Icon name="focus" />Explore instances</button> : null}
                </div>
              </div>
            ) : (
              <div className="overlay quick">
                <h4>Ontology schema</h4>
                <div className="small muted">Entity types sized by instance count; link width by link count. Red dashed links have no instances yet (a data gap). Click a type to select it; double-click for its schema.</div>
              </div>
            )}
          </>
        }
      >
        <g>
          {[...agg.values()].filter((l) => visible.has(l.source) && visible.has(l.target) && positions[l.source] && positions[l.target]).map((l) => {
            const [x1, y1] = positions[l.source];
            const [x2, y2] = positions[l.target];
            const gap = l.count === 0;
            const conflict = l.kind === "ASSIGNED_TO_UNIT" || l.kind === "LATERAL_IN_UNIT";
            return (
              <g key={`${l.source}|${l.kind}|${l.target}`}>
                <line x1={x1} y1={y1} x2={x2} y2={y2} className={`edge m-${l.method}${gap || conflict ? " conflict" : ""}`} strokeWidth={gap ? 1.5 : 1.5 + Math.log10(l.count)} strokeDasharray={gap ? "6 5" : undefined}>
                  <title>{`${l.kind}: ${nf(l.count)} links (${l.method})`}</title>
                </line>
                <text x={(x1 + x2) / 2} y={(y1 + y2) / 2 - 4} className="edge-label" textAnchor="middle">{`${l.kind} · ${gap ? "0 (gap)" : nf(l.count)}`}</text>
              </g>
            );
          })}
        </g>
        <g>
          {data.types.filter((t) => visible.has(t.type) && positions[t.type]).map((t) => {
            const [x, y] = positions[t.type];
            const r = 14 + Math.sqrt(t.count) * 1.3;
            return (
              <g key={t.type} transform={`translate(${x},${y})`}>
                <NodeGlyph id={t.type} type={t.type} label={t.type} r={Math.min(r, 70)} sub={nf(t.count)} selected={sel === t.type} counts={t.issues} severities={nav.severities} onSelect={() => patch({ schemaType: t.type })} onOpen={() => openDrawer({ kind: "type", name: t.type })} />
              </g>
            );
          })}
        </g>
      </GraphCanvas>
    );
  }

  return (
    <div className="explore">
      {toolbar}
      {filters}
      {body}
    </div>
  );
}
