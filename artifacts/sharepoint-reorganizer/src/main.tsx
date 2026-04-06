import { createRoot } from "react-dom/client";
import { msalInstance } from "./lib/msalConfig";
import App from "./App";
import "./index.css";

msalInstance.initialize().then(() => {
  createRoot(document.getElementById("root")!).render(
    <App msalInstance={msalInstance} />
  );
});
