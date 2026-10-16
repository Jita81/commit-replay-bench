// exmap/src/web/main.tsx — mounts App (design §10.1). The web module adds the window.__exmap test hooks
// (import.meta.env.DEV or ?testhooks=1) and the store/audio wiring.
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App.js";
import "./styles.css";

const root = document.getElementById("root");
if (!root) throw new Error("exmap: #root is missing from index.html");
createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
