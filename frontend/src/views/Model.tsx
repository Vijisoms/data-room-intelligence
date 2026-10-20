// Model: the project's model and how it grows. Changes proposed for new kinds of data, field mappings to approve,
// the dictionary (base model plus project additions) and the schema graph.
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { api, useFetch, type ChangeItem, type EntityTypeDef, type FileDetail, type MeasureDef, type ModelProposal, type PropertyDef, type RebuildResult, type RelationshipDef } from "../api";
import { useApp, type ModelTab } from "../store";
import { ErrorBox, Icon, Kv, Loading, Section, SevChip, Tabs, TypeTag } from "../ui";
import { basename, clip, nf, when } from "../util";
import { Explore } from "./Explore";
import { MappingsPanel } from "./Inputs";
import { Schema } from "./Schema";

type Edits = { type?: string; prefix?: string; description?: string; members: Record<string, string>; rels: Record<string, string> };
const EMPTY_EDITS: Edits = { members: {}, rels: {} };
const TYPE_NAME = /^[A-Z][A-Za-z]+$/;
const MEMBER_NAME = /^[a-z0-9_]+$/;
const REL_NAME = /^[A-Z][A-Z_]+$/;

function entityOf(proposal: ModelProposal): EntityTypeDef | null {
  const item = proposal.items.find((i) => i.op === "add_entity_type");
  return item && typeof item.entity_type === "object" ? item.entity_type : null;
}

/** Applies the steward's renames to the change set before it is approved. Header rules and mappings follow. */
export function applyEdits(proposal: ModelProposal, edits: Edits): ChangeItem[] {
  const entity = entityOf(proposal);
  const oldType = entity?.name ?? proposal.subject;
  const newType = edits.type && TYPE_NAME.test(edits.type) ? edits.type : oldType;
  const member = (type: string, name: string) => (type === oldType ? edits.members[name] : undefined) ?? name;
  const rel = (name: string) => edits.rels[name] ?? name;
  const target = (t: string) => {
    const [type, name] = t.split(".");
    const renamedType = type === oldType ? newType : type;
    const renamedName = edits.rels[name] ?? member(type, name);
    return `${renamedType}.${renamedName}`;
  };
  return proposal.items.map((item): ChangeItem => {
    if (item.op === "add_entity_type" && typeof item.entity_type === "object") {
      const e = item.entity_type;
      return { ...item, entity_type: { ...e, name: newType, id_prefix: edits.prefix || (newType !== e.name ? newType.toLowerCase() : e.id_prefix), key: member(e.name, e.key), description: edits.description ?? e.description, properties: e.properties.map((p) => ({ ...p, name: member(e.name, p.name) })) } };
    }
    if (item.op === "add_property" && item.property) return { ...item, property: { ...item.property, name: member(item.entity_type as string, item.property.name) } };
    if (item.op === "add_measure" && item.measure) return { ...item, measure: { ...item.measure, subject: item.measure.subject === oldType ? newType : item.measure.subject, name: member(item.measure.subject, item.measure.name) } };
    if (item.op === "add_relationship" && item.relationship) return { ...item, relationship: { ...item.relationship, source: item.relationship.source === oldType ? newType : item.relationship.source, name: rel(item.relationship.name) } };
    if (item.op === "add_header_rule" && item.rule) return { ...item, rule: { ...item.rule, target: target(item.rule.target) } };
    return item;
  });
}

function NameInput({ value, onChange, pattern, mono, disabled }: { value: string; onChange: (v: string) => void; pattern: RegExp; mono?: boolean; disabled?: boolean }) {
  const ok = pattern.test(value);
  return <input className={`name-input${mono ? " mono" : ""}`} value={value} disabled={disabled} aria-invalid={!ok} title={ok ? "" : `Must match ${pattern.source}`} onChange={(e) => onChange(e.target.value)} />;
}

