"use client";

import { startTransition, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Clipboard, ExternalLink, Search, SkipForward, WandSparkles } from "lucide-react";

import { ScoreWhyPopover } from "@/components/score-why-popover";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { api } from "@/lib/api";

const LOCAL_QUICK_PAGES = 1;
const LOCAL_PAGES = 4;
const LOCAL_QUICK_LIMIT = 25;
const LOCAL_LIMIT = 160;
const NATIONWIDE_LIMIT = 25;
const SPRINT_QUEUE_MAX = 40;

const SORT_OPTIONS_LOCAL = [
  { value: "expected_value", label: "Best expected value" },
  { value: "interview", label: "Highest interview score" },
  { value: "compatibility", label: "Highest compatibility" },
  { value: "salary", label: "Highest salary" },
  { value: "distance", label: "Closest first" },
  { value: "newest", label: "Newest first" },
];

const SORT_OPTIONS_NATIONWIDE = [
  { value: "expected_value", label: "Best expected value" },
  { value: "interview", label: "Highest interview score" },
  { value: "compatibility", label: "Highest compatibility" },
  { value: "salary", label: "Highest salary" },
  { value: "newest", label: "Newest first" },
];

const STRATEGY_EXPLANATIONS = [
  ["Apply now", "Strong fit, solid interview odds, and low enough effort that it should be near the front of your queue."],
  ["Tailor lightly", "Good target. Small resume tweaks or keyword alignment should improve your odds."],
  ["Tailor heavily", "There is upside here, but enough gaps exist that a generic application would likely underperform."],
  ["Reach out first", "Worth pursuing, but the process looks heavy enough that outreach or a warm contact may help first."],
  ["Save for later", "Decent option, but not a top-priority application compared with stronger jobs already on the board."],
  ["Skip", "Low return for the effort, low trust, or too many fit gaps compared with better alternatives."],
];

const TERM_DEFINITIONS = [
  ["EV", "Expected Value. A 0-100 priority score combining fit, interview odds, pay upside, and application effort."],
  ["Friction", "How much work the application is likely to take. Lower is better because it means faster throughput."],
  ["Confidence", "How reliable the score is based on how complete and trustworthy the job data looks."],
];

function parsePositiveNumber(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return null;
  return n;
}

function parseBoundedScore(value, fallback = 8) {
  const n = Number(value);
  if (!Number.isFinite(n)) return fallback;
  return Math.max(0, Math.min(10, n));
}

function formatDateTime(value) {
  if (!value) return "Never";
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return "Never";
  return dt.toLocaleString();
}

function formatMoney(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return null;
  return `$${Math.round(n).toLocaleString()}`;
}

function compatibilityScore10(job) {
  return Number(job.compatibility_score_10 || job.potential_match_score_10 || 0);
}

function interviewScore10(job) {
  return Number(job.interview_score_10 || 0);
}

function salaryText(job) {
  if (job.pay_text) return job.pay_text;
  const low = formatMoney(job.pay_min);
  const high = formatMoney(job.pay_max);
  if (low && high) return `${low} - ${high}`;
  if (high) return high;
  if (low) return low;
  return "Not listed";
}

function compensationBasis(job) {
  const text = String(job.pay_text || "").toLowerCase();
  if (/(hour|hourly|\/hr|\/h|\bhr\b)/.test(text)) return "Hourly";
  if (/(year|annual|salary|\/yr|\/year)/.test(text)) return "Salary";
  const anchor = Number(job.pay_max || job.pay_min || 0);
  if (anchor > 0 && anchor <= 500) return "Hourly";
  if (anchor >= 10000) return "Salary";
  return "Unknown";
}

function annualizedSalary(job) {
  const low = Number(job.pay_min || 0);
  const high = Number(job.pay_max || 0);
  const anchor = high || low;
  if (!anchor) return null;

  const basis = compensationBasis(job);
  if (basis === "Hourly") {
    const wage = high && low ? (low + high) / 2 : anchor;
    return wage * 2080;
  }

  if (basis === "Salary") {
    return high && low ? (low + high) / 2 : anchor;
  }

  if (anchor >= 10000) {
    return high && low ? (low + high) / 2 : anchor;
  }
  return null;
}

function expectedValueScore(job) {
  const backend = Number(job.expected_value_score);
  if (Number.isFinite(backend) && backend > 0) {
    return Math.max(0, Math.min(100, backend));
  }

  const annual = annualizedSalary(job);
  if (!annual) return 0;
  const interview = interviewScore10(job) / 10;
  const compatibility = compatibilityScore10(job) / 10;
  const sentiment = Number(job.company_sentiment_score_10 || 5) / 10;
  const salaryBand = Math.max(0.3, Math.min(1, annual / 150000));
  const effortPenalty = Number(job.application_friction_score_10 || 4.5) / 10;
  const score = 100 * ((0.45 * interview) + (0.35 * compatibility) + (0.2 * sentiment)) * salaryBand * (1 - 0.35 * effortPenalty);
  return Math.max(0, Math.min(100, score));
}

function expectedValueLabel(job) {
  const value = expectedValueScore(job);
  return value > 0 ? `${value.toFixed(1)}/100` : "N/A";
}

