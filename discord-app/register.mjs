// Explicit/manual command registration only. Never invoked by CI or server startup.
import { commands } from "./commands.mjs";

const appId = process.env.DISCORD_APPLICATION_ID || "";
const token = process.env.DISCORD_BOT_TOKEN || "";
if (!/^\d{15,22}$/.test(appId) || !token) {
  console.error("Set DISCORD_APPLICATION_ID and DISCORD_BOT_TOKEN in your secure host environment");
  process.exit(1);
}
const endpoint = `https://discord.com/api/v10/applications/${appId}/commands`;
const controller = new AbortController();
const timeout = setTimeout(() => controller.abort(), 12000);
try {
  const result = await fetch(endpoint, {
    method: "PUT", signal: controller.signal,
    headers: { Authorization: "Bot " + token, "Content-Type": "application/json" },
    body: JSON.stringify(commands),
  });
  if (!result.ok) throw new Error("Discord command registration failed with HTTP " + result.status);
  const payload = await result.json();
  if (!Array.isArray(payload) || payload.length !== commands.length) {
    throw new Error("Discord registration returned unexpected command count");
  }
  console.log("StatRally commands registered:", payload.map(x => x.name).join(", "));
} catch (error) {
  // Never log a token or response body.
  console.error(error.message);
  process.exitCode = 1;
} finally { clearTimeout(timeout); }
