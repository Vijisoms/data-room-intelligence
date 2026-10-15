// App state: navigation (mirrored in the URL hash for deep links), drawer, chat and shared data.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, useFetch, type Action, type Answer, type FileItem, type Health, type Room, type Sev } from "./api";
import { SEVERITIES } from "./util";

export type View = "explore" | "inputs" | "schema" | "review";
export type CatalogSel = { kind: "type" | "rel" | "measure" | "rule" | "alias"; name: string };

export interface Nav {
  view: View;
  mode: "schema" | "neighborhood";
  focus: string;
  depth: 1 | 2;
  selected: string | null;
  hiddenTypes: string[];
  methods: string[];
  severities: Sev[];
  issuesOnly: boolean;
  schemaType: string | null;
  fileId: string;
  sheet: string | null;
  cell: string | null;
  page: number;
  figure: string | null;
  feature: number | null;
  side: string;
  rule: string | null;
  issueId: string | null;
  catalog: CatalogSel;
}

export type DrawerState =
  | { kind: "entity"; id: string }
  | { kind: "type"; name: string }
  | { kind: "cell"; fileId: string; sheet: string; cell: string; value?: unknown }
  | { kind: "figure"; fileId: string; figure: string };

export interface ChatMessage { id: number; role: "user" | "bot"; text?: string; answer?: Answer; pending?: boolean; error?: string }

interface AppValue {
  nav: Nav;
  patch: (p: Partial<Nav>) => void;
  go: (view: View, p?: Partial<Nav>) => void;
  version: number;
  refresh: () => void;
  room: Room | null;
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
  view: "explore",
  mode: "neighborhood",
  focus: "well:42901144110000",
  depth: 2,
  selected: null,
  hiddenTypes: [],
  methods: ["source", "key", "spatial", "alias", "document", "crosswalk"],
  severities: [...SEVERITIES],
  issuesOnly: false,
  schemaType: "Well",
  fileId: "combocurve",
  sheet: "ONELINE",
  cell: null,
  page: 2,
  figure: null,
  feature: null,
  side: "fields",
  rule: "UNIT_ASSIGNMENT_CONFLICT",
  issueId: null,
  catalog: { kind: "type", name: "Well" },
};

const HASH_KEYS: (keyof Nav)[] = ["view", "mode", "focus", "depth", "selected", "fileId", "sheet", "cell", "page", "figure", "side", "rule", "issueId"];

function navFromHash(): { nav: Nav; drawer: DrawerState | null; ask: string | null; chat: boolean } {
  const params = new URLSearchParams(location.hash.slice(1));
  const nav: Nav = { ...DEFAULT_NAV };
  const record = nav as unknown as Record<string, unknown>;
  for (const key of HASH_KEYS) {
    const value = params.get(key);
    if (value == null) continue;
    record[key] = key === "depth" ? (Number(value) === 1 ? 1 : 2) : key === "page" ? Number(value) || 1 : value;
  }
  if (params.get("type")) nav.catalog = { kind: "type", name: params.get("type") as string };
  if (params.get("theme") === "light") document.documentElement.classList.remove("dark");
  const target = params.get("drawer");
  let drawer: DrawerState | null = null;
  if (target?.startsWith("type:")) drawer = { kind: "type", name: target.slice(5) };
  else if (target === "figure" && nav.figure) drawer = { kind: "figure", fileId: nav.fileId, figure: nav.figure };
  else if (target === "cell" && nav.sheet && nav.cell) drawer = { kind: "cell", fileId: nav.fileId, sheet: nav.sheet, cell: nav.cell };
  else if (target) drawer = { kind: "entity", id: target };
  return { nav, drawer, ask: params.get("ask"), chat: params.get("chat") !== "off" };
}

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
  const [nav, setNav] = useState<Nav>(boot.nav);
  const [drawer, setDrawer] = useState<DrawerState | null>(boot.drawer);
  const [version, setVersion] = useState(0);
  const [chatOpen, setChatOpen] = useState(boot.chat);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [toast, setToast] = useState<string | null>(null);
  const counter = useRef(0);
  const toastTimer = useRef<number | undefined>(undefined);

  const room = useFetch<Room>("/api/room", version).data;
  const health = useFetch<Health>("/api/health", 0).data;
  const files = useFetch<FileItem[]>("/api/files", version).data ?? [];

  useEffect(() => {
    const params = new URLSearchParams();
    const record = nav as unknown as Record<string, unknown>;
    for (const key of HASH_KEYS) if (record[key] != null && record[key] !== (DEFAULT_NAV as unknown as Record<string, unknown>)[key]) params.set(key, String(record[key]));
    if (drawer?.kind === "entity") params.set("drawer", drawer.id);
    if (drawer?.kind === "type") params.set("drawer", `type:${drawer.name}`);
    if (!document.documentElement.classList.contains("dark")) params.set("theme", "light");
    history.replaceState(null, "", `#${params.toString()}`);
  }, [nav, drawer]);

  useEffect(() => {
    if (chatOpen) document.documentElement.style.removeProperty("--chat-w");
    else document.documentElement.style.setProperty("--chat-w", "0px");
  }, [chatOpen]);

  const patch = useCallback((p: Partial<Nav>) => setNav((current) => ({ ...current, ...p })), []);
  const go = useCallback((view: View, p?: Partial<Nav>) => setNav((current) => ({ ...current, ...p, view })), []);
  const refresh = useCallback(() => {
    api.invalidate();
    setVersion((v) => v + 1);
  }, []);
  const notify = useCallback((message: string) => {
    setToast(message);
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 5000);
  }, []);
  const fileByPath = useCallback((key: string | null | undefined) => files.find((f) => f.path === key || f.file_id === key), [files]);
  const openDrawer = useCallback((d: DrawerState) => setDrawer(d), []);
  const closeDrawer = useCallback(() => setDrawer(null), []);
  const openEntity = useCallback((id: string) => setDrawer({ kind: "entity", id }), []);
  const focusGraph = useCallback((id: string, depth?: 1 | 2) => {
    setDrawer(null);
    setNav((current) => ({ ...current, view: "explore", mode: "neighborhood", focus: id, selected: id, depth: depth ?? current.depth }));
  }, []);
  const openSource = useCallback(
    (file: string | null | undefined, locator: string | null | undefined) => {
      const item = fileByPath(file);
      if (!item) return;
      setDrawer(null);
      const parsed = parseLocator(locator);
      setNav((current) => ({
        ...current,
        view: "inputs",
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
        go("review", { rule: a.rule ?? null, issueId: null });
      } else if (a.type === "document" && a.file_id) {
        setDrawer(null);
        go("inputs", { fileId: a.file_id, page: a.page ?? 1, figure: null, side: "figures" });
      } else if (a.type === "view" && a.view) go(a.view as View, a.mode ? { mode: a.mode as Nav["mode"] } : undefined);
    },
    [focusGraph, openEntity, go],
  );

  const asked = useRef(false);
  useEffect(() => {
    if (boot.ask && !asked.current) {
      asked.current = true;
      ask(boot.ask);
    }
  }, [boot.ask, ask]);

  const value: AppValue = {
    nav, patch, go, version, refresh, room, health, files, fileByPath, drawer, openDrawer, closeDrawer, openEntity, focusGraph, openSource,
    chatOpen, setChatOpen, messages, ask, runAction, toast, notify,
  };
  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}
