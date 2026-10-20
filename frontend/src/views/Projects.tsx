// Projects: one card per data room with its health, and a form to start a new project from the governed base model.
import { useState } from "react";
import { api, type Project } from "../api";
import { useApp, type Nav, type View } from "../store";
import { Icon, Loading, SevChip } from "../ui";
import { nf, when } from "../util";

const plural = (n: number, word: string) => `${nf(n)} ${word}${n === 1 ? "" : "s"}`;

function statusChip(project: Project) {
  if (!project.has_snapshot) return <SevChip sev="info">no data yet</SevChip>;
  if (project.status === "published") return <SevChip sev="ok">published</SevChip>;
  if (project.blocking_questions > 0) return <SevChip sev="blocking">{`${plural(project.blocking_questions, "open question")} before publishing`}</SevChip>;
  return <SevChip sev="ok">ready to publish</SevChip>;
}

function ProjectCard({ project, isDefault }: { project: Project; isDefault: boolean }) {
  const { openProject, refresh, notify } = useApp();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const pending = project.pending_proposals + project.pending_mappings;
  const remove = async () => {
    setBusy(true);
    try {
      await api.del(`/api/projects/${encodeURIComponent(project.room_id)}`);
      notify(`Deleted project ${project.name}: its files, snapshots, decisions and model changes are gone.`);
      refresh();
    } catch (e) {
      notify(`Could not delete: ${(e as Error).message}`);
      setBusy(false);
      setConfirming(false);
    }
  };
  // The primary button names the next thing the project needs, so nobody has to work out where to go.
  const next: [View, string, Partial<Nav>?] = !project.has_snapshot
    ? ["data", "Add files"]
    : project.pending_proposals ? ["model", `Review ${plural(project.pending_proposals, "model change")}`, { modelTab: "changes" }]
    : project.pending_mappings ? ["model", `Approve ${plural(project.pending_mappings, "mapping")}`, { modelTab: "mappings" }]
    : project.blocking_questions ? ["decisions", `Answer ${plural(project.blocking_questions, "question")}`]
    : project.status !== "published" ? ["publish", "Publish"]
    : ["ask", "Ask"];
  return (
    <div className="project-card">
      <div className="head">
        <h3>{project.name}</h3>
        {statusChip(project)}
      </div>
      <div className="small muted desc">{project.description || (isDefault ? "Sample data room registered from the repository." : "Created in the app.")}</div>
      <dl className="stats">
        <div><dt>Files</dt><dd>{nf(project.files)}</dd></div>
        <div><dt>Model</dt><dd title={project.catalog_version}>{project.model_changes ? `base + ${project.model_changes} change${project.model_changes > 1 ? "s" : ""}` : "base"}</dd></div>
        <div><dt>Waiting for review</dt><dd>{pending ? <SevChip sev="warning">{nf(pending)}</SevChip> : "0"}</dd></div>
        <div><dt>Open issues</dt><dd title="Items where the seller's files disagree; each question in Decisions settles many at once">{project.open_issues.blocking ? `${nf(project.open_issues.blocking)} blocking` : nf(project.decided_issues) + " decided"}</dd></div>
        <div><dt>Last built</dt><dd>{when(project.built_at)}</dd></div>
        {project.counts ? <div><dt>Facts</dt><dd>{nf(project.counts.facts)}</dd></div> : null}
      </dl>
      {confirming ? (
        <div className="confirm">
          <div className="small">{`Delete ${project.name}? Its files, snapshots, decisions and model changes are removed. This cannot be undone.`}</div>
          <div className="acts">
            <button className="btn danger" disabled={busy} onClick={remove}>{busy ? <span className="spinner" /> : <Icon name="x" />}Delete project</button>
            <button className="btn" disabled={busy} onClick={() => setConfirming(false)}>Keep it</button>
          </div>
        </div>
      ) : (
        <div className="acts">
          <button className="btn primary" onClick={() => openProject(project.room_id, next[0], next[2])}>{next[1]}</button>
          <button className="btn" onClick={() => openProject(project.room_id, project.has_snapshot ? "ask" : "data")}>Open</button>
          {!isDefault ? <button className="icon-btn" aria-label={`Delete ${project.name}`} title="Delete this project" onClick={() => setConfirming(true)}><Icon name="trash" /></button> : null}
        </div>
      )}
    </div>
  );
}

function NewProject({ projects, onCreated }: { projects: Project[]; onCreated: (room: string) => void }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [template, setTemplate] = useState<"base" | "copy">("base");
  const [copyFrom, setCopyFrom] = useState(projects.find((p) => p.model_changes)?.room_id ?? projects[0]?.room_id ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      const created = await api.post<Project>("/api/projects", { name, description, template, copied_from: template === "copy" ? copyFrom : null });
      onCreated(created.room_id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="project-card new" onSubmit={(e) => { e.preventDefault(); if (name.trim()) create(); }}>
      <div className="head"><h3><Icon name="plus" />New project</h3></div>
      <label className="field">
        <span>Project name</span>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Delaware Basin Package B" maxLength={80} required />
      </label>
      <label className="field">
        <span>Description (optional)</span>
        <input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Seller, asset, stage" maxLength={200} />
      </label>
      <fieldset className="field">
        <legend>Starting model</legend>
        <label className="radio"><input type="radio" checked={template === "base"} onChange={() => setTemplate("base")} /><span><b>Upstream deal template</b><br /><span className="small muted">The governed base model: units, wells, locations, ownership, economics, pricing, documents.</span></span></label>
        <label className="radio"><input type="radio" checked={template === "copy"} onChange={() => setTemplate("copy")} /><span><b>Copy a project's model</b><br /><span className="small muted">Base model plus the entity types, links and header rules another project added.</span></span></label>
        {template === "copy" ? (
          <select value={copyFrom} onChange={(e) => setCopyFrom(e.target.value)} aria-label="Project to copy the model from">
            {projects.map((p) => <option key={p.room_id} value={p.room_id}>{`${p.name}${p.model_changes ? ` (${p.model_changes} change${p.model_changes > 1 ? "s" : ""})` : " (base only)"}`}</option>)}
          </select>
        ) : null}
      </fieldset>
      <div className="small muted">The project starts empty. Add the seller's files in the Data step: a zip of the data room, or files one at a time.</div>
      {error ? <div className="small" style={{ color: "hsl(var(--blocking))" }}>{error}</div> : null}
      <div className="acts"><button className="btn primary" type="submit" disabled={busy || !name.trim()}>{busy ? <span className="spinner" /> : <Icon name="plus" />}Create project</button></div>
    </form>
  );
}

export function Projects() {
  const { projects, refresh, openProject, notify } = useApp();
  if (!projects) return <Loading label="Loading projects" />;
  return (
    <div className="projects">
      <div className="projects-head">
        <h1>Projects</h1>
        <div className="muted">Each project is one data room: its files, its model, its decisions and its published snapshots. Every project starts from the same governed base model and may extend it.</div>
      </div>
      <div className="project-grid">
        {[...projects.projects]
          .sort((a, b) => Number(b.room_id === projects.default) - Number(a.room_id === projects.default) || (b.built_at ?? b.created_at ?? "").localeCompare(a.built_at ?? a.created_at ?? ""))
          .map((p) => <ProjectCard key={p.room_id} project={p} isDefault={p.room_id === projects.default} />)}
        <NewProject projects={projects.projects} onCreated={(room) => { refresh(); notify("Project created. Add the seller's files to build the first snapshot."); openProject(room, "data"); }} />
      </div>
    </div>
  );
}
