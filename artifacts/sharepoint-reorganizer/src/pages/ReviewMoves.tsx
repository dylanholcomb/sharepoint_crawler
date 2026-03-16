import { useState, useMemo } from "react";
import { Link, useLocation } from "wouter";
import { motion } from "framer-motion";
import { useMigration } from "@/context/MigrationContext";
import { Check, X, Pencil, ChevronRight, ChevronDown, CheckCircle2, ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";

export default function ReviewMoves() {
  const [, setLocation] = useLocation();
  const { proposal, activePlan, approvedMoves, setApprovedMoves } = useMigration();

  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({});

  if (!proposal) {
    return (
      <div className="text-center py-20">
        <h2 className="text-xl font-bold text-slate-900">No Proposal Loaded</h2>
        <Link href="/" className="mt-4 inline-block text-primary hover:underline">Go back to Upload</Link>
      </div>
    );
  }

  const assignments = proposal[activePlan].assignments;

  // Group by first part of proposed path
  const grouped = useMemo(() => {
    const groups: Record<string, typeof assignments> = {};
    assignments.forEach((a) => {
      const parts = a.proposed_path.split("/");
      const root = parts.length > 1 ? parts[0] : "Root";
      if (!groups[root]) groups[root] = [];
      groups[root].push(a);
    });
    return groups;
  }, [assignments]);

  const toggleGroup = (group: string) => {
    setExpandedGroups(prev => ({ ...prev, [group]: !prev[group] }));
  };

  const approve = (fileName: string, proposedPath: string) => {
    setApprovedMoves(prev => ({ ...prev, [fileName]: proposedPath }));
  };

  const reject = (fileName: string) => {
    setApprovedMoves(prev => {
      const next = { ...prev };
      delete next[fileName];
      return next;
    });
  };

  const isApproved = (fileName: string) => fileName in approvedMoves;
  
  const approvedCount = Object.keys(approvedMoves).length;
  const pendingCount = assignments.length - approvedCount;

  return (
    <div className="space-y-6 max-w-5xl mx-auto pb-24 animate-in fade-in slide-in-from-bottom-4 duration-500">
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4 bg-white p-6 rounded-2xl border border-slate-200 shadow-sm sticky top-20 z-40">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Review Moves</h1>
          <p className="text-slate-500 text-sm mt-1">
            Approve, reject, or edit individual file destinations.
          </p>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex gap-4 text-sm font-medium">
            <div className="flex items-center gap-1.5 text-green-600 bg-green-50 px-3 py-1 rounded-lg">
              <CheckCircle2 className="w-4 h-4" /> {approvedCount} Approved
            </div>
            <div className="flex items-center gap-1.5 text-slate-500 bg-slate-100 px-3 py-1 rounded-lg">
              {pendingCount} Pending
            </div>
          </div>
          <button
            onClick={() => setLocation("/execute")}
            disabled={approvedCount === 0}
            className="py-2.5 px-5 bg-slate-900 hover:bg-slate-800 text-white rounded-xl font-medium transition-colors shadow-sm disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            Execute {approvedCount} Moves <ArrowRight className="w-4 h-4" />
          </button>
        </div>
      </div>

      <div className="space-y-4">
        {Object.entries(grouped).map(([groupName, items]) => {
          const isOpen = expandedGroups[groupName] !== false; // open by default
          const groupApproved = items.filter(i => isApproved(i.file_name)).length;

          return (
            <div key={groupName} className="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden">
              <button
                onClick={() => toggleGroup(groupName)}
                className="w-full flex items-center justify-between p-4 bg-slate-50/50 hover:bg-slate-50 transition-colors border-b border-slate-100"
              >
                <div className="flex items-center gap-3">
                  {isOpen ? <ChevronDown className="w-5 h-5 text-slate-400" /> : <ChevronRight className="w-5 h-5 text-slate-400" />}
                  <span className="font-semibold text-slate-900">{groupName}</span>
                  <span className="text-xs font-medium text-slate-500 bg-slate-200 px-2 py-0.5 rounded-full">
                    {items.length} files
                  </span>
                </div>
                <div className="text-xs font-medium text-green-600 bg-green-50 px-2 py-1 rounded-md border border-green-100">
                  {groupApproved} / {items.length} Approved
                </div>
              </button>
              
              {isOpen && (
                <div className="p-4 space-y-3">
                  {items.map((item) => (
                    <MoveRow 
                      key={item.file_name} 
                      assignment={item} 
                      status={isApproved(item.file_name) ? "approved" : "pending"}
                      approvedPath={approvedMoves[item.file_name] || item.proposed_path}
                      onApprove={(path) => approve(item.file_name, path)}
                      onReject={() => reject(item.file_name)}
                    />
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function MoveRow({ 
  assignment, 
  status, 
  approvedPath,
  onApprove, 
  onReject 
}: { 
  assignment: any, 
  status: "approved" | "pending", 
  approvedPath: string,
  onApprove: (path: string) => void, 
  onReject: () => void 
}) {
  const [editing, setEditing] = useState(false);
  const [draftPath, setDraftPath] = useState(approvedPath);

  const handleSaveEdit = () => {
    onApprove(draftPath);
    setEditing(false);
  };

  return (
    <div className={cn(
      "flex items-start gap-4 p-4 rounded-xl border transition-all duration-200",
      status === "approved" 
        ? "bg-green-50/30 border-green-200 shadow-sm" 
        : "bg-white border-slate-200 hover:border-slate-300"
    )}>
      {/* Actions */}
      <div className="flex flex-col gap-1.5 shrink-0 mt-0.5">
        <button
          onClick={() => onApprove(draftPath)}
          className={cn(
            "p-1.5 rounded-md transition-colors",
            status === "approved" 
              ? "bg-green-500 text-white shadow-sm" 
              : "bg-slate-100 text-slate-400 hover:bg-green-100 hover:text-green-600"
          )}
        >
          <Check className="w-4 h-4" />
        </button>
        <button
          onClick={onReject}
          className={cn(
            "p-1.5 rounded-md transition-colors",
            status === "pending" 
              ? "bg-red-50 text-red-500 hover:bg-red-100" 
              : "bg-slate-100 text-slate-400 hover:bg-red-100 hover:text-red-600"
          )}
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="font-semibold text-slate-900 text-sm truncate mb-1.5">
          {assignment.file_name}
        </div>
        
        <div className="flex flex-col sm:flex-row sm:items-center gap-1.5 sm:gap-3 text-xs font-mono">
          <div className="text-slate-400 truncate max-w-full sm:max-w-[40%]" title={assignment.current_path}>
            {assignment.current_path}
          </div>
          <ChevronRight className="w-3.5 h-3.5 text-slate-300 shrink-0 hidden sm:block" />
          
          {editing ? (
            <input
              autoFocus
              value={draftPath}
              onChange={(e) => setDraftPath(e.target.value)}
              onBlur={handleSaveEdit}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleSaveEdit();
                if (e.key === "Escape") {
                  setDraftPath(approvedPath);
                  setEditing(false);
                }
              }}
              className="flex-1 min-w-0 border-b-2 border-primary bg-transparent focus:outline-none text-primary pb-0.5"
            />
          ) : (
            <button
              onClick={() => setEditing(true)}
              className={cn(
                "truncate flex items-center gap-1.5 transition-colors group text-left",
                status === "approved" ? "text-green-700 font-medium" : "text-primary hover:text-primary-hover"
              )}
              title={approvedPath}
            >
              {approvedPath}
              <Pencil className="w-3 h-3 opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
            </button>
          )}
        </div>
        
        {assignment.reason && (
          <div className="mt-2 text-xs text-slate-500 italic flex items-center gap-1.5 border-l-2 border-slate-200 pl-2">
            Reason: {assignment.reason}
          </div>
        )}
      </div>
    </div>
  );
}
