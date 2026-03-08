import "./globals.css";
import Link from "next/link";
import { BriefcaseBusiness, CalendarClock, LayoutDashboard, UserCircle2 } from "lucide-react";

import { ThemeToggle } from "@/components/theme-toggle";

export const metadata = {
  title: "Local Job Application Assistant",
  description: "Modern dashboard for local job search and tracking",
};

const nav = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/jobs", label: "Jobs", icon: BriefcaseBusiness },
  { href: "/followups", label: "Follow-ups", icon: CalendarClock },
  { href: "/profile", label: "Profile", icon: UserCircle2 },
];

export default function RootLayout({ children }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen bg-background text-foreground antialiased transition-colors">
        <div className="mx-auto flex min-h-screen max-w-7xl flex-col px-4 py-6 sm:px-6 lg:px-8">
          <header className="mb-6 rounded-lg border bg-card p-4 shadow-soft">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div className="text-sm font-semibold text-muted-foreground">Local Job Application Assistant</div>
              <ThemeToggle />
            </div>
            <nav className="flex flex-wrap gap-2">
              {nav.map((item) => {
                const Icon = item.icon;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className="inline-flex items-center gap-2 rounded-md border border-border bg-card px-3 py-2 text-sm font-medium hover:bg-secondary"
                  >
                    <Icon className="h-4 w-4" />
                    {item.label}
                  </Link>
                );
              })}
            </nav>
          </header>
          <main className="flex-1">{children}</main>
        </div>
      </body>
    </html>
  );
}
