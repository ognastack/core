"use client";

import { createContext, useContext } from "react";

// import { OgnaClient, Session } from "@/api/OgnaClient";
import { OgnaClient } from '@ogna/js';

export const OgnaContext = createContext<OgnaClient | undefined>(undefined);


export const useAuth = () => {
  const ctx = useContext(OgnaContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
};
