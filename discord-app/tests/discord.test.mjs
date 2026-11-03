import test from "node:test";
import assert from "node:assert/strict";
import crypto from "node:crypto";
import { once } from "node:events";
import { commands, centralDay, GUIDE } from "../commands.mjs";
import { readGitHub, deliveredRecords, savedPerformance, renderPick } from "../data.mjs";
import { allowedGuildChannel, commandText, createApp, verifyDiscord } from "../server.mjs";

const APP_ID = "123456789012345678";
const CHANNEL_ID = "888888888888888888";
const now = new Date("2026-11-03T18:00:00.000Z");
const record = {
  number: 21, user: { login: "github-actions[bot]" },
  body: [
    "statrally-beta-id:astatc-demo|YES|2026-11-03T21:00:00+00:00",
    'statrally-beta-data:{"away_team":"Away","espn_event_id":"12345","fixture_verified":true,"home_team":"Home","kickoff_utc":"2026-11-03T21:00:00Z","league":"epl","market_ticker":"astatc-demo","model_probability":0.55,"observed_at_utc":"2026-11-03T17:58:00Z","quote_verified":true,"side":"YES"}',
  ].join("\n"),
};
const receipt = {
  user: { login: "github-actions[bot]" },
  body: "Discord delivery returned success. Paper signal posted; outcome pending.\nstatrally-beta-delivery-proof:" + "a".repeat(64),
};
const dashboard = {
  title: "StatRally BETA | experimental paper performance",
  number: 13, user: { login: "github-actions[bot]" },
  body: "Graded: 3 | Wins: 2 | Losses: 1 | Pending: 4\nHit rate: 0.6667\nBrier score (where probabilities available): 0.22",
  updated_at: "2026-11-03T17:30:00Z",
};
function mockFetch({ issueList = [record, dashboard], comments = [receipt], failure = false } = {}) {
  const requests = [];
  const fetcher = async (url, opts = {}) => {
    requests.push({ url: String(url), method: opts.method || "GET", body: opts.body });
    if (failure) return { ok: false, status: 503 };
    if (String(url).includes("/webhooks/")) return { ok: true, status: 200 };
    if (String(url).includes("/comments")) return { ok: true, json: async () => comments };
    return { ok: true, json: async () => issueList };
  };
  return { fetcher, requests };
}

