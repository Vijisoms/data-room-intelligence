// Publish: the snapshot's status and gate, what changed since the previous build, history and exports.
import { useState, type ReactNode } from "react";
import { api, q, scoped, useFetch, type RuleSummary, type SnapshotDiff, type SnapshotInfo } from "../api";
import { useApp } from "../store";
import { ErrorBox, Icon, Kv, Loading, Section, SevChip, TypeTag } from "../ui";
import { basename, nf, typeShort, when } from "../util";

function Delta({ label, added, removed }: { label: string; added: number; removed: number }) {
  if (!added && !removed) return null;
  return <div className="metric"><b>{added ? `+${nf(added)}` : ""}{added && removed ? " / " : ""}{removed ? `−${nf(removed)}` : ""}</b><span>{label}</span></div>;
}

function byKey(record: Record<string, number> | undefined, format: (k: string) => ReactNode): ReactNode {
  const entries = Object.entries(record ?? {});
  if (!entries.length) return null;
  return <div className="chips">{entries.map(([k, v]) => <span key={k} className="chip">{format(k)}<span className="n">{nf(v)}</span></span>)}</div>;
}

function Changes({ diff }: { diff: SnapshotDiff }) {
  const { openEntity } = useApp();
  if (!diff.before) return <div className="note">{diff.message ?? "This is the first snapshot of the project."}</div>;
  const e = diff.entities;
  const l = diff.links;
  const f = diff.facts;
  const i = diff.issues;
  const quiet = !diff.files?.added.length && !diff.files?.removed.length && !diff.files?.changed.length && !e?.added && !e?.removed && !l?.added && !l?.removed && !f?.changed && f?.before === f?.after && !i?.new && !i?.resolved;
  return (
    <div>
      <div className="small muted" style={{ marginBottom: 8 }}>{`${diff.before.snapshot_id} (${when(diff.before.built_at)}, model ${diff.before.catalog_version}) → ${diff.after.snapshot_id} (${when(diff.after.built_at)}, model ${diff.after.catalog_version})`}</div>
      {quiet ? <div className="note">Nothing changed in the data between these two snapshots.</div> : null}
      <div className="metrics" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))" }}>
        <Delta label="files" added={diff.files?.added.length ?? 0} removed={diff.files?.removed.length ?? 0} />
        <Delta label="entities" added={e?.added ?? 0} removed={e?.removed ?? 0} />
        <Delta label="links" added={l?.added ?? 0} removed={l?.removed ?? 0} />
        {f && f.after !== f.before ? <div className="metric"><b>{`${f.after > f.before ? "+" : "−"}${nf(Math.abs(f.after - f.before))}`}</b><span>facts</span></div> : null}
        {f?.changed ? <div className="metric"><b>{nf(f.changed)}</b><span>values changed</span></div> : null}
        <Delta label="issues (new / resolved)" added={i?.new ?? 0} removed={i?.resolved ?? 0} />
      </div>
      {diff.files?.added.length ? <Section title="Files added">{diff.files.added.map((p) => <div key={p} className="mono small">{basename(p)}</div>)}</Section> : null}
      {diff.files?.changed.length ? <Section title="Files replaced with a new version">{diff.files.changed.map((p) => <div key={p} className="mono small">{basename(p)}</div>)}</Section> : null}
      {e?.added ? (
        <Section title="Entities added">
          {byKey(e.added_by_type, (k) => <TypeTag type={k} />)}
          <div className="chips" style={{ marginTop: 6 }}>{e.added_sample.map((n) => <button key={n.id} className="cite" onClick={() => openEntity(n.id)}>{n.label}</button>)}</div>
        </Section>
      ) : null}
      {e?.removed ? <Section title="Entities no longer present">{byKey(e.removed_by_type, (k) => <TypeTag type={k} />)}</Section> : null}
      {l?.added || l?.removed ? <Section title="Links">{byKey(l.added_by_kind, (k) => <span className="mono small">{`+ ${k}`}</span>)}{byKey(l.removed_by_kind, (k) => <span className="mono small">{`− ${k}`}</span>)}</Section> : null}
      {f?.changed ? (
        <Section title={`Values that changed · ${nf(f.changed)}`}>
          <table className="simple">
            <thead><tr><th>Entity</th><th>Measure</th><th>Dims</th><th className="num">Before</th><th className="num">After</th></tr></thead>
            <tbody>{f.changed_sample.map((c, k) => <tr key={k}><td><button className="cite" style={{ border: 0, padding: 0, background: "none" }} onClick={() => openEntity(c.subject)}>{c.subject}</button></td><td className="mono small">{c.measure}</td><td className="small">{[c.zone, c.period?.slice(0, 7), c.item].filter(Boolean).join(" · ") || "—"}</td><td className="num">{nf(c.before, 2)}</td><td className="num">{nf(c.after, 2)}</td></tr>)}</tbody>
          </table>
        </Section>
      ) : null}
      {i?.new || i?.resolved ? (
        <Section title="Issues">
          {byKey(i.new_by_rule, (k) => <span className="small">{`new ${k}`}</span>)}
          {byKey(i.resolved_by_rule, (k) => <span className="small">{`resolved ${k}`}</span>)}
          <div className="small muted" style={{ marginTop: 6 }}>Decisions recorded on earlier snapshots keep applying: issue IDs are stable, so a decided conflict stays decided when it reappears.</div>
        </Section>
      ) : null}
    </div>
  );
}

