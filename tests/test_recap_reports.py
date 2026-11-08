"""Offline tests for StatRally recaps. All fixtures are synthetic."""
import copy
from datetime import date, timedelta
from io import BytesIO
import unittest
from unittest.mock import patch

from PIL import Image
from prediction_ledger import Ledger, GRADE, DELIVERY
from recap_reports import (sunday_start, weekly_bounds, month_bounds, summary,
                           weekly_payload, monthly_payload, calendar_png,
                           model_summary, model_payload, publish_period, run)
from test_prediction_platform import FakeGitHub, REPO, NOW, prediction, slate, verify_synthetic


class RecapTests(unittest.TestCase):
    def setUp(self):
        self.api=FakeGitHub()
        self.ledger=Ledger(REPO,"synthetic-token",call=self.api).load()
        data=slate(5)
        data["fixtures"][3]=prediction(4,p_yes="0.70")
        data["fixtures"][4]=prediction(5,p_yes="0.70")
        data["fixtures"][3]["confidence"]="0.70"
        data["fixtures"][4]["confidence"]="0.70"
        issued=self.ledger.issue_slate(data,now=NOW)
        verify_synthetic(self.ledger,issued["predictions"])
        self.posts=[]
        self.edits=[]

    def grade(self,i,correct=True):
        row=self.ledger.forecasts[i]
        p=row["prediction"]
        actual=(p["side"]=="YES") if correct else (p["side"]=="NO")
        self.ledger.append(row["issue_number"],GRADE,
            {"prediction_id":p["prediction_id"],"status":"graded",
             "result":"WIN" if correct else "LOSS","correct":correct,
             "btts_yes":actual})

    def highlight(self,i):
        r=self.ledger.forecasts[i]
        self.ledger.append(r["issue_number"],DELIVERY,
            {"prediction_id":r["prediction"]["prediction_id"],"kind":"top","state":"reserved"})

    def send(self,payload,hook,**kwargs):
        self.posts.append(copy.deepcopy(payload))
        return {"message_id":"111111111","channel_id":"222222222"}

    def edit(self,payload,hook,receipt):
        self.edits.append(copy.deepcopy(payload))

    def test_week_starts_sunday_ends_saturday_even_at_year_boundary(self):
        self.assertEqual(weekly_bounds(date(2026,11,7)),(date(2026,11,1),date(2026,11,7)))
        self.assertEqual(weekly_bounds(date(2026,11,8)),(date(2026,11,8),date(2026,11,14)))
        self.assertEqual(weekly_bounds(date(2027,1,1)),(date(2026,12,27),date(2027,1,2)))
        self.assertEqual(month_bounds(date(2026,11,7)),(date(2026,11,1),date(2026,11,30)))

    def test_weekly_has_no_calendar_and_total_is_weighted(self):
        for i in range(4):self.grade(i,correct=i!=2)
        self.highlight(0);self.highlight(2)
        x=summary(self.ledger,date(2026,11,1),date(2026,11,7))
        self.assertEqual(x["overall"]["ALL"]["graded"],4)
        self.assertEqual(x["overall"]["ALL"]["correct"],3)
        self.assertEqual(x["overall"]["NO"]["correct"],2)
        self.assertEqual(x["overall"]["NO"]["incorrect"],1)
        self.assertEqual(x["top"]["graded"],4)
        self.assertEqual(x["top"]["correct"],3)
        self.assertEqual(x["overall"]["ALL"]["graded"], 4)  # Highlight subset, no double count.
        self.assertIn("included in Overall", str(weekly_payload(x)))
        self.assertIn("70%+ Model Picks", str(weekly_payload(x)))
        self.assertIn("included in Overall", str(monthly_payload(x)))
        payload=weekly_payload(x)
        self.assertIn("Sunday–Saturday",payload["embeds"][0]["description"])
        self.assertNotIn("calendar",str(payload).lower())
        self.assertIn("Sun Nov 01",str(payload))

    def test_month_calendar_is_png_without_yellow_or_top3_marks(self):
        self.grade(0);self.grade(1,False);self.grade(2)
        x=summary(self.ledger,date(2026,11,1),date(2026,11,30))
        blob=calendar_png(x)
        self.assertTrue(blob.startswith(b"\x89PNG\r\n\x1a\n"))
        img=Image.open(BytesIO(blob))
        self.assertGreaterEqual(img.width,900)
        self.assertEqual(img.format,"PNG")
        self.assertIn("70%+ Model Picks Accuracy",str(monthly_payload(x)))
        self.assertNotIn("yellow",monthly_payload(x)["embeds"][0]["description"].lower())
        self.assertIn("Sunday–Saturday", monthly_payload(x)["embeds"][0]["description"])

    def test_model_metrics_derived_from_saved_verified_probabilities(self):
        self.grade(0);self.grade(1,False);self.grade(3)
        d=model_summary(self.ledger)
        self.assertEqual(d["graded_total"],3)
        version=next(iter(d["versions"].values()))
        self.assertEqual(version["performance"]["ALL"]["correct"],2)
        self.assertIsNotNone(version["brier"])
        self.assertIsNotNone(version["log_loss"])
        self.assertAlmostEqual(version["baseline_accuracy"], 100*2/3)  # Synthetic predictions contain a frozen prevalence baseline.
        p=model_payload(d)
        self.assertIn("Not validated",str(p))
        self.assertIn("precision / recall",str(p))
        self.assertIn("included in Overall",str(p))
        self.assertNotIn("Good reliability",str(p))

    def test_durable_weekly_post_update_repeat_and_ambiguous_send(self):
        self.grade(0)
        x=summary(self.ledger,date(2026,11,1),date(2026,11,7))
        data={k:v for k,v in x.items() if k!="records"}
        params={"kind":"weekly","period_id":"2026-11-01","issue_day":date(2026,11,7),
                "webhook":"https://discord.com/api/webhooks/123456/token",
                "sender":self.send,"editor":self.edit}
        self.assertEqual(publish_period(self.ledger,data=data,payload=weekly_payload(x),**params),"posted")
        self.assertEqual(publish_period(self.ledger,data=data,payload=weekly_payload(x),**params),"unchanged")
        self.grade(1,False)
        y=summary(self.ledger,date(2026,11,1),date(2026,11,7))
        data2={k:v for k,v in y.items() if k!="records"}
        self.assertEqual(publish_period(self.ledger,data=data2,payload=weekly_payload(y),**params),"updated")
        self.assertEqual(len(self.posts),1)
        self.assertEqual(len(self.edits),1)
        self.assertEqual(publish_period(self.ledger,data=data2,payload=weekly_payload(y),**params),"unchanged")

    def test_unconfirmed_receipt_fails_closed(self):
        self.grade(0)
        x=summary(self.ledger,date(2026,11,1),date(2026,11,7))
        params={"kind":"weekly","period_id":"2026-11-01","issue_day":date(2026,11,7),
                "webhook":"https://discord.com/api/webhooks/123456/token",
                "data":{k:v for k,v in x.items() if k!="records"},
                "payload":weekly_payload(x)}
        with self.assertRaises(TimeoutError):
            publish_period(self.ledger,sender=lambda *a,**kw: (_ for _ in ()).throw(TimeoutError()),**params)
        with self.assertRaisesRegex(RuntimeError,"Ambiguous"):
            publish_period(self.ledger,sender=self.send,**params)
        self.assertEqual(len(self.posts),0)

    def test_empty_groups_and_missing_webhooks_do_not_publish(self):
        data=summary(self.ledger,date(2026,11,1),date(2026,11,30))
        self.assertEqual(data["overall"]["ALL"]["graded"],0)
        with self.assertRaisesRegex(RuntimeError, "Monthly recap Discord webhook"):
            run(self.ledger,date(2026,11,8),{"weekly":"","monthly":"","model":""})

    def test_november_monthly_posts_before_grading_and_updates_in_place(self):
        hook="https://discord.com/api/webhooks/123456/token"
        messages=[]
        def fake_month(payload, webhook, png, *, message_id=None):
            self.assertEqual(webhook,hook)
            self.assertTrue(png.startswith(bytes([137,80,78,71])))
            messages.append(message_id)
            return {"message_id":"111111111","channel_id":"222222222"}
        with patch("recap_reports.month_send",side_effect=fake_month):
            result=run(self.ledger,date(2026,11,8),
                       {"weekly":"","monthly":hook,"model":""},weekly=False,model=False)
            self.assertEqual(result["monthly"],"posted")
            self.assertEqual(len(messages),1)
            self.assertIsNone(messages[0])
            self.grade(0)
            result=run(self.ledger,date(2026,11,8),
                       {"weekly":"","monthly":hook,"model":""},weekly=False,model=False)
            self.assertEqual(result["monthly"],"updated")
            self.assertEqual(messages,[None,"111111111"])

    def test_monthly_multipart_send_and_patch_use_same_message(self):
        self.grade(0)
        x=summary(self.ledger,date(2026,11,1),date(2026,11,30))
        data={k:v for k,v in x.items() if k!="records"}
        calls=[]
        def fake_month(payload,hook,png,*,message_id=None):
            self.assertTrue(png.startswith(b"\x89PNG"))
            calls.append(message_id)
            return {"message_id":"111111111","channel_id":"222222222"}
        params={"kind":"monthly","period_id":"2026-11","issue_day":date(2026,11,1),
                "webhook":"https://discord.com/api/webhooks/123456/token"}
        with patch("recap_reports.month_send",side_effect=fake_month):
            self.assertEqual(publish_period(self.ledger,data=data,payload=monthly_payload(x),
                                            png=calendar_png(x),**params),"posted")
            self.grade(1)
            y=summary(self.ledger,date(2026,11,1),date(2026,11,30))
            self.assertEqual(publish_period(self.ledger,data={k:v for k,v in y.items() if k!="records"},
                                            payload=monthly_payload(y),png=calendar_png(y),**params),"updated")
        self.assertEqual(calls,[None,"111111111"])


if __name__=="__main__":
    unittest.main()
