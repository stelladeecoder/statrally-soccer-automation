# M13 experimental beta picks — implementation status

**Status: formatter and CLI route implemented; unattended automatic publishing remains OFF.**

The public repository contains `src/m13_beta_signals.py` and `tests/test_m13_beta_signals.py`. Experimental paper signals are sent through the existing *picks-specific* Discord webhook when an operator explicitly invokes:

```bash
PYTHONPATH=src python src/m13_discord_publish.py --input /private/path/to/verified_beta_envelope.json --mode beta
```

Dry run is the default. `--send` additionally requires `STATRALLY_PICKS_DISCORD_WEBHOOK`. Never commit real records or webhook values.

The JSON input must contain `schema_version:1`, `status:"experimental_paper"`, `trades_placed:0`, and 1–3 signals, each with `market_ticker`, `home_team`, `away_team`, `side` (YES/NO), `kickoff_utc`, `observed_at_utc`, `model_probability`, `market_price`, and independently verified `fixture_verified` and `quote_verified` fields. Quotes older than 15 minutes or games already started are rejected. These flags are an input contract, **not independent proof**: the upstream scanner and independent verification must supply actual evidence. All posts carry explicit unvalidated / paper-only labeling.

**Blockers before automated beta posting:** The current private M12 scan emits no model probability or executable market price and usually returns NO_BET without independently reviewed fixture mappings. It cannot be used to produce legitimate beta recommendations. Implement a separate read-only source exporter that attaches observed probability, price, timestamps, and provenance to each independently verified match. Then add a private persistent signal log, duplicate prevention across scheduled runs, outcome tracking, and a tested scheduled job. Test end to end with synthetic input and verify output before enabling any unattended Discord sends. Do not weaken `render_approved_picks` or interpret experimental signals as qualified EV picks.

No automated order placement or trading is authorized.
