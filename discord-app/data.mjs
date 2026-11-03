// Public read-only GitHub Issues adapter. No write permissions or trading API.
import { centralDay, safeText } from "./commands.mjs";

const API = "https://api.github.com";
const REPO = "stelladeecoder/statrally-soccer-automation";
const BOT = "github-actions[bot]";
const DELIVERY = "Discord delivery returned success. Paper signal posted; outcome pending.";
const ALLOWED = new Set([
  "league", "espn_event_id", "espn_home_team_id", "espn_away_team_id",
  "home_team", "away_team", "kickoff_utc", "observed_at_utc", "side",
  "market_ticker", "model_probability", "market_price", "fixture_verified", "quote_verified",
]);

export async function readGitHub(path, { fetcher = fetch } = {}) {
  if (!/^\/(repos\/stelladeecoder\/statrally-soccer-automation\/issues(?:\?|\/\d+\/comments\?))/.test(path)) {
    throw new Error("Unsupported public source path");
  }
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5500);
  try {
    const response = await fetcher(API + path, {
      headers: { Accept: "application/vnd.github+json", "User-Agent": "StatRally-Discord/0.1" },
      signal: controller.signal,
    });
    if (!response.ok) throw new Error("Public GitHub source unavailable (" + response.status + ")");
    const result = await response.json();
    if (!Array.isArray(result)) throw new Error("Invalid GitHub source");
    return result;
  } finally {
    clearTimeout(timeout);
  }
}

export async function issuePages({ fetcher = fetch, maxPages = 4 } = {}) {
  const result = [];
  for (let page = 1; page <= maxPages; page++) {
    const batch = await readGitHub(
      `/repos/${REPO}/issues?state=all&per_page=100&page=${page}`, { fetcher });
    result.push(...batch);
    if (batch.length < 100) return result;
  }
  throw new Error("Issue history exceeds read limit; refusing incomplete results");
}

function recordFromIssue(issue) {
  if (!issue || issue.pull_request || issue.user?.login !== BOT) return null;
  const lines = String(issue.body || "").split("\n");
  const raw = lines.find((line) => line.startsWith("statrally-beta-data:"));
  if (!raw || !lines.some(line => line.startsWith("statrally-beta-id:"))) return null;
  let signal;
  try {
    signal = JSON.parse(raw.slice("statrally-beta-data:".length));
  } catch {
    return null;
  }
  if (!signal || typeof signal !== "object" || Array.isArray(signal)) return null;
  if (Object.keys(signal).some(key => !ALLOWED.has(key))) return null;
  if (signal.fixture_verified !== true || signal.quote_verified !== true) return null;
  for (const key of ["home_team", "away_team", "league", "market_ticker", "espn_event_id", "kickoff_utc", "observed_at_utc"]) {
    if (typeof signal[key] !== "string" || !signal[key].trim()) return null;
  }
  if (!/^\d{1,20}$/.test(signal.espn_event_id) || !["YES", "NO"].includes(signal.side)) return null;
  const kickoff = new Date(signal.kickoff_utc);
  const observed = new Date(signal.observed_at_utc);
  if (Number.isNaN(kickoff.getTime()) || Number.isNaN(observed.getTime()) ||
      !/[zZ]|[+-]\d\d:\d\d$/.test(signal.kickoff_utc) ||
      !/[zZ]|[+-]\d\d:\d\d$/.test(signal.observed_at_utc)) return null;
  if (!(observed < kickoff)) return null;
  if (!Number.isInteger(issue.number) || issue.number < 1) return null;
  return { number: issue.number, signal, kickoff, observed, created_at: issue.created_at };
}

function reservationMatches(record, issue) {
  const marker = `statrally-beta-id:${record.signal.market_ticker}|${record.signal.side}|`;
  return String(issue.body || "").split("\n").some(line => line.startsWith(marker) &&
    new Date(line.slice(marker.length)).getTime() === record.kickoff.getTime());
}

export async function deliveredRecords({ fetcher = fetch, day = null, eventId = null } = {}) {
  const issues = await issuePages({ fetcher });
  const candidates = [];
  for (const issue of issues) {
    const item = recordFromIssue(issue);
    if (!item || !reservationMatches(item, issue)) continue;
    if (day && centralDay(item.kickoff) !== day) continue;
    if (eventId && item.signal.espn_event_id !== eventId) continue;
    candidates.push(item);
  }
  // The command displays only the official three most recent confirmed records.
  // Do not turn a requested match into another official prediction.
  const selected = candidates.slice(0, eventId ? 20 : 20);
  const delivered = [];
  for (const item of selected) {
    const comments = await readGitHub(
      `/repos/${REPO}/issues/${item.number}/comments?per_page=100&page=1`, { fetcher });
    const confirmed = comments.some(comment => comment.user?.login === BOT &&
      typeof comment.body === "string" &&
      comment.body.startsWith(DELIVERY + "\nstatrally-beta-delivery-proof:") &&
      /^[a-f0-9]{64}$/.test(comment.body.slice((DELIVERY + "\nstatrally-beta-delivery-proof:").length).trim()) &&
      !comment.body.includes("\n", (DELIVERY + "\nstatrally-beta-delivery-proof:").length));
    if (confirmed) delivered.push(item);
  }
  return delivered.sort((a,b) => a.kickoff - b.kickoff);
}

export async function savedPerformance({ fetcher = fetch } = {}) {
  const issues = await issuePages({ fetcher });
  const dashboards = issues.filter(item => item?.user?.login === BOT &&
    item.title === "StatRally BETA | experimental paper performance" && !item.pull_request);
  if (dashboards.length !== 1) return null;
  const issue = dashboards[0];
  const body = String(issue.body || "");
  const match = body.match(/Graded: (\d+) \| Wins: (\d+) \| Losses: (\d+) \| Pending: (\d+)/);
  if (!match) return null;
  const [graded, wins, losses, pending] = match.slice(1).map(Number);
  if (!Number.isSafeInteger(graded) || !Number.isSafeInteger(wins) ||
      !Number.isSafeInteger(losses) || !Number.isSafeInteger(pending) ||
      graded !== wins + losses) return null;
  const hit = body.match(/Hit rate: ([\d.]+|None)/);
  const brier = body.match(/Brier score \(where probabilities available\): ([\d.]+|N\/A)/);
  return { graded, wins, losses, pending,
    hit: hit?.[1] ?? "not available", brier: brier?.[1] ?? "not available",
    updated: issue.updated_at || "unknown" };
}

export function renderPick(record) {
  const s = record.signal;
  const kickoff = record.kickoff.toISOString();
  const observed = record.observed.toISOString();
  const probability = Number(s.model_probability);
  const p = Number.isFinite(probability) && probability >= 0 && probability <= 1
    ? " | Model estimate " + (probability * 100).toFixed(1) + "%" : "";
  return `• **${safeText(s.home_team)} vs ${safeText(s.away_team)}** | BTTS ${s.side}${p}\n  ${safeText(s.league)} · kickoff ${kickoff} · quote observed ${observed} · ESPN ${s.espn_event_id}`;
}
