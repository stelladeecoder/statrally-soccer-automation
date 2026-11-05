// Standalone Discord Interactions HTTP endpoint for server and user installs.
// No message-reading gateway, DM sender, order route, account token or scheduled post.
import http from "node:http";
import crypto from "node:crypto";
import { pathToFileURL } from "node:url";
import { commands, centralDay, optionsFor, PRIVATE_FLAGS, textResponse } from "./commands.mjs";
import { deliveredRecords, renderPick, savedPerformance } from "./data.mjs";
import { snapshotBackedFetch } from "./snapshot.mjs";
import { publicPlatform } from "./platform-data.mjs";
import { readFile } from "node:fs/promises";
import { platformCommand } from "./platform-commands.mjs";

export function verifyDiscord(body, timestamp, signature, publicKey, now = Date.now()) {
  if (!Buffer.isBuffer(body) || typeof timestamp !== "string" ||
      !/^\d{10}$/.test(timestamp) || typeof signature !== "string" ||
      !/^[a-fA-F0-9]{128}$/.test(signature) ||
      typeof publicKey !== "string" || !/^[a-fA-F0-9]{64}$/.test(publicKey)) return false;
  const secs = Number(timestamp);
  if (!Number.isSafeInteger(secs) || Math.abs(now - secs * 1000) > 300000) return false;
  try {
    // Discord provides a 32-byte Ed25519 key; SPKI DER prefix is fixed.
    const key = crypto.createPublicKey({
      key: Buffer.from("302a300506032b6570032100" + publicKey, "hex"),
      format: "der", type: "spki",
    });
    return crypto.verify(null, Buffer.concat([Buffer.from(timestamp), body]),
      key, Buffer.from(signature, "hex"));
  } catch {
    return false;
  }
}

export async function commandText(interaction, { fetcher = fetch, now = new Date(), platformData = null } = {}) {
  const name = interaction?.data?.name;
  if (!commands.some(c => c.name === name)) return "This command is not available.";
  if (platformData) {
    const eventId=optionsFor(interaction).find(o=>o.name==="event_id")?.value;
    const legacyMatch=name==="match" && /^\d{1,20}$/.test(eventId||"") &&
      !platformData.records.some(r=>r.prediction.espn_event_id===eventId);
    if (name==="picks") {
      const current=platformData.records.filter(r=>centralDay(new Date(r.prediction.kickoff_utc))===centralDay(now) &&
        r.deliveries.some(e=>e.kind==="top"&&e.state==="accepted"));
      const currentIds=new Set(current.map(r=>r.prediction.espn_event_id));
      let legacy=[];
      try { legacy=(await deliveredRecords({fetcher,day:centralDay(now)})).filter(r=>!currentIds.has(r.signal.espn_event_id)).slice(0,Math.max(0,3-current.length)); }
      catch { return platformCommand(interaction,platformData,now)+"\nLegacy delivery history is temporarily unavailable; canonical records above remain saved."; }
      if(legacy.length) return (current.length?platformCommand(interaction,platformData,now):"**StatRally | Delivered paper highlights**")+
        "\nLegacy delivered records (original saved estimates):\n"+legacy.map(renderPick).join("\n")+
        "\nLegacy records remain separate from the new forward monitoring cohort. No trades or new forecasts.";
    }
    if(!legacyMatch)return platformCommand(interaction,platformData,now);
  }
  if (name === "performance") {
    const item = await savedPerformance({ fetcher });
    if (!item) return "**StatRally performance**\nNo independently saved paper-performance snapshot is available. No betting ROI is claimed.";
    return `**StatRally paper performance**\nGraded: ${item.graded} | Wins: ${item.wins} | Losses: ${item.losses} | Pending: ${item.pending}\nHit rate: ${item.hit} | Brier: ${item.brier}\nSaved snapshot updated: ${item.updated}\nExperimental paper picks only; no real trades, verified edge or realized ROI.`;
  }
  if (name === "match") {
    const options = optionsFor(interaction);
    if (options.length !== 1 || options[0]?.name !== "event_id" ||
        typeof options[0]?.value !== "string" ||
        !/^\d{1,20}$/.test(options[0].value)) {
      return "Enter a valid numeric ESPN event ID shown in StatRally.";
    }
    const matches = await deliveredRecords({ fetcher, eventId: options[0].value });
    if (!matches.length) return "No confirmed StatRally paper record for that ESPN event ID. Unrecorded matches are not automatically evaluated.";
    return "**Recorded fixture**\n" + matches.slice(0, 3).map(renderPick).join("\n") +
      "\nRecorded experimental signals; quotes shown are historical observations, not live offers or new predictions.";
  }
  const day = centralDay(now);
  const picks = await deliveredRecords({ fetcher, day });
  const message = `**StatRally | ${day} Central**\n`;
  if (!picks.length) return message + "No confirmed official paper picks recorded for this date. This does not prove there are no matches or no BTTS opportunities.";
  const content = message + picks.slice(0, 3).map(renderPick).join("\n") +
    "\nExperimental paper predictions. No proven betting edge, no trades. Showing stored records, not a fresh scan.";
  if (name === "btts") {
    return content + "\nFull league-wide BTTS trend exploration and on-demand model refresh are planned, not deployed.";
  }
  return content;
}

