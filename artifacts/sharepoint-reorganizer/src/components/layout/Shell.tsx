import { ReactNode } from "react";
import { Link, useLocation } from "wouter";
import { CheckCircle2, FolderTree, FileDown, Layers, PlayCircle, LogOut } from "lucide-react";
import { useMsal } from "@azure/msal-react";
import { useMigration } from "@/context/MigrationContext";
import { cn } from "@/lib/utils";

export function Shell({ children }: { children: ReactNode }) {
  const [location] = useLocation();
  const { proposal, msalUser } = useMigration();
  const { instance, accounts } = useMsal();

  const displayUser = msalUser || (accounts[0]
    ? { name: accounts[0].name || accounts[0].username, email: accounts[0].username }
    : null);

  const navItems = [
    { href: "/", label: "Upload & Connect", icon: FileDown },
    { href: "/overview", label: "Overview", icon: FolderTree },
    { href: "/review", label: "Review Moves", icon: Layers },
    { href: "/execute", label: "Execute", icon: PlayCircle },
  ];

  return (
    <div className="min-h-screen bg-slate-50/50 flex flex-col font-sans">
      <header className="sticky top-0 z-50 glass-panel border-b border-border/40">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between gap-4">
          <div className="flex items-center gap-2 flex-shrink-0">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-primary to-blue-400 flex items-center justify-center text-white shadow-md">
              <FolderTree className="w-4 h-4" />
            </div>
            <span className="font-display font-bold text-lg text-slate-900 tracking-tight">
              SP Reorganizer
            </span>
          </div>

          <nav className="hidden md:flex items-center gap-1 bg-slate-100/80 p-1 rounded-xl border border-slate-200/50">
            {navItems.map((item) => {
              const Icon = item.icon;
              const isActive = location === item.href;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    "flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg transition-all duration-200",
                    isActive
                      ? "bg-white text-primary shadow-sm ring-1 ring-black/5"
                      : "text-slate-600 hover:text-slate-900 hover:bg-white/50"
                  )}
                >
                  <Icon className={cn("w-4 h-4", isActive ? "text-primary" : "text-slate-400")} />
                  {item.label}
                </Link>
              );
            })}
          </nav>

          <div className="flex items-center gap-3 flex-shrink-0">
            {proposal && (
              <div className="hidden sm:flex items-center gap-1.5 px-3 py-1.5 bg-green-50 text-green-700 rounded-full border border-green-200/50 text-xs font-semibold shadow-sm animate-in fade-in zoom-in duration-300">
                <CheckCircle2 className="w-3.5 h-3.5" />
                Proposal Ready
              </div>
            )}
            {displayUser && (
              <div className="flex items-center gap-2">
                <div className="flex items-center gap-2 px-3 py-1.5 bg-white border border-slate-200 rounded-full shadow-sm">
                  <div className="w-5 h-5 rounded-full bg-gradient-to-br from-primary to-blue-400 flex items-center justify-center text-white font-bold text-xs">
                    {displayUser.name.charAt(0).toUpperCase()}
                  </div>
                  <span className="text-xs font-medium text-slate-700 max-w-24 truncate hidden sm:block">
                    {displayUser.name.split(" ")[0]}
                  </span>
                </div>
                <button
                  onClick={() => instance.logoutPopup()}
                  title="Sign out"
                  className="w-8 h-8 rounded-full flex items-center justify-center text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors"
                >
                  <LogOut className="w-4 h-4" />
                </button>
              </div>
            )}
          </div>
        </div>
      </header>

      <main className="flex-1 w-full max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {children}
      </main>
    </div>
  );
}
