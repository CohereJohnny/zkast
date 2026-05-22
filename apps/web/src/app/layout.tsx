import type { Metadata } from "next";
import { IBM_Plex_Mono, Inter } from "next/font/google";
import { Suspense, type ReactNode } from "react";

import { ErrorBoundary } from "@/components/error-boundary";
import { FeedbackProvider } from "@/components/feedback-provider";
import { QueryProvider } from "@/components/query-provider";
import { ThemeProvider } from "@/components/theme-provider";

import "./globals.css";

const fontSans = Inter({
  subsets: ["latin"],
  variable: "--font-family-regular",
  display: "swap",
});

const fontMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-mono-regular",
  display: "swap",
});

export const metadata: Metadata = {
  title: "zkast",
  description: "Self-hosted knowledge workspace — documents, notes, graph, chat.",
};

function LoadingShell() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background text-muted-foreground">
      <p className="text-p" role="status">
        Loading…
      </p>
    </div>
  );
}

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body
        className={`${fontSans.variable} ${fontMono.variable} font-regular antialiased`}
      >
        <a href="#main-content" className="skip-link">
          Skip to main content
        </a>
        <ThemeProvider>
          <QueryProvider>
            <FeedbackProvider>
              <ErrorBoundary>
                <Suspense fallback={<LoadingShell />}>{children}</Suspense>
              </ErrorBoundary>
            </FeedbackProvider>
          </QueryProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
