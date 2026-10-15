// Chat panel: questions go to POST /api/graph/ask; answers come from named operations with citations and actions.
import { useEffect, useRef, useState, type ReactNode } from "react";
import type { Answer, Json } from "./api";
import { useApp } from "./store";
import { Cite, Icon, SevChip } from "./ui";
import { nf } from "./util";

const PROMPTS = ["What did JARDINE 4-27 A 4LS produce in June 2026?", "What are the Wolfcamp A net acres, net locations and PV-10?", "Does the asset overview deck agree with the data?", "What are the data gaps?"];

function ResultWidget({ answer }: { answer: Answer }) {
  const result = answer.results[0];
  if (!result) return null;
  const data = result.data as Json;
  if (result.operation === "zone_summary" && data.net_acres != null) {
    const rows = (data.by_status as { status: string; count: number; ky_musd: number; mf_musd: number }[]) ?? [];
    return (
      <div className="result">
        <div className="metrics">
          <div className="metric"><b>{nf(data.net_acres, 0)}</b><span>net acres</span></div>
          <div className="metric"><b>{nf(data.net_locations_10k, 2)}</b><span>net locations</span></div>
          <div className="metric"><b>{nf(data.economic_locations)}</b><span>economic locations</span></div>
        </div>
        {rows.length ? (
          <table className="simple">
            <thead><tr><th>Status</th><th className="num">Locs</th><th className="num">KY $MM</th><th className="num">MF $MM</th></tr></thead>
            <tbody>{rows.map((r) => <tr key={r.status}><td>{r.status}</td><td className="num">{r.count}</td><td className="num">{nf(r.ky_musd, 1)}</td><td className="num">{nf(r.mf_musd, 1)}</td></tr>)}</tbody>
          </table>
        ) : null}
        {Number(data.pv10_open_conflicts) ? <div className="small" style={{ marginTop: 6 }}><SevChip sev="blocking">VALUE_FIELD_CONFLICT</SevChip> blocks a single PV-10 figure.</div> : null}
      </div>
    );
  }
  if (result.operation === "claim_check") {
    const claims = (data.claims as { claim: string; page: number; check: string; computed: number | null }[]) ?? [];
    return (
      <div className="result">
        <table className="simple">
          <thead><tr><th>Claim</th><th>Check</th><th className="num">Room</th></tr></thead>
          <tbody>{claims.map((c) => <tr key={c.claim} className={c.check === "mismatch" ? "flag" : ""}><td>{c.claim}</td><td><SevChip sev={c.check === "match" ? "ok" : c.check === "mismatch" ? "blocking" : "warning"}>{c.check}</SevChip></td><td className="num">{nf(c.computed, 2)}</td></tr>)}</tbody>
        </table>
      </div>
    );
  }
  if (result.operation === "well_profile") {
    const months = (data.monthly_production as { month: string; oil_bbl?: number; gas_mcf?: number; water_bbl?: number }[]) ?? [];
    if (!months.length) return null;
    return (
      <div className="result">
        <table className="simple">
          <thead><tr><th>Month</th><th className="num">Oil bbl</th><th className="num">Gas mcf</th><th className="num">Water bbl</th></tr></thead>
          <tbody>{months.slice(-6).map((m) => <tr key={m.month}><td>{m.month.slice(0, 7)}</td><td className="num">{nf(m.oil_bbl)}</td><td className="num">{nf(m.gas_mcf)}</td><td className="num">{nf(m.water_bbl)}</td></tr>)}</tbody>
        </table>
      </div>
    );
  }
  return null;
}

function BotMessage({ answer }: { answer: Answer }) {
  const { runAction } = useApp();
  const trace = answer.operations.map((o) => `${o.operation}(${Object.entries(o.args).filter(([, v]) => v != null).map(([k, v]) => `${k}="${String(v)}"`).join(", ")})`).join(" → ");
  const paragraphs = answer.answer.split(/\n+/).filter((p) => p.trim());
  return (
    <div className="msg bot">
      <div className="trace"><Icon name="spark" /><span className="mono" title={trace}>{trace}</span></div>
      <div className="text">{paragraphs.map((p, i) => <p key={i}>{p.replace(/^[-*]\s+/, "• ")}</p>)}</div>
      <ResultWidget answer={answer} />
      {answer.citations.length ? <div className="cites">{answer.citations.map((c, i) => <Cite key={i} citation={c} />)}</div> : null}
      {answer.actions.length ? <div className="actions">{answer.actions.map((a, i) => <button key={i} className="btn" onClick={() => runAction(a)}>{a.label}</button>)}</div> : null}
      <div className="mode">{`${answer.mode} · ${answer.seconds}s`}</div>
    </div>
  );
}

export function Chat() {
  const { messages, ask, setChatOpen, health, drawer } = useApp();
  const [text, setText] = useState("");
  const log = useRef<HTMLDivElement>(null);
  useEffect(() => {
    log.current?.scrollTo({ top: log.current.scrollHeight });
  }, [messages]);
  const send = () => {
    const question = text.trim();
    if (!question) return;
    setText("");
    ask(question, drawer?.kind === "entity" ? drawer.id : null);
  };
  let content: ReactNode[] = messages.map((m) => {
    if (m.role === "user") return <div key={m.id} className="msg user">{m.text}</div>;
    if (m.pending) return <div key={m.id} className="msg bot"><div className="thinking"><span className="spinner" />Calling named operations…</div></div>;
    if (m.error) return <div key={m.id} className="msg bot"><div className="text"><p>{`The question could not be answered: ${m.error}`}</p></div></div>;
    return m.answer ? <BotMessage key={m.id} answer={m.answer} /> : null;
  });
  if (!messages.length) {
    content = [
      <div key="intro" className="msg bot">
        <div className="trace"><Icon name="spark" /><span className="mono">named operations over snapshot facts</span></div>
        <div className="text">
          <p>Ask about units, wells, zones, conflicts, documents or data gaps. I answer only with named operations over the snapshot, cite the source cells, pages and map features, and say when the data cannot support an answer.</p>
        </div>
      </div>,
    ];
  }
  return (
    <aside className="chat" aria-label="Ask the data room">
      <div className="chat-head">
        <Icon name="spark" />
        <h3>Ask the data room</h3>
        <span style={{ flex: 1 }} />
        <SevChip sev="ai">{health ? (health.offline || !health.model ? "offline router" : `${health.model} · Foundry`) : "…"}</SevChip>
        <button className="icon-btn" aria-label="Hide chat" onClick={() => setChatOpen(false)}><Icon name="x" /></button>
      </div>
      <div className="chat-log" role="log" aria-live="polite" ref={log}>{content}</div>
      <div className="chat-foot">
        <div className="prompts">{PROMPTS.map((p) => <button key={p} className="chip" onClick={() => ask(p)}>{p}</button>)}</div>
        <div className="ask">
          <input type="text" value={text} placeholder="Ask about units, wells, zones, conflicts…" aria-label="Ask a question" onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()} />
          <button className="btn primary" aria-label="Send" onClick={send}><Icon name="send" /></button>
        </div>
        <div className="small muted" style={{ marginTop: 6 }}>The model routes and explains; numbers come only from operation results and are checked before display.</div>
      </div>
    </aside>
  );
}
