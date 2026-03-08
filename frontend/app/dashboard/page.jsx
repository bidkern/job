"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";

function MetricCard({ title, value, subtitle }) {
  return (
    <Card>
      <CardHeader>
        <CardDescription>{title}</CardDescription>
        <CardTitle className="text-3xl">{value}</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-sm text-muted-foreground">{subtitle}</p>
      </CardContent>
    </Card>
  );
}

export default function DashboardPage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .getMetrics()
      .then(setData)
      .catch((e) => setError(e.message));
  }, []);

  const total = data ? Object.values(data.by_status || {}).reduce((sum, v) => sum + v, 0) : 0;

  return (
    <section className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
        <p className="text-sm text-muted-foreground">Track pipeline health and focus areas at a glance.</p>
      </div>

      {error ? <p className="text-sm text-red-600">{error}</p> : null}

      <div className="grid gap-4 md:grid-cols-3">
        <MetricCard title="Total Jobs" value={total} subtitle="Across all statuses" />
        <MetricCard
          title="Applied"
          value={data?.by_status?.applied ?? 0}
          subtitle="Jobs currently in active application flow"
        />
        <MetricCard
          title="Interview"
          value={data?.by_status?.interview ?? 0}
          subtitle="Leads that reached interview stage"
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Status Breakdown</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {Object.entries(data?.by_status || {}).map(([k, v]) => (
                <div key={k} className="flex items-center justify-between rounded-md border px-3 py-2">
                  <span className="capitalize">{k}</span>
                  <span className="font-medium">{v}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Role Category Breakdown</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {Object.entries(data?.by_role_category || {}).map(([k, v]) => (
                <div key={k} className="flex items-center justify-between rounded-md border px-3 py-2">
                  <span>{k.replaceAll("_", " ")}</span>
                  <span className="font-medium">{v}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Quick Actions</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-3">
          <Link href="/jobs" className="rounded-md border px-3 py-2 text-sm hover:bg-secondary">
            Open Jobs Table
          </Link>
          <Link href="/followups" className="rounded-md border px-3 py-2 text-sm hover:bg-secondary">
            View Follow-ups
          </Link>
        </CardContent>
      </Card>
    </section>
  );
}
