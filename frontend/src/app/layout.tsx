import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "CivicGrid — Connected Municipal Waste Infrastructure",
  description: "End-to-end municipal waste tracking, independent cross-check verification, and tamper-evident audit trails.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-paper font-sans text-ink antialiased selection:bg-track-100 selection:text-track-700">
        {children}
      </body>
    </html>
  );
}