function recommendationScore(job, distanceCap = 35) {
  const compatibility = compatibilityScore10(job) / 10;
  const interview = interviewScore10(job) / 10;
  const sentiment = Number(job.company_sentiment_score_10 || 5) / 10;
  const expected = expectedValueScore(job) / 100;

  const annual = annualizedSalary(job);
  let salary = 0.35;
  if (annual != null) {
    if (annual >= 120000) salary = 1;
    else if (annual >= 90000) salary = 0.85;
    else if (annual >= 70000) salary = 0.72;
    else if (annual >= 50000) salary = 0.58;
    else salary = 0.45;
  }

  let location = 0.45;
  if ((job.remote_type || "").toLowerCase() === "remote") {
    location = 0.6;
  } else if (job.distance_miles != null) {
    const d = Number(job.distance_miles);
    const cap = Math.max(10, Number(distanceCap) || 35);
    location = Math.max(0, 1 - d / (cap * 1.2));
  }

  return (
    0.30 * compatibility +
    0.20 * interview +
    0.18 * salary +
    0.12 * location +
    0.08 * sentiment +
    0.12 * expected
  );
}

function typeLabel(job) {
  return (job.job_type || job.remote_type || "unknown").toUpperCase();
}

function companyWebsite(job) {
  const company = (job.company || "").trim().toLowerCase().replace(/[^a-z0-9]/g, "");
  if (job.url) {
    try {
      const u = new URL(job.url);
      const host = u.hostname.toLowerCase();
      if (!host.includes("greenhouse.io") && !host.includes("lever.co")) {
        return `${u.protocol}//${u.hostname}`;
      }
    } catch {
      // Ignore malformed URL.
    }
  }
  return company ? `https://www.${company}.com` : job.url || "#";
}

function dedupeJobs(items) {
  const byKey = new Map();
  for (const item of items || []) {
    const key = item?.id ?? item?.canonical_url ?? item?.url ?? `${item?.title || ""}-${item?.company || ""}`;
    if (!byKey.has(key)) byKey.set(key, item);
  }
  return Array.from(byKey.values());
}

function sortJobs(rows, sortKey, panel = "local") {
  const out = [...(rows || [])];
  out.sort((a, b) => {
    if (sortKey === "expected_value") {
      const diff = expectedValueScore(b) - expectedValueScore(a);
      if (diff !== 0) return diff;
    }
    if (sortKey === "interview") {
      const diff = interviewScore10(b) - interviewScore10(a);
      if (diff !== 0) return diff;
    }
    if (sortKey === "compatibility") {
      const diff = compatibilityScore10(b) - compatibilityScore10(a);
      if (diff !== 0) return diff;
    }
    if (sortKey === "salary") {
      const diff = Number(b.pay_max || b.pay_min || 0) - Number(a.pay_max || a.pay_min || 0);
      if (diff !== 0) return diff;
    }
    if (sortKey === "distance" && panel === "local") {
      const ad = a.distance_miles == null ? 999999 : Number(a.distance_miles);
      const bd = b.distance_miles == null ? 999999 : Number(b.distance_miles);
      const diff = ad - bd;
      if (diff !== 0) return diff;
    }
    const ad = new Date(a.posted_date || 0).getTime();
    const bd = new Date(b.posted_date || 0).getTime();
    return bd - ad;
  });
  return out;
}

function selectedSetFromJobs(jobs) {
  return new Set((jobs || []).map((j) => j.id));
}

function packetTextFromMaterials(job, materials) {
  const ats = (materials?.ats_keywords || []).slice(0, 20);
  const bullets = (materials?.resume_bullet_suggestions || []).slice(0, 6);
  const cover = materials?.cover_letter_draft || "";
  const outreach = materials?.outreach_message_draft || "";

  const lines = [
    `Job: ${job.title || "-"}`,
    `Company: ${job.company || "-"}`,
    `Location: ${job.location_text || "-"}`,
    `Type: ${typeLabel(job)}`,
    `Salary: ${salaryText(job)}`,
    `Expected Value Score: ${expectedValueLabel(job)}`,
    `Listing URL: ${job.url || "-"}`,
    "",
    "ATS Keywords:",
    ...ats.map((x) => `- ${x}`),
    "",
    "Resume Bullet Suggestions:",
    ...bullets.map((x) => `- ${x}`),
    "",
    "Short Cover Note:",
    cover || "(none)",
    "",
    "Outreach Message:",
    outreach || "(none)",
  ];
  return lines.join("\n");
}

