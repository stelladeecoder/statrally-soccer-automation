// Explicit/manual StatRally command registration. Does not overwrite unrelated commands.
// Never runs on server startup, pull request builds, or scheduled posting jobs.
import { commands } from "./commands.mjs";

const appId = process.env.DISCORD_APPLICATION_ID || "";
const token = process.env.DISCORD_BOT_TOKEN || "";
if (!/^\d{15,22}$/.test(appId) || !token || token.trim() !== token) {
  console.error("Missing valid DISCORD_APPLICATION_ID or DISCORD_BOT_TOKEN in secure environment.");
  process.exit(1);
}

const endpoint = `https://discord.com/api/v10/applications/${appId}/commands`;
const controller = new AbortController();
const timeout = setTimeout(() => controller.abort(), 12000);
const headers = { Authorization: "Bot " + token, "Content-Type": "application/json" };
try {
  // GET first: never silently delete or replace an unrelated global command.
  const initial = await fetch(endpoint, { headers, signal: controller.signal });
  if (!initial.ok) throw new Error("Discord command lookup failed (HTTP " + initial.status + ")");
  const existing = await initial.json();
  if (!Array.isArray(existing)) throw new Error("Unexpected Discord command inventory");
  const desired = new Set(commands.map(cmd => cmd.name));
  const conflicting = existing.filter(cmd => cmd.type !== 1 && desired.has(cmd.name));
  if (conflicting.length) throw new Error("Conflicting command type requires operator review");

  for (const command of commands) {
    const prior = existing.find(item => item.type === command.type && item.name === command.name);
    // POST upserts only these four commands, preserves all other registered commands.
    const response = await fetch(endpoint, {
      method: "POST", headers, signal: controller.signal, body: JSON.stringify(command),
    });
    if (!response.ok) throw new Error("Discord rejected registration for /" + command.name + " (HTTP " + response.status + ")");
    const item = await response.json();
    if (item.name !== command.name || item.type !== 1 || item.application_id !== appId)
      throw new Error("Unexpected Discord acknowledgment for /" + command.name);
    console.log((prior ? "Updated " : "Registered ") + "/" + command.name);
  }

  // Read back: confirm all four definitions exist on Discord.
  const final = await fetch(endpoint, { headers, signal: controller.signal });
  if (!final.ok) throw new Error("Discord read-back failed (HTTP " + final.status + ")");
  const entries = await final.json();
  if (!Array.isArray(entries) || !commands.every(cmd => entries.some(item =>
    item.type === cmd.type && item.name === cmd.name &&
    JSON.stringify(item.integration_types?.slice().sort()) === JSON.stringify(cmd.integration_types.slice().sort()) &&
    JSON.stringify(item.contexts?.slice().sort()) === JSON.stringify(cmd.contexts.slice().sort()))))
    throw new Error("Discord command registration read-back mismatch");

  console.log("Verified four registered global StatRally commands; no unrelated commands removed.");
} catch (error) {
  // Never print the bot token, response body, or request headers.
  console.error(error.message);
  process.exitCode = 1;
} finally { clearTimeout(timeout); }
