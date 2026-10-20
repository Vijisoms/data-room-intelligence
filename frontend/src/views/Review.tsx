// Issue queue for one rule: the list, side-by-side evidence with citations, and per-issue decisions.
import { useEffect, useState } from "react";
import { api, q, useFetch, type Interpret, type Issue } from "../api";
import { useApp } from "../store";
import { Cite, ErrorBox, Icon, Loading, SevChip, TypeTag } from "../ui";
import { DECISION_OPTIONS, clip, nf } from "../util";
import { geometryPaths } from "./Inputs";

const PAGE = 100;

function MiniMap({ issue }: { issue: Issue }) {
  const { version } = useApp();
  const [a, b] = issue.assertions;
  const unitA = useFetch<Interpret>(a?.entity ? `/api/graph/viz/interpret?${q({ id: a.entity })}` : null, version).data;
  const unitB = useFetch<Interpret>(b?.entity ? `/api/graph/viz/interpret?${q({ id: b.entity })}` : null, version).data;
  const well = useFetch<Interpret>(`/api/graph/viz/interpret?${q({ id: issue.subject })}`, version).data;
  if (!unitA || !unitB || !well) return <Loading label="Loading map evidence" />;
  const shapes = [
    { g: unitA.geometry[0], stroke: "hsl(var(--warning))", fill: "hsl(var(--warning) / 0.15)", label: `A: ${unitA.node.label}` },
    { g: unitB.geometry[0], stroke: "hsl(var(--type-unit))", fill: "hsl(var(--type-unit) / 0.15)", label: `B: ${unitB.node.label}` },
    { g: well.geometry[0], stroke: "hsl(var(--blocking))", fill: "none", label: "" },
  ].filter((s) => s.g);
  const coords: number[][] = [];
  shapes.forEach((s) => {
    const g = s.g;
    if (g.type === "Polygon") coords.push(...g.coordinates[0]);
    else if (g.type === "LineString") coords.push(...g.coordinates);
    else if (g.type === "MultiPolygon") g.coordinates.forEach((p) => coords.push(...p[0]));
    else if (g.type === "MultiLineString") g.coordinates.forEach((l) => coords.push(...l));
  });
  if (!coords.length) return null;
  const lons = coords.map((c) => c[0]);
  const lats = coords.map((c) => c[1]);
  const [x0, x1, y0, y1] = [Math.min(...lons), Math.max(...lons), Math.min(...lats), Math.max(...lats)];
  const W = 420;
  const H = 230;
  const pad = 24;
  const kx = Math.cos((((y0 + y1) / 2) * Math.PI) / 180);
  const k = Math.min((W - 2 * pad) / Math.max((x1 - x0) * kx, 1e-9), (H - 2 * pad) / Math.max(y1 - y0, 1e-9));
  const ox = (W - (x1 - x0) * kx * k) / 2;
  const oy = (H - (y1 - y0) * k) / 2;
  const xy = (c: number[]): [number, number] => [ox + (c[0] - x0) * kx * k, oy + (y1 - c[1]) * k];
  const P = (c: number[]) => xy(c).join(",");
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", maxHeight: 260, marginTop: 12, background: "hsl(var(--background))", borderRadius: 8, border: "1px solid hsl(var(--border))" }} role="img" aria-label="Both units and the lateral">
        {shapes.map((s, i) =>
          geometryPaths(s.g, P).map((p, j) =>
            p.kind === "polygon" ? (
              <polygon key={`${i}-${j}`} points={p.points} fill={s.fill} stroke={s.stroke} strokeWidth={2} />
            ) : (
              <polyline key={`${i}-${j}`} points={p.points} fill="none" stroke={s.stroke} strokeWidth={3} />
            ),
          ),
        )}
        {shapes.filter((s) => s.label && s.g.type === "Polygon").map((s) => {
          const ring = (s.g as { coordinates: number[][][] }).coordinates[0].map(xy);
          const top = Math.min(...ring.map((p) => p[1]));
          const mid = (Math.min(...ring.map((p) => p[0])) + Math.max(...ring.map((p) => p[0]))) / 2;
          const anchor = mid < W * 0.3 ? "start" : mid > W * 0.7 ? "end" : "middle";
          const x = anchor === "start" ? Math.min(...ring.map((p) => p[0])) : anchor === "end" ? Math.max(...ring.map((p) => p[0])) : mid;
          return <text key={s.label} x={x} y={Math.max(top - 5, 12)} textAnchor={anchor} style={{ fontSize: 11, fill: "hsl(var(--secondary-text))" }}>{s.label}</text>;
        })}
      </svg>
      <div className="small muted">A: unit in ComboCurve (amber). B: unit containing the lateral (blue). Red: the PDP lateral.</div>
    </div>
  );
}