async function copyToClipboard(text) {
  if (!text) return false;
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

export default function JobsPage() {
  const [query, setQuery] = useState("");
  const [baseZip, setBaseZip] = useState("44224");
  const [maxDistance, setMaxDistance] = useState("35");
  const [minSalary, setMinSalary] = useState("");
  const [localRemoteType, setLocalRemoteType] = useState("local");

  const [nationwideState, setNationwideState] = useState("");
  const [nationwideCity, setNationwideCity] = useState("");
  const [nationwideZip, setNationwideZip] = useState("");
  const [nationwideRemoteType, setNationwideRemoteType] = useState("any");
  const [minInterviewNationwide, setMinInterviewNationwide] = useState("5.5");
  const [minCompatibilityNationwide, setMinCompatibilityNationwide] = useState("6.5");

  const [localJobs, setLocalJobs] = useState([]);
  const [nationwideJobs, setNationwideJobs] = useState([]);
  const [profileSkills, setProfileSkills] = useState([]);
  const [scoreMode, setScoreMode] = useState("balanced");
  const [lastRescoredAt, setLastRescoredAt] = useState("");

  const [localSort, setLocalSort] = useState("expected_value");
  const [nationwideSort, setNationwideSort] = useState("expected_value");

  const [selectedLocal, setSelectedLocal] = useState(new Set());
  const [selectedNationwide, setSelectedNationwide] = useState(new Set());

  const [loadingLocal, setLoadingLocal] = useState(false);
  const [loadingNationwide, setLoadingNationwide] = useState(false);
  const [errorLocal, setErrorLocal] = useState("");
  const [errorNationwide, setErrorNationwide] = useState("");
  const [notice, setNotice] = useState("");

  const [sprintQueueIds, setSprintQueueIds] = useState([]);
  const [sprintIndex, setSprintIndex] = useState(0);
  const [sprintMinInterview, setSprintMinInterview] = useState("7.5");
  const [sprintMinCompatibility, setSprintMinCompatibility] = useState("6.5");
  const [sprintQueueSize, setSprintQueueSize] = useState("25");
  const [sprintPacketById, setSprintPacketById] = useState({});
  const [loadingSprintPacket, setLoadingSprintPacket] = useState(false);
  const [sprintError, setSprintError] = useState("");

  const localViewJobs = useMemo(() => sortJobs(localJobs, localSort, "local"), [localJobs, localSort]);
  const nationwideViewJobs = useMemo(
    () => sortJobs(nationwideJobs, nationwideSort, "nationwide"),
    [nationwideJobs, nationwideSort]
  );

  const localCount = localViewJobs.length;
  const nationwideCount = nationwideViewJobs.length;
  const applyRecommendations = useMemo(() => {
    const all = dedupeJobs([...localViewJobs, ...nationwideViewJobs]);
    const scored = all
      .map((job) => ({
        ...job,
        _applyScore: recommendationScore(job, parsePositiveNumber(maxDistance) || 35),
      }))
      .sort((a, b) => b._applyScore - a._applyScore);

    const chosen = [];
    const perCompany = new Map();
    for (const row of scored) {
      if (chosen.length >= 5) break;
      const key = String(row.company || "unknown").toLowerCase();
      const count = perCompany.get(key) || 0;
      if (count >= 2) continue;
      perCompany.set(key, count + 1);
      chosen.push(row);
    }
    return chosen;
  }, [localViewJobs, nationwideViewJobs, maxDistance]);

  const jobLookup = useMemo(() => {
    const map = new Map();
    for (const row of [...localJobs, ...nationwideJobs]) {
      map.set(row.id, row);
    }
    return map;
  }, [localJobs, nationwideJobs]);

  const currentSprintJob = useMemo(() => {
    if (!sprintQueueIds.length) return null;
    const id = sprintQueueIds[Math.max(0, Math.min(sprintIndex, sprintQueueIds.length - 1))];
    return jobLookup.get(id) || null;
  }, [sprintQueueIds, sprintIndex, jobLookup]);

  const currentSprintPacket = currentSprintJob ? sprintPacketById[currentSprintJob.id] || "" : "";

  const refreshLocal = async ({ quick = false, background = false } = {}) => {
    if (!background) {
      setLoadingLocal(true);
      setErrorLocal("");
    }
    try {
      const hasQuery = Boolean(String(query || "").trim());
      let rows = [];
      if (quick && !hasQuery) {
        const recommendationParams = {
          limit: Math.min(LOCAL_QUICK_LIMIT, LOCAL_LIMIT),
          base_zip: String(baseZip || "").trim() || null,
          max_distance: parsePositiveNumber(maxDistance),
          min_salary: parsePositiveNumber(minSalary),
          remote_type: localRemoteType,
          salary_required: true,
          exclude_confidential: true,
        };
        try {
          rows = await api.getRecommendations(recommendationParams, { timeoutMs: 25000 });
        } catch {
          rows = await api.searchJobs({
            query: null,
            base_zip: recommendationParams.base_zip,
            max_distance: recommendationParams.max_distance,
            min_salary: recommendationParams.min_salary,
            remote_type: recommendationParams.remote_type,
            salary_required: recommendationParams.salary_required,
            exclude_confidential: recommendationParams.exclude_confidential,
            pages: LOCAL_QUICK_PAGES,
            limit: LOCAL_QUICK_LIMIT,
          });
          if (!background) {
            setNotice("Saved local matches were slow. Showing a fresh local search instead.");
          }
        }
      } else {
        rows = await api.searchJobs({
          query: String(query || "").trim() || null,
          base_zip: String(baseZip || "").trim() || null,
          max_distance: parsePositiveNumber(maxDistance),
          min_salary: parsePositiveNumber(minSalary),
          remote_type: localRemoteType,
          salary_required: true,
          exclude_confidential: true,
          pages: quick ? LOCAL_QUICK_PAGES : LOCAL_PAGES,
          limit: quick ? LOCAL_QUICK_LIMIT : LOCAL_LIMIT,
        });
      }
      if ((rows || []).length > 0 || !background) {
        startTransition(() => {
          setLocalJobs(dedupeJobs(rows || []));
          setSelectedLocal(new Set());
        });
      }
    } catch (e) {
      if (!background) setErrorLocal(e.message || "Failed to load local jobs.");
    } finally {
      if (!background) setLoadingLocal(false);
    }
  };

  const refreshNationwide = async ({ refreshPool = true, background = false } = {}) => {
    if (!background) {
      setLoadingNationwide(true);
      setErrorNationwide("");
    }
    try {
      const rows = await api.getNationalRecommendations({
        query: String(query || "").trim() || null,
        city: String(nationwideCity || "").trim() || null,
        state: String(nationwideState || "").trim() || null,
        zip_code: String(nationwideZip || "").trim() || null,
        base_zip: String(baseZip || "").trim() || null,
        max_distance: parsePositiveNumber(maxDistance),
        min_salary: parsePositiveNumber(minSalary),
        remote_type: nationwideRemoteType,
        salary_required: true,
        exclude_confidential: true,
        min_interview_score_10: parseBoundedScore(minInterviewNationwide, 8),
        min_compatibility_score_10: parseBoundedScore(minCompatibilityNationwide, 7),
        limit: NATIONWIDE_LIMIT,
        pages_per_region: 2,
        refresh_pool: refreshPool,
        adaptive_thresholds: true,
      });
      startTransition(() => {
        setNationwideJobs(dedupeJobs(rows || []));
        setSelectedNationwide(new Set());
      });
    } catch (e) {
      if (refreshPool) {
        try {
          const fallbackRows = await api.getNationalRecommendations({
            query: String(query || "").trim() || null,
            city: String(nationwideCity || "").trim() || null,
            state: String(nationwideState || "").trim() || null,
            zip_code: String(nationwideZip || "").trim() || null,
            base_zip: String(baseZip || "").trim() || null,
            max_distance: parsePositiveNumber(maxDistance),
            min_salary: parsePositiveNumber(minSalary),
            remote_type: nationwideRemoteType,
            salary_required: true,
            exclude_confidential: true,
            min_interview_score_10: parseBoundedScore(minInterviewNationwide, 8),
            min_compatibility_score_10: parseBoundedScore(minCompatibilityNationwide, 7),
            limit: NATIONWIDE_LIMIT,
            pages_per_region: 1,
            refresh_pool: false,
            adaptive_thresholds: true,
          });
          startTransition(() => {
            setNationwideJobs(dedupeJobs(fallbackRows || []));
            setSelectedNationwide(new Set());
          });
          setErrorNationwide("");
          if (!background) setNotice("Nationwide search timed out, showing the best saved recommendations instead.");
          return;
        } catch {
          // Fall through to primary error.
        }
      }
      if (!background) setErrorNationwide(e.message || "Failed to load nationwide recommendations.");
    } finally {
      if (!background) setLoadingNationwide(false);
    }
  };

  const searchJobs = async () => {
    setNotice("Searching local jobs first...");
    await refreshLocal({ quick: true, background: false });
    setNotice("Local jobs loaded. Searching nationwide recommendations...");

    void (async () => {
      await refreshNationwide({ refreshPool: false, background: false });
    })();

    void (async () => {
      await refreshLocal({ quick: false, background: true });
      await refreshNationwide({ refreshPool: true, background: true });
      setNotice("Search updated with broader results.");
    })();
  };

  const loadInitialJobs = async () => {
    setNotice("Loading your best local matches...");
    await refreshLocal({ quick: true, background: false });
    setNotice("Local matches ready. Loading saved nationwide recommendations...");
    void refreshNationwide({ refreshPool: false, background: false });
  };

  function applySearchPreset(preset) {
    if (preset === "closest") {
      setLocalSort("distance");
      setLocalRemoteType("local");
      setNotice("Preset applied: Closest local jobs.");
    } else if (preset === "interview") {
      setLocalSort("interview");
      setNotice("Preset applied: Highest interview odds.");
    } else if (preset === "pay_local") {
      setLocalSort("salary");
      setLocalRemoteType("local");
      setNotice("Preset applied: Highest paying local jobs.");
    }
    void refreshLocal({ quick: true });
  }

  useEffect(() => {
    api
      .getProfile()
      .then((p) => {
        if (p?.zip_code) setBaseZip(p.zip_code);
        if (p?.distance_miles) setMaxDistance(String(Math.round(Number(p.distance_miles) || 35)));
        setProfileSkills(Array.isArray(p?.skills) ? p.skills : []);
        if (p?.score_tuning_mode) setScoreMode(String(p.score_tuning_mode).toLowerCase());
        if (p?.last_rescored_at) setLastRescoredAt(p.last_rescored_at);
        setTimeout(() => {
          loadInitialJobs();
        }, 0);
      })
      .catch(() => {
        setTimeout(() => {
          loadInitialJobs();
        }, 0);
      });
  }, []);

  const allLocalSelected = useMemo(
    () => localViewJobs.length > 0 && localViewJobs.every((j) => selectedLocal.has(j.id)),
    [localViewJobs, selectedLocal]
  );

  const allNationwideSelected = useMemo(
    () => nationwideViewJobs.length > 0 && nationwideViewJobs.every((j) => selectedNationwide.has(j.id)),
    [nationwideViewJobs, selectedNationwide]
  );

  function applyStatusToLists(ids, status) {
    setLocalJobs((prev) => prev.map((j) => (ids.has(j.id) ? { ...j, status } : j)));
    setNationwideJobs((prev) => prev.map((j) => (ids.has(j.id) ? { ...j, status } : j)));
  }

  function removeFromLists(ids) {
    setLocalJobs((prev) => prev.filter((j) => !ids.has(j.id)));
    setNationwideJobs((prev) => prev.filter((j) => !ids.has(j.id)));
  }

  function openJobListing(job) {
    if (!job?.url) return;
    window.open(job.url, "_blank", "noopener,noreferrer");
  }

  async function ensureSprintPacket(job) {
    if (!job) return "";
    if (sprintPacketById[job.id]) return sprintPacketById[job.id];
    setLoadingSprintPacket(true);
    setSprintError("");
    try {
      const materials = await api.generateMaterials(job.id, {
        profile_skills: profileSkills,
        experience_areas: profileSkills.slice(0, 10),
        include_cover_letter: true,
      });
      const text = packetTextFromMaterials(job, materials);
      setSprintPacketById((prev) => ({ ...prev, [job.id]: text }));
      return text;
    } catch (e) {
      const msg = e.message || "Failed to generate apply packet.";
      setSprintError(msg);
      return "";
    } finally {
      setLoadingSprintPacket(false);
    }
  }

  async function copySprintPacket(job) {
    if (!job) return;
    const text = await ensureSprintPacket(job);
    if (!text) return;
    const ok = await copyToClipboard(text);
    setNotice(ok ? "Apply packet copied to clipboard." : "Could not copy packet to clipboard.");
  }

  function buildSprintQueue() {
    setSprintError("");
    const candidates = dedupeJobs([...localViewJobs, ...nationwideViewJobs]);
    const minInterview = parseBoundedScore(sprintMinInterview, 7.5);
    const minCompatibility = parseBoundedScore(sprintMinCompatibility, 6.5);
    const size = Math.max(5, Math.min(SPRINT_QUEUE_MAX, Number(sprintQueueSize) || 25));

    let filtered = candidates.filter(
      (j) =>
        interviewScore10(j) >= minInterview &&
        compatibilityScore10(j) >= minCompatibility &&
        annualizedSalary(j) != null
    );
    if (filtered.length < Math.min(10, size)) {
      filtered = candidates.filter(
        (j) => interviewScore10(j) >= Math.max(6.5, minInterview - 0.7) && compatibilityScore10(j) >= Math.max(5.8, minCompatibility - 0.7)
      );
    }

    const ranked = sortJobs(filtered, "expected_value", "nationwide");
    const ids = ranked.slice(0, size).map((j) => j.id);
    setSprintQueueIds(ids);
    setSprintIndex(0);
    setNotice(`Sprint queue built with ${ids.length} jobs.`);
  }

  async function applyCurrentAndNext() {
    if (!currentSprintJob) return;
    setSprintError("");
    openJobListing(currentSprintJob);
    await copySprintPacket(currentSprintJob);

    try {
      await api.bulkAction([currentSprintJob.id], "apply");
      applyStatusToLists(new Set([currentSprintJob.id]), "applied");
      setNotice(`Applied ${currentSprintJob.title} and moved to next job.`);
      if (sprintIndex < sprintQueueIds.length - 1) {
        setSprintIndex((i) => i + 1);
      }
    } catch (e) {
      setSprintError(e.message || "Failed to mark sprint job as applied.");
    }
  }

  async function quickApplyPanel(panel) {
    const sourceJobs = panel === "local" ? localViewJobs : nationwideViewJobs;
    const selected = panel === "local" ? selectedLocal : selectedNationwide;
    const ids = selected.size > 0 ? Array.from(selected) : sourceJobs.map((j) => j.id);
    if (ids.length === 0) return;

    const idSet = new Set(ids);
    const jobsToOpen = sourceJobs.filter((j) => idSet.has(j.id) && j.url).slice(0, 40);
    jobsToOpen.forEach((job) => openJobListing(job));

    try {
      await api.bulkAction(ids, "apply");
      applyStatusToLists(idSet, "applied");
      if (panel === "local") setSelectedLocal(new Set());
      else setSelectedNationwide(new Set());

      const openedText = jobsToOpen.length ? `Opened ${jobsToOpen.length} listing tabs and ` : "";
      const capped = ids.length > jobsToOpen.length && jobsToOpen.length === 40;
      setNotice(
        `${openedText}marked ${ids.length} job(s) as applied.${capped ? " (Tab opening capped at 40 per click.)" : ""}`
      );
    } catch (e) {
      if (panel === "local") setErrorLocal(e.message || "Quick apply failed.");
      else setErrorNationwide(e.message || "Quick apply failed.");
    }
  }

  async function runBulkAction(panel, action) {
    const ids = panel === "local" ? Array.from(selectedLocal) : Array.from(selectedNationwide);
    if (ids.length === 0) return;
    try {
      await api.bulkAction(ids, action);
      const idSet = new Set(ids);
      if (action === "delete") {
        removeFromLists(idSet);
      } else if (action === "apply") {
        applyStatusToLists(idSet, "applied");
      } else if (action === "save") {
        applyStatusToLists(idSet, "saved");
      } else if (action === "not_interested") {
        applyStatusToLists(idSet, "rejected");
      }

      if (panel === "local") setSelectedLocal(new Set());
      else setSelectedNationwide(new Set());

      setNotice(`Applied ${action} to ${ids.length} job(s).`);
    } catch (e) {
      setNotice("");
      if (panel === "local") setErrorLocal(e.message || "Bulk action failed.");
      else setErrorNationwide(e.message || "Bulk action failed.");
    }
  }

  async function saveRecommendedJob(job) {
    if (!job?.id) return;
    try {
      await api.bulkAction([job.id], "save");
      applyStatusToLists(new Set([job.id]), "saved");
      setNotice(`Saved ${job.title}.`);
    } catch (e) {
      setNotice("");
      setErrorLocal(e.message || "Save failed.");
    }
  }

  function toggleSprintJob(jobId) {
    setSprintQueueIds((prev) => {
      if (prev.includes(jobId)) return prev.filter((id) => id !== jobId);
      const next = [...prev, jobId];
      return next.slice(0, SPRINT_QUEUE_MAX);
    });
  }

  function JobListPanel({
    title,
    subtitle,
    jobs,
    selected,
    setSelected,
    allSelected,
    loading,
    error,
    panelKey,
    sortValue,
    setSortValue,
    sortOptions,
  }) {
    return (
      <Card className="h-full">
        <CardHeader className="pb-3">
          <CardTitle>{title}</CardTitle>
          <CardDescription>{subtitle}</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="mb-3 flex flex-wrap items-center gap-2 border-b pb-3">
            <span className="text-xs text-muted-foreground">{jobs.length} jobs</span>
            <span className="text-xs text-muted-foreground">{selected.size} selected</span>
            <Select className="w-52" value={sortValue} onChange={(e) => setSortValue(e.target.value)}>
              {sortOptions.map((opt) => (
                <option key={`${panelKey}-${opt.value}`} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </Select>
            <Button size="sm" variant="outline" onClick={() => setSelected(selectedSetFromJobs(jobs))}>
              Select all
            </Button>
            <Button size="sm" variant="outline" onClick={() => setSelected(new Set())}>
              Clear
            </Button>
            <Button size="sm" variant="secondary" onClick={() => quickApplyPanel(panelKey)}>
              1-Click Quick Apply
            </Button>
            <Button size="sm" onClick={() => runBulkAction(panelKey, "save")}>
              Save
            </Button>
            <Button size="sm" variant="secondary" onClick={() => runBulkAction(panelKey, "apply")}>
              Apply
            </Button>
            <Button size="sm" variant="outline" onClick={() => runBulkAction(panelKey, "not_interested")}>
              Not Interested
            </Button>
            <Button size="sm" variant="destructive" onClick={() => runBulkAction(panelKey, "delete")}>
              Delete
            </Button>
            <label className="ml-auto inline-flex items-center gap-2 text-xs text-muted-foreground">
              <input
                type="checkbox"
                checked={allSelected}
                onChange={(e) => (e.target.checked ? setSelected(selectedSetFromJobs(jobs)) : setSelected(new Set()))}
              />
              all
            </label>
          </div>

          {loading ? <p className="mb-2 text-sm text-muted-foreground">Searching jobs...</p> : null}
          {error ? <p className="mb-2 text-sm text-red-600">{error}</p> : null}

          <div className="max-h-[68vh] space-y-2 overflow-y-auto pr-1">
            {!loading && jobs.length === 0 ? (
              <p className="text-sm text-muted-foreground">No jobs found for current settings.</p>
            ) : null}
            {jobs.map((job) => {
              const checked = selected.has(job.id);
              const inSprint = sprintQueueIds.includes(job.id);
              return (
                <div key={`${panelKey}-${job.id}`} className="rounded-md border p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-start gap-2">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={(e) => {
                          const next = new Set(selected);
                          if (e.target.checked) next.add(job.id);
                          else next.delete(job.id);
                          setSelected(next);
                        }}
                      />
                      <div>
                        <Link href={`/jobs/${job.id}`} className="font-medium text-primary hover:underline">
                          {job.title}
                        </Link>
                        <div className="mt-0.5 text-xs text-muted-foreground">
                          {job.company ? (
                            <a
                              href={companyWebsite(job)}
                              target="_blank"
                              rel="noreferrer"
                              className="inline-flex items-center gap-1 text-primary hover:underline"
                            >
                              {job.company}
                              <ExternalLink className="h-3.5 w-3.5" />
                            </a>
                          ) : (
                            "Unknown company"
                          )}
                        </div>
                        <div className="text-xs text-muted-foreground">{job.location_text || "Location not listed"}</div>
                      </div>
                    </div>
                    <StatusBadge status={job.status} />
                  </div>

                  <div className="mt-3 grid grid-cols-2 gap-2 text-xs md:grid-cols-5">
                    <div>
                      EV: <span className="font-medium">{expectedValueLabel(job)}</span>
                    </div>
                    <div>
                      Final: <span className="font-medium">{Number(job.final_weighted_score || job.score || 0).toFixed(1)}/100</span>
                    </div>
                    <div>Type: <span className="font-medium">{typeLabel(job)}</span></div>
                    <div>Pay Basis: <span className="font-medium">{compensationBasis(job)}</span></div>
                    <div>Salary: <span className="font-medium">{salaryText(job)}</span></div>
                    <div>
                      Distance:{" "}
                      <span className="font-medium">
                        {job.distance_miles != null ? `${job.distance_miles} mi` : job.remote_type === "remote" ? "Remote" : "N/A"}
                      </span>
                    </div>
                    <div>
                      Interview: <span className="font-medium">{job.interview_score_10 != null ? `${job.interview_score_10.toFixed(1)}/10` : "-"}</span>
                      {job.interview_drift_10 != null ? (
                        <span className="ml-1 text-[11px] text-muted-foreground">
                          ({job.interview_drift_10 > 0 ? "+" : ""}{Number(job.interview_drift_10).toFixed(1)})
                        </span>
                      ) : null}
                      <ScoreWhyPopover job={job} metric="interview" />
                    </div>
                    <div>
                      Compatibility:{" "}
                      <span className="font-medium">
                        {job.compatibility_score_10 != null
                          ? `${job.compatibility_score_10.toFixed(1)}/10`
                          : job.potential_match_score_10 != null
                            ? `${job.potential_match_score_10.toFixed(1)}/10`
                            : "-"}
                      </span>
                      {job.compatibility_drift_10 != null ? (
                        <span className="ml-1 text-[11px] text-muted-foreground">
                          ({job.compatibility_drift_10 > 0 ? "+" : ""}{Number(job.compatibility_drift_10).toFixed(1)})
                        </span>
                      ) : null}
                      <ScoreWhyPopover job={job} metric="compatibility" />
                    </div>
                    <div>
                      Sentiment:{" "}
                      <span className="font-medium">{job.company_sentiment_score_10 != null ? `${job.company_sentiment_score_10.toFixed(1)}/10` : "-"}</span>
                    </div>
                    <div>
                      Role family: <span className="font-medium">{job.role_family_label || "General fallback"}</span>
                    </div>
                    <div>
                      Strategy: <span className="font-medium">{job.strategy_tag || "Review"}</span>
                    </div>
                    <div>
                      Confidence: <span className="font-medium">{job.confidence_score != null ? `${Number(job.confidence_score).toFixed(0)}%` : "-"}</span>
                    </div>
                    <div>
                      Friction: <span className="font-medium">{job.application_friction_score_10 != null ? `${Number(job.application_friction_score_10).toFixed(1)}/10` : "-"}</span>
                    </div>
                    {job.reason_summary ? (
                      <div className="md:col-span-5 text-muted-foreground">
                        Why ranked: {job.reason_summary}
                      </div>
                    ) : null}
                    <div className="flex flex-wrap gap-2">
                      {job.url ? (
                        <a href={job.url} target="_blank" rel="noreferrer" className="text-primary hover:underline">
                          Listing
                        </a>
                      ) : null}
                      <Link href={`/jobs/${job.id}`} className="text-primary hover:underline">
                        Details
                      </Link>
                      <button
                        type="button"
                        className="text-primary hover:underline"
                        onClick={() => toggleSprintJob(job.id)}
                      >
                        {inSprint ? "Remove from Sprint" : "Add to Sprint"}
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <section className="space-y-4">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Split Job Explorer</h1>
        <p className="text-sm text-muted-foreground">
          Left panel: local jobs matching your search settings. Right panel: most recommended nationwide.
        </p>
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span className="rounded-full border px-2 py-0.5">Score mode: {scoreMode}</span>
          <span className="rounded-full border px-2 py-0.5">Last rescored: {formatDateTime(lastRescoredAt)}</span>
        </div>
      </div>

      {notice ? <p className="text-sm text-emerald-600">{notice}</p> : null}

      <Card>
        <CardHeader>
          <CardTitle>Search Preferences</CardTitle>
          <CardDescription>Set your local preferences and optional nationwide refinement.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-6">
          <Input
            className="md:col-span-2"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search role/company (optional)"
          />
          <Input value={baseZip} onChange={(e) => setBaseZip(e.target.value)} placeholder="Your ZIP" />
          <Input value={maxDistance} onChange={(e) => setMaxDistance(e.target.value)} placeholder="Max miles" type="number" />
          <Input value={minSalary} onChange={(e) => setMinSalary(e.target.value)} placeholder="Minimum salary" type="number" />
          <Select value={localRemoteType} onChange={(e) => setLocalRemoteType(e.target.value)}>
            <option value="local">Local (On-Site + Hybrid)</option>
            <option value="onsite">On-Site</option>
            <option value="hybrid">Hybrid</option>
            <option value="remote">Remote</option>
            <option value="any">Any</option>
          </Select>

          <Input value={nationwideState} onChange={(e) => setNationwideState(e.target.value)} placeholder="Nationwide State (optional)" />
          <Input value={nationwideCity} onChange={(e) => setNationwideCity(e.target.value)} placeholder="Nationwide City (optional)" />
          <Input value={nationwideZip} onChange={(e) => setNationwideZip(e.target.value)} placeholder="Nationwide ZIP (optional)" />
          <Input
            value={minInterviewNationwide}
            onChange={(e) => setMinInterviewNationwide(e.target.value)}
            placeholder="Min interview (0-10)"
            type="number"
            step="0.1"
            min="0"
            max="10"
          />
          <Input
            value={minCompatibilityNationwide}
            onChange={(e) => setMinCompatibilityNationwide(e.target.value)}
            placeholder="Min compatibility (0-10)"
            type="number"
            step="0.1"
            min="0"
            max="10"
          />
          <Select value={nationwideRemoteType} onChange={(e) => setNationwideRemoteType(e.target.value)}>
            <option value="any">Nationwide: Any</option>
            <option value="local">Nationwide: Local</option>
            <option value="onsite">Nationwide: On-Site</option>
            <option value="hybrid">Nationwide: Hybrid</option>
            <option value="remote">Nationwide: Remote</option>
          </Select>

          <div className="md:col-span-6 flex flex-wrap gap-2">
            <Button className="gap-2" onClick={searchJobs}>
              <Search className="h-4 w-4" />
              Search Jobs
            </Button>
            <Button variant="outline" onClick={() => refreshLocal({ quick: true })}>Search Local</Button>
            <Button variant="outline" onClick={() => refreshNationwide({ refreshPool: true })}>
              Search Nationwide
            </Button>
            <Button variant="outline" onClick={() => refreshNationwide({ refreshPool: false })}>
              Use Saved Nationwide
            </Button>
            <Button variant="secondary" onClick={() => applySearchPreset("closest")}>
              Preset: Closest jobs
            </Button>
            <Button variant="secondary" onClick={() => applySearchPreset("interview")}>
              Preset: Highest interview odds
            </Button>
            <Button variant="secondary" onClick={() => applySearchPreset("pay_local")}>
              Preset: Highest pay local
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Sprint Mode Queue</CardTitle>
          <CardDescription>
            Build a high-value queue, generate packet, open listing, mark applied, and advance to next job.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 md:grid-cols-6">
            <Input
              value={sprintMinInterview}
              onChange={(e) => setSprintMinInterview(e.target.value)}
              placeholder="Sprint min interview (0-10)"
              type="number"
              step="0.1"
              min="0"
              max="10"
            />
            <Input
              value={sprintMinCompatibility}
              onChange={(e) => setSprintMinCompatibility(e.target.value)}
              placeholder="Sprint min compatibility (0-10)"
              type="number"
              step="0.1"
              min="0"
              max="10"
            />
            <Input
              value={sprintQueueSize}
              onChange={(e) => setSprintQueueSize(e.target.value)}
              placeholder="Queue size"
              type="number"
              min="5"
              max={String(SPRINT_QUEUE_MAX)}
            />
            <div className="md:col-span-3 flex flex-wrap gap-2">
              <Button className="gap-2" onClick={buildSprintQueue}>
                <WandSparkles className="h-4 w-4" />
                Build Sprint Queue
              </Button>
              <Button variant="outline" onClick={() => setSprintQueueIds([])}>
                Clear Queue
              </Button>
            </div>
          </div>

          <div className="text-xs text-muted-foreground">
            Queue size: {sprintQueueIds.length} | Current position: {sprintQueueIds.length ? sprintIndex + 1 : 0}
          </div>
          {sprintError ? <p className="text-sm text-red-600">{sprintError}</p> : null}

          {currentSprintJob ? (
            <div className="space-y-3 rounded-md border p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="text-sm font-semibold">{currentSprintJob.title}</div>
                  <div className="text-xs text-muted-foreground">{currentSprintJob.company || "Unknown company"}</div>
                </div>
                <div className="text-xs text-muted-foreground">
                  EV {expectedValueLabel(currentSprintJob)} | Interview {interviewScore10(currentSprintJob).toFixed(1)}/10 | Compatibility {compatibilityScore10(currentSprintJob).toFixed(1)}/10 | {currentSprintJob.strategy_tag || "Apply now"}
                </div>
              </div>

              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="outline" onClick={() => openJobListing(currentSprintJob)}>
                  Open Listing
                </Button>
                <Button size="sm" variant="outline" onClick={() => ensureSprintPacket(currentSprintJob)} disabled={loadingSprintPacket}>
                  Generate Packet
                </Button>
                <Button size="sm" variant="outline" className="gap-1" onClick={() => copySprintPacket(currentSprintJob)}>
                  <Clipboard className="h-3.5 w-3.5" />
                  Copy Packet
                </Button>
                <Button size="sm" className="gap-1" onClick={applyCurrentAndNext}>
                  <SkipForward className="h-3.5 w-3.5" />
                  Apply + Next
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setSprintIndex((i) => Math.min(sprintQueueIds.length - 1, i + 1))}
                  disabled={sprintIndex >= sprintQueueIds.length - 1}
                >
                  Next
                </Button>
              </div>

              <textarea
                className="min-h-48 w-full rounded-md border bg-card p-3 text-xs"
                readOnly
                value={currentSprintPacket || "Generate packet to view/edit copy-ready application text."}
              />
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">Build a sprint queue to start fast sequential applications.</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Jobs We Recommend You Apply To!</CardTitle>
          <CardDescription>
            Top 5 picks based on compatibility, interview potential, salary, distance/location, and company sentiment.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {applyRecommendations.length === 0 ? (
            <p className="text-sm text-muted-foreground">Searching top recommendations...</p>
          ) : (
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
              {applyRecommendations.map((job) => (
                <div key={`apply-rec-${job.id}`} className="rounded-md border p-3">
                  <Link href={`/jobs/${job.id}`} className="line-clamp-2 text-sm font-semibold text-primary hover:underline">
                    {job.title}
                  </Link>
                  <p className="mt-1 text-xs text-muted-foreground">{job.company || "Unknown company"}</p>
                  <p className="text-xs text-muted-foreground">{job.location_text || "Location not listed"}</p>
                  <div className="mt-2 space-y-1 text-xs">
                    <div>EV: <span className="font-medium">{expectedValueLabel(job)}</span></div>
                    <div>Salary: <span className="font-medium">{salaryText(job)}</span></div>
                    <div>Compatibility: <span className="font-medium">{compatibilityScore10(job).toFixed(1)}/10</span></div>
                    <div>Interview: <span className="font-medium">{interviewScore10(job).toFixed(1)}/10</span></div>
                    <div>Sentiment: <span className="font-medium">{Number(job.company_sentiment_score_10 || 0).toFixed(1)}/10</span></div>
                    <div>Strategy: <span className="font-medium">{job.strategy_tag || "Apply now"}</span></div>
                    <div>
                      Distance:{" "}
                      <span className="font-medium">
                        {job.distance_miles != null ? `${job.distance_miles} mi` : job.remote_type === "remote" ? "Remote" : "N/A"}
                      </span>
                    </div>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {job.url ? (
                      <Button size="sm" variant="outline" onClick={() => openJobListing(job)}>
                        Open Listing
                      </Button>
                    ) : null}
                    <Button size="sm" onClick={() => saveRecommendedJob(job)}>
                      Save
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <JobListPanel
          title={`Local Matches (${localCount})`}
          subtitle="Jobs near your ZIP and radius, matching your search settings."
          jobs={localViewJobs}
          selected={selectedLocal}
          setSelected={setSelectedLocal}
          allSelected={allLocalSelected}
          loading={loadingLocal}
          error={errorLocal}
          panelKey="local"
          sortValue={localSort}
          setSortValue={setLocalSort}
          sortOptions={SORT_OPTIONS_LOCAL}
        />

        <JobListPanel
          title={`Top Nationwide Recommended (${nationwideCount})`}
          subtitle="Highest-fit recommendations across the U.S. with your score thresholds."
          jobs={nationwideViewJobs}
          selected={selectedNationwide}
          setSelected={setSelectedNationwide}
          allSelected={allNationwideSelected}
          loading={loadingNationwide}
          error={errorNationwide}
          panelKey="nationwide"
          sortValue={nationwideSort}
          setSortValue={setNationwideSort}
          sortOptions={SORT_OPTIONS_NATIONWIDE}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Strategy Guide</CardTitle>
            <CardDescription>What each application strategy tag is telling you to do.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            {STRATEGY_EXPLANATIONS.map(([label, copy]) => (
              <div key={label} className="rounded-md border p-3">
                <p className="font-medium">{label}</p>
                <p className="mt-1 text-muted-foreground">{copy}</p>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Score Glossary</CardTitle>
            <CardDescription>Quick definitions for the decision signals used across the page.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            {TERM_DEFINITIONS.map(([label, copy]) => (
              <div key={label} className="rounded-md border p-3">
                <p className="font-medium">{label}</p>
                <p className="mt-1 text-muted-foreground">{copy}</p>
              </div>
            ))}
            <div className="rounded-md border border-dashed p-3 text-muted-foreground">
              Goal: prioritize the jobs that are the best mix of compatibility, pay, and realistic interview odds so you can apply faster with less wasted effort.
            </div>
          </CardContent>
        </Card>
      </div>
    </section>
  );
}
