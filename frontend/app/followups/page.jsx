"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { StatusBadge } from "@/components/status-badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead } from "@/components/ui/table";
import { api } from "@/lib/api";

export default function FollowupsPage() {
  const [jobs, setJobs] = useState([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .listJobs()
      .then(setJobs)
      .catch((e) => setError(e.message));
  }, []);

  const followups = useMemo(
    () =>
      jobs
        .filter((job) => !!job.follow_up_date || (job.status || "").toLowerCase() === "applied")
        .sort((a, b) => new Date(a.follow_up_date || "2100-01-01") - new Date(b.follow_up_date || "2100-01-01")),
    [jobs]
  );

  return (
    <section className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Follow-ups</h1>
        <p className="text-sm text-muted-foreground">Jobs requiring outreach based on follow-up date or applied status.</p>
      </div>

      {error ? <p className="text-sm text-red-600">{error}</p> : null}

      <Card>
        <CardHeader>
          <CardTitle>Queue</CardTitle>
          <CardDescription>{followups.length} jobs currently in follow-up queue</CardDescription>
        </CardHeader>
        <CardContent className="overflow-x-auto p-0">
          <Table>
            <THead>
              <tr>
                <TH>Role</TH>
                <TH>Company</TH>
                <TH>Status</TH>
                <TH>Follow-up Date</TH>
                <TH>Notes</TH>
              </tr>
            </THead>
            <TBody>
              {followups.map((job) => (
                <tr key={job.id} className="hover:bg-secondary/30">
                  <TD>
                    <Link href={`/jobs/${job.id}`} className="font-medium text-primary hover:underline">
                      {job.title}
                    </Link>
                  </TD>
                  <TD>{job.company || "-"}</TD>
                  <TD>
                    <StatusBadge status={job.status} />
                  </TD>
                  <TD>{job.follow_up_date ? new Date(job.follow_up_date).toLocaleDateString() : "Not set"}</TD>
                  <TD className="max-w-[360px] truncate">{job.notes || "-"}</TD>
                </tr>
              ))}
            </TBody>
          </Table>
        </CardContent>
      </Card>
    </section>
  );
}
