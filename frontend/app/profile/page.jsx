"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";

const MODE_INDEX = { strict: 0, balanced: 1, aggressive: 2 };
const INDEX_MODE = ["strict", "balanced", "aggressive"];
const DEFAULT_HOBBIES = [
  "Cryptocurrency",
  "Rock Climbing",
  "Video Games",
  "Smoking Marijuana",
  "Pokemon",
  "Working Out/Staying Active",
  "Taking Care of Plants",
  "VibeCoding applications",
  "Thrifting",
  "Driving",
  "Music",
];

function modeText(mode) {
  const normalized = (mode || "balanced").toLowerCase();
  if (normalized === "strict") return "Strict: harder grading, lower optimism.";
  if (normalized === "aggressive") return "Aggressive: optimistic interview scoring.";
  return "Balanced: recommended default.";
}

function fmtDate(iso) {
  if (!iso) return "Never";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "Never";
  return d.toLocaleString();
}

export default function ProfilePage() {
  const [profile, setProfile] = useState({
    full_name: "",
    email: "",
    phone: "",
    zip_code: "44224",
    distance_miles: 30,
    skills: [],
    hobbies: [],
    score_tuning_mode: "balanced",
  });
  const [skillsText, setSkillsText] = useState("");
  const [hobbiesText, setHobbiesText] = useState(DEFAULT_HOBBIES.join(", "));
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getProfile().then((p) => {
      const hobbies = (p.hobbies || []).length ? p.hobbies : DEFAULT_HOBBIES;
      setProfile({ ...p, hobbies });
      setSkillsText((p.skills || []).join(", "));
      setHobbiesText(hobbies.join(", "));
      setLoading(false);
    });
  }, []);

  async function saveProfile() {
    try {
      const payload = {
        ...profile,
        skills: skillsText
          .split(",")
          .map((x) => x.trim())
          .filter(Boolean),
        hobbies: hobbiesText
          .split(",")
          .map((x) => x.trim())
          .filter(Boolean),
      };
      const updated = await api.updateProfile(payload);
      setProfile(updated);
      setSkillsText((updated.skills || []).join(", "));
      setHobbiesText((updated.hobbies || []).join(", "));
      setMessage("Profile saved. Hobbies stay private and are only used for your internal recommendations.");
    } catch (e) {
      setMessage(`Failed to save profile: ${e.message}`);
    }
  }

  async function rescoreAllNow() {
    try {
      const result = await api.rescoreAllJobs();
      if (result?.last_rescored_at) {
        setProfile((p) => ({ ...p, last_rescored_at: result.last_rescored_at }));
      }
      setMessage(`Rescored ${result?.rescored_count || 0} jobs using ${result?.score_tuning_mode || "balanced"} mode.`);
    } catch (e) {
      setMessage(`Rescore failed: ${e.message}`);
    }
  }

  async function onResumeUpload(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const result = await api.uploadResume(file);
      const refreshed = await api.getProfile();
      setProfile(refreshed);
      setSkillsText((refreshed.skills || []).join(", "));
      if (result?.warning) {
        setMessage(`Resume uploaded, but text extraction failed. ${result.warning}`);
      } else {
        setMessage(`Resume uploaded. Extracted ${result?.extracted_skills_count || 0} skills. Click Rescore All Jobs Now to refresh grades.`);
      }
    } catch (err) {
      setMessage(`Resume upload failed: ${err.message}`);
    }
  }

  if (loading) return <p className="text-sm text-muted-foreground">Loading profile...</p>;

  return (
    <section className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Profile Setup</h1>
        <p className="text-sm text-muted-foreground">Set your basics once. We use ZIP and distance to keep jobs local and clear.</p>
      </div>

      {message ? <p className="text-sm text-emerald-600">{message}</p> : null}

      <Card>
        <CardHeader>
          <CardTitle>Your Info</CardTitle>
          <CardDescription>Easy settings for matching, scoring, and applications.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2">
          <Input placeholder="Full name" value={profile.full_name || ""} onChange={(e) => setProfile((p) => ({ ...p, full_name: e.target.value }))} />
          <Input placeholder="Email" value={profile.email || ""} onChange={(e) => setProfile((p) => ({ ...p, email: e.target.value }))} />
          <Input placeholder="Phone" value={profile.phone || ""} onChange={(e) => setProfile((p) => ({ ...p, phone: e.target.value }))} />
          <Input placeholder="ZIP code" value={profile.zip_code || ""} onChange={(e) => setProfile((p) => ({ ...p, zip_code: e.target.value }))} />
          <Input placeholder="Distance in miles" type="number" value={profile.distance_miles || 35} onChange={(e) => setProfile((p) => ({ ...p, distance_miles: Number(e.target.value || 35) }))} />
          <div className="space-y-1">
            <label className="text-sm font-medium">Interview score tuning</label>
            <input
              type="range"
              min="0"
              max="2"
              step="1"
              value={MODE_INDEX[(profile.score_tuning_mode || "balanced").toLowerCase()] ?? 1}
              onChange={(e) => {
                const idx = Number(e.target.value || 1);
                setProfile((p) => ({ ...p, score_tuning_mode: INDEX_MODE[idx] || "balanced" }));
              }}
              className="w-full"
            />
            <div className="flex justify-between text-[11px] text-muted-foreground">
              <span>Strict</span>
              <span>Balanced</span>
              <span>Aggressive</span>
            </div>
            <p className="text-xs text-muted-foreground">{modeText(profile.score_tuning_mode)}</p>
          </div>
          <Input placeholder="Skills (comma-separated)" value={skillsText} onChange={(e) => setSkillsText(e.target.value)} className="md:col-span-2" />
          <div className="space-y-1 md:col-span-2">
            <Input
              placeholder="Hobbies (comma-separated, private)"
              value={hobbiesText}
              onChange={(e) => setHobbiesText(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Private only: hobbies are a light preference layer (about 8%) and are never included in employer-facing materials.
            </p>
          </div>

          <div className="md:col-span-2 flex items-center gap-3">
            <label className="text-sm font-medium">Upload Resume</label>
            <input type="file" accept=".pdf,.doc,.docx,.txt" onChange={onResumeUpload} />
            {profile.resume_filename ? <span className="text-xs text-muted-foreground">Current: {profile.resume_filename}</span> : null}
          </div>
          <p className="md:col-span-2 text-xs text-muted-foreground">
            Uploading a new resume replaces the previous resume-based skill signal used for scoring. You can still edit skills manually below if needed.
          </p>

          <div className="md:col-span-2 flex flex-wrap gap-2">
            <Button onClick={saveProfile}>Save Profile</Button>
            <Button variant="outline" onClick={rescoreAllNow}>Rescore All Jobs Now</Button>
            <span className="self-center text-xs text-muted-foreground">
              Last rescored: {fmtDate(profile.last_rescored_at)}
            </span>
          </div>
        </CardContent>
      </Card>
    </section>
  );
}