export function allowedGuildChannel(interaction, guildId, channelId) {
  if (!guildId || !channelId || !/^\d{15,22}$/.test(guildId) ||
      !/^\d{15,22}$/.test(channelId)) return true;
  // Limit only the StatRally home server; preserve user installs elsewhere.
  if (interaction.context !== 0 || interaction.guild_id !== guildId) return true;
  return interaction.channel_id === channelId;
}

export async function editDeferred(applicationId, token, content, fetcher = fetch) {
  if (!/^\d{15,22}$/.test(applicationId) || !/^[A-Za-z0-9_.-]{20,300}$/.test(token)) {
    throw new Error("Invalid interaction identifiers");
  }
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10000);
  try {
    const response = await fetcher(
      `https://discord.com/api/v10/webhooks/${applicationId}/${token}/messages/@original`,
      { method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: textResponse(content).content, allowed_mentions: { parse: [] } }), signal: controller.signal });
    if (!response.ok) throw new Error("Deferred response delivery failed (Discord HTTP " + response.status + ")");
  } finally { clearTimeout(timeout); }
}

function safeFailure(error) {
  const kind = error?.name === "AbortError" ? "timeout" :
    error?.name === "TypeError" ? "network_error" : "application_error";
  const message = String(error?.message || "").slice(0, 180);
  // Only internally generated, non-secret error messages are emitted to logs.
  const known = /^(Deferred response delivery failed \(Discord HTTP \d{3}\)|Public GitHub source unavailable \(\d{3}\)|Issue history exceeds read limit; refusing incomplete results|Invalid GitHub source|Invalid interaction identifiers|The operation was aborted|fetch failed)$/;
  return kind + (known.test(message) ? ": " + message : "");
}

