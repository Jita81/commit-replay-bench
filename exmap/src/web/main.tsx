// exmap/src/web/main.tsx — mounts App (design §10.1). The window.__exmap test hooks are installed by the session screen
// when import.meta.env.DEV or ?testhooks=1 (design §7.7, §10.9); production pages without the flag expose nothing.
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App.js";
import { testHooksEnabled } from "./testHooks.js";
import "./styles.css";

const root = document.getElementById("root");
if (!root) throw new Error("exmap: #root is missing from index.html");
createRoot(root).render(
  <StrictMode>
    <App testHooks={testHooksEnabled()} />
  </StrictMode>,
);
