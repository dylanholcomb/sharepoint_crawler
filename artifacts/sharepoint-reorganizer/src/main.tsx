import { createRoot } from "react-dom/client";
import { msalInstance } from "./lib/msalConfig";
import App from "./App";
import "./index.css";

msalInstance.initialize().then(() => {
  msalInstance.addEventCallback((event: any) => {
    console.log("[MSAL]", event.eventType, event.interactionType ?? "", event.error ?? "");
  });

  createRoot(document.getElementById("root")!).render(
    <App msalInstance={msalInstance} />
  );
});
