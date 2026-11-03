// Standalone Discord Interactions HTTP endpoint for server and user installs.
// No message-reading gateway, DM sender, order route, account token or scheduled post.
import http from "node:http";
import crypto from "node:crypto";
import { pathToFileURL } from "node:url";
import { commands, centralDay, optionsFor, PRIVATE_FLAGS, textResponse } from "./commands.mjs";
import { deliveredRecords, renderPick, savedPerformance } from "./data.mjs";

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

export async function commandText(interaction, { fetcher = fetch, now = new Date() } = {}) {
  const name = interaction?.data?.name;
  if (!commands.some(c => c.name === name)) return "This command is not available.";
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
  if (!guildId || !channelId || !/^\\d{15,22}$/.test(guildId) ||
      !/^\\d{15,22}$/.test(channelId)) return true;
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
    if (!response.ok) throw new Error("Deferred response delivery failed");
  } finally { clearTimeout(timeout); }
}

export function createApp({ publicKey, applicationId, guildId = "", channelId = "", fetcher = fetch,
                            clock = () => new Date(), logger = console } = {}) {
  const seen = new Map();
  return http.createServer(async (req, res) => {
    const reply = (status, payload) => {
      res.writeHead(status, { "Content-Type": "application/json", "Cache-Control": "no-store" });
      res.end(JSON.stringify(payload));
    };
    if (req.method === "GET" && req.url === "/health") {
      reply(200, { status: "ready", mode: "read_only", credentials_required: false });
      return;
    }
    if (req.method !== "POST" || req.url !== "/interactions") {
      reply(404, { error: "Not found" });
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
          text = await commandText(interaction, { fetcher, now: clock() });
        } catch (err) {
          logger.error("StatRally command failed:", err?.name || "UnknownError");
          text = "Latest verified records are unavailable right now. No new analysis was generated.";
        }
        try { await editDeferred(applicationId, interaction.token, text, fetcher); }
        catch (err) { logger.error("Discord response failed:", err?.name || "UnknownError"); }
      })();
    } catch (err) {
      logger.error("Discord interaction request failed:", err?.name || "UnknownError");
      if (!res.headersSent) reply(500, { error: "Request processing failed" });
    }
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const { DISCORD_PUBLIC_KEY: publicKey, DISCORD_APPLICATION_ID: applicationId,
          STAT_RALLY_COMMAND_CHANNEL_ID: channelId, STAT_RALLY_GUILD_ID: guildId, PORT = "3000" } = process.env;
  if (!publicKey || !applicationId) {
    console.error("DISCORD_PUBLIC_KEY and DISCORD_APPLICATION_ID are required");
    process.exit(1);
  }
  const server = createApp({ publicKey, applicationId, guildId, channelId });
  server.listen(Number(PORT), "0.0.0.0", () => console.log("StatRally interaction endpoint listening"));
}
