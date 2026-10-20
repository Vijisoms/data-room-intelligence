// App state: the current project, the step the user is on (mirrored in the URL hash for deep links),
// the inspector drawer, the chat and shared data.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, useFetch, type Action, type Answer, type Catalog, type FileItem, type Health, type Project, type ProjectList, type Room, type Sev } from "./api";
import { SEVERITIES } from "./util";

export type View = "projects" | "data" | "model" | "decisions" | "publish" | "ask";
export type ModelTab = "changes" | "mappings" | "dictionary" | "graph";
export type CatalogSel = { kind: "type" | "rel" | "measure" | "rule" | "alias"; name: string };
/** Names the old views used in links written before the step bar existed. */
const LEGACY_VIEWS: Record<string, View> = { inputs: "data", schema: "model", review: "decisions", explore: "ask" };

export interface Nav {
  room: string | null;
  view: View;
  modelTab: ModelTab;
  proposalId: string | null;
  mode: "schema" | "neighborhood";
  focus: string;
  depth: 1 | 2;
  selected: string | null;
  hiddenTypes: string[];
  methods: string[];
  severities: Sev[];
  issuesOnly: boolean;
  schemaType: string | null;
  fileId: string | null;
  sheet: string | null;
  cell: string | null;
  page: number;
  figure: string | null;
  feature: number | null;
  side: string;
  rule: string | null;
  issueId: string | null;
  queue: boolean;
  catalog: CatalogSel;
}

export type DrawerState =
  | { kind: "entity"; id: string }
  | { kind: "type"; name: string }
  | { kind: "cell"; fileId: string; sheet: string; cell: string; value?: unknown }
  | { kind: "figure"; fileId: string; figure: string };

export interface ChatMessage { id: number; role: "user" | "bot"; text?: string; answer?: Answer; pending?: boolean; error?: string }

export interface Place { nav: Nav; drawer: DrawerState | null }
type HistoryEntry = Place & { back: Place | null };

interface AppValue {
  nav: Nav;
  patch: (p: Partial<Nav>) => void;
  go: (view: View, p?: Partial<Nav>) => void;
  openProject: (room: string, view?: View, extra?: Partial<Nav>) => void;
  back: Place | null;
  goBack: () => void;
  version: number;
  refresh: () => void;
  room: Room | null;
  roomError: string | null;
  project: Project | null;
  projects: ProjectList | null;
  catalog: Catalog | null;
  health: Health | null;
  files: FileItem[];
  fileByPath: (pathOrId: string | null | undefined) => FileItem | undefined;
  drawer: DrawerState | null;
  openDrawer: (d: DrawerState) => void;
  closeDrawer: () => void;
  openEntity: (id: string) => void;
  focusGraph: (id: string, depth?: 1 | 2) => void;
  openSource: (file: string | null | undefined, locator: string | null | undefined) => void;
  chatOpen: boolean;
  setChatOpen: (v: boolean) => void;
  messages: ChatMessage[];
  ask: (question: string, scope?: string | null) => void;
  runAction: (a: Action) => void;
  toast: string | null;
  notify: (message: string) => void;
}

const AppContext = createContext<AppValue | null>(null);

export const useApp = (): AppValue => {
  const value = useContext(AppContext);
  if (!value) throw new Error("useApp outside AppProvider");
  return value;
};

const DEFAULT_NAV: Nav = {
  room: null,
  view: "projects",
  modelTab: "changes",
  proposalId: null,
  mode: "neighborhood",
  focus: "well:42901144110000",
  depth: 2,
  selected: null,
  hiddenTypes: [],
  methods: ["source", "key", "spatial", "alias", "document", "crosswalk"],
  severities: [...SEVERITIES],
  issuesOnly: false,
  schemaType: "Well",
  fileId: null,
  sheet: null,
  cell: null,
  page: 1,
  figure: null,
  feature: null,
  side: "fields",
  rule: null,
  issueId: null,
  queue: false,
  catalog: { kind: "type", name: "Well" },
};

const HASH_KEYS: (keyof Nav)[] = ["room", "view", "modelTab", "proposalId", "mode", "focus", "depth", "selected", "fileId", "sheet", "cell", "page", "figure", "side", "rule", "issueId", "queue"];