export function Publish() {
  const { room, version, refresh, notify, go } = useApp();
  const history = useFetch<SnapshotInfo[]>("/api/snapshots", version);
  const rules = useFetch<RuleSummary[]>("/api/rules", version);
  const [pair, setPair] = useState<{ from: string | null; to: string | null }>({ from: null, to: null });
  const diff = useFetch<SnapshotDiff>(history.data?.length ? `/api/snapshots/diff?${q({ from: pair.from, to: pair.to })}` : null, version);
  const [reviewer, setReviewer] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [override, setOverride] = useState(false);
  const publish = async (force: boolean) => {
    setBusy(true);
    try {
      const result = await api.post<{ published: boolean; snapshot_id: string; open_blocking: number; rules?: string[] }>("/api/publish", force ? { force: true, reviewer, reason } : {});
      if (result.published) {
        setOverride(false);
        notify(`Published snapshot ${result.snapshot_id}.`);
        refresh();
      } else notify(`Not published: ${nf(result.open_blocking)} blocking issues are still open.`);
    } finally {
      setBusy(false);
    }
  };
  if (!room) return <Loading label="Loading snapshot" />;
  const blocking = room.open_issues.blocking ?? 0;
  const blockingRules = rules.data?.filter((r) => r.severity === "blocking" && r.open) ?? [];
  const published = room.status === "published";
  const snapshots = [...(history.data ?? [])].reverse();
  return (
    <div className="publish">
      <div className="step-head">
        <div>
          <h2>Publish</h2>
          <div className="small muted">A snapshot is rebuilt from the original files, the project model and the recorded decisions, so it can always be reproduced. It can be published once no blocking question is open.</div>
        </div>
        <div className="row"><SevChip sev={published ? "ok" : blocking ? "warning" : "ok"}>{published ? "published" : blocking ? "gated" : "ready to publish"}</SevChip></div>
      </div>
      <div className="step-body publish-grid">
        <div>
          <Section title="Current snapshot">
            <Kv pairs={[
              ["Snapshot", <span className="mono">{room.snapshot_id}</span>],
              ["Built", when(room.built_at)],
              ["Model version", <span className="mono">{room.catalog_version}</span>],
              ["Files", nf(room.files)],
              ["Contents", `${nf(room.counts.entities)} entities · ${nf(room.counts.relationships)} links · ${nf(room.counts.facts)} facts`],
              ["Open issues", `${nf(blocking)} blocking · ${nf(room.open_issues.warning ?? 0)} warnings · ${nf(room.open_issues.info ?? 0)} notes · ${nf(room.decided_issues)} decided`],
            ]} />
          </Section>
          <Section title="Publish gate">
            {published ? <div className="note">This snapshot is published. Decisions and new files create a new snapshot, which goes through the gate again.</div> : blocking ? (
              <div>
                <div className="note warn">{`${nf(blocking)} blocking issues are open across ${blockingRules.length} question${blockingRules.length !== 1 ? "s" : ""}: ${blockingRules.map((r) => r.title.toLowerCase()).join(", ")}.`}</div>
                <div className="row" style={{ margin: "10px 0" }}>
                  <button className="btn primary" onClick={() => go("decisions")}><Icon name="shield" />Decide them</button>
                  {!override ? <button className="btn" onClick={() => setOverride(true)}>Publish with open issues…</button> : null}
                </div>
                {override ? (
                  <div className="force">
                    <div className="small">Publishing with open blocking issues needs a named reviewer and a reason; both are recorded in the snapshot together with the number of open issues.</div>
                    <div className="row">
                      <input value={reviewer} onChange={(e) => setReviewer(e.target.value)} placeholder="Reviewer" aria-label="Reviewer" />
                      <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason for publishing with open issues" aria-label="Reason" style={{ flex: 1 }} />
                      <button className="btn" disabled={busy || !reviewer.trim() || !reason.trim()} onClick={() => publish(true)}>Publish anyway</button>
                      <button className="btn" style={{ border: 0 }} disabled={busy} onClick={() => setOverride(false)}>Cancel</button>
                    </div>
                  </div>
                ) : null}
              </div>
            ) : (
              <div className="row"><button className="btn primary" disabled={busy} onClick={() => publish(false)}><Icon name="check" />Publish snapshot</button><span className="small muted">No blocking issue is open.</span></div>
            )}
          </Section>
          <Section title="What changed" aside={snapshots.length > 1 ? (
            <span className="row small">
              <select value={pair.from ?? ""} aria-label="Compare from" onChange={(e) => setPair((p) => ({ ...p, from: e.target.value || null }))}>
                <option value="">previous build</option>
                {snapshots.map((s) => <option key={s.snapshot_id} value={s.snapshot_id}>{`${s.snapshot_id} · ${when(s.built_at)}`}</option>)}
              </select>
              <span className="muted">→</span>
              <select value={pair.to ?? ""} aria-label="Compare to" onChange={(e) => setPair((p) => ({ ...p, to: e.target.value || null }))}>
                <option value="">latest</option>
                {snapshots.map((s) => <option key={s.snapshot_id} value={s.snapshot_id}>{`${s.snapshot_id} · ${when(s.built_at)}`}</option>)}
              </select>
            </span>
          ) : null}>
            {diff.error ? <ErrorBox error={diff.error} /> : diff.data ? <Changes diff={diff.data} /> : <Loading label="Comparing snapshots" />}
          </Section>
        </div>
        <div>
          <Section title={`Snapshot history · ${snapshots.length}`}>
            <table className="simple">
              <thead><tr><th>Snapshot</th><th>Built</th><th>Model</th><th>Status</th><th className="num">Facts</th></tr></thead>
              <tbody>
                {snapshots.map((s) => (
                  <tr key={s.snapshot_id} className={s.snapshot_id === room.snapshot_id ? "warn" : ""}>
                    <td className="mono small">{s.snapshot_id}</td><td className="small">{when(s.built_at)}</td><td className="mono small">{s.catalog_version}</td>
                    <td><SevChip sev={s.status === "published" ? "ok" : s.status === "in_review" ? "warning" : "info"}>{s.status === "in_review" ? "gated" : s.status}</SevChip></td><td className="num">{nf(s.counts.facts)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="small muted" style={{ marginTop: 6 }}>Rebuilding the same files with the same model and decisions gives the same snapshot ID and byte-identical tables.</div>
          </Section>
          <Section title="Exports">
            <div className="chips">
              <a className="btn" href={scoped("/api/export/decisions.csv")} download><Icon name="table" />Decision log (CSV)</a>
              <a className="btn" href={scoped("/api/export/entities.csv")} download><Icon name="table" />Entities (CSV)</a>
              <a className="btn" href={scoped("/api/export/facts.csv")} download><Icon name="table" />Facts with sources (CSV)</a>
            </div>
            <div className="small muted" style={{ marginTop: 8 }}>Every fact row carries its file and cell, page or map feature. The decision log carries reviewer, reason, scope and the snapshot the decision was made on.</div>
          </Section>
          {room.pending_proposals || room.mappings?.proposed ? (
            <Section title="Waiting in the Model step">
              <div className="small">{[room.pending_proposals ? `${room.pending_proposals} model change${room.pending_proposals > 1 ? "s" : ""}` : null, room.mappings?.proposed ? `${room.mappings.proposed} field mapping${room.mappings.proposed > 1 ? "s" : ""}` : null].filter(Boolean).join(" and ")} still need review. Approving them creates a new snapshot.</div>
              <button className="btn" style={{ marginTop: 8 }} onClick={() => go("model")}>Open Model</button>
            </Section>
          ) : null}
          <Section title="Entity types in this snapshot">
            <div className="chips">{Object.entries(room.counts.entities_by_type).map(([t, n]) => <span key={t} className="chip"><TypeTag type={t} />{typeShort(t) === t ? "" : ""}<span className="n">{nf(n)}</span></span>)}</div>
          </Section>
        </div>
      </div>
    </div>
  );
}
