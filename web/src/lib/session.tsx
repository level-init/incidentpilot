"use client";

import { createContext, useContext, type ReactNode } from "react";

import type { Session } from "@/lib/auth";

const SessionContext = createContext<Session | null>(null);

export function SessionProvider({
  session,
  children,
}: {
  session: Session;
  children: ReactNode;
}) {
  return (
    <SessionContext.Provider value={session}>{children}</SessionContext.Provider>
  );
}

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) {
    throw new Error("useSession requires SessionProvider");
  }
  return session;
}
