// Application shell: top bar, view rail, main view, chat panel, inspector drawer and toast.
import { Chat } from "./Chat";
import { Drawer } from "./Drawer";
import { useApp, type View } from "./store";
import { Icon, SevChip } from "./ui";
import { nf } from "./util";
import { Explore } from "./views/Explore";
import { Inputs } from "./views/Inputs";
import { Review } from "./views/Review";
import { Schema } from "./views/Schema";

const VIEWS: [View, string, string][] = [["explore", "Explore", "graph"], ["inputs", "Inputs", "folder"], ["schema", "Schema", "book"], ["review", "Review", "shield"]];

export function App() {
  const { nav, go, room, chatOpen, setChatOpen, toast, files } = useApp();
  const blocking = room?.open_issues.blocking ?? 0;
  return (
    <>
      <div className={`app${chatOpen ? "" : " chat-collapsed"}`} id="app">
        <header className="topbar">
          <div className="brand">
            <span className="brand-mark" aria-hidden="true"><Icon name="graph" /></span>
            Data Room Intelligence
          </div>
          <nav className="crumbs" aria-label="Context">
            <span>{room?.name ?? "…"}</span>
            <span className="sep">›</span>
            <span className="mono">{`snapshot ${room?.snapshot_id ?? "…"}`}</span>
            <span className="sep">›</span>
            <span>{`catalog ${room?.catalog_version ?? "…"}`}</span>
          </nav>
          <div className="spacer" />
          <div className="status-row">
            <span className="chip">{`${files.length} files`}</span>
            <span className="chip">{`${nf(room?.counts.entities)} entities · ${nf(room?.counts.relationships)} links · ${nf(room?.counts.facts)} facts`}</span>
            <SevChip sev="blocking">{`${nf(blocking)} blocking`}</SevChip>
            <SevChip sev="warning">{`${nf(room?.open_issues.warning ?? 0)} warnings`}</SevChip>
          </div>
          <button className="icon-btn" aria-label="Toggle light or dark theme" onClick={() => { document.documentElement.classList.toggle("dark"); go(nav.view); }}><Icon name="moon" /></button>
          <button className="icon-btn" aria-label="Show or hide the chat panel" aria-pressed={chatOpen} onClick={() => setChatOpen(!chatOpen)}><Icon name="chat" /></button>
        </header>
        <nav className="rail" aria-label="Views">
          {VIEWS.map(([id, label, icon]) => (
            <button key={id} aria-current={nav.view === id ? "page" : undefined} onClick={() => go(id)}>
              <Icon name={icon} />
              {label}
              {id === "review" && blocking ? <span className="count">{nf(blocking)}</span> : null}
            </button>
          ))}
        </nav>
        <main className="main" id="main">
          {nav.view === "explore" ? <Explore /> : nav.view === "inputs" ? <Inputs /> : nav.view === "schema" ? <Schema /> : <Review />}
        </main>
        {chatOpen ? <Chat /> : null}
      </div>
      <Drawer />
      {toast ? <div className="toast" role="status">{toast}</div> : null}
    </>
  );
}
