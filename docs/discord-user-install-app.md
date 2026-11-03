# StatRally Discord slash-command app: implementation and deployment

**Stage: code + offline tests; not yet registered, hosted or installed.** The free interaction app is independent of the existing GitHub Actions scheduled webhook workflows. It does not access the private Trade Desk, execute orders, create new picks, or change Discord channels automatically.

## Shipped source

| File | Responsibility |
|---|---|
| `discord-app/commands.mjs` | Four global application command definitions with guild + user installation contexts; copyable channel guide |
| `discord-app/data.mjs` | Read-only access to *public*, bot-authored StatRally paper Issues and confirmed delivery receipts |
| `discord-app/server.mjs` | Signed Discord interactions, PING, channel restriction, ephemeral defer, and follow-up |
| `discord-app/register.mjs` | **Explicit/manual** global application-command registration |
| `discord-app/tests/discord.test.mjs` | Offline tests with generated Ed25519 keys and synthetic public issue fixtures |
| `.github/workflows/validate-discord-app.yml` | Node 22 syntax and regression verification |

The app currently returns **existing official paper records only**. `/picks` and `/btts` read today's confirmed published signals; `/match event_id:...` looks up a confirmed existing ESPN fixture; `/performance` shows the saved paper-performance Issue snapshot with its update time. `/btts` is **not yet** a complete all-league BTTS trends engine. Results are labeled experimental and historical; no new predictions, fresh trading prices, real returns, or betting edge are claimed.

### What must happen before people can use it

