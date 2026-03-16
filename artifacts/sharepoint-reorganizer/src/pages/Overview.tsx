import { useState } from "react";
import { Link } from "wouter";
import { motion, AnimatePresence } from "framer-motion";
import { useMigration } from "@/context/MigrationContext";
import { ChevronRight, ChevronDown, Folder, File, ArrowRight, LayoutList, Layers } from "lucide-react";
import { cn } from "@/lib/utils";

// Recursive Folder Tree Component
const FolderNode = ({ name, content, level = 0 }: { name: string, content: any, level?: number }) => {
  const [isOpen, setIsOpen] = useState(level < 1);
  const isObject = typeof content === "object" && content !== null;
  const isArray = Array.isArray(content);

  if (!isObject) return null;

  const entries = Object.entries(content);
  if (entries.length === 0 && !isArray) return null;

  return (
    <div className="font-mono text-sm">
      <div 
        className={cn(
          "flex items-center gap-1.5 py-1.5 px-2 rounded-md cursor-pointer hover:bg-slate-100 text-slate-700 transition-colors",
          level === 0 && "font-semibold text-slate-900 mt-2"
        )}
        style={{ paddingLeft: `${level * 16 + 8}px` }}
        onClick={() => setIsOpen(!isOpen)}
      >
        {isOpen ? (
          <ChevronDown className="w-4 h-4 text-slate-400 shrink-0" />
        ) : (
          <ChevronRight className="w-4 h-4 text-slate-400 shrink-0" />
        )}
        <Folder className="w-4 h-4 text-amber-500 fill-amber-500/20 shrink-0" />
        <span className="truncate">{name}</span>
      </div>
      
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            {entries.map(([key, val]) => (
              <FolderNode key={key} name={key} content={val} level={level + 1} />
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default function Overview() {
  const { proposal, activePlan, setActivePlan } = useMigration();

  if (!proposal) {
    return (
      <div className="flex flex-col items-center justify-center py-32 text-center animate-in fade-in">
        <div className="w-16 h-16 bg-slate-100 rounded-full flex items-center justify-center mb-4">
          <Folder className="w-8 h-8 text-slate-300" />
        </div>
        <h2 className="text-xl font-bold text-slate-900">No Proposal Loaded</h2>
        <p className="text-slate-500 mt-2 max-w-sm mb-6">
          Upload a directory snapshot on the Home page to generate and view the restructuring proposal.
        </p>
        <Link href="/" className="px-6 py-2.5 bg-primary text-white rounded-xl hover:bg-primary-hover font-medium shadow-sm transition-colors">
          Go to Upload
        </Link>
      </div>
    );
  }

  const currentPlanData = proposal[activePlan];
  const fileCount = currentPlanData.assignments.length;

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Compare Plans</h1>
          <p className="text-slate-500 text-sm mt-1">Review the AI-generated organizational structures.</p>
        </div>
        
        <div className="flex items-center p-1 bg-slate-200/50 rounded-xl border border-slate-200">
          <button
            onClick={() => setActivePlan("clean_slate")}
            className={cn(
              "px-4 py-2 rounded-lg text-sm font-semibold transition-all flex items-center gap-2",
              activePlan === "clean_slate" 
                ? "bg-white text-slate-900 shadow-sm ring-1 ring-black/5" 
                : "text-slate-500 hover:text-slate-900"
            )}
          >
            <LayoutList className="w-4 h-4" />
            Clean Slate
          </button>
          <button
            onClick={() => setActivePlan("incremental")}
            className={cn(
              "px-4 py-2 rounded-lg text-sm font-semibold transition-all flex items-center gap-2",
              activePlan === "incremental" 
                ? "bg-white text-slate-900 shadow-sm ring-1 ring-black/5" 
                : "text-slate-500 hover:text-slate-900"
            )}
          >
            <Layers className="w-4 h-4" />
            Incremental
          </button>
        </div>
      </div>

      <div className="grid lg:grid-cols-3 gap-6">
        {/* Left Col: Tree */}
        <div className="lg:col-span-2 bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden flex flex-col h-[600px]">
          <div className="px-6 py-4 border-b border-slate-100 bg-slate-50/50 flex justify-between items-center">
            <h3 className="font-semibold text-slate-900">Proposed Hierarchy</h3>
            <span className="text-xs font-medium px-2.5 py-1 rounded-full bg-blue-50 text-blue-700 border border-blue-100">
              {activePlan === "clean_slate" ? "Aggressive Reorg" : "Conservative Reorg"}
            </span>
          </div>
          <div className="p-4 flex-1 overflow-auto">
            <FolderNode name="Root Directory" content={currentPlanData.folder_tree} />
          </div>
        </div>

        {/* Right Col: Stats & CTA */}
        <div className="space-y-6">
          <div className="bg-white border border-slate-200 rounded-2xl shadow-sm p-6">
            <h3 className="font-semibold text-slate-900 mb-6">Plan Overview</h3>
            
            <div className="space-y-4">
              <div className="flex items-center justify-between p-4 bg-slate-50 rounded-xl border border-slate-100">
                <div className="flex items-center gap-3">
                  <div className="p-2 bg-blue-100 text-blue-600 rounded-lg">
                    <File className="w-5 h-5" />
                  </div>
                  <div>
                    <div className="text-sm text-slate-500 font-medium">Files to Move</div>
                    <div className="text-xl font-bold text-slate-900">{fileCount}</div>
                  </div>
                </div>
              </div>
              
              <div className="text-sm text-slate-600 leading-relaxed bg-slate-50 p-4 rounded-xl border border-slate-100">
                {activePlan === "clean_slate" 
                  ? "The Clean Slate plan creates a deeply organized, normalized structure. Best when the current structure is too chaotic to save."
                  : "The Incremental plan attempts to keep files near their current location while fixing obvious misplacements. Less disruptive for users."}
              </div>
            </div>

            <div className="mt-8 pt-6 border-t border-slate-100">
              <Link 
                href="/review"
                className="w-full py-3 px-4 bg-primary hover:bg-primary-hover text-white rounded-xl font-medium transition-all shadow-sm shadow-primary/20 flex items-center justify-center gap-2 group"
              >
                Review File Moves
                <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
              </Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
