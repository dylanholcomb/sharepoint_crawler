import { useEffect } from "react";
import { msalInstance } from "../lib/msalConfig";

export default function AuthRedirect() {
  useEffect(() => {
    msalInstance
      .initialize()
      .then(() => msalInstance.handleRedirectPromise())
      .then((result) => {
        if (result) {
          console.log("Auth redirect handled:", result.account?.username);
        }
      })
      .catch((error) => {
        console.error("Auth redirect error:", error);
      });
  }, []);

  return (
    <div style={{
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      height: "100vh",
      fontFamily: "sans-serif",
      backgroundColor: "#f8fafc",
    }}>
      <div style={{ textAlign: "center" }}>
        <div style={{
          width: 28,
          height: 28,
          border: "3px solid #0078d4",
          borderTopColor: "transparent",
          borderRadius: "50%",
          margin: "0 auto 12px",
          animation: "spin 0.8s linear infinite",
        }} />
        <p style={{ margin: 0, fontSize: 14, color: "#64748b" }}>Completing sign in...</p>
      </div>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
