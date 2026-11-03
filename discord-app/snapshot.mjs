// GitHub's unauthenticated API returns HTTP 403 on some shared hosting IPs.
// On access-denied only, read a recent, publicly published snapshot built by
// authenticated GitHub Actions. Never invent empty picks when the data is stale.
const source = "https://raw.githubusercontent.com/stelladeecoder/statrally-soccer-automation/main/docs/discord-public-snapshot.json";
const api = "https://api.github.com/repos/stelladeecoder/statrally-soccer-automation/issues";
const maxAgeMs = 45 * 60 * 1000;
let cache = null;
let cachedAt = 0;

export async function snapshotBackedFetch(url, options = {}, network = fetch, clock = Date.now) {
  const location = String(url);
  if (options.method && options.method !== "GET") return network(url, options);
  if (!location.startsWith(api)) return network(url, options);
  const result = await network(url, options);
  if (result.status !== 403 && result.status !== 429) return result;
  try {
    const now = clock();
    if (!cache || now - cachedAt >= 60000) {
      const response = await network(source, { headers: { "User-Agent": "StatRally-Discord/0.1" },
        signal: options.signal });
      if (!response.ok) throw new Error("Snapshot unavailable");
      const candidate = await response.json();
      if (candidate?.schema !== 1 || !Array.isArray(candidate.issues) ||
          !candidate.comments || typeof candidate.comments !== "object") throw new Error("Invalid snapshot");
      cache = candidate;
      cachedAt = now;
    }
    const created = Date.parse(cache.generated_at);
    if (!Number.isFinite(created) || created > now + 60000 ||
        now - created > maxAgeMs) throw new Error("Stale snapshot");
    const path = new URL(location).pathname;
    const comments = path.match(/^\/repos\/stelladeecoder\/statrally-soccer-automation\/issues\/(\d+)\/comments$/);
    const issues = path === "/repos/stelladeecoder/statrally-soccer-automation/issues";
    if (!comments && !issues) return result;
    let data;
    if (comments) data = cache.comments[comments[1]] || [];
    else {
      const query = new URL(location).searchParams;
      const page = Number(query.get("page") || "1");
      if (!Number.isInteger(page) || page < 1) return result;
      data = cache.issues.slice((page-1)*100, page*100);
    }
    return new Response(JSON.stringify(data), { status: 200,
      headers: { "Content-Type": "application/json", "X-StatRally-Source": "public-snapshot" } });
  } catch {
    // Keep the original source failure, never substitute an unverified empty list.
    return result;
  }
}
