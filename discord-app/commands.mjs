// Free StatRally slash commands, registered for server and user installations.
// This describes interfaces only; it does not auto-register or send messages.
export const commands = [
  {
    name: "btts", description: "Show today's latest recorded BTTS research",
    type: 1, integration_types: [0, 1], contexts: [0, 1, 2],
    options: [{name:"page",description:"Page of today's complete prediction slate",type:4,required:false,min_value:1,max_value:10000}],
  },
  {
    name: "match", description: "Inspect an existing StatRally match record",
    type: 1, integration_types: [0, 1], contexts: [0, 1, 2],
    options: [{ name: "event_id", description: "ESPN event ID shown in StatRally",
      type: 3, required: true, min_length: 1, max_length: 20 }],
  },
  {
    name: "picks", description: "Show today's officially delivered paper picks",
    type: 1, integration_types: [0, 1], contexts: [0, 1, 2],
  },
  {
    name: "performance", description: "Show the latest saved paper-performance snapshot",
    type: 1, integration_types: [0, 1], contexts: [0, 1, 2],
  },
];

export const GUIDE = `**StatRally | Free BTTS analytics**
Use these slash commands in **#bot-commands**:
• \`/btts\` — latest recorded BTTS activity for today (not an automatic fresh scan)
• \`/match event_id:<ESPN_ID>\` — review one recorded fixture
• \`/picks\` — the same official paper picks announced by the bot
• \`/performance\` — latest saved graded record and sample size

The app currently reads already-published, bot-verified paper records. It does not generate new forecasts, create more picks or place trades. Availability and timestamps are shown; missing/stale records are not invented. General match-trend analytics and live refresh are future work.\n`;

export const PRIVATE_FLAGS = 64;
export function textResponse(content) {
  return { content: String(content).slice(0, 1900), allowed_mentions: { parse: [] }, flags: PRIVATE_FLAGS };
}

export function centralDay(date = new Date()) {
  if (!(date instanceof Date) || Number.isNaN(date.getTime())) throw new Error("Valid clock required");
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Chicago", year: "numeric", month: "2-digit", day: "2-digit",
  }).format(date);
}

export function safeText(value, max = 90) {
  if (typeof value !== "string") return "Unknown";
  return value.replace(/[\r\n\t]+/g, " ").replace(/[@*`<>|]/g, "").slice(0, max).trim() || "Unknown";
}

export function optionsFor(interaction) {
  return Array.isArray(interaction?.data?.options) ? interaction.data.options : [];
}