export function createApp({ publicKey, applicationId, guildId = "", channelId = "", fetcher = snapshotBackedFetch,
                            clock = () => new Date(), logger = console, platformReader = publicPlatform } = {}) {
  const configured = /^[a-fA-F0-9]{64}$/.test(publicKey || "") &&
    /^\d{15,22}$/.test(applicationId || "") &&
    /^\d{15,22}$/.test(guildId || "") &&
    /^\d{15,22}$/.test(channelId || "");
  const seen = new Map();
  return http.createServer(async (req, res) => {
    const reply = (status, payload) => {
      res.writeHead(status, { "Content-Type": "application/json", "Cache-Control": "no-store" });
      res.end(JSON.stringify(payload));
    };
    if (req.method === "GET" && req.url === "/health") {
      reply(200, { status: configured ? "ready" : "configuration_pending", mode: "read_only", discord_connected: false });
      return;
    }
    if (req.method === "GET" && req.url === "/api/predictions") {
      try { reply(200,await platformReader({fetcher,now:clock()})); }
      catch { reply(503,{error:"Canonical public predictions unavailable"}); }
      return;
    }
    const assets={"/":"platform.html","/platform.css":"platform.css","/platform-web.mjs":"platform-web.mjs","/platform-ui.mjs":"platform-ui.mjs"};
    if (req.method === "GET" && Object.hasOwn(assets,req.url)) {
      const name=assets[req.url];
      const type=name.endsWith(".html")?"text/html; charset=utf-8":name.endsWith(".css")?"text/css; charset=utf-8":"text/javascript; charset=utf-8";
      res.writeHead(200,{"Content-Type":type,"X-Content-Type-Options":"nosniff","Content-Security-Policy":"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"});
      res.end(await readFile(new URL(name,import.meta.url)));return;
    }
    if (req.method !== "POST" || req.url !== "/interactions") {
      reply(404, { error: "Not found" });
      return;
    }
    if (!configured) {
      reply(503, { error: "Discord application configuration pending" });
      return;
    }
    let chunks = [], size = 0;
    try {
      for await (const chunk of req) {
        size += chunk.length;
        if (size > 65536) {
          reply(413, { error: "Request too large" });
          return;
        }
        chunks.push(chunk);
      }
      const body = Buffer.concat(chunks);
      const timestamp = req.headers["x-signature-timestamp"];
      const signature = req.headers["x-signature-ed25519"];
      if (!verifyDiscord(body, timestamp, signature, publicKey, clock().getTime())) {
        reply(401, { error: "Invalid Discord signature" });
        return;
      }
      // Suppress duplicated signed deliveries inside this process.
      const nonce = String(signature).toLowerCase();
      const nowMs = clock().getTime();
      for (const [key, until] of seen) if (until <= nowMs) seen.delete(key);
      if (seen.has(nonce)) {
        reply(409, { error: "Duplicate interaction" });
        return;
      }
      seen.set(nonce, nowMs + 300000);
      if (seen.size > 10000) seen.delete(seen.keys().next().value);
      let interaction;
      try { interaction = JSON.parse(body.toString("utf8")); }
      catch { reply(400, { error: "Invalid JSON" }); return; }
      if (interaction.type === 1) { reply(200, { type: 1 }); return; }
      if (interaction.type !== 2 || !commands.some(c => c.name === interaction.data?.name)) {
        reply(200, { type: 4, data: textResponse("This command is not supported.") });
        return;
      }
      if (!allowedGuildChannel(interaction, guildId, channelId)) {
        reply(200, { type: 4, data: textResponse("Use this command in #bot-commands in the StatRally server.") });
        return;
      }
      if (interaction.application_id !== applicationId || typeof interaction.token !== "string") {
        reply(401, { error: "Application mismatch" });
        return;
      }
      // Immediately acknowledge; source lookups happen only after this response.
      reply(200, { type: 5, data: { flags: PRIVATE_FLAGS } });
      void (async () => {
        let text;
        try {
          let platformData=null;
          try { platformData=await platformReader({fetcher,now:clock()}); } catch { /* Keep existing verified legacy records available during migration. */ }
          text = await commandText(interaction, { fetcher, now: clock(), platformData });
        } catch (err) {
          logger.error("StatRally command failed:", safeFailure(err));
          text = "Latest verified records are unavailable right now. No new analysis was generated.";
        }
        try { await editDeferred(applicationId, interaction.token, text, fetcher); }
        catch (err) { logger.error("Discord response failed:", safeFailure(err)); }
      })();
    } catch (err) {
      logger.error("Discord interaction request failed:", safeFailure(err));
      if (!res.headersSent) reply(500, { error: "Request processing failed" });
    }
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const { DISCORD_PUBLIC_KEY: publicKey, DISCORD_APPLICATION_ID: applicationId,
          STAT_RALLY_COMMAND_CHANNEL_ID: channelId, STAT_RALLY_GUILD_ID: guildId, PORT = "3000" } = process.env;
  // The public staging endpoint starts in a safe, non-interactive mode.
  // Without verified Discord settings, all POST /interactions calls return 503.
  // This allows hosting checks without dummy keys or publicly enabled commands.
  const server = createApp({ publicKey, applicationId, guildId, channelId });
  server.listen(Number(PORT), "0.0.0.0", () => console.log("StatRally interaction endpoint listening"));
}
