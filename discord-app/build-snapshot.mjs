// Publish a minimal read-only copy of the already-public, bot-authored Issues.
// Runs only in GitHub Actions with a scoped GITHUB_TOKEN; never sends tokens to Render.
import fs from "node:fs/promises";
const repo = "stelladeecoder/statrally-soccer-automation";
const token = process.env.GITHUB_TOKEN;
if (!token) { console.error("Missing GITHUB_TOKEN"); process.exit(1); }
async function get(path) {
  const response = await fetch("https://api.github.com" + path, {
    headers: { Authorization: "Bearer " + token, Accept: "application/vnd.github+json",
      "User-Agent": "StatRally-Snapshot-Builder/1.0" },
    signal: AbortSignal.timeout(15000),
  });
  if (!response.ok) throw new Error("GitHub source status " + response.status);
  const items = await response.json();
  if (!Array.isArray(items)) throw new Error("Unexpected GitHub response shape");
  return items;
}
const selected = [];
for (let page = 1; page <= 4; page++) {
  const batch = await get(`/repos/${repo}/issues?state=all&per_page=100&page=${page}`);
  for (const item of batch) {
    if (item.pull_request || item.user?.login !== "github-actions[bot]") continue;
    if (!String(item.body || "").includes("statrally-beta-data:") &&
        item.title !== "StatRally BETA | experimental paper performance") continue;
    selected.push({ number: item.number, title: item.title, body: item.body,
      created_at: item.created_at, updated_at: item.updated_at,
      user: { login: "github-actions[bot]" } });
  }
  if (batch.length < 100) break;
  if (page === 4) throw new Error("Issues pagination limit exceeded");
}
const comments = {};
for (const issue of selected) {
  if (!String(issue.body || "").includes("statrally-beta-data:")) continue;
  const batch = await get(`/repos/${repo}/issues/${issue.number}/comments?per_page=100&page=1`);
  if (batch.length === 100) throw new Error("Comment pagination limit exceeded");
  comments[String(issue.number)] = batch.filter(item => item.user?.login === "github-actions[bot]")
    .map(item => ({ user: { login: "github-actions[bot]" }, body: item.body }));
}
const snapshot = { schema: 1, generated_at: new Date().toISOString(), issues: selected, comments };
await fs.mkdir("docs", { recursive: true });
await fs.writeFile("docs/discord-public-snapshot.json", JSON.stringify(snapshot) + "\n");
console.log("Published verified-source snapshot with " + selected.length + " public bot-authored issue entries");