function navFromHash(): { nav: Nav; drawer: DrawerState | null; ask: string | null; chat: boolean | null } {
  const params = new URLSearchParams(location.hash.slice(1));
  const nav: Nav = { ...DEFAULT_NAV };
  const record = nav as unknown as Record<string, unknown>;
  for (const key of HASH_KEYS) {
    const value = params.get(key);
    if (value == null) continue;
    record[key] = key === "depth" ? (Number(value) === 1 ? 1 : 2) : key === "page" ? Number(value) || 1 : key === "queue" ? value === "1" : value;
  }
  if (LEGACY_VIEWS[nav.view as string]) {
    const legacy = nav.view as string;
    nav.view = LEGACY_VIEWS[legacy];
    if (legacy === "schema") nav.modelTab = "dictionary";
    if (legacy === "review") nav.queue = true;
  }
  if (params.get("type")) nav.catalog = { kind: "type", name: params.get("type") as string };
  if (params.get("theme") === "light") document.documentElement.classList.remove("dark");
  // A link into a step without a project means the default (sample) project.
  if (!nav.room && nav.view !== "projects") nav.room = params.get("room") ?? "__default__";
  const target = params.get("drawer");
  let drawer: DrawerState | null = null;
  if (target?.startsWith("type:")) drawer = { kind: "type", name: target.slice(5) };
  else if (target === "figure" && nav.figure && nav.fileId) drawer = { kind: "figure", fileId: nav.fileId, figure: nav.figure };
  else if (target === "cell" && nav.sheet && nav.cell && nav.fileId) drawer = { kind: "cell", fileId: nav.fileId, sheet: nav.sheet, cell: nav.cell };
  else if (target) drawer = { kind: "entity", id: target };
  const chat = params.get("chat");
  return { nav, drawer, ask: params.get("ask"), chat: chat === "off" ? false : chat === "on" ? true : null };
}

const savedEntry = (state: unknown): HistoryEntry | null => (state as { dri?: HistoryEntry } | null)?.dri ?? null;

function parseLocator(locator: string | null | undefined): Partial<Nav> {
  if (!locator) return {};
  let m = /^(.+?)!\$?([A-Z]{1,3})\$?(\d+)/.exec(locator);
  if (m) return { sheet: m[1], cell: `${m[2]}${m[3]}`, side: "fields" };
  m = /^page (\d+)/i.exec(locator);
  if (m) return { page: Number(m[1]), side: "claims" };
  m = /^feature (\d+)/i.exec(locator);
  if (m) return { feature: Number(m[1]), side: "fields" };
  return {};
}

