import { useState } from "react";
import { useLocation } from "wouter";
import { motion } from "framer-motion";
import {
  UploadCloud, CheckCircle, XCircle, ArrowRight,
  Loader2, LogIn, User, Globe, ChevronRight, Sparkles
} from "lucide-react";
import { useMsal } from "@azure/msal-react";
import { loginRequest } from "@/lib/msalConfig";
import { testConnection, runOrganize, analyzeStream } from "@/api/client";
import type { AnalyzeEvent } from "@/api/client";
import { useMigration } from "@/context/MigrationContext";
import type { MsalUser } from "@/context/MigrationContext";
import { cn } from "@/lib/utils";

type StepStatus = "idle" | "loading" | "done" | "error";

export default function Home() {
  const [, setLocation] = useLocation();
  const { instance, accounts } = useMsal();
  const {
    setProposal,
    accessToken, setAccessToken,
    msalUser, setMsalUser,
    siteUrl, setSiteUrl,
  } = useMigration();

  const [signInStatus, setSignInStatus] = useState<StepStatus>(
    accounts.length > 0 ? "done" : "idle"
  );
  const [connStatus, setConnStatus] = useState<StepStatus>("idle");
  const [connMessage, setConnMessage] = useState("");
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState("");
  const [analyzeLog, setAnalyzeLog] = useState<string[]>([]);
  const [analyzeProgress, setAnalyzeProgress] = useState<number | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [showUpload, setShowUpload] = useState(false);

  const isSignedIn = accounts.length > 0 || signInStatus === "done";
  const isConnected = connStatus === "done";

  const handleSignIn = async () => {
    setSignInStatus("loading");
    try {
      const result = await instance.loginPopup(loginRequest);
      const user: MsalUser = {
        name: result.account.name || result.account.username,
        email: result.account.username,
        tenantId: result.account.tenantId,
      };
      setMsalUser(user);
      setAccessToken(result.accessToken);
      setSignInStatus("done");
    } catch (err: any) {
      if (err.errorCode !== "user_cancelled") {
        setSignInStatus("error");
      } else {
        setSignInStatus("idle");
      }
    }
  };

  const handleSignOut = () => {
    instance.logoutPopup();
    setAccessToken(null);
    setMsalUser(null);
    setSignInStatus("idle");
    setConnStatus("idle");
  };

  const handleTestConnection = async () => {
    setConnStatus("loading");
    const auth = accessToken ? { token: accessToken, siteUrl } : undefined;
    const res = await testConnection(auth);
    if (res.success) {
      setConnStatus("done");
      setConnMessage(res.message);
    } else {
      setConnStatus("error");
      setConnMessage(res.message);
    }
  };

  const handleAnalyze = () => {
    setIsAnalyzing(true);
    setAnalyzeError("");
    setAnalyzeLog([]);
    setAnalyzeProgress(null);
    const auth = accessToken ? { token: accessToken, siteUrl } : undefined;

    analyzeStream((event: AnalyzeEvent) => {
      if (event.message) {
        setAnalyzeLog((prev) => [...prev, event.message]);
      }
      if (event.progress != null) {
        setAnalyzeProgress(event.progress);
      }
      if (event.phase === "complete" && event.proposal) {
        setProposal(event.proposal);
        setIsAnalyzing(false);
        setLocation("/overview");
      }
      if (event.phase === "error") {
        setAnalyzeError(event.message || "Analysis failed.");
        setIsAnalyzing(false);
      }
    }, auth);
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setIsUploading(true);
    setUploadError("");
    try {
      const auth = accessToken ? { token: accessToken, siteUrl } : undefined;
      if (file.name.endsWith(".json")) {
        const text = await file.text();
        setProposal(JSON.parse(text));
        setLocation("/overview");
      } else if (file.name.endsWith(".csv")) {
        const data = await runOrganize(file, auth);
        setProposal(data);
        setLocation("/overview");
      } else {
        throw new Error("Please upload a .csv or .json file");
      }
    } catch (err: any) {
      setUploadError(err.message || "Failed to process file");
    } finally {
      setIsUploading(false);
      if (e.target) e.target.value = "";
    }
  };

  const steps = [
    {
      number: 1,
      label: "Sign In",
      done: isSignedIn,
      active: !isSignedIn,
    },
    {
      number: 2,
      label: "Connect to SharePoint",
      done: isConnected,
      active: isSignedIn && !isConnected,
    },
    {
      number: 3,
      label: "Upload & Propose",
      done: false,
      active: isConnected,
    },
  ];

  const displayUser = msalUser || (accounts[0]
    ? { name: accounts[0].name || accounts[0].username, email: accounts[0].username, tenantId: accounts[0].tenantId }
    : null);

  return (
    <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
      {/* Hero */}
      <div className="relative overflow-hidden rounded-3xl bg-white border border-slate-200 shadow-sm">
        <div className="absolute inset-0 w-full h-full">
          <img
            src={`${import.meta.env.BASE_URL}images/hero-bg.png`}
            alt=""
            className="w-full h-full object-cover opacity-20"
          />
          <div className="absolute inset-0 bg-gradient-to-r from-white via-white/90 to-transparent" />
        </div>
        <div className="relative p-8 md:p-12 lg:p-16 max-w-3xl">
          <h1 className="text-4xl md:text-5xl font-display font-bold text-slate-900 leading-tight">
            Intelligently Reorganize <br className="hidden md:block" />
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-primary to-blue-400">
              SharePoint Storage
            </span>
          </h1>
          <p className="mt-4 text-lg text-slate-600 max-w-xl">
            Sign in with your Microsoft account, connect to any SharePoint site, receive a clean folder structure proposal— then execute it safely.
          </p>
        </div>
      </div>

      {/* Step progress strip */}
      <div className="flex items-center gap-2 px-1">
        {steps.map((step, i) => (
          <div key={step.number} className="flex items-center gap-2 flex-1">
            <div className={cn(
              "flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium flex-1 transition-all",
              step.done
                ? "bg-green-50 text-green-700 border border-green-200"
                : step.active
                  ? "bg-blue-50 text-blue-700 border border-blue-200"
                  : "bg-slate-50 text-slate-400 border border-slate-200"
            )}>
              <div className={cn(
                "w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0",
                step.done ? "bg-green-500 text-white" : step.active ? "bg-blue-500 text-white" : "bg-slate-300 text-slate-500"
              )}>
                {step.done ? <CheckCircle className="w-3.5 h-3.5" /> : step.number}
              </div>
              <span className="truncate">{step.label}</span>
            </div>
            {i < steps.length - 1 && (
              <ChevronRight className="w-4 h-4 text-slate-300 flex-shrink-0" />
            )}
          </div>
        ))}
      </div>

      {/* Step 1 — Sign In */}
      <motion.div
        whileHover={{ y: -2 }}
        className={cn(
          "bg-white rounded-2xl p-8 border shadow-sm",
          isSignedIn ? "border-green-200 bg-green-50/30" : "border-slate-200"
        )}
      >
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-4 flex-1">
            <div className={cn(
              "w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0",
              isSignedIn ? "bg-green-100 text-green-600" : "bg-blue-50 text-blue-600"
            )}>
              {isSignedIn ? <CheckCircle className="w-5 h-5" /> : <LogIn className="w-5 h-5" />}
            </div>
            <div className="flex-1">
              <h2 className="text-lg font-bold text-slate-900">Step 1: Sign In with Microsoft</h2>
              {isSignedIn && displayUser ? (
                <div className="mt-3 flex items-center gap-3">
                  <div className="w-9 h-9 rounded-full bg-gradient-to-br from-primary to-blue-400 flex items-center justify-center text-white font-bold text-sm">
                    {displayUser.name.charAt(0).toUpperCase()}
                  </div>
                  <div>
                    <div className="font-semibold text-slate-900 text-sm">{displayUser.name}</div>
                    <div className="text-xs text-slate-500">{displayUser.email}</div>
                  </div>
                </div>
              ) : (
                <p className="mt-1 text-slate-500 text-sm">
                  Sign in with your Microsoft 365 account to access your SharePoint.
                </p>
              )}
            </div>
          </div>
          {!isSignedIn ? (
            <button
              onClick={handleSignIn}
              disabled={signInStatus === "loading"}
              className="flex-shrink-0 flex items-center gap-2 px-5 py-2.5 bg-[#0078d4] hover:bg-[#106ebe] text-white rounded-xl text-sm font-semibold transition-colors shadow-sm disabled:opacity-70"
            >
              {signInStatus === "loading"
                ? <><Loader2 className="w-4 h-4 animate-spin" /> Signing in...</>
                : <><User className="w-4 h-4" /> Sign in with Microsoft</>
              }
            </button>
          ) : (
            <button
              onClick={handleSignOut}
              className="flex-shrink-0 text-sm text-slate-400 hover:text-slate-600 underline"
            >
              Sign out
            </button>
          )}
        </div>
      </motion.div>

      {/* Step 2 — Connect */}
      <motion.div
        whileHover={isSignedIn ? { y: -2 } : {}}
        className={cn(
          "bg-white rounded-2xl p-8 border shadow-sm transition-opacity",
          !isSignedIn && "opacity-40 pointer-events-none",
          isConnected ? "border-green-200 bg-green-50/30" : "border-slate-200"
        )}
      >
        <div className="flex items-start gap-4">
          <div className={cn(
            "w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0",
            isConnected ? "bg-green-100 text-green-600" : "bg-indigo-50 text-indigo-600"
          )}>
            {isConnected ? <CheckCircle className="w-5 h-5" /> : <Globe className="w-5 h-5" />}
          </div>
          <div className="flex-1">
            <h2 className="text-lg font-bold text-slate-900">Step 2: Connect to SharePoint</h2>
            <p className="mt-1 text-slate-500 text-sm">
              Enter the URL of the SharePoint site you want to reorganize.
            </p>
            <div className="mt-4 space-y-3">
              <div className="flex gap-2">
                <input
                  type="url"
                  value={siteUrl}
                  onChange={(e) => setSiteUrl(e.target.value)}
                  placeholder="https://yourorg.sharepoint.com/sites/YourSite"
                  className="flex-1 px-4 py-2.5 border border-slate-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary transition-all"
                />
                <button
                  onClick={handleTestConnection}
                  disabled={connStatus === "loading" || !siteUrl}
                  className="flex-shrink-0 flex items-center gap-2 px-5 py-2.5 bg-slate-900 hover:bg-slate-800 text-white rounded-xl text-sm font-semibold transition-colors shadow-sm disabled:opacity-50"
                >
                  {connStatus === "loading"
                    ? <><Loader2 className="w-4 h-4 animate-spin" /> Testing...</>
                    : "Test Connection"
                  }
                </button>
              </div>
              {connStatus !== "idle" && connStatus !== "loading" && (
                <div className={cn(
                  "p-3 rounded-xl text-sm flex items-center gap-2 border",
                  connStatus === "done"
                    ? "bg-green-50 text-green-800 border-green-200"
                    : "bg-red-50 text-red-800 border-red-200"
                )}>
                  {connStatus === "done"
                    ? <CheckCircle className="w-4 h-4 flex-shrink-0" />
                    : <XCircle className="w-4 h-4 flex-shrink-0" />
                  }
                  {connMessage}
                </div>
              )}
            </div>
          </div>
        </div>
      </motion.div>

      {/* Step 3 — Generate */}
      <motion.div
        whileHover={isConnected ? { y: -2 } : {}}
        className={cn(
          "bg-white rounded-2xl p-8 border shadow-sm transition-opacity",
          !isConnected && "opacity-40 pointer-events-none",
          "border-slate-200"
        )}
      >
        <div className="flex items-start gap-4">
          <div className="w-10 h-10 rounded-xl bg-violet-50 text-violet-600 flex items-center justify-center flex-shrink-0">
            <Sparkles className="w-5 h-5" />
          </div>
          <div className="flex-1">
            <h2 className="text-lg font-bold text-slate-900">Step 3: Generate Reorganization Proposal</h2>
            <p className="mt-1 text-slate-500 text-sm">
              Let AI scan your SharePoint files and propose a clean folder structure — no manual steps needed.
            </p>

            {/* Primary action */}
            <div className="mt-5 space-y-3">
              <button
                onClick={handleAnalyze}
                disabled={isAnalyzing || isUploading}
                className="w-full flex items-center justify-center gap-3 px-6 py-4 bg-gradient-to-r from-violet-600 to-blue-600 hover:from-violet-700 hover:to-blue-700 text-white rounded-xl font-semibold text-base transition-all shadow-md hover:shadow-lg disabled:opacity-60 disabled:cursor-not-allowed"
              >
                {isAnalyzing ? (
                  <>
                    <Loader2 className="w-5 h-5 animate-spin" />
                    Running analysis…
                  </>
                ) : (
                  <>
                    <Sparkles className="w-5 h-5" />
                    Analyze & Generate Proposal
                  </>
                )}
              </button>

              {/* Live progress log */}
              {isAnalyzing && analyzeLog.length > 0 && (
                <div className="rounded-xl border border-violet-200 bg-violet-50/60 p-4 space-y-1.5">
                  {analyzeProgress != null && (
                    <div className="mb-2">
                      <div className="flex justify-between text-xs text-violet-700 mb-1">
                        <span>Progress</span>
                        <span>{Math.round(analyzeProgress)}%</span>
                      </div>
                      <div className="h-1.5 bg-violet-200 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-violet-500 rounded-full transition-all duration-300"
                          style={{ width: `${analyzeProgress}%` }}
                        />
                      </div>
                    </div>
                  )}
                  {analyzeLog.map((msg, i) => (
                    <div key={i} className={cn(
                      "text-xs flex items-start gap-2",
                      i === analyzeLog.length - 1 ? "text-violet-800 font-medium" : "text-violet-500"
                    )}>
                      <span className="mt-0.5 flex-shrink-0">
                        {i === analyzeLog.length - 1
                          ? <Loader2 className="w-3 h-3 animate-spin" />
                          : <CheckCircle className="w-3 h-3" />
                        }
                      </span>
                      {msg}
                    </div>
                  ))}
                </div>
              )}

              {analyzeError && (
                <div className="p-3 bg-red-50 text-red-800 rounded-xl border border-red-200 text-sm flex items-center gap-2">
                  <XCircle className="w-4 h-4 flex-shrink-0" />
                  {analyzeError}
                </div>
              )}
            </div>

            {/* Divider */}
            <div className="mt-6 flex items-center gap-3">
              <div className="flex-1 h-px bg-slate-200" />
              <span className="text-xs text-slate-400 font-medium">or use a previous run</span>
              <div className="flex-1 h-px bg-slate-200" />
            </div>

            {/* Secondary — file upload (two clear options) */}
            <div className="mt-4">
              {!showUpload ? (
                <button
                  onClick={() => setShowUpload(true)}
                  className="w-full py-2.5 px-4 border border-slate-200 rounded-xl text-sm text-slate-500 hover:text-slate-700 hover:border-slate-300 transition-colors flex items-center justify-center gap-2"
                >
                  <UploadCloud className="w-4 h-4" />
                  Load from file
                </button>
              ) : (
                <div className="space-y-3">
                  {/* Option descriptions */}
                  <div className="grid grid-cols-2 gap-3 text-xs text-slate-500">
                    <div className="p-3 bg-slate-50 rounded-lg border border-slate-200">
                      <div className="font-semibold text-slate-700 mb-0.5">documents.csv</div>
                      Re-run the organizer on a previous file crawl. Skips re-scanning SharePoint.
                    </div>
                    <div className="p-3 bg-slate-50 rounded-lg border border-slate-200">
                      <div className="font-semibold text-slate-700 mb-0.5">proposal.json</div>
                      Load a completed proposal directly — skips all analysis steps.
                    </div>
                  </div>
                  <label className={cn(
                    "relative w-full py-6 px-6 border-2 border-dashed rounded-xl flex flex-col items-center justify-center text-center cursor-pointer transition-colors group",
                    isUploading
                      ? "border-violet-300 bg-violet-50/50"
                      : "border-slate-300 hover:border-violet-400 hover:bg-violet-50/30"
                  )}>
                    <input
                      type="file"
                      accept=".csv,.json"
                      onChange={handleFileUpload}
                      disabled={isUploading}
                      className="hidden"
                    />
                    {isUploading ? (
                      <div className="flex flex-col items-center text-violet-600">
                        <Loader2 className="w-7 h-7 animate-spin mb-2" />
                        <span className="font-semibold text-sm">Processing…</span>
                      </div>
                    ) : (
                      <>
                        <UploadCloud className="w-6 h-6 text-slate-400 group-hover:text-violet-500 mb-2" />
                        <span className="font-medium text-slate-700 text-sm">Click to upload</span>
                        <span className="text-xs text-slate-400 mt-0.5">documents.csv or proposal.json</span>
                      </>
                    )}
                  </label>
                  {uploadError && (
                    <div className="p-3 bg-red-50 text-red-800 rounded-xl border border-red-200 text-sm flex items-center gap-2">
                      <XCircle className="w-4 h-4 flex-shrink-0" />
                      {uploadError}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      </motion.div>
    </div>
  );
}