1. **Create/review a Discord application** in the [Developer Portal](https://discord.com/developers/applications). In *Installation*, enable appropriate **Guild Install** and **User Install** types and set the allowed scopes for application commands. Configure contexts to permit guild, bot DM and private channel as allowed by Discord. Discord may require installing/authorizing the bot separately for server administration; keep permissions minimal.
2. **Host the interaction endpoint** on a reachable HTTPS service that accepts POST at `/interactions` continuously (or on a serverless platform with compatible request handling). GitHub Actions does not provide this HTTP hosting. Set `DISCORD_PUBLIC_KEY` (application public key), `DISCORD_APPLICATION_ID`, required `STAT_RALLY_GUILD_ID` (the StatRally server ID) and `STAT_RALLY_COMMAND_CHANNEL_ID` (the numeric ID of `#bot-commands`), and `PORT` on the host. The endpoint validates raw request bytes with Ed25519 and rejects unknown/expired signatures. Do **not** expose a secret in this repository.
3. Set the Discord application's **Interactions Endpoint URL** to `https://YOUR_HOST/interactions`; pass Discord's PING/signature validation in the Developer Portal.
4. To explicitly register global commands, temporarily set `DISCORD_APPLICATION_ID` and **`DISCORD_BOT_TOKEN` only in a secure operator environment**, then run `node discord-app/register.mjs`. Never commit or paste the token into Issues/chat. This calls Discord's command registration API once; CI does not register commands.
5. Create `#bot-commands` in the server, copy its numeric ID into `STAT_RALLY_COMMAND_CHANNEL_ID`, and **pin** the command guide from `discord-app/commands.mjs` (the exported `GUIDE` constant). This repo cannot create a channel or pin a guide through webhooks.
6. Install the application in your StatRally server, verify commands inside `#bot-commands`, verify normal commands are restricted in scheduled announcement channels, then independently test **User Install** contexts if approved. Slash commands themselves cannot be pinned, only the guide.
7. Validate interaction latency, actual saved-data freshness, null/missing data, install permissions, privacy/ephemeral behavior and a controlled rollback. Keep the app disabled until hosting/installation end-to-end tests are confirmed.

**Critical:** Set the real `STAT_RALLY_COMMAND_CHANNEL_ID` before enabling guild usage. The service now refuses startup if either the guild or channel ID is unset or malformed; Discord administrator permissions can restrict commands separately. The app permits user-install contexts independently.

## Channel created: deployment preparation checkpoint

**Owner-reported:** The StatRally Discord server now has a `#bot-commands` channel. The channel has **not** yet been verified through Discord's API, and the pinned guide, slash-command installation and live interaction endpoint have not been verified.

A [Render Blueprint](../render.yaml) is available as an **optional deployment configuration**. Adding it does not create a service, authorize charges or make the Discord app live. The blueprint disables auto-deploy and requires these environment variables:

| Variable | Source | Handling |
|---|---|---|
| `DISCORD_APPLICATION_ID` | Discord Developer Portal, General Information | Public ID |
| `DISCORD_PUBLIC_KEY` | Discord Developer Portal, General Information | Public verification key, **not bot token** |
| `STAT_RALLY_GUILD_ID` | Numeric StatRally server ID from Discord | Public ID |
| `STAT_RALLY_COMMAND_CHANNEL_ID` | Numeric `#bot-commands` channel ID from Discord | Public ID |

The server now **refuses startup** when these four values are missing or malformed. This avoids silently running without the intended home-server channel restriction. User installs elsewhere remain independently supported by the command definitions.

To copy IDs in Discord: enable **User Settings → Advanced → Developer Mode**, right-click the server and choose **Copy Server ID**, then right-click `#bot-commands` and choose **Copy Channel ID**. Do not share any bot token, client secret or private key.

When a trusted HTTPS hosting service has been provisioned, inspect `GET /health`, set the application's Interactions Endpoint URL to `https://YOUR_HOST/interactions` and pass Discord's signature/PING validation. Register the global commands only through the explicit script in an authorized operator environment. Set Discord's channel/role permissions, install the app, and manually pin the guide below. Keep the scheduled webhook channels untouched.

**Status:** Configuration prepared only; service creation, application installation, token-based registration, channel pinning and real Discord end-to-end tests remain outstanding.

## Local offline verification

```bash
node --version   # Node 22 supported
node --test discord-app/tests/*.test.mjs
```

No extra npm dependencies are required. To start the hosted HTTP service once provisioned:

```bash
DISCORD_APPLICATION_ID=<app_id> DISCORD_PUBLIC_KEY=<public_key_hex> \
STAT_RALLY_GUILD_ID=<numeric_guild_id> STAT_RALLY_COMMAND_CHANNEL_ID=<numeric_channel_id> PORT=3000 \
node discord-app/server.mjs
```

The health endpoint is `GET /health`. The signed interaction endpoint is `POST /interactions`. Discord requires an initial response within three seconds; this handler acknowledges immediately with an ephemeral deferred response, and then looks up existing public records.

## Source integrity and limitations

- GitHub public Issues are a **read-only published record**. The adapter requires an issue authored by `github-actions[bot]`, a matching paper-reservation marker, and a bot-authored successful Discord delivery receipt. It does **not** independently verify the receipt's SHA-256 against the source signal, and does not regrade completed matches. Thus a confirmed delivered paper record is **not** proof of verified match outcome or model calibration.
- `/performance` displays a previously saved, bot-authored performance snapshot, not a live regrade. If the source is unavailable or ambiguous, show unavailable rather than fabricated zeros.
- The initial adapter caps GitHub Issue pagination and matching-record review; if history exceeds the configured limit, it errors rather than interpreting incomplete history as no picks. High-volume production use will require a dedicated read-only indexed/cached public analytics endpoint with reconciliation, stronger provenance verification and rate limits.
- A user's `/btts` or `/match` command never consumes a pick quota or causes a new prediction, market quote request, Discord scheduled post or public issue write.
- User installs can invoke supported commands in Discord contexts permitted by app settings and Discord rules. **This does not authorize unsolicited DMs** or other bot automation.
- This repository has no hosting configuration and no permanent worker URL. Secrets, Discord installations, permission settings, channel creation and pinning require owner/host-side authorization and real-world validation.
- The scheduled `#match-watchlist`, `#btts-picks`, `#btts-results` posts remain unchanged. Admin-only operational alerts are separate.

## Pinned guide

Copy this into the real `#bot-commands` channel and pin it after installation:

> **StatRally | Free BTTS Research**
>
> Use `/btts` for today's recorded BTTS activity, `/match` with an ESPN event ID to inspect a recorded fixture, `/picks` for today's official paper picks, and `/performance` for saved grading stats.
>
> These responses are based on the latest **already-published** records. No new picks are generated, and old observations are not live prices. The app is experimental and does not place real-money trades.
>
> Scheduled watchlists, paper picks and results stay in their announcement channels. Use this channel for questions and commands.

## Deployment acceptance checklist

- [ ] CI and offline signed-request tests pass on the merged code
- [ ] Discord application registered for user + guild install and command contexts reviewed
- [ ] TLS host configured and verified by Discord's endpoint challenge
- [ ] `#bot-commands` created, guide posted/pinned, channel ID configured and restrictions verified
- [ ] All four commands tested using real existing saved records and truthful empty/error responses
- [ ] User installation tested independently in supported contexts
- [ ] No exposed secrets, unsolicited messages, fresh unverified forecasts or bypassed daily cap
- [ ] Existing scheduler and Discord webhooks unaffected

Do not call this production-ready until those checks pass.
