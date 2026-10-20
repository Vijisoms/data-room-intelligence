// Decisions: one card per question the seller's files raise. Decide once for the whole question, or review the exceptions.
import { useEffect, useRef, useState } from "react";
import { api, useFetch, type RuleSummary } from "../api";
import { useApp } from "../store";
import { ErrorBox, Icon, Loading, SevChip } from "../ui";
import { DECISION_OPTIONS, RULE_LABELS, nf, when } from "../util";
import { IssueQueue } from "./Review";

const ORDER = { blocking: 0, warning: 1, info: 2 };

function DecisionCard({ rule, active }: { rule: RuleSummary; active: boolean }) {
  const { patch, refresh, notify, nav } = useApp();
  const labels = RULE_LABELS[rule.code];
  const [reason, setReason] = useState("");
  const [missing, setMissing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [custom, setCustom] = useState(false);
  const options = custom ? DECISION_OPTIONS[rule.code] ?? ["Accept", "Reject", "Defer"] : [...(labels?.policy ?? DECISION_OPTIONS[rule.code]?.slice(0, 2) ?? ["Accept"]), "Defer"];
  const decide = async (choice: string) => {
    if (!reason.trim()) {
      setMissing(true);
      return;
    }
    setBusy(true);
    try {
      await api.post("/api/issues/decision", { rule: rule.code, scope: "rule", choice, reason, reviewer: labels?.owner ? `${labels.owner} reviewer` : "reviewer" });
      notify(`Recorded "${choice}" for all ${nf(rule.open)} ${rule.title.toLowerCase()} issues. Answers now use it; both source values stay in the graph.`);
      refresh();
    } catch (e) {
      notify(`Decision failed: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };
  const queueOpen = active && nav.queue;
  return (
    <div className={`decision-card${active ? " active" : ""}`}>
      <div className="row">
        <SevChip sev={rule.severity} />
        <b>{rule.title}</b>
        {labels ? <span className="chip">{labels.owner}</span> : null}
        <span style={{ flex: 1 }} />
        <span className="counts">{rule.open ? <b>{`${nf(rule.open)} open`}</b> : <SevChip sev="ok">all decided</SevChip>}{rule.decided ? <span className="muted">{` · ${nf(rule.decided)} decided`}</span> : null}</span>
      </div>
      <div className="question">{labels?.question ?? rule.check}</div>
      <div className="small muted">{`Check: ${rule.check}. Blocks: ${rule.blocks}.`}</div>
      {rule.policy ? (
        <div className="policy-done">
          <Icon name="check" />
          <div>
            <b>{rule.policy.choice}</b>
            <div className="small muted">{`${rule.policy.scope === "rule" ? "Decided for the whole question" : "Every issue decided the same way"} by ${rule.policy.reviewer}${rule.policy.decided_at ? ` on ${when(rule.policy.decided_at)}` : ""}. Reason: ${rule.policy.reason}`}</div>
          </div>
        </div>
      ) : rule.open ? (
        <div className="policy">
          <div className="small" style={{ fontWeight: 600 }}>Decide for all {nf(rule.open)}:</div>
          <input value={reason} aria-invalid={missing} onChange={(e) => { setReason(e.target.value); setMissing(false); }} placeholder="Reason (required, recorded with the decision)" aria-label="Reason" />
          <div className="decide">
            {options.map((o) => <button key={o} className="btn" disabled={busy} onClick={() => decide(o)}>{o}</button>)}
            {!custom && (DECISION_OPTIONS[rule.code]?.length ?? 0) > options.length ? <button className="btn" style={{ border: 0 }} onClick={() => setCustom(true)}>More…</button> : null}
          </div>
          {missing ? <div className="small" style={{ color: "hsl(var(--blocking))" }}>Enter a reason first.</div> : null}
        </div>
      ) : null}
      <div className="acts">
        <button className="btn" aria-pressed={queueOpen} onClick={() => patch({ rule: rule.code, queue: !queueOpen, issueId: null })}>
          <Icon name="shield" />{queueOpen ? "Hide the list" : rule.policy ? "Review exceptions one by one" : "Review one by one"}
        </button>
      </div>
    </div>
  );
}

function Queue({ rule }: { rule: RuleSummary }) {
  const { patch } = useApp();
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    box.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [rule.code]);
  const labels = RULE_LABELS[rule.code];
  return (
    <div className="queue" ref={box}>
      <div className="queue-head">
        <SevChip sev={rule.severity} />
        <div>
          <b>{labels?.question ?? rule.title}</b>
          <div className="small muted">{`${rule.title} · ${nf(rule.open)} open, ${nf(rule.decided)} decided. Pick a row for its evidence; decide this item alone, or the whole question.`}</div>
        </div>
        <span style={{ flex: 1 }} />
        <button className="btn" onClick={() => patch({ queue: false, issueId: null })}><Icon name="x" />Close list</button>
      </div>
      <IssueQueue rule={rule.code} />
    </div>
  );
}

export function Decisions() {
  const { nav, version, room, go, catalog } = useApp();
  const rules = useFetch<RuleSummary[]>("/api/rules", version);
  if (rules.error) return <ErrorBox error={rules.error} />;
  if (!rules.data) return <Loading label="Loading decisions" />;
  const sorted = [...rules.data].sort((a, b) => ORDER[a.severity] - ORDER[b.severity] || b.open - a.open);
  const blocking = sorted.filter((r) => r.severity === "blocking" && r.open);
  const active = nav.rule && sorted.some((r) => r.code === nav.rule) ? nav.rule : null;
  const blockingIssues = room?.open_issues.blocking ?? 0;
  return (
    <div className="decisions">
      <div className="step-head">
        <div>
          <h2>Decisions</h2>
          <div className="small muted">
            {blocking.length
              ? `${blocking.length} question${blocking.length > 1 ? "s" : ""} (${nf(blockingIssues)} issues) must be decided before the snapshot can be published. Decide each once, for all affected items, or review the exceptions one by one. Every decision needs a reason and is kept in an append-only log; the original values are never overwritten.`
              : "No blocking question is open. Warnings and notes can still be decided; the snapshot can be published."}
          </div>
        </div>
        <div className="row">
          {blockingIssues ? <SevChip sev="blocking">{`${nf(blockingIssues)} blocking`}</SevChip> : <SevChip sev="ok">publish gate open</SevChip>}
          <button className="btn" onClick={() => go("publish")}><Icon name="open" />Publish step</button>
        </div>
      </div>
      <div className="step-body">
        {sorted.length ? (
          <div className="decision-grid">
            {sorted.map((r) => <DecisionCard key={r.code} rule={r} active={r.code === active} />)}
          </div>
        ) : (
          <div className="empty" style={{ padding: "18px 22px" }}>
            <h3>Nothing to decide yet</h3>
            <p>
              The checks run on every rebuild and raise a question only when two sources disagree or a value cannot be placed. This snapshot
              ({nf(room?.counts.entities)} entities in {Object.keys(room?.counts.entities_by_type ?? {}).length} types, {nf(room?.counts.relationships)} links) raised none.
              {room && room.counts.relationships === 0 ? " Its entity types are not connected to each other, so there is nothing to compare: add the files that relate them (for example the unit workbook and the map layers, or the economics file), and the checks will have material to work on." : ""}
            </p>
            <p>What the checks look for:</p>
            <ul>
              {(catalog?.rules ?? []).map((r) => (
                <li key={r.code}><b>{RULE_LABELS[r.code]?.question ?? r.title}</b> <span className="muted">{`— ${r.check}.`}</span></li>
              ))}
            </ul>
          </div>
        )}
        {nav.queue && active ? <Queue rule={sorted.find((r) => r.code === active) as RuleSummary} /> : null}
      </div>
    </div>
  );
}
