import { useState, useRef, useEffect } from "react";
import { Link } from "wouter";
import { motion, AnimatePresence } from "framer-motion";
import { executeMovesStream } from "@/api/client";
import { useMigration } from "@/context/MigrationContext";
import { CheckCircle2, XCircle, SkipForward, FolderPlus, Loader2, StopCircle, ArrowLeft } from "lucide-react";
import { cn } from "@/lib/utils";

export default function Execute() {
  const { approvedMoves } = useMigration();
  
  const [log, setLog] = useState<any[]>([]);
  const [progress, setProgress] = useState(0);
  const [running, setRunning] = useState(false);
  const [summary, setSummary] = useState<any>(null);
  const [autoCreate, setAutoCreate] = useState(true);
  
  const cancelRef = useRef<(() => void) | null>(null);
  const logEndRef = useRef<HTMLDivElement>(null);

  const assignments = Object.values(approvedMoves).map((a) => ({
    file_name: a.file_name,
    proposed_path: a.proposed_path,
    drive_id: a.drive_id,
    item_id: a.item_id,
    drive_item_path: a.drive_item_path,
  }));

  // Auto-scroll log
  useEffect(() => {
    if (logEndRef.current) {
      logEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [log]);

  const start = () => {
    setLog([]);
    setProgress(0);
    setSummary(null);
    setRunning(true);

    const cancel = executeMovesStream(assignments, autoCreate, (event) => {
      if (event.progress !== undefined) {
        setProgress(event.progress);
      }
      
      if (event.phase === "summary") {
        setSummary(event.summary);
        setRunning(false);
        setProgress(1); // ensure 100%
        return;
      }
      
      if (event.phase === "error") {
        setLog((l) => [...l, { status: "error", message: event.message, file_name: null }]);
        setRunning(false);
        return;
      }
      
      setLog((l) => [...l, event]);
    });

    cancelRef.current = cancel;
  };

  const stop = () => {
    cancelRef.current?.();
    setRunning(false);
  };

  const iconFor = (ev: any) => {
    if (ev.phase === "folders" || ev.status === "folder_created") return <FolderPlus className="w-4 h-4 text-amber-500 shrink-0 mt-0.5" />;
    if (ev.status === "success") return <CheckCircle2 className="w-4 h-4 text-green-500 shrink-0 mt-0.5" />;
    if (ev.status === "error") return <XCircle className="w-4 h-4 text-red-500 shrink-0 mt-0.5" />;
    return <SkipForward className="w-4 h-4 text-slate-400 shrink-0 mt-0.5" />;
  };

  if (assignments.length === 0) {
    return (
      <div className="text-center py-20">
        <h2 className="text-xl font-bold text-slate-900">No Approved Moves</h2>
        <p className="text-slate-500 mt-2">Approve some files in the Review tab first.</p>
        <Link href="/review" className="mt-6 inline-flex items-center gap-2 px-6 py-2.5 bg-primary text-white rounded-xl hover:bg-primary-hover font-medium">
          <ArrowLeft className="w-4 h-4" /> Go to Review
        </Link>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
      
      {/* Header Card */}
      <div className="bg-white p-6 rounded-2xl border border-slate-200 shadow-sm">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
          <div>
            <h1 className="text-2xl font-bold text-slate-900">Execute Migration</h1>
            <p className="text-slate-500 text-sm mt-1">
              Live run of {assignments.length} approved moves directly in SharePoint.
            </p>
          </div>

          <div className="flex flex-col sm:flex-row items-center gap-4">
            <label className="flex items-center gap-2 text-sm font-medium text-slate-700 cursor-pointer p-2 rounded-lg hover:bg-slate-50">
              <input
                type="checkbox"
                checked={autoCreate}
                onChange={(e) => setAutoCreate(e.target.checked)}
                disabled={running}
                className="w-4 h-4 rounded text-primary focus:ring-primary border-slate-300 disabled:opacity-50"
              />
              Auto-create missing folders
            </label>

            {!running ? (
              <button
                onClick={start}
                disabled={summary !== null && progress === 1}
                className="w-full sm:w-auto py-2.5 px-6 bg-slate-900 hover:bg-slate-800 text-white rounded-xl font-medium transition-colors shadow-sm disabled:opacity-50 flex items-center justify-center gap-2"
              >
                Execute {assignments.length} Moves
              </button>
            ) : (
              <button
                onClick={stop}
                className="w-full sm:w-auto py-2.5 px-6 bg-red-500 hover:bg-red-600 text-white rounded-xl font-medium transition-colors shadow-sm flex items-center justify-center gap-2"
              >
                <StopCircle className="w-4 h-4" /> Cancel Run
              </button>
            )}
          </div>
        </div>

        {/* Progress Bar */}
        <AnimatePresence>
          {(running || progress > 0) && (
            <motion.div 
              initial={{ height: 0, opacity: 0, marginTop: 0 }}
              animate={{ height: "auto", opacity: 1, marginTop: 24 }}
              className="space-y-2"
            >
              <div className="flex justify-between text-xs font-semibold text-slate-500">
                <span>Migration Progress</span>
                <span>{Math.round(progress * 100)}%</span>
              </div>
              <div className="w-full bg-slate-100 rounded-full h-3 overflow-hidden shadow-inner">
                <div
                  className="bg-gradient-to-r from-blue-500 to-primary h-full rounded-full transition-all duration-300 relative"
                  style={{ width: `${Math.max(2, progress * 100)}%` }}
                >
                  {running && (
                    <div className="absolute inset-0 bg-white/20 animate-pulse" />
                  )}
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Results Summary */}
      {summary && (
        <motion.div 
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="grid grid-cols-2 md:grid-cols-4 gap-4"
        >
          {[
            { label: "Succeeded", value: summary.successes, color: "text-green-600", bg: "bg-green-50", border: "border-green-100" },
            { label: "Failed", value: summary.failures, color: "text-red-600", bg: "bg-red-50", border: "border-red-100" },
            { label: "Skipped", value: summary.skips, color: "text-slate-600", bg: "bg-slate-50", border: "border-slate-200" },
            { label: "Folders Created", value: summary.folders_created, color: "text-amber-600", bg: "bg-amber-50", border: "border-amber-100" },
          ].map((stat, i) => (
            <div key={i} className={cn("p-5 rounded-2xl border text-center", stat.bg, stat.border)}>
              <div className={cn("text-3xl font-display font-bold", stat.color)}>
                {stat.value}
              </div>
              <div className="text-sm font-medium text-slate-600 mt-1">{stat.label}</div>
            </div>
          ))}
        </motion.div>
      )}

      {/* Live Log Terminal */}
      <div className="bg-[#0F172A] rounded-2xl border border-slate-800 shadow-xl overflow-hidden flex flex-col h-[500px]">
        <div className="px-4 py-3 border-b border-slate-800 bg-[#1E293B] flex items-center gap-3">
          <div className="flex gap-1.5">
            <div className="w-3 h-3 rounded-full bg-red-500/80" />
            <div className="w-3 h-3 rounded-full bg-amber-500/80" />
            <div className="w-3 h-3 rounded-full bg-green-500/80" />
          </div>
          <span className="text-slate-400 text-xs font-mono font-medium ml-2">migration_runner.log</span>
          {running && <Loader2 className="w-4 h-4 text-primary animate-spin ml-auto" />}
        </div>
        
        <div className="p-4 flex-1 overflow-y-auto font-mono text-sm space-y-1.5 scroll-smooth">
          {log.length === 0 && !running && !summary && (
            <div className="text-slate-600 italic">Waiting to begin execution...</div>
          )}
          
          {log.map((ev, i) => (
            <motion.div 
              initial={{ opacity: 0, x: -5 }}
              animate={{ opacity: 1, x: 0 }}
              key={i} 
              className="flex items-start gap-3 hover:bg-white/5 p-1 -mx-1 rounded"
            >
              {iconFor(ev)}
              <span className="text-slate-300 break-all leading-snug">
                {ev.file_name && <span className="text-blue-300 font-semibold">{ev.file_name}: </span>}
                <span className={cn(ev.status === "error" && "text-red-400", ev.status === "success" && "text-slate-300")}>
                  {ev.message}
                </span>
              </span>
            </motion.div>
          ))}
          <div ref={logEndRef} className="h-4" />
        </div>
      </div>
    </div>
  );
}
