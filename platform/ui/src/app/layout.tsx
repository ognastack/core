"use client";

import { Geist, Geist_Mono } from "next/font/google";
import { Toaster } from "@/components/ui/sonner";
import React, { useMemo } from "react";
import { OgnaClient } from '@ogna/js';

import "./globals.css";
import { OgnaContext } from "@/api/OgnaContext";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const client = useMemo(
    () =>
      new OgnaClient(
        process.env.NEXT_PUBLIC_OGNA_URL ||
          (typeof window !== "undefined" ? window.location.origin : "http://localhost:8000")
      ),
    []
  );


  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        <OgnaContext.Provider value={client}>
          {children}
        </OgnaContext.Provider>
        <Toaster />
      </body>
    </html>
  );
}
