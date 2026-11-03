# StatRally Discord App Privacy Policy

**Effective date:** November 3, 2026  
**Applies to:** The StatRally Discord slash-command application (the "App") operated as a free soccer analytics and experimental paper-pick project.

## What the App does
StatRally responds to voluntary Discord application commands such as `/picks`, `/btts`, `/match`, and `/performance`. Current commands read previously published public StatRally paper records. They do not place bets, make purchases, send unsolicited direct messages, or access private trading accounts. Some future analytics features described in the project documentation are not deployed.

## Data received when you use a command
Discord sends the App the interaction information needed to validate and respond to your request. Depending on where you invoke a command, this includes an application identifier, command name and options, an interaction token, Discord user/member and server/channel identifiers, a timestamp, and signature information. The App processes these to authenticate the request, enforce the home-server channel restriction, locate public records, and send the requested private response.

The deployed interaction handler does not intentionally write the content of individual commands, user identifiers, or interaction tokens to the project's GitHub records or application logs. However, hosting, network and platform providers may process or retain request metadata and operational/security logs under their own policies. Error logs include limited diagnostic information such as generic error categories and upstream HTTP status codes. The App temporarily tracks a signature-derived duplicate-request identifier in process memory for up to five minutes; this memory is not a permanent database. Interaction tokens are used to deliver deferred responses and are not intentionally persisted by App code.

## Public data and third parties
The App reads historical public records from the StatRally GitHub repository. An automated public snapshot of bot-authored paper records and delivery confirmations may be served when GitHub's API rejects an unauthenticated request. These snapshots contain the App's public paper-record data, not a database of individual Discord users' commands. The snapshot is periodically refreshed and committed to the public repository.

The App uses **Discord** for interactions, **Render** for HTTP hosting, and **GitHub** for public research records and automation. These services process data according to their own privacy practices. The App does not intentionally use third-party advertising trackers and does not sell Discord user data.

## Storage and retention
The current application code has no dedicated user profile or analytics database and does not intentionally store per-user command histories. Temporary duplicate-request entries expire after five minutes, while public paper records, delivery receipts and their repository history may remain available on GitHub. Render, Discord and GitHub can independently retain logs or other data under their own practices. We cannot guarantee deletion of information retained by those services or of previously published public repository history.

## Access, corrections and privacy questions
For questions, access or deletion requests relating to data held by StatRally, contact the project operator through the [StatRally GitHub repository](https://github.com/stelladeecoder/statrally-soccer-automation) or the project's Discord community. **Do not post personal information, authentication tokens, or sensitive requests publicly in GitHub Issues or Discord channels.** Ask for a private contact method first. The operator can investigate App-controlled records and respond as appropriate; requests for information controlled by Discord, Render or GitHub may need to be directed to those providers.

## Minors and limitations
StatRally is a sports research app, not a gambling or payment service. It does not facilitate wagering. Users must comply with Discord's age requirements and applicable laws. Historical research and experimental predictions are not a guarantee of betting success.

## Changes
This policy may be updated as features and data practices change. Material changes will be reflected by revisions to this publicly available document. The latest version and its revision history are accessible in the GitHub repository.

**Project:** [StatRally](https://github.com/stelladeecoder/statrally-soccer-automation)