test("global commands support both guild and user installs, with four names", () => {
  assert.deepEqual(commands.map(x => x.name), ["btts", "match", "picks", "performance"]);
  for (const item of commands) {
    assert.deepEqual(item.integration_types, [0, 1]);
    assert.deepEqual(item.contexts, [0, 1, 2]);
  }
  assert.match(GUIDE, /#bot-commands/);
});

test("central timezone date and guild-specific channel restriction", () => {
  assert.equal(centralDay(new Date("2026-11-04T04:00:00Z")), "2026-11-03");
  assert.equal(allowedGuildChannel({ context: 0, channel_id: "111" }, CHANNEL_ID), false);
  assert.equal(allowedGuildChannel({ context: 0, channel_id: CHANNEL_ID }, CHANNEL_ID), true);
  assert.equal(allowedGuildChannel({ context: 2, channel_id: "111" }, CHANNEL_ID), true);
});

test("only bot-authored records with a delivery receipt appear", async () => {
  const { fetcher } = mockFetch();
  const picks = await deliveredRecords({ fetcher, day: "2026-11-03" });
  assert.equal(picks.length, 1);
  assert.match(renderPick(picks[0]), /Home vs Away/);
  const spoofed = mockFetch({ issueList: [{ ...record, user: { login: "stranger" } }] });
  assert.deepEqual(await deliveredRecords({ fetcher: spoofed.fetcher }), []);
  const unconfirmed = mockFetch({ comments: [] });
  assert.deepEqual(await deliveredRecords({ fetcher: unconfirmed.fetcher }), []);
});

test("no false positive with missing or conflicting reservation", async () => {
  const wrong = { ...record, body: record.body.replace("astatc-demo|YES|", "astatc-demo|NO|") };
  const { fetcher } = mockFetch({ issueList: [wrong] });
  assert.deepEqual(await deliveredRecords({ fetcher }), []);
});

test("picks and BTTS return historical saved data, not new picks", async () => {
  const { fetcher, requests } = mockFetch();
  const picks = await commandText({ data: { name: "picks" } }, { fetcher, now });
  assert.match(picks, /Home vs Away/);
  assert.match(picks, /stored records, not a fresh scan/);
  const btts = await commandText({ data: { name: "btts" } }, { fetcher, now });
  assert.match(btts, /planned, not deployed/);
  assert.equal(requests.every(x => x.method === "GET"), true);
});

test("match lookup accepts numeric ESPN IDs only", async () => {
  const { fetcher } = mockFetch();
  const found = await commandText({ data: { name: "match", options: [{ name: "event_id", value: "12345" }] } }, { fetcher });
  assert.match(found, /Recorded fixture/);
  const invalid = await commandText({ data: { name: "match", options: [{ name: "event_id", value: "12345;DROP" }] } }, { fetcher });
  assert.match(invalid, /valid numeric/);
  const absent = await commandText({ data: { name: "match", options: [{ name: "event_id", value: "999" }] } }, { fetcher });
  assert.match(absent, /No confirmed/);
});

test("performance honors saved paper metrics and unknown status", async () => {
  const good = mockFetch();
  const summary = await commandText({ data: { name: "performance" } }, { fetcher: good.fetcher });
  assert.match(summary, /Graded: 3/);
  assert.match(summary, /no real trades/i);
  const none = mockFetch({ issueList: [] });
  assert.match(await commandText({ data: { name: "performance" } }, { fetcher: none.fetcher }), /No independently saved/);
  const malformed = mockFetch({ issueList: [{ ...dashboard, body: "Graded: 2 | Wins: 2 | Losses: 1 | Pending: 0" }] });
  assert.equal(await savedPerformance({ fetcher: malformed.fetcher }), null);
});

test("source failure does not turn into an empty-day claim", async () => {
  const bad = mockFetch({ failure: true });
  await assert.rejects(() => commandText({ data: { name: "picks" } }, { fetcher: bad.fetcher, now }), /unavailable/);
});

test("rejects disallowed public GitHub URL paths", async () => {
  await assert.rejects(() => readGitHub("/users/secret"), /Unsupported/);
});

const keys = crypto.generateKeyPairSync("ed25519");
const publicKey = keys.publicKey.export({ format: "der", type: "spki" }).subarray(-32).toString("hex");
function signed(payload, ts = Math.floor(now.getTime() / 1000)) {
  const body = JSON.stringify(payload);
  return { body, ts: String(ts),
    signature: crypto.sign(null, Buffer.from(String(ts) + body), keys.privateKey).toString("hex") };
}

test("signature verifies raw body, timestamp age and tampering", () => {
  const sign = signed({ type: 1 });
  assert.equal(verifyDiscord(Buffer.from(sign.body), sign.ts, sign.signature, publicKey, now.getTime()), true);
  assert.equal(verifyDiscord(Buffer.from(sign.body + " "), sign.ts, sign.signature, publicKey, now.getTime()), false);
  assert.equal(verifyDiscord(Buffer.from(sign.body), String(Number(sign.ts)-999), sign.signature, publicKey, now.getTime()), false);
  assert.equal(verifyDiscord(Buffer.from(sign.body), sign.ts, "0".repeat(128), publicKey, now.getTime()), false);
});

test("signed Discord ping returns expected ping response", async (t) => {
  const app = createApp({ publicKey, applicationId: APP_ID, channelId: CHANNEL_ID, clock: () => now });
  app.listen(0, "127.0.0.1");
  await once(app, "listening");
  t.after(() => app.close());
  const request = signed({ type: 1 });
  const response = await fetch(`http://127.0.0.1:${app.address().port}/interactions`, {
    method: "POST", headers: { "x-signature-timestamp": request.ts,
       "x-signature-ed25519": request.signature }, body: request.body });
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { type: 1 });
});

test("guild restriction rejects unauthorized channels before data calls", async (t) => {
  const mock = mockFetch();
  const app = createApp({ publicKey, applicationId: APP_ID, channelId: CHANNEL_ID,
                           fetcher: mock.fetcher, clock: () => now });
  app.listen(0, "127.0.0.1");
  await once(app, "listening");
  t.after(() => app.close());
  const req = signed({ type: 2, context: 0, application_id: APP_ID,
                       channel_id: "111", token: "a".repeat(40), data: { name: "picks" } });
  const response = await fetch(`http://127.0.0.1:${app.address().port}/interactions`, {
    method: "POST", headers: { "x-signature-timestamp": req.ts,
       "x-signature-ed25519": req.signature }, body: req.body });
  assert.equal((await response.json()).type, 4);
  assert.equal(mock.requests.length, 0);
});

test("command acknowledges before remote lookup, then edits private deferred response", async (t) => {
  const mock = mockFetch();
  const app = createApp({ publicKey, applicationId: APP_ID, channelId: CHANNEL_ID,
                           fetcher: mock.fetcher, clock: () => now });
  app.listen(0, "127.0.0.1");
  await once(app, "listening");
  t.after(() => app.close());
  const req = signed({ type: 2, context: 0, application_id: APP_ID,
                       channel_id: CHANNEL_ID, token: "b".repeat(40), data: { name: "picks" } });
  const response = await fetch(`http://127.0.0.1:${app.address().port}/interactions`, {
    method: "POST", headers: { "x-signature-timestamp": req.ts,
       "x-signature-ed25519": req.signature }, body: req.body });
  assert.deepEqual(await response.json(), { type: 5, data: { flags: 64 } });
  for (let i=0; i<30 && !mock.requests.some(x => x.method === "PATCH"); i++)
    await new Promise(resolve => setTimeout(resolve, 10));
  const patch = mock.requests.find(x => x.method === "PATCH");
  assert.ok(patch);
  assert.match(JSON.parse(patch.body).content, /Home vs Away/);
  assert.deepEqual(JSON.parse(patch.body).allowed_mentions, { parse: [] });
});
