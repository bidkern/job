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
    .replace(/Ã¢â‚¬â€œ|Ã¢â‚¬â€/g, "-")
    .replace(/Ã¢â‚¬Ëœ|Ã¢â‚¬â„¢/g, "'")
    .replace(/Ã¢â‚¬Å“|Ã¢â‚¬Â/g, '"')
    .replace(/\u00a0/g, " ")
    .replace(/\s+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/[ \t]{2,}/g, " ");
  return stripped.trim() || "No description available.";
}

async function copyText(text) {
  if (!text) return false;
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

function eventLabel(value) {
  return String(value || "").replaceAll("_", " ");
}

export default function JobDetailPage({ params }) {
  const [job, setJob] = useState(null);
  const [history, setHistory] = useState({ status_events: [], packet_history: [] });
  const [profile, setProfile] = useState({ skills: [] });
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [loadingPacket, setLoadingPacket] = useState(false);

  async function loadAll() {
    const [jobData, historyData, profileData] = await Promise.all([
      api.getJob(params.id),
      api.getJobHistory(params.id).catch(() => ({ status_events: [], packet_history: [] })),
      api.getProfile().catch(() => ({ skills: [] })),
    ]);
    setJob(jobData);
    setHistory(historyData || { status_events: [], packet_history: [] });
    setProfile(profileData || { skills: [] });
  }

  useEffect(() => {
    loadAll().catch((e) => setError(e.message || "Failed to load job details."));
  }, [params.id]);

  async function setStatus(status) {
    await api.updateJob(params.id, { status });
    setMsg(`Status updated to ${status}`);
    await loadAll();
  }

  async function generatePacket() {
    setLoadingPacket(true);
    setError("");
    try {
      await api.generateMaterials(params.id, {
        profile_skills: Array.isArray(profile?.skills) ? profile.skills : [],
        experience_areas: Array.isArray(profile?.skills) ? profile.skills.slice(0, 10) : [],
        include_cover_letter: true,
      });
      setMsg("Saved packet generated.");
      await loadAll();
    } catch (e) {
      setError(e.message || "Could not generate packet.");
    } finally {
      setLoadingPacket(false);
    }
  }

  async function copyLatestPacket() {
    const latest = history?.packet_history?.[0];
    if (!latest?.packet_text) return;
    const ok = await copyText(latest.packet_text);
    setMsg(ok ? "Latest packet copied." : "Could not copy latest packet.");
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
      {error ? <p className="text-sm text-red-600">{error}</p> : null}

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
          <CardDescription>Save progress, generate reusable packet text, and keep history attached to this job.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          {job.url ? (
            <a href={job.url} target="_blank" rel="noreferrer" className="inline-flex items-center rounded-md border px-3 py-2 text-sm hover:bg-secondary">
              Open Original Listing
            </a>
          ) : null}
          <Button onClick={() => setStatus("saved")} variant="secondary">Save</Button>
          <Button onClick={() => setStatus("applied")}>Apply</Button>
          <Button onClick={() => setStatus("interview")} variant="outline">Interview</Button>
          <Button onClick={() => setStatus("final_round")} variant="outline">Final Round</Button>
          <Button onClick={() => setStatus("offer")} variant="outline">Offer</Button>
          <Button onClick={() => setStatus("no_response")} variant="outline">No Response</Button>
          <Button onClick={() => setStatus("declined")} variant="outline">Declined</Button>
          <Button onClick={() => setStatus("rejected")} variant="destructive">Reject</Button>
          <Button onClick={generatePacket} variant="outline" disabled={loadingPacket}>
            {loadingPacket ? "Generating..." : "Generate Saved Packet"}
          </Button>
          <Button onClick={copyLatestPacket} variant="outline" disabled={!history?.packet_history?.length}>
            Copy Latest Packet
          </Button>
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Application History</CardTitle>
            <CardDescription>Status and outcome changes for this job.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            {(history?.status_events || []).length === 0 ? (
              <p className="text-muted-foreground">No saved status history yet.</p>
            ) : (
              history.status_events.map((event) => (
                <div key={event.id} className="rounded-md border p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="font-medium">
                      {event.previous_status ? `${eventLabel(event.previous_status)} -> ` : ""}
                      {eventLabel(event.new_status)}
                    </p>
                    <p className="text-xs text-muted-foreground">{new Date(event.created_at).toLocaleString()}</p>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">Source: {eventLabel(event.action_source)}</p>
                  {event.note ? <p className="mt-1 text-xs text-muted-foreground">{event.note}</p> : null}
                </div>
              ))
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Saved Packet History</CardTitle>
            <CardDescription>Stored outreach/resume packet generations for this job.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            {(history?.packet_history || []).length === 0 ? (
              <p className="text-muted-foreground">No saved packets yet.</p>
            ) : (
              history.packet_history.map((packet) => (
                <div key={packet.id} className="rounded-md border p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="font-medium">Generated via {eventLabel(packet.generated_via)}</p>
                    <p className="text-xs text-muted-foreground">{new Date(packet.created_at).toLocaleString()}</p>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {packet.openai_used ? "OpenAI-assisted" : "Offline/default"} packet
                  </p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <Button size="sm" variant="outline" onClick={() => copyText(packet.packet_text).then((ok) => setMsg(ok ? "Packet copied." : "Could not copy packet."))}>
                      Copy Packet
                    </Button>
                  </div>
                  <pre className="mt-2 max-h-52 overflow-y-auto rounded-md border bg-secondary/40 p-3 text-xs whitespace-pre-wrap">
                    {packet.packet_text}
                  </pre>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>

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
