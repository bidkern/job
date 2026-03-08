"use client";

function clampToTen(value) {
  const numeric = Number(value || 0);
  if (!Number.isFinite(numeric)) return 0;
  return Math.max(0, Math.min(10, numeric * 10));
}

function modeLabel(mode) {
  const normalized = String(mode || "balanced").toLowerCase();
  if (normalized === "strict") return "Strict";
  if (normalized === "aggressive") return "Aggressive";
  return "Balanced";
}

export function ScoreWhyPopover({ job, metric = "interview" }) {
  const breakdown = job?.score_breakdown || {};
  const components = breakdown.components || {};
  const reasons = breakdown.why_ranked_high || [];
  const directCount = breakdown?.skill_signals?.direct_overlap_count ?? 0;
  const transferableCount = breakdown?.skill_signals?.transferable_group_count ?? 0;
  const requirementsIgnored = breakdown?.requirements_ignored_count ?? 0;
  const tuningMode = breakdown?.score_tuning_mode || "balanced";
  const decision = breakdown?.decision || {};
  const roleFamily = breakdown?.role_family?.label || decision?.role_family_label;
  const strategy = decision?.strategy_tag || job?.strategy_tag;
  const expectedValue = Number(job?.expected_value_score ?? decision?.expected_value_score ?? 0);
  const confidence = Number(job?.confidence_score ?? ((decision?.confidence || 0) * 100));

  const title = metric === "compatibility" ? "Why compatibility score?" : "Why interview score?";
  const reasonText = metric === "compatibility" ? (job?.compatibility_reason || "Compatibility details unavailable.") : (job?.interview_reason || "Interview details unavailable.");

  return (
    <details className="relative inline-block">
      <summary className="ml-1 inline-flex h-4 w-4 cursor-pointer items-center justify-center rounded-full border text-[10px] leading-none text-muted-foreground list-none">
        i
      </summary>
      <div className="absolute right-0 z-30 mt-1 w-80 rounded-md border bg-card p-3 text-xs shadow-lg">
        <p className="font-semibold">{title}</p>
        <p className="mt-1 text-muted-foreground">{reasonText}</p>
        <div className="mt-2 space-y-1 text-[11px] text-muted-foreground">
          <p>Mode: {modeLabel(tuningMode)}</p>
          {roleFamily ? <p>Role family: {roleFamily}</p> : null}
          {strategy ? <p>Strategy: {strategy}</p> : null}
          {expectedValue > 0 ? <p>Expected value: {expectedValue.toFixed(1)}/100</p> : null}
          {confidence > 0 ? <p>Confidence: {confidence.toFixed(0)}%</p> : null}
          <p>
            Signals: role {clampToTen(components.role).toFixed(1)}/10, direct skills {clampToTen(components.skills_direct ?? components.skills).toFixed(1)}/10, transferable {clampToTen(components.skills_transferable).toFixed(1)}/10
          </p>
          <p>Resume quality: {clampToTen(components.resume_strength).toFixed(1)}/10</p>
          <p>
            Other factors: distance {clampToTen(components.distance).toFixed(1)}/10, freshness {clampToTen(components.freshness).toFixed(1)}/10, salary {clampToTen(components.salary).toFixed(1)}/10
          </p>
          <p>Matched skills: {directCount} direct + {transferableCount} transferable</p>
          <p>Ignored requirement phrases: {requirementsIgnored}</p>
          {decision?.reason_summary ? <p>Decision: {decision.reason_summary}</p> : null}
          {reasons.length ? <p>Summary: {reasons.join(" | ")}</p> : null}
        </div>
      </div>
    </details>
  );
}
