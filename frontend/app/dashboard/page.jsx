"use client";

import { useEffect, useMemo, useState } from "react";
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

function prettyLabel(value) {
  return String(value || "").replaceAll("_", " ");
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
  const applied = Number(data?.by_status?.applied ?? 0);
  const interviews = Number(data?.by_status?.interview ?? 0) + Number(data?.by_status?.final_round ?? 0);
  const offers = Number(data?.by_status?.offer ?? 0);
  const responseRate = Number(data?.response_rate ?? 0).toFixed(1);
  const topSource = useMemo(() => (data?.source_performance || [])[0] || null, [data]);

  return (
    <section className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
        <p className="text-sm text-muted-foreground">
          See which sources are working, where your pipeline is moving, and how much application prep you have already banked.
        </p>
      </div>

      {error ? <p className="text-sm text-red-600">{error}</p> : null}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        <MetricCard title="Total Jobs" value={total} subtitle="Across all current statuses" />
        <MetricCard title="Applied" value={applied} subtitle="Jobs currently marked applied" />
        <MetricCard title="Interview Stage" value={interviews} subtitle="Interview + final round jobs" />
        <MetricCard title="Offers" value={offers} subtitle="Current jobs that reached offer stage" />
        <MetricCard title="Response Rate" value={`${responseRate}%`} subtitle="Interview-stage jobs divided by applied pipeline" />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Status Breakdown</CardTitle>
            <CardDescription>Current pipeline distribution by status.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {Object.entries(data?.by_status || {}).map(([k, v]) => (
              <div key={k} className="flex items-center justify-between rounded-md border px-3 py-2">
                <span className="capitalize">{prettyLabel(k)}</span>
                <span className="font-medium">{v}</span>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Packet Activity</CardTitle>
            <CardDescription>Reusable application prep already saved in the system.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="flex items-center justify-between rounded-md border px-3 py-2">
              <span>Total packets generated</span>
              <span className="font-medium">{data?.packet_metrics?.total_generated ?? 0}</span>
            </div>
            <div className="flex items-center justify-between rounded-md border px-3 py-2">
              <span>Generated in last 7 days</span>
              <span className="font-medium">{data?.packet_metrics?.generated_last_7_days ?? 0}</span>
            </div>
            <div className="flex items-center justify-between rounded-md border px-3 py-2">
              <span>Last packet generated</span>
              <span className="font-medium">
                {data?.packet_metrics?.last_generated_at
                  ? new Date(data.packet_metrics.last_generated_at).toLocaleString()
                  : "Never"}
              </span>
            </div>
            {topSource ? (
              <div className="rounded-md border border-dashed px-3 py-2 text-sm text-muted-foreground">
                Best source right now: <span className="font-medium text-foreground">{prettyLabel(topSource.source)}</span>{" "}
                with {Number(topSource.response_rate || 0).toFixed(1)}% response rate and {Number(topSource.avg_expected_value || 0).toFixed(1)} average EV.
              </div>
            ) : null}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Source Performance</CardTitle>
            <CardDescription>Which sources are actually yielding better downstream outcomes.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {(data?.source_performance || []).length === 0 ? (
              <p className="text-muted-foreground">Not enough source history yet.</p>
            ) : (
              data.source_performance.map((row) => (
                <div key={row.source} className="rounded-md border p-3">
                  <div className="flex items-center justify-between gap-2">
                    <p className="font-medium">{prettyLabel(row.source)}</p>
                    <p className="text-xs text-muted-foreground">{row.total_jobs} jobs</p>
                  </div>
                  <div className="mt-2 grid gap-2 text-xs md:grid-cols-3">
                    <div>Applied: <span className="font-medium">{row.applied_count}</span></div>
                    <div>Interview rate: <span className="font-medium">{Number(row.interview_rate || 0).toFixed(1)}%</span></div>
                    <div>Response rate: <span className="font-medium">{Number(row.response_rate || 0).toFixed(1)}%</span></div>
                    <div>Offers: <span className="font-medium">{row.offer_count}</span></div>
                    <div>Avg final: <span className="font-medium">{Number(row.avg_final_score || 0).toFixed(1)}</span></div>
                    <div>Avg EV: <span className="font-medium">{Number(row.avg_expected_value || 0).toFixed(1)}</span></div>
                  </div>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Recent Activity</CardTitle>
            <CardDescription>Latest saved pipeline changes from status history.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {(data?.recent_activity || []).length === 0 ? (
              <p className="text-muted-foreground">No saved status activity yet.</p>
            ) : (
              data.recent_activity.map((event) => (
                <div key={event.id} className="rounded-md border p-3">
                  <div className="flex items-center justify-between gap-2">
                    <p className="font-medium">
                      Job #{event.job_id}: {event.previous_status ? `${prettyLabel(event.previous_status)} -> ` : ""}
                      {prettyLabel(event.new_status)}
                    </p>
                    <p className="text-xs text-muted-foreground">{new Date(event.created_at).toLocaleString()}</p>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">Source: {prettyLabel(event.action_source)}</p>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Role Category Breakdown</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {Object.entries(data?.by_role_category || {}).map(([k, v]) => (
                <div key={k} className="flex items-center justify-between rounded-md border px-3 py-2">
                  <span>{prettyLabel(k)}</span>
                  <span className="font-medium">{v}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

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
      </div>
    </section>
  );
}
