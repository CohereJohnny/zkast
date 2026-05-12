import type { Metadata } from "next";
import { Crimson_Pro, JetBrains_Mono, Plus_Jakarta_Sans } from "next/font/google";
import { Suspense, type ReactNode } from "react";

import { ErrorBoundary } from "@/components/error-boundary";
import { FeedbackProvider } from "@/components/feedback-provider";
import { QueryProvider } from "@/components/query-provider";

import "./globals.css";

const plusJakarta = Plus_Jakarta_Sans({
  subsets: ["latin"],
  variable: "--font-plus-jakarta",
  display: "swap",
});

const crimson = Crimson_Pro({
  subsets: ["latin"],
  variable: "--font-crimson",
  display: "swap",
});

const jetbrains = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains",
  display: "swap",
});

export const metadata: Metadata = {
  title: "zkast",
  description: "Self-hosted knowledge workspace — documents, notes, graph, chat.",
};

function LoadingShell() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas text-secondary">
      <p className="text-body" role="status">
        Loading…
      </p>
    </div>
  );
}

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" data-theme="dark" suppressHydrationWarning>
      <body
        className={`${plusJakarta.variable} ${crimson.variable} ${jetbrains.variable} font-sans`}
      >
        <a href="#main-content" className="skip-link">
          Skip to main content
        </a>
        <QueryProvider>
          <FeedbackProvider>
            <ErrorBoundary>
              <Suspense fallback={<LoadingShell />}>{children}</Suspense>
            </ErrorBoundary>
          </FeedbackProvider>
        </QueryProvider>
      </body>
    </html>
  );
}