function ProposalDetail({ proposal, onDecided }: { proposal: ModelProposal; onDecided: (result: { proposal: ModelProposal; rebuild?: RebuildResult }) => void }) {
  const { notify } = useApp();
  const [edits, setEdits] = useState<Edits>(EMPTY_EDITS);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [showRules, setShowRules] = useState(false);
  useEffect(() => { setEdits(EMPTY_EDITS); setReason(""); setShowRules(false); }, [proposal.proposal_id]);
  const items = useMemo(() => applyEdits(proposal, edits), [proposal, edits]);
  const entity = items.find((i) => i.op === "add_entity_type")?.entity_type as EntityTypeDef | undefined;
  const original = entityOf(proposal);
  const measures = items.filter((i) => i.op === "add_measure").map((i) => i.measure as MeasureDef);
  const relationships = items.filter((i) => i.op === "add_relationship").map((i) => i.relationship as RelationshipDef);
  const properties = items.filter((i) => i.op === "add_property");
  const rules = items.filter((i) => i.op === "add_header_rule");
  const open = proposal.status === "proposed";
  const valid = items.every((i) => (i.op !== "add_entity_type" || TYPE_NAME.test((i.entity_type as EntityTypeDef).name)) && (i.op !== "add_relationship" || REL_NAME.test(i.relationship?.name ?? "")) && (i.op !== "add_measure" || MEMBER_NAME.test(i.measure?.name ?? "")) && (i.op !== "add_property" || MEMBER_NAME.test(i.property?.name ?? "")));
  const setMember = (name: string, value: string) => setEdits((e) => ({ ...e, members: { ...e.members, [name]: value } }));
  const setRel = (name: string, value: string) => setEdits((e) => ({ ...e, rels: { ...e.rels, [name]: value } }));
  const decide = async (status: "approved" | "rejected") => {
    setBusy(true);
    try {
      const result = await api.post<{ proposal: ModelProposal; rebuild?: RebuildResult }>(`/api/model/proposals/${proposal.proposal_id}/decision`, { status, reviewer: "data steward", reason: reason || (status === "approved" ? "approved in the app" : "rejected in the app"), items: status === "approved" ? items : null });
      onDecided(result);
    } catch (e) {
      notify(`Could not record the decision: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };
  const origProps = original?.properties ?? [];
  const links = (proposal.evidence.links as { header: string; target_type: string; hits: number; total: number }[] | undefined) ?? [];
  const typeLabel = entity?.name ?? proposal.subject;
  return (
    <div className="proposal-detail">
      <div className="row">
        <SevChip sev={proposal.status === "proposed" ? "warning" : proposal.status === "approved" ? "ok" : "blocking"}>{proposal.status}</SevChip>
        <span className="chip">{proposal.kind === "new_entity" ? "new entity type" : proposal.kind === "extend_entity" ? "extends a type" : "links two types"}</span>
        <SevChip sev={proposal.method === "model" ? "ai" : "info"}>{proposal.method === "model" ? "names drafted by the model" : "names drafted from headers"}</SevChip>
      </div>
      <h2>{proposal.title}</h2>
      <div className="small muted"><span className="mono">{basename(proposal.file)}</span>{` · sheet ${proposal.sheet} · ${nf(proposal.rows)} rows`}</div>
      <p className="summary">{proposal.summary}</p>
      {open ? <div className="note">Review the names below, change any that do not fit the house vocabulary, then approve. Approval adds a numbered change to this project's model, rebuilds the snapshot and creates the entities, links and facts from the file. The governed base model is not changed.</div> : null}
      {entity && original ? (
        <Section title="Entity type">
          <div className="model-grid">
            <label><span>Name</span>{open ? <NameInput value={entity.name} pattern={TYPE_NAME} onChange={(v) => setEdits((e) => ({ ...e, type: v }))} /> : <b>{entity.name}</b>}</label>
            <label><span>ID prefix</span><span className="mono">{`${entity.id_prefix}:<${entity.key}>`}</span></label>
            <label><span>Standard</span><span>{entity.standard ?? "custom (check against OSDU)"}</span></label>
            <label className="wide"><span>Description</span>{open ? <textarea value={entity.description} rows={2} onChange={(e) => setEdits((ed) => ({ ...ed, description: e.target.value }))} /> : <span>{entity.description}</span>}</label>
          </div>
          <table className="simple" style={{ marginTop: 10 }}>
            <thead><tr><th>Property</th><th>Type</th><th>From column</th><th>Description</th></tr></thead>
            <tbody>
              {entity.properties.map((p, i) => {
                const orig = origProps[i] as PropertyDef | undefined;
                const mapping = proposal.mappings.find((m) => m.target.endsWith(`.${orig?.name}`));
                return (
                  <tr key={orig?.name ?? i}>
                    <td>{open && orig ? <NameInput value={p.name} pattern={MEMBER_NAME} mono onChange={(v) => setMember(orig.name, v)} /> : <span className="mono">{p.name}</span>}{p.required ? <SevChip sev="info">key</SevChip> : null}</td>
                    <td>{p.type}</td>
                    <td className="small">{mapping ? `${mapping.column} · ${mapping.header}` : "—"}</td>
                    <td className="small muted">{p.description}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Section>
      ) : null}
      {properties.length ? (
        <Section title={`Properties added to ${proposal.subject} · ${properties.length}`}>
          <table className="simple">
            <thead><tr><th>Property</th><th>Type</th><th>Description</th></tr></thead>
            <tbody>
              {properties.map((item, i) => {
                const orig = (proposal.items.filter((x) => x.op === "add_property")[i]?.property as PropertyDef).name;
                const p = item.property as PropertyDef;
                return <tr key={orig}><td>{open ? <NameInput value={p.name} pattern={MEMBER_NAME} mono onChange={(v) => setMember(orig, v)} /> : <span className="mono">{p.name}</span>}</td><td>{p.type}</td><td className="small muted">{p.description}</td></tr>;
              })}
            </tbody>
          </table>
        </Section>
      ) : null}
      {measures.length ? (
        <Section title={`Measures (numeric facts) · ${measures.length}`}>
          <table className="simple">
            <thead><tr><th>Measure</th><th>Unit</th><th>Dimensions</th><th>Description</th></tr></thead>
            <tbody>
              {measures.map((m, i) => {
                const orig = (proposal.items.filter((x) => x.op === "add_measure")[i]?.measure as MeasureDef).name;
                return <tr key={orig}><td>{open ? <NameInput value={m.name} pattern={MEMBER_NAME} mono onChange={(v) => setMember(orig, v)} /> : <span className="mono">{m.name}</span>}</td><td>{m.unit || "—"}</td><td className="small">{m.dimensions.join(", ") || "—"}</td><td className="small muted">{m.description}</td></tr>;
              })}
            </tbody>
          </table>
        </Section>
      ) : null}
      {relationships.length ? (
        <Section title={`Relationships · ${relationships.length}`}>
          <table className="simple">
            <thead><tr><th>Link</th><th>From → to</th><th>Evidence</th></tr></thead>
            <tbody>
              {relationships.map((r, i) => {
                const orig = (proposal.items.filter((x) => x.op === "add_relationship")[i]?.relationship as RelationshipDef).name;
                const link = links.find((l) => l.target_type === r.target);
                return (
                  <tr key={orig}>
                    <td>{open ? <NameInput value={r.name} pattern={REL_NAME} mono onChange={(v) => setRel(orig, v)} /> : <span className="mono">{r.name}</span>}</td>
                    <td><TypeTag type={r.source} /> → <TypeTag type={r.target} /></td>
                    <td className="small muted">{link ? `${link.hits} of ${link.total} "${link.header}" values match an existing ${r.target}` : r.build_rule}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Section>
      ) : null}
      <Section title={`Column mappings · ${proposal.mappings.length}`} aside={rules.length ? <button className="btn" onClick={() => setShowRules(!showRules)}>{showRules ? "Hide header rules" : `${rules.length} header rules`}</button> : null}>
        <div className="small muted" style={{ marginBottom: 6 }}>Each column becomes a header rule in the project model, so the next file with the same headers maps without another review.</div>
        <table className="simple">
          <thead><tr><th>Col</th><th>Header</th><th>Maps to</th><th>Kind</th>{showRules ? <th>Header rule</th> : null}</tr></thead>
          <tbody>
            {proposal.mappings.map((m) => {
              const rule = rules.find((r) => r.rule?.pattern.includes(m.header.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim().replace(/ /g, "\\ ")) || r.rule?.target === m.target);
              const [type, name] = m.target.split(".");
              const renamed = `${type === (original?.name ?? proposal.subject) ? typeLabel : type}.${edits.rels[name] ?? (type === (original?.name ?? proposal.subject) ? edits.members[name] : undefined) ?? name}`;
              return <tr key={m.column}><td className="mono">{m.column}</td><td>{m.header}</td><td className="mono small">{renamed}</td><td className="small">{m.kind}</td>{showRules ? <td className="mono small">{rule?.rule?.pattern ?? "—"}</td> : null}</tr>;
            })}
          </tbody>
        </table>
      </Section>
      {proposal.evidence.key ? (
        <Section title="Evidence">
          <Kv pairs={[
            ["Row identifier", <span>{`${(proposal.evidence.key as { header: string }).header}`}{(proposal.evidence.key as { distinct_ratio?: number }).distinct_ratio != null ? <span className="muted">{` · ${nf(((proposal.evidence.key as { distinct_ratio: number }).distinct_ratio) * 100, 1)}% distinct`}</span> : null}</span>],
            ...links.map((l): [ReactNode, ReactNode] => [`${l.header} column`, `${l.hits} of ${l.total} values match an existing ${l.target_type}`]),
          ]} />
        </Section>
      ) : null}
      {open ? (
        <div className="decide-box">
          <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (recorded with the change)" aria-label="Reason" />
          <button className="btn primary" disabled={busy || !valid} onClick={() => decide("approved")}>{busy ? <span className="spinner" /> : <Icon name="check" />}Approve and rebuild</button>
          <button className="btn" disabled={busy} onClick={() => decide("rejected")}>Reject</button>
          {!valid ? <span className="small" style={{ color: "hsl(var(--blocking))" }}>Fix the highlighted names first.</span> : null}
        </div>
      ) : (
        <div className="note" style={{ margin: "12px 0 0" }}>{`${proposal.status === "approved" ? "Approved" : "Rejected"} by ${proposal.decided_by} on ${when(proposal.decided_at)}${proposal.reason ? `. Reason: ${proposal.reason}` : ""}${proposal.catalog_version ? `. Model version ${proposal.catalog_version}.` : ""}`}</div>
      )}
    </div>
  );
}

function ChangesTab({ proposals }: { proposals: ModelProposal[] }) {
  const { nav, patch, refresh, notify, go, catalog } = useApp();
  const selected = proposals.find((p) => p.proposal_id === nav.proposalId) ?? proposals[0];
  const changes = catalog?.changes ?? [];
  return (
    <div className="changes">
      <div className="changes-list">
        <h3 className="pane-title">Proposed changes</h3>
        {proposals.length ? proposals.map((p) => (
          <button key={p.proposal_id} className="change-item" aria-current={p.proposal_id === selected?.proposal_id} onClick={() => patch({ proposalId: p.proposal_id })}>
            <div className="row"><SevChip sev={p.status === "proposed" ? "warning" : p.status === "approved" ? "ok" : "blocking"}>{p.status}</SevChip><span className="small muted">{basename(p.file)}</span></div>
            <b>{p.title}</b>
            <div className="small muted">{clip(p.summary, 110)}</div>
          </button>
        )) : <div className="section small muted">No model changes proposed. When a file brings a kind of data the model lacks, it appears here for review.</div>}
        <h3 className="pane-title">Change log · {changes.length}</h3>
        {changes.length ? (
          <ul className="list" style={{ padding: "0 14px" }}>
            {[...changes].reverse().map((c) => (
              <li key={c.change_id}>
                <div style={{ flex: 1 }}>
                  <b className="mono small">{c.catalog_version}</b>
                  <div className="small">{c.reason}</div>
                  <div className="small muted">{`${c.items.length} item${c.items.length > 1 ? "s" : ""} · ${c.applied_by} · ${when(c.applied_at)}`}</div>
                </div>
              </li>
            ))}
          </ul>
        ) : <div className="section small muted">The project uses the base model unchanged.</div>}
      </div>
      <div className="changes-detail">
        {selected ? (
          <ProposalDetail
            proposal={selected}
            onDecided={(result) => {
              refresh();
              if (result.proposal.status === "approved" && result.rebuild) {
                const type = entityOf(result.proposal)?.name ?? result.proposal.subject;
                const added = result.rebuild.counts.entities_by_type[type];
                notify(`Model updated to ${result.rebuild.catalog_version}. ${added ? `${nf(added)} ${type} entities` : "The new fields"} are now in the graph with cell citations.`);
                window.setTimeout(() => go("publish"), 50);
              } else notify(result.proposal.status === "rejected" ? "Proposal rejected. The file stays in the room; its values are kept but not modelled." : "Decision recorded.");
            }}
          />
        ) : (
          <div className="empty">
            <h3>How the model grows</h3>
            <p>Files the base model already understands are read automatically. When a file brings something new, the system proposes one of three changes and waits for the data steward:</p>
            <ul>
              <li><b>A new entity type</b>, when a column identifies the rows but matches no existing key (for example a lease schedule).</li>
              <li><b>Extra fields on an existing type</b>, when the rows are wells or units but some columns fit no property the type has.</li>
              <li><b>A link between two types</b>, when the file is a crosswalk (for example battery codes to pricing facilities).</li>
            </ul>
            <p>Approved changes are numbered, logged with who approved them and why, and travel with the project. The governed base model is never edited here.</p>
          </div>
        )}
      </div>
    </div>
  );
}

function MappingsTab() {
  const { files, nav, patch, version, catalog } = useApp();
  const candidates = files.filter((f) => f.pending_mappings || f.incoming);
  const file = candidates.find((f) => f.file_id === nav.fileId) ?? candidates.find((f) => f.pending_mappings) ?? candidates[0];
  const detail = useFetch<FileDetail>(file ? `/api/files/${file.file_id}` : null, version);
  const gapKinds = useMemo(() => new Set(catalog?.relationship_types.filter((r) => !(catalog.counts.relationships[r.name] ?? 0)).map((r) => r.name) ?? []), [catalog]);
  return (
    <div className="changes">
      <div className="changes-list">
        <h3 className="pane-title">Files with mappings to review</h3>
        {candidates.length ? candidates.map((f) => (
          <button key={f.file_id} className="change-item" aria-current={f.file_id === file?.file_id} onClick={() => patch({ fileId: f.file_id })}>
            <div className="row">{f.pending_mappings ? <SevChip sev="warning">{`${f.pending_mappings} to review`}</SevChip> : <SevChip sev="ok">reviewed</SevChip>}</div>
            <b>{basename(f.path)}</b>
          </button>
        )) : <div className="section small muted">No field mappings await review. Files added to the project appear here when a column needs a decision.</div>}
      </div>
      <div className="changes-detail">
        {file ? (detail.error ? <ErrorBox error={detail.error} /> : detail.data && detail.data.entry.file_id === file.file_id ? <MappingsPanel detail={detail.data} gapKinds={gapKinds} /> : <Loading label="Loading mappings" />) : null}
      </div>
    </div>
  );
}

export function Model() {
  const { nav, patch, room, version, catalog } = useApp();
  const proposals = useFetch<ModelProposal[]>("/api/model/proposals", version);
  const pending = proposals.data?.filter((p) => p.status === "proposed").length ?? 0;
  const pendingMappings = room?.mappings?.proposed ?? 0;
  const projectTypes = catalog?.entity_types.filter((t) => t.origin === "project").length ?? 0;
  const projectRels = catalog?.relationship_types.filter((r) => r.origin === "project").length ?? 0;
  const tabs: [ModelTab, ReactNode, number?][] = [["changes", "Changes", pending || undefined], ["mappings", "Field mappings", pendingMappings || undefined], ["dictionary", "Dictionary"], ["graph", "Graph"]];
  useEffect(() => {
    if (nav.modelTab === "graph" && nav.mode !== "schema") patch({ mode: "schema" });
  }, [nav.modelTab, nav.mode, patch]);
  if (proposals.error) return <ErrorBox error={proposals.error} />;
  return (
    <div className="model">
      <div className="step-head">
        <div>
          <h2>{`Model ${room?.catalog_version ?? ""}`}</h2>
          <div className="small muted">
            {catalog ? `${catalog.entity_types.length - projectTypes} base entity types and ${catalog.relationship_types.length - projectRels} relationships from the governed model` : ""}
            {projectTypes || projectRels ? `, plus ${projectTypes} entity type${projectTypes !== 1 ? "s" : ""} and ${projectRels} relationship${projectRels !== 1 ? "s" : ""} added in this project` : ""}
            {catalog ? "." : ""}
          </div>
        </div>
        <div className="row">
          {pending ? <SevChip sev="warning">{`${pending} model change${pending > 1 ? "s" : ""} to review`}</SevChip> : null}
          {pendingMappings ? <SevChip sev="warning">{`${pendingMappings} field mapping${pendingMappings > 1 ? "s" : ""} to approve`}</SevChip> : null}
          {!pending && !pendingMappings ? <SevChip sev="ok">nothing waiting</SevChip> : null}
        </div>
      </div>
      <Tabs tabs={tabs} active={nav.modelTab} onChange={(k) => patch({ modelTab: k })} />
      <div className="step-body">
        {nav.modelTab === "changes" ? (proposals.data ? <ChangesTab proposals={proposals.data} /> : <Loading label="Loading proposals" />) : nav.modelTab === "mappings" ? <MappingsTab /> : nav.modelTab === "dictionary" ? <Schema /> : <Explore />}
      </div>
    </div>
  );
}
