import { useState } from "react";
import { useLocation } from "wouter";
import { motion } from "framer-motion";
import { UploadCloud, CheckCircle, XCircle, ArrowRight, ShieldCheck, Database, Loader2 } from "lucide-react";
import { testConnection, runOrganize } from "@/api/client";
import { useMigration } from "@/context/MigrationContext";
import { cn } from "@/lib/utils";

export default function Home() {
  const [, setLocation] = useLocation();
  const { setProposal } = useMigration();
  
  const [connStatus, setConnStatus] = useState<"idle" | "testing" | "success" | "error">("idle");
  const [connMessage, setConnMessage] = useState("");
  
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");

  const handleTestConnection = async () => {
    setConnStatus("testing");
    const res = await testConnection();
    if (res.success) {
      setConnStatus("success");
      setConnMessage(res.message);
    } else {
      setConnStatus("error");
      setConnMessage(res.message);
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setIsUploading(true);
    setUploadError("");

    try {
      if (file.name.endsWith(".json")) {
        // Local parse for manual JSON overrides
        const text = await file.text();
        const data = JSON.parse(text);
        setProposal(data);
        setLocation("/overview");
      } else if (file.name.endsWith(".csv")) {
        // Run full organize pipeline on backend
        const data = await runOrganize(file);
        setProposal(data);
        setLocation("/overview");
      } else {
        throw new Error("Please upload a .csv or .json file");
      }
    } catch (err: any) {
      setUploadError(err.message || "Failed to process file");
    } finally {
      setIsUploading(false);
      if (e.target) e.target.value = ""; // Reset input
    }
  };

  return (
    <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
      {/* Hero Section */}
      <div className="relative overflow-hidden rounded-3xl bg-white border border-slate-200 shadow-sm">
        <div className="absolute inset-0 w-full h-full">
          <img 
            src={`${import.meta.env.BASE_URL}images/hero-bg.png`} 
            alt="Hero background" 
            className="w-full h-full object-cover opacity-20"
          />
          <div className="absolute inset-0 bg-gradient-to-r from-white via-white/90 to-transparent" />
        </div>
        
        <div className="relative p-8 md:p-12 lg:p-16 max-w-3xl">
          <h1 className="text-4xl md:text-5xl font-display font-bold text-slate-900 leading-tight">
            Intelligently Reorganize <br className="hidden md:block"/>
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-primary to-blue-400">
              SharePoint Storage
            </span>
          </h1>
          <p className="mt-4 text-lg text-slate-600 max-w-xl">
            Upload your directory snapshot and let AI propose a clean, structured hierarchy. Review moves safely before executing them directly in SharePoint.
          </p>
        </div>
      </div>

      <div className="grid md:grid-cols-2 gap-6">
        {/* Connection Card */}
        <motion.div 
          whileHover={{ y: -4 }}
          className="bg-white rounded-2xl p-8 border border-slate-200 shadow-sm card-hover flex flex-col"
        >
          <div className="w-12 h-12 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center mb-6">
            <Database className="w-6 h-6" />
          </div>
          <h2 className="text-xl font-bold text-slate-900">Step 1: Connection</h2>
          <p className="mt-2 text-slate-500 flex-1">
            Ensure your API credentials and backend are properly configured to securely access SharePoint data.
          </p>
          
          <div className="mt-8 space-y-4">
            <button
              onClick={handleTestConnection}
              disabled={connStatus === "testing"}
              className="w-full py-3 px-4 bg-slate-900 hover:bg-slate-800 text-white rounded-xl font-medium transition-colors shadow-sm disabled:opacity-70 flex items-center justify-center gap-2"
            >
              {connStatus === "testing" ? (
                <><Loader2 className="w-5 h-5 animate-spin" /> Testing Connection...</>
              ) : (
                <><ShieldCheck className="w-5 h-5" /> Test SharePoint Connection</>
              )}
            </button>

            {connStatus !== "idle" && (
              <div className={cn(
                "p-4 rounded-xl text-sm flex items-start gap-3",
                connStatus === "success" ? "bg-green-50 text-green-800 border border-green-200" : "bg-red-50 text-red-800 border border-red-200"
              )}>
                {connStatus === "success" ? <CheckCircle className="w-5 h-5 mt-0.5" /> : <XCircle className="w-5 h-5 mt-0.5" />}
                <div className="flex-1 font-medium">{connMessage}</div>
              </div>
            )}
          </div>
        </motion.div>

        {/* Upload Card */}
        <motion.div 
          whileHover={{ y: -4 }}
          className="bg-white rounded-2xl p-8 border border-slate-200 shadow-sm card-hover flex flex-col"
        >
          <div className="w-12 h-12 rounded-xl bg-indigo-50 text-indigo-600 flex items-center justify-center mb-6">
            <UploadCloud className="w-6 h-6" />
          </div>
          <h2 className="text-xl font-bold text-slate-900">Step 2: Generate Proposal</h2>
          <p className="mt-2 text-slate-500 flex-1">
            Upload your CSV directory dump to generate an AI organization proposal, or load an existing JSON proposal.
          </p>

          <div className="mt-8 space-y-4">
            <label className={cn(
              "relative w-full py-8 px-6 border-2 border-dashed rounded-xl flex flex-col items-center justify-center text-center cursor-pointer transition-colors group",
              isUploading ? "border-indigo-300 bg-indigo-50/50" : "border-slate-300 hover:border-indigo-400 hover:bg-indigo-50/30"
            )}>
              <input
                type="file"
                accept=".csv,.json"
                onChange={handleFileUpload}
                disabled={isUploading}
                className="hidden"
              />
              {isUploading ? (
                <div className="flex flex-col items-center text-indigo-600">
                  <Loader2 className="w-8 h-8 animate-spin mb-3" />
                  <span className="font-semibold">Processing Data...</span>
                  <span className="text-sm mt-1 opacity-80">This may take a minute</span>
                </div>
              ) : (
                <>
                  <div className="w-12 h-12 rounded-full bg-slate-100 flex items-center justify-center mb-3 group-hover:bg-indigo-100 transition-colors">
                    <ArrowRight className="w-6 h-6 text-slate-400 group-hover:text-indigo-600 -rotate-45" />
                  </div>
                  <span className="font-semibold text-slate-900">Click to upload files</span>
                  <span className="text-sm text-slate-500 mt-1">Supports .csv dumps or existing .json proposals</span>
                </>
              )}
            </label>

            {uploadError && (
              <div className="p-4 bg-red-50 text-red-800 rounded-xl border border-red-200 text-sm font-medium flex items-start gap-3">
                <XCircle className="w-5 h-5 mt-0.5" />
                {uploadError}
              </div>
            )}
          </div>
        </motion.div>
      </div>
    </div>
  );
}
