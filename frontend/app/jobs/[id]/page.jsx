"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { StatusBadge } from "@/components/status-badge";
import { api } from "@/lib/api";

function salaryText(job) {
  if (job.pay_text) return job.pay_text;
  if (job.pay_min || job.pay_max) return `$${job.pay_min || "?"} - $${job.pay_max || "?"}`;
  return "Not listed";
}

function cleanDescriptionText(text) {
  if (!text) return "No description available.";
  const htmlDecoded = text
    .replace(/&nbsp;/gi, " ")
    .replace(/&amp;/gi, "&")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">")
    .replace(/&#39;/g, "'")
    .replace(/&quot;/g, '"');
  const stripped = htmlDecoded
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/(p|div|li|h1|h2|h3|h4|h5|h6)>/gi, "\n")
    .replace(/<li[^>]*>/gi, "- ")
    .replace(/<[^>]+>/g, " ")
    .replace(/â€“|â€”/g, "-")
    .replace(/â€˜|â€™/g, "'")
    .replace(/â€œ|â€/g, '"')
    .replace(/\u00a0/g, " ")
    .replace(/\s+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/[ \t]{2,}/g, " ");
  return stripped.trim() || "No description available.";
}

export default function JobDetailPage({ params }) {
  const [job, setJob] = useState(null);
  const [msg, setMsg] = useState("");

  async function load() {
    const data = await api.getJob(params.id);
    setJob(data);
  }

  useEffect(() => {
    load();
  }, [params.id]);

  async function setStatus(status) {
    await api.updateJob(params.id, { status });
    setMsg(`Status updated to ${status}`);
    await load();
  }

  if (!job) return <p className="text-sm text-muted-foreground">Loading job details...</p>;

  const originalDescription = cleanDescriptionText(job.clean_description || job.raw_description || job.description);

  return (
    <section className="space-y-5">
      <p className="text-sm">
        <Link href="/jobs" className="underline">Back to jobs</Link>
      </p>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{job.title}</h1>
          <p className="text-sm text-muted-foreground">{job.company || "Unknown company"}</p>
        </div>
        <StatusBadge status={job.status} />
      </div>

      {msg ? <p className="text-sm text-emerald-600">{msg}</p> : null}

      <Card>
        <CardHeader>
          <CardTitle>Quick Facts</CardTitle>
          <CardDescription>Easy read summary from the listing.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-2 md:grid-cols-2">
          <p><strong>Salary:</strong> {salaryText(job)}</p>
          <p><strong>Work type:</strong> {(job.remote_type || "unknown").toUpperCase()}</p>
          <p><strong>Location:</strong> {job.location_text || "Not listed"}</p>
          <p><strong>Distance:</strong> {job.distance_miles ?? "N/A"} miles from your ZIP</p>
          <p><strong>Interview potential:</strong> {job.interview_score_10 != null ? `${job.interview_score_10.toFixed(1)}/10` : "-"}</p>
          <p><strong>Interview drift:</strong> {job.interview_drift_10 != null ? `${job.interview_drift_10 > 0 ? "+" : ""}${job.interview_drift_10.toFixed(1)}` : "-"}</p>
          <p><strong>Compatibility:</strong> {job.compatibility_score_10 != null ? `${job.compatibility_score_10.toFixed(1)}/10` : "-"}</p>
          <p><strong>Compatibility drift:</strong> {job.compatibility_drift_10 != null ? `${job.compatibility_drift_10 > 0 ? "+" : ""}${job.compatibility_drift_10.toFixed(1)}` : "-"}</p>
          <p><strong>Role family:</strong> {job.role_family_label || "General fallback"}</p>
          <p><strong>Strategy:</strong> {job.strategy_tag || "Review"}</p>
          <p><strong>Expected value:</strong> {job.expected_value_score != null ? `${Number(job.expected_value_score).toFixed(1)}/100` : "-"}</p>
          <p><strong>Final weighted score:</strong> {job.final_weighted_score != null ? `${Number(job.final_weighted_score).toFixed(1)}/100` : "-"}</p>
          <p><strong>Confidence:</strong> {job.confidence_score != null ? `${Number(job.confidence_score).toFixed(0)}%` : "-"}</p>
          <p><strong>Employee satisfaction:</strong> {job.company_sentiment_score_10 != null ? `${job.company_sentiment_score_10.toFixed(1)}/10` : "-"}</p>
          <p><strong>Posted:</strong> {job.posted_date ? new Date(job.posted_date).toLocaleDateString() : "Unknown"}</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Actions</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          {job.url ? (
            <a href={job.url} target="_blank" rel="noreferrer" className="inline-flex items-center rounded-md border px-3 py-2 text-sm hover:bg-secondary">
              Open Original Listing
            </a>
          ) : null}
          <Button onClick={() => setStatus("saved")} variant="secondary">Save</Button>
          <Button onClick={() => setStatus("applied")}>Apply</Button>
          <Button onClick={() => setStatus("rejected")} variant="destructive">Reject</Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Score Reasoning</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <p><strong>Interview potential:</strong> {job.interview_reason || "Not available."}</p>
          <p><strong>Compatibility:</strong> {job.compatibility_reason || "Not available."}</p>
          {job.reason_summary ? <p><strong>Decision summary:</strong> {job.reason_summary}</p> : null}
          {(job.top_matched_qualifications || []).length ? (
            <p><strong>Top matched:</strong> {(job.top_matched_qualifications || []).join(", ")}</p>
          ) : null}
          {(job.top_missing_qualifications || []).length ? (
            <p><strong>Top missing:</strong> {(job.top_missing_qualifications || []).join(", ")}</p>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Full Job Description (Clean Read)</CardTitle>
          <CardDescription>Cleaned for readability while preserving full posting content.</CardDescription>
        </CardHeader>
        <CardContent>
          <pre className="rounded-md border bg-secondary/40 p-3 text-xs whitespace-pre-wrap leading-6">{originalDescription}</pre>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Why this matched</CardTitle>
        </CardHeader>
        <CardContent>
          <pre className="rounded-md border bg-secondary/40 p-3 text-xs">
            {JSON.stringify(job.score_breakdown || {}, null, 2)}
          </pre>
        </CardContent>
      </Card>
    </section>
  );
}
