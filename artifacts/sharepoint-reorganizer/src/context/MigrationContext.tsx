import React, { createContext, useContext, useState, useEffect, ReactNode } from "react";
import type { Proposal, ProposalAssignment } from "@/api/client";

export interface MsalUser {
  name: string;
  email: string;
  tenantId: string;
}

export function assignmentKey(a: Pick<ProposalAssignment, "drive_id" | "item_id" | "current_path" | "file_name">): string {
  if (a.drive_id && a.item_id) return `${a.drive_id}:${a.item_id}`;
  return `${a.current_path}||${a.file_name}`;
}

interface MigrationState {
  proposal: Proposal | null;
  setProposal: (p: Proposal | null) => void;
  activePlan: "clean_slate" | "incremental";
  setActivePlan: (plan: "clean_slate" | "incremental") => void;
  approvedMoves: Record<string, ProposalAssignment>;
  setApprovedMoves: React.Dispatch<React.SetStateAction<Record<string, ProposalAssignment>>>;
  clearApprovals: () => void;
  accessToken: string | null;
  setAccessToken: (token: string | null) => void;
  msalUser: MsalUser | null;
  setMsalUser: (user: MsalUser | null) => void;
  siteUrl: string;
  setSiteUrl: (url: string) => void;
}

const MigrationContext = createContext<MigrationState | undefined>(undefined);

export function MigrationProvider({ children }: { children: ReactNode }) {
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [activePlan, setActivePlan] = useState<"clean_slate" | "incremental">("clean_slate");
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [msalUser, setMsalUser] = useState<MsalUser | null>(null);
  const [siteUrl, setSiteUrl] = useState<string>(() =>
    localStorage.getItem("sp-site-url") || ""
  );

  const [approvedMoves, setApprovedMoves] = useState<Record<string, ProposalAssignment>>(() => {
    try {
      const saved = localStorage.getItem("sp-approved-moves-v2");
      return saved ? JSON.parse(saved) : {};
    } catch {
      return {};
    }
  });

  useEffect(() => {
    localStorage.setItem("sp-approved-moves-v2", JSON.stringify(approvedMoves));
  }, [approvedMoves]);

  useEffect(() => {
    if (siteUrl) localStorage.setItem("sp-site-url", siteUrl);
  }, [siteUrl]);

  const clearApprovals = () => setApprovedMoves({});

  return (
    <MigrationContext.Provider
      value={{
        proposal,
        setProposal,
        activePlan,
        setActivePlan,
        approvedMoves,
        setApprovedMoves,
        clearApprovals,
        accessToken,
        setAccessToken,
        msalUser,
        setMsalUser,
        siteUrl,
        setSiteUrl,
      }}
    >
      {children}
    </MigrationContext.Provider>
  );
}

export function useMigration() {
  const context = useContext(MigrationContext);
  if (!context) {
    throw new Error("useMigration must be used within a MigrationProvider");
  }
  return context;
}
