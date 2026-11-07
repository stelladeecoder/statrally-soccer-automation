"""Read-only Discord paper-pick quote presentation; no actual market calls."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import unittest

from prediction_platform import prediction_pages, verified_quote_map
from m13_discord_embeds import validate_payload

NOW=datetime(2026,11,7,15,tzinfo=timezone.utc)
def item():
    kickoff=(NOW+timedelta(hours=3)).isoformat()
    return {"prediction":{"prediction_id":"p1","fixture_id":"espn:epl:123",
        "home_team":"Fictional City","away_team":"Fictional United",
        "league":"epl","kickoff_utc":kickoff,"side":"YES",
        "p_yes":"0.60","p_no":"0.40","confidence":"0.60",
        "model_version":"rolling-poisson-10-v1","probabilities_calibrated":False,
        "data_quality_status":"research_snapshot"},
        "market":{"status":"verified_available","market_slug":"fictional-btts"},
        "grade":{"status":"pending"}}
def bundle(side="YES",status="verified",at=None):
    row={"prediction_id":"p1","side":side,"status":status}
    if status=="verified":
        row.update(market_slug="fictional-btts",price_dollars="0.60",
                   observed_at=(at or NOW).isoformat())
    return {"schema_version":1,"source":"polymarket_us","trades_placed":0,"quotes":[row]}

class PaperQuoteRendering(unittest.TestCase):
    def render(self,quotes):
        return prediction_pages([item()],"PAPER TEST",highlighted=True,
            quotes=quotes,now=NOW)[0]["embeds"][0]

    def test_verified_quote_includes_timestamp_and_gross_illustration(self):
        q=verified_quote_map(bundle())
        card=self.render(q)
        fields={f["name"]:f["value"] for f in card["fields"]}
        self.assertEqual(fields["Market ask at posting"],"$0.6000")
        self.assertIn("$6.67",fields["Illustrative $10 gross profit"])
        self.assertIn("2026-11-07",fields["Quote observed"])
        self.assertIn("not guaranteed fill",card["footer"]["text"])
        validate_payload({"embeds":[card]})

    def test_unavailable_quote_never_assumes_model_confidence_is_price(self):
        for rows in ({},verified_quote_map(bundle(status="unavailable"))):
            card=self.render(rows)
            fields={f["name"]:f["value"] for f in card["fields"]}
            self.assertIn("Unavailable",fields["Market price"])
            self.assertNotIn("Market ask at posting",fields)

    def test_side_and_market_mismatch_or_staleness_suppress_quote(self):
        q=verified_quote_map(bundle(side="NO"))
        self.assertIn("Unavailable",self.render(q)["fields"][-1]["value"])
        q=verified_quote_map(bundle())
        q["p1"]["market_slug"]="wrong-market"
        self.assertIn("Unavailable",self.render(q)["fields"][-1]["value"])
        q=verified_quote_map(bundle(at=NOW-timedelta(minutes=6)))
        self.assertIn("Unavailable",self.render(q)["fields"][-1]["value"])

    def test_closed_market_not_quoted(self):
        r=item();r["market"]["status"]="market_closed"
        q=verified_quote_map(bundle())
        payload=prediction_pages([r],"TEST",highlighted=True,quotes=q,now=NOW)
        self.assertIn("Unavailable",payload[0]["embeds"][0]["fields"][-1]["value"])

    def test_duplicate_quote_ids_rejected(self):
        b=bundle();b["quotes"].append(dict(b["quotes"][0]))
        with self.assertRaises(ValueError):verified_quote_map(b)

if __name__=="__main__":
    unittest.main()
