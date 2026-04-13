import { useEffect } from "react";
import { useLocation } from "wouter";
import { useMsal } from "@azure/msal-react";

export default function AuthRedirect() {
  const { instance } = useMsal();
  const [, navigate] = useLocation();

  useEffect(() => {
    instance
      .handleRedirectPromise()
      .then((result) => {
        if (result?.account) {
          instance.setActiveAccount(result.account);
        }
      })
      .catch((err) => {
        console.error("MSAL redirect error:", err);
      })
      .finally(() => {
        if (window.opener) {
          window.close();
        } else {
          navigate("/", { replace: true });
        }
      });
  }, [instance, navigate]);

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