function Evidence({ issue, onDecided }: { issue: Issue; onDecided: () => void }) {
  const { openEntity, focusGraph, notify } = useApp();
  const [reason, setReason] = useState("");
  const [scope, setScope] = useState<"issue" | "rule">("issue");
  const [missing, setMissing] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setReason("");
    setMissing(false);
    setScope("issue");
  }, [issue.issue_id]);
  const decide = async (choice: string) => {
    if (!reason.trim()) {
      setMissing(true);
      return;
    }
    setBusy(true);
    try {
      await api.post("/api/issues/decision", { issue_id: issue.issue_id, rule: issue.rule, scope, choice, reason, reviewer: "reviewer" });
      notify(`Recorded "${choice}" for ${scope === "rule" ? `every ${issue.rule} issue` : issue.subject_label ?? issue.subject}. Decisions are append-only (reviews/decisions.jsonl).`);
      onDecided();
    } catch (e) {
      notify(`Decision failed: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <SevChip sev={issue.severity} />
        <b>{issue.rule}</b>
        {issue.status === "decided" ? <SevChip sev="ok">decided</SevChip> : null}
      </div>
      <h2 style={{ margin: "6px 0 2px", fontSize: 18 }}>{issue.subject_label ?? issue.subject}</h2>
      <div className="mono muted small">{issue.subject}{issue.qualifier ? ` · ${issue.qualifier}` : ""}</div>
      <div className="small" style={{ marginTop: 6 }}>{issue.detail}</div>
      <div className="small muted" style={{ marginTop: 2 }}>Blocks: {issue.blocks}</div>
      <div className="evidence">
        {issue.assertions.slice(0, 2).map((a, i) => (
          <div className="assertion" key={i}>
            <h5>{`Assertion ${i === 0 ? "A" : "B"}`}</h5>
            <div className="small muted">{a.label}</div>
            <div className="val">{typeof a.value === "number" ? nf(a.value, Math.abs(a.value) < 10 ? 4 : 2) : Array.isArray(a.value) ? a.value.join(", ") : String(a.value ?? "—")}</div>
            {a.file ? <Cite citation={{ file: a.file, locator: a.locator, label: a.locator ?? "file" }} /> : <span className="muted small">no source value</span>}
          </div>
        ))}
      </div>
      {issue.assertions.length > 2 ? <div className="small muted" style={{ marginTop: 6 }}>{`+ ${issue.assertions.length - 2} more assertions`}</div> : null}
      {issue.rule === "UNIT_ASSIGNMENT_CONFLICT" ? <MiniMap issue={issue} /> : null}
      {issue.decision ? (
        <div className="note" style={{ margin: "12px 0 0" }}>
          {`Decided: ${issue.decision.choice} by ${issue.decision.reviewer}${issue.decision.decided_at ? ` on ${issue.decision.decided_at.slice(0, 10)}` : ""}${issue.decision.scope === "rule" ? " (for the whole question)" : ""}. Reason: ${issue.decision.reason}`}
        </div>
      ) : (
        <>
          <div className="decide">
            <input
              type="text"
              value={reason}
              onChange={(e) => { setReason(e.target.value); setMissing(false); }}
              placeholder="Reason (required for a decision)"
              aria-label="Decision reason"
              aria-invalid={missing}
              style={{ flex: 1, height: 32, padding: "0 10px", borderRadius: 6, border: `1px solid hsl(var(--${missing ? "blocking" : "border"}))`, background: "hsl(var(--background))" }}
            />
            <div className="seg" role="group" aria-label="Decision scope">
              <button aria-pressed={scope === "issue"} onClick={() => setScope("issue")}>This issue</button>
              <button aria-pressed={scope === "rule"} onClick={() => setScope("rule")}>Whole question</button>
            </div>
          </div>
          <div className="decide">
            {(DECISION_OPTIONS[issue.rule] ?? ["Accept", "Reject", "Defer"]).map((o) => (
              <button key={o} className="btn" disabled={busy} onClick={() => decide(o)}>{o}</button>
            ))}
          </div>
          <div className="small muted" style={{ marginTop: 8 }}>{missing ? "Enter a reason first." : "Decisions are append-only with reviewer, reason and snapshot; both source values stay in the graph."}</div>
        </>
      )}
      <div style={{ marginTop: 12, display: "flex", gap: 6 }}>
        <button className="btn" onClick={() => openEntity(issue.subject)}>Open entity</button>
        <button className="btn" onClick={() => focusGraph(issue.subject)}><Icon name="focus" />Show on graph</button>
      </div>
    </div>
  );
}

export function IssueQueue({ rule }: { rule: string }) {
  const { nav, patch, version, refresh, openEntity } = useApp();
  const [page, setPage] = useState(0);
  const [status, setStatus] = useState<"open" | "decided" | "">("open");
  useEffect(() => setPage(0), [rule, status]);
  const issues = useFetch<{ total: number; items: Issue[] }>(`/api/issues?${q({ rule, status: status || null, limit: PAGE, offset: page * PAGE })}`, version);
  const items = issues.data?.items ?? [];
  const listed = items.find((i) => i.issue_id === nav.issueId);
  // An issue opened from another view can sit outside the current page or status filter, so load it directly.
  const outside = nav.issueId && issues.data && !listed ? nav.issueId : null;
  const direct = useFetch<{ total: number; items: Issue[] }>(outside ? `/api/issues?${q({ issue_id: outside })}` : null, version);
  const selected = listed ?? direct.data?.items.find((i) => i.issue_id === outside) ?? (direct.loading ? undefined : items[0]);
  const turnPage = (next: number) => {
    setPage(next);
    patch({ issueId: null });
  };
  const filterStatus = (next: typeof status) => {
    if (next === status) return;
    setStatus(next);
    patch({ issueId: null });
  };
  const decided = () => {
    if (status === "open") patch({ issueId: null });
    refresh();
  };
  return (
    <div className="review-split">
      <div>
        <div className="row" style={{ margin: "0 18px 8px", gap: 10 }}>
          <span className="small muted">{issues.data ? `${nf(issues.data.total)} ${status || "total"} · showing ${nf(page * PAGE + 1)}–${nf(Math.min((page + 1) * PAGE, issues.data.total))} · double-click a row for the entity` : "Loading…"}</span>
          <span style={{ flex: 1 }} />
          <div className="seg" role="group" aria-label="Issue status">
            {(["open", "decided", ""] as const).map((s) => <button key={s || "all"} aria-pressed={status === s} onClick={() => filterStatus(s)}>{s || "all"}</button>)}
          </div>
        </div>
        {issues.error ? <ErrorBox error={issues.error} /> : (
          <table className="simple" style={{ margin: "0 18px 12px", width: "calc(100% - 36px)" }}>
            <thead><tr><th>Entity</th><th>Detail</th><th>Status</th></tr></thead>
            <tbody>
              {items.map((i) => (
                <tr key={i.issue_id} className={`clickable${i.issue_id === selected?.issue_id ? " warn" : ""}`} onClick={() => patch({ issueId: i.issue_id })} onDoubleClick={() => openEntity(i.subject)}>
                  <td>{i.subject_type ? <TypeTag type={i.subject_type} /> : null}<div>{clip(i.subject_label ?? i.subject, 30)}</div></td>
                  <td className="small">{i.detail}</td>
                  <td>{i.decision ? <SevChip sev="ok">{clip(i.decision.choice, 18)}</SevChip> : <span className="muted small">open</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {issues.data && issues.data.total > PAGE ? (
          <div className="pager">
            <button className="btn" disabled={page === 0} onClick={() => turnPage(page - 1)}>Previous</button>
            <span>{`Page ${page + 1} of ${Math.ceil(issues.data.total / PAGE)}`}</span>
            <button className="btn" disabled={(page + 1) * PAGE >= issues.data.total} onClick={() => turnPage(page + 1)}>Next</button>
          </div>
        ) : null}
      </div>
      <div>{selected ? <Evidence issue={selected} onDecided={decided} /> : direct.loading ? <Loading label="Loading issue" /> : <div className="muted">{issues.data ? "No issues with this status." : ""}</div>}</div>
    </div>
  );
}
