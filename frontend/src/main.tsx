import { StrictMode, useEffect } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { AppProvider, useApp } from "./store";
import "./styles.css";

window.addEventListener("error", (event) => {
  document.body.dataset.error = `${document.body.dataset.error ?? ""}${event.message}; `;
});

/** Marks the page ready once room data has loaded (used by headless smoke tests). */
function Ready() {
  const { room, files, projects } = useApp();
  useEffect(() => {
    if ((room && files.length) || projects) document.body.dataset.ready = "true";
  }, [room, files, projects]);
  return null;
}

createRoot(document.getElementById("root") as HTMLElement).render(
  <StrictMode>
    <AppProvider>
      <App />
      <Ready />
    </AppProvider>
  </StrictMode>,
);
