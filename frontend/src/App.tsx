// Application shell: top bar with the project and the step bar, the current step, the chat panel, the inspector drawer and the toast.
import type { FileItem } from "./api";
import { Chat } from "./Chat";
import { Drawer } from "./Drawer";
import { useApp, type Place, type View } from "./store";
import { ErrorBox, Icon } from "./ui";
import { STEPS, nf } from "./util";
import { Ask } from "./views/Ask";
import { Decisions } from "./views/Decisions";
import { Inputs, Upload } from "./views/Inputs";
import { Model } from "./views/Model";
import { Projects } from "./views/Projects";
import { Publish } from "./views/Publish";

// Returns [short label, full tooltip] for the place the Back button returns to.
function describePlace({ nav, drawer }: Place, file: FileItem | undefined): [string, string] {
  if (nav.view === "projects") return ["all projects", "all projects"];
  if (nav.view !== "data") {
    const where = nav.view === "ask" ? (drawer?.kind === "entity" ? drawer.id : nav.mode === "schema" ? "schema graph" : nav.focus) : nav.view === "model" ? nav.modelTab : nav.view === "decisions" ? nav.rule ?? "all decisions" : "snapshot";
    return [where, where];
  }
  const name = file?.path.split("/").pop() ?? nav.fileId ?? "";
  const at = drawer?.kind === "cell" ? `${drawer.sheet}!${drawer.cell}` : file?.kind === "pdf" ? `page ${nav.page}` : file?.kind === "gis_layer" ? (nav.feature != null ? `feature ${nav.feature}` : "") : nav.cell ? `${nav.sheet}!${nav.cell}` : "";
  return at ? [at, `${at} in ${name}`] : [name, name];
}

const STEP_LABEL: Record<View, string> = { projects: "Projects", data: "Data", model: "Model", decisions: "Decisions", publish: "Publish", ask: "Ask" };

export function App() {
  const { nav, go, back, goBack, fileByPath, room, roomError, project, chatOpen, setChatOpen, toast, files } = useApp();
  const blocking = room?.open_issues.blocking ?? 0;
  const pendingModel = (room?.pending_proposals ?? 0) + (room?.mappings?.proposed ?? 0);
  const backView = back ? STEP_LABEL[back.nav.view] : null;
  const [backShort, backFull] = back ? describePlace(back, fileByPath(back.nav.fileId)) : ["", ""];
  const projectsPage = nav.view === "projects" || !nav.room;
  const badge = (id: View): [string, "blocking" | "warning" | "ok" | "info" | null] | null => {
    if (!room) return null;
    if (id === "data") return [`${files.length}`, null];
    if (id === "model") return pendingModel ? [`${nf(pendingModel)} to review`, "warning"] : [room.catalog_version, null];
    if (id === "decisions") return blocking ? [`${nf(blocking)} blocking`, "blocking"] : [`${nf(room.decided_issues)} decided`, "ok"];
    if (id === "publish") return room.status === "published" ? ["published", "ok"] : [room.status === "in_review" ? "gated" : "ready", room.status === "in_review" ? "warning" : "ok"];
    return null;
  };
  const emptyProject = Boolean(roomError?.includes("503"));
  let main = null;
  if (projectsPage) main = <Projects />;
  else if (emptyProject) {
    // A new project has no snapshot yet: every step shows the upload box until the first file arrives.
    main = (
      <div className="empty-room">
        <Upload empty />
        <div className="small muted" style={{ maxWidth: 560 }}>Nothing has been read yet. The first snapshot is built as soon as a file arrives: workbooks, slide decks and map layers are read, every value keeps its source cell, page or feature, and the files are checked against each other.</div>
      </div>
    );
  } else if (roomError) main = <ErrorBox error={roomError} />;
  else if (nav.view === "data") main = <Inputs />;
  else if (nav.view === "model") main = <Model />;
  else if (nav.view === "decisions") main = <Decisions />;
  else if (nav.view === "publish") main = <Publish />;
  else main = <Ask />;
  return (
    <>
      <div className={`app${chatOpen ? "" : " chat-collapsed"}`} id="app">
        <header className="topbar">
          <button className="brand" onClick={() => go("projects")} title="All projects">
            <span className="brand-mark" aria-hidden="true"><Icon name="graph" /></span>
            Data Room Intelligence
          </button>
          {!projectsPage ? (
            <>
              <span className="sep muted">›</span>
              <button className="project-name" onClick={() => go("projects")} title="Switch project">{project?.name ?? room?.name ?? nav.room}</button>
            </>
          ) : null}
          {back && !projectsPage ? (
            <button className="btn back-btn" onClick={goBack} title={`Back to ${backView}: ${backFull}`}>
              <Icon name="back" />
              {`Back to ${backView}`}
              <span className="back-detail mono">{backShort}</span>
            </button>
          ) : null}
          {!projectsPage ? (
            <nav className="steps" aria-label="Steps">
              {STEPS.map((step, index) => {
                const b = badge(step.id);
                const disabled = emptyProject && step.id !== "data";
                return (
                  <button key={step.id} aria-current={nav.view === step.id ? "step" : undefined} disabled={disabled} title={disabled ? "Add files first" : step.hint} onClick={() => go(step.id)}>
                    <span className="num">{index + 1}</span>
                    {step.label}
                    {b ? <span className={`badge ${b[1] ?? ""}`}>{b[0]}</span> : null}
                  </button>
                );
              })}
            </nav>
          ) : <div className="spacer" />}
          <div className="spacer" />
          {!projectsPage && nav.view !== "ask" && !emptyProject ? (
            <button className="btn" aria-pressed={chatOpen} onClick={() => setChatOpen(!chatOpen)} title="Ask a question about this project without leaving the step"><Icon name="spark" />Ask</button>
          ) : null}
          <button className="icon-btn" aria-label="Toggle light or dark theme" onClick={() => { document.documentElement.classList.toggle("dark"); go(nav.view); }}><Icon name="moon" /></button>
        </header>
        <main className="main" id="main">{main}</main>
        {chatOpen ? <Chat /> : null}
      </div>
      <Drawer />
      {toast ? <div className="toast" role="status">{toast}</div> : null}
    </>
  );
}