export function AppProvider({ children }: { children: ReactNode }) {
  const boot = useMemo(navFromHash, []);
  const health = useFetch<Health>("/api/health", 0).data;
  const [nav, setNav] = useState<Nav>(boot.nav);
  // "__default__" stands for the sample project until /api/health tells us its ID.
  const roomId = nav.room === "__default__" ? health?.room_id ?? null : nav.room;
  api.setRoom(roomId);
  const [drawer, setDrawer] = useState<DrawerState | null>(boot.drawer);
  const [back, setBack] = useState<Place | null>(() => savedEntry(history.state)?.back ?? null);
  const backRef = useRef(back);
  const shown = useRef<Place | null>(null);
  const restoring = useRef(false);
  const [version, setVersion] = useState(0);
  const [chatOpen, setChatOpen] = useState(boot.chat ?? false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [toast, setToast] = useState<string | null>(null);
  const counter = useRef(0);
  const toastTimer = useRef<number | undefined>(undefined);

  const inProject = Boolean(roomId) && nav.view !== "projects";
  const roomFetch = useFetch<Room>(inProject ? `/api/room?room=${encodeURIComponent(roomId as string)}` : null, version);
  const room = roomFetch.data;
  const project = useFetch<Project>(roomId ? `/api/projects/${encodeURIComponent(roomId)}` : null, version).data;
  const projects = useFetch<ProjectList>("/api/projects", version).data;
  const files = useFetch<FileItem[]>(inProject && room ? `/api/files?room=${encodeURIComponent(roomId as string)}` : null, version).data ?? [];
  const catalog = useFetch<Catalog>(inProject && room ? `/api/catalog?room=${encodeURIComponent(roomId as string)}` : null, version).data;

  useEffect(() => {
    if (nav.room === "__default__" && health?.room_id) setNav((current) => ({ ...current, room: health.room_id }));
  }, [health, nav.room]);

  useEffect(() => {
    const params = new URLSearchParams();
    const record = nav as unknown as Record<string, unknown>;
    for (const key of HASH_KEYS) {
      const value = record[key];
      if (value == null || value === (DEFAULT_NAV as unknown as Record<string, unknown>)[key] || value === "__default__") continue;
      params.set(key, key === "queue" ? "1" : String(value));
    }
    if (drawer?.kind === "entity") params.set("drawer", drawer.id);
    if (drawer?.kind === "type") params.set("drawer", `type:${drawer.name}`);
    if (!document.documentElement.classList.contains("dark")) params.set("theme", "light");
    const url = `#${params.toString()}`;
    const previous = shown.current;
    shown.current = { nav, drawer };
    // A step change adds a browser history entry, so Back (in-app or browser) restores the step as it was left.
    if (previous && (previous.nav.view !== nav.view || previous.nav.room !== nav.room) && !restoring.current) {
      backRef.current = previous;
      setBack(previous);
      history.pushState({ dri: { nav, drawer, back: previous } }, "", url);
    } else history.replaceState({ dri: { nav, drawer, back: backRef.current } }, "", url);
    restoring.current = false;
  }, [nav, drawer]);

  useEffect(() => {
    const onPop = (event: PopStateEvent) => {
      const saved = savedEntry(event.state);
      const place = saved ? { nav: { ...DEFAULT_NAV, ...saved.nav }, drawer: saved.drawer } : navFromHash();
      restoring.current = true;
      backRef.current = saved?.back ?? null;
      setBack(backRef.current);
      setNav(place.nav);
      setDrawer(place.drawer);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const chatVisible = inProject && (nav.view === "ask" || chatOpen);
  useEffect(() => {
    if (chatVisible) document.documentElement.style.removeProperty("--chat-w");
    else document.documentElement.style.setProperty("--chat-w", "0px");
  }, [chatVisible]);

  const patch = useCallback((p: Partial<Nav>) => setNav((current) => ({ ...current, ...p })), []);
  const go = useCallback((view: View, p?: Partial<Nav>) => setNav((current) => ({ ...current, ...p, view })), []);
  const openProject = useCallback((roomName: string, view: View = "data", extra?: Partial<Nav>) => {
    setDrawer(null);
    setMessages([]);
    setNav((current) => ({ ...DEFAULT_NAV, room: roomName, view, catalog: current.catalog, ...extra }));
  }, []);
  const goBack = useCallback(() => history.back(), []);
  const refresh = useCallback(() => {
    api.invalidate();
    setVersion((v) => v + 1);
  }, []);
  const notify = useCallback((message: string) => {
    setToast(message);
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 6000);
  }, []);
  const fileByPath = useCallback((key: string | null | undefined) => files.find((f) => f.path === key || f.file_id === key), [files]);
  const openDrawer = useCallback((d: DrawerState) => setDrawer(d), []);
  const closeDrawer = useCallback(() => setDrawer(null), []);
  const openEntity = useCallback((id: string) => setDrawer({ kind: "entity", id }), []);
  const focusGraph = useCallback((id: string, depth?: 1 | 2) => {
    setDrawer(null);
    setNav((current) => ({ ...current, view: "ask", mode: "neighborhood", focus: id, selected: id, depth: depth ?? current.depth }));
  }, []);
  const openSource = useCallback(
    (file: string | null | undefined, locator: string | null | undefined) => {
      const item = fileByPath(file);
      if (!item) return;
      setDrawer(null);
      const parsed = parseLocator(locator);
      setNav((current) => ({
        ...current,
        view: "data",
        fileId: item.file_id,
        sheet: parsed.sheet ?? (item.sheets[0]?.sheet || null),
        cell: parsed.cell ?? null,
        page: parsed.page ?? (item.kind === "pdf" ? 1 : current.page),
        figure: null,
        feature: parsed.feature ?? null,
        side: parsed.side ?? (item.kind === "pdf" ? "claims" : "fields"),
      }));
    },
    [fileByPath],
  );

  const ask = useCallback((question: string, scope?: string | null) => {
    const id = ++counter.current;
    setChatOpen(true);
    setMessages((list) => [...list, { id: id * 2, role: "user", text: question }, { id: id * 2 + 1, role: "bot", pending: true }]);
    api.post<Answer>("/api/graph/ask", { question, scope: scope ?? null }).then(
      (answer) => setMessages((list) => list.map((m) => (m.id === id * 2 + 1 ? { ...m, pending: false, answer } : m))),
      (error: Error) => setMessages((list) => list.map((m) => (m.id === id * 2 + 1 ? { ...m, pending: false, error: error.message } : m))),
    );
  }, []);

  const runAction = useCallback(
    (a: Action) => {
      if (a.type === "focus" && a.entity) focusGraph(a.entity, a.entity.startsWith("zone:") ? 1 : undefined);
      else if (a.type === "inspect" && a.entity) openEntity(a.entity);
      else if (a.type === "review") {
        setDrawer(null);
        go("decisions", { rule: a.rule ?? null, issueId: null, queue: true });
      } else if (a.type === "document" && a.file_id) {
        setDrawer(null);
        go("data", { fileId: a.file_id, page: a.page ?? 1, figure: null, side: "figures" });
      } else if (a.type === "view" && a.view) go((LEGACY_VIEWS[a.view] ?? a.view) as View, a.mode ? { mode: a.mode as Nav["mode"] } : undefined);
    },
    [focusGraph, openEntity, go],
  );

  const asked = useRef(false);
  useEffect(() => {
    if (boot.ask && !asked.current && room) {
      asked.current = true;
      ask(boot.ask);
    }
  }, [boot.ask, ask, room]);

  const value: AppValue = {
    nav, patch, go, openProject, back, goBack, version, refresh, room, roomError: roomFetch.error, project, projects, catalog, health, files, fileByPath, drawer, openDrawer, closeDrawer, openEntity, focusGraph, openSource,
    chatOpen: chatVisible, setChatOpen, messages, ask, runAction, toast, notify,
  };
  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}
