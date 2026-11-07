"""Fictional offline ledger, grading, pagination and failure-recovery scenarios."""
import copy
from datetime import datetime, timedelta, timezone
import json
import re
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from m13_discord_embeds import COMPETITIONS, validate_payload
from prediction_ledger import Ledger, DELIVERY, PREDICTION
from prediction_platform import annotate, grade_issued, prediction_pages, publish_predictions, publish_results, verified_outcome, report_provider_outage
from prediction_schema import forecast_identity, validate

NOW=datetime(2026,11,5,11,tzinfo=timezone.utc)
REPO="stelladeecoder/statrally-soccer-automation"


class FakeGitHub:
    def __init__(self):self.issues=[];self.comments={};self.now=NOW+timedelta(seconds=1);self.sequence=100
    def __call__(self,method,path,token,data=None):
        if method not in {"GET","POST"}:raise AssertionError("Canonical records must never be patched")
        parts=urlsplit(path);match=re.search(r"/issues/(\d+)/comments$",parts.path)
        if method=="GET":
            values=self.comments.get(int(match[1]),[]) if match else self.issues
            page=int(parse_qs(parts.query).get('page',['1'])[0]);return copy.deepcopy(values[(page-1)*100:page*100])
        self.sequence+=1;stamp=self.now.isoformat();self.now+=timedelta(seconds=1)
        result={"id":self.sequence,"body":data['body'],"user":{"login":"github-actions[bot]"},"created_at":stamp,"updated_at":stamp}
        if match:self.comments.setdefault(int(match[1]),[]).append(copy.deepcopy(result))
        else:
            result.update(number=len(self.issues)+1,title=data['title']);self.issues.append(copy.deepcopy(result));self.comments[result['number']]=[]
        return copy.deepcopy(result)


def prediction(index=1,p_yes="0.28",kickoff="2026-11-05T18:00:00+00:00"):
    p=float(p_yes)
    return {"fixture_id":f"espn:epl:{index}","espn_event_id":str(index),"league":"epl",
            "home_team":f"Fictional Home {index}","away_team":f"Fictional Away {index}","espn_home_team_id":str(index*2),
            "espn_away_team_id":str(index*2+1),"kickoff_utc":kickoff,"fixture_observed_at":NOW.isoformat(),
            "fixture_source":"ESPN scoreboard","prediction_status":"predicted","p_yes":p_yes,"p_no":format(1-p,'.17g'),
            "side":"YES" if p>=.5 else "NO","confidence":format(max(p,1-p),'.17g'),
            "model_name":"uncalibrated_rolling_poisson","model_version":"rolling-poisson-10-v1","created_at":NOW.isoformat(),
            "history_coverage":{"minimum_matches_per_team":10,"home_matches_used":10,"away_matches_used":10,
                                "latest_history_date":"2026-11-04","source":"same_competition"},
            "identity_verified":True,"probabilities_calibrated":False,"data_quality_status":"research_snapshot",
            "baseline_yes_probability":"0.55","prediction_source":"forward_recorded"}


def slate(n=1):
    return {"schema_version":1,"date_central":"2026-11-05","generated_at":NOW.isoformat(),"trades_placed":0,
            "fixtures":[prediction(i) for i in range(1,n+1)],"coverage":{league:{"provider_status":"complete","fixtures":n if league=='epl' else 0,
                "predicted":n if league=='epl' else 0,"excluded":{},"failed_queries":0} for league in COMPETITIONS}}


def final_feed(record,hg=2,ag=0,status="STATUS_FULL_TIME",completed=True):
    p=record
    return {"events":[{"id":p['espn_event_id'],"date":p['kickoff_utc'],"status":{"type":{"completed":completed,"name":status}},
                       "competitions":[{"competitors":[{"homeAway":"home","team":{"id":p['espn_home_team_id']},"score":str(hg)},
                                                          {"homeAway":"away","team":{"id":p['espn_away_team_id']},"score":str(ag)}]}]}]}


class PredictionPlatformTests(unittest.TestCase):
    def setUp(self):self.api=FakeGitHub();self.ledger=Ledger(REPO,'synthetic-token',call=self.api).load()
    def issue(self,n=1):return self.ledger.issue_slate(slate(n),now=NOW)
    def sender(self,payload,hook,**kwargs):validate_payload(payload);return {'message_id':'123456789012345678','channel_id':'223456789012345678'}

    def test_prediction_without_market_is_saved_displayable_and_gradeable(self):
        issued=self.issue();p=issued['predictions'][0]
        annotate(self.ledger,{"schema_version":1,"trades_placed":0,"markets":[{'prediction_id':p['prediction_id'],'status':'not_found','provider':'polymarket_us','checked_at':NOW.isoformat()}]})
        rows=self.ledger.export()['records'];self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['market']['status'],'not_found')
        pages=prediction_pages(rows,'FICTIONAL OFFLINE DESIGN TEST');self.assertIn('Not found',json.dumps(pages))
        self.api.now=NOW+timedelta(hours=10)
        grade_issued(self.ledger,scoreboard=lambda l,d:final_feed(p),now=self.api.now)
        self.assertTrue(self.ledger.export()['records'][0]['grade']['correct'])

    def test_no_72_percent_never_switches_to_yes(self):
        p=self.issue()['predictions'][0]
        self.assertEqual(p['side'],'NO');self.assertAlmostEqual(float(p['confidence']),.72)
        card=prediction_pages(self.ledger.export()['records'],'TEST')[0]['embeds'][0]
        self.assertIn('🔵 BTTS NO',card['fields'][0]['value']);self.assertEqual(card['color'],0x3498DB)

    def test_top_three_accent_is_orange_while_daily_remains_blue(self):
        self.issue()
        records = self.ledger.export()['records']
        regular = prediction_pages(records, 'Daily BTTS predictions')
        highlighted = prediction_pages(records, 'Top 3 highlighted', highlighted=True)
        self.assertEqual(regular[0]['embeds'][0]['color'], 0x3498DB)
        self.assertEqual(highlighted[0]['embeds'][0]['color'], 0xF97316)
        self.assertIn('🔵 BTTS NO', highlighted[0]['embeds'][0]['fields'][0]['value'])
        self.assertIn('Highlighted experimental pick', highlighted[0]['embeds'][0]['footer']['text'])
        validate_payload(regular[0])
        validate_payload(highlighted[0])

    def test_fourteen_predictions_only_three_markets_full_pagination_and_top_three(self):
        records=self.issue(14)['predictions']
        annotations=[dict(prediction_id=p['prediction_id'],provider='polymarket_us',checked_at=NOW.isoformat(),
                          status='verified_available' if i<3 else 'not_found',
                          **({'event_slug':f'fictional-{i}','market_slug':f'fictional-btts-{i}'} if i<3 else {})) for i,p in enumerate(records)]
        annotate(self.ledger,{'schema_version':1,'trades_placed':0,'markets':annotations})
        output=self.ledger.export()['records'];self.assertEqual(len(output),14)
        self.assertEqual(sum(r['market']['status']=='verified_available' for r in output),3)
        self.assertEqual(sum(len(p['embeds']) for p in prediction_pages(output,'OFFLINE TEST')),14)
        posted=[]
        def send(payload,*args,**kwargs):posted.append(copy.deepcopy(payload));return self.sender(payload,*args,**kwargs)
        counts=publish_predictions(self.ledger,'fake-offline',now=NOW,sender=send)
        self.assertEqual(counts,{'daily':14,'top':0})
        self.assertEqual(publish_predictions(self.ledger,'fake-offline',now=NOW,sender=send),{'daily':0,'top':0})
        self.assertEqual(sum(len(p['embeds']) for p in posted if p['content'].startswith('Daily')),14)

    def test_repeat_and_intentional_revision_preserve_original(self):
        first=copy.deepcopy(self.issue()['predictions'][0]);again=self.issue()['predictions'][0]
        self.assertEqual(first,again);self.assertEqual(len(self.ledger.forecasts),1)
        changed=slate();changed['fixtures'][0]=prediction(p_yes='.65')
        revised=self.ledger.issue_slate(changed,now=NOW)['predictions'][0]
        self.assertEqual(revised['revision'],2);self.assertNotEqual(revised['prediction_id'],first['prediction_id'])
        self.assertEqual(self.ledger.forecasts[0]['prediction'],first)
        reloaded=Ledger(REPO,'fake',call=self.api).load();self.assertEqual(len(reloaded.forecasts),2)

    def test_post_kickoff_and_edited_forecasts_fail_integrity_checks(self):
        self.issue();item=next(c for c in self.api.comments[1] if c['body'].startswith(PREDICTION))
        item['updated_at']=(NOW+timedelta(hours=12)).isoformat()
        with self.assertRaisesRegex(RuntimeError,'Edited'):Ledger(REPO,'fake',call=self.api).load()

    def test_post_kickoff_issuance_never_gets_silently_accepted(self):
        self.api.now=NOW+timedelta(hours=8)
        with self.assertRaisesRegex(RuntimeError,'before kickoff'):self.issue()
        self.assertEqual(len(Ledger(REPO,'fake',call=self.api).load().forecasts),0)

    def test_unknown_private_fields_rejected_before_any_public_write(self):
        data=slate();data['fixtures'][0]['private_dataset']='must-never-leave-runner'
        with self.assertRaises(ValueError):self.ledger.issue_slate(data,now=NOW)
        self.assertFalse(self.api.issues)

    def test_uncertain_discord_delivery_keeps_forecasts_and_reservations(self):
        self.issue()
        def fail(*args,**kwargs):raise OSError('Simulated ambiguous POST')
        with self.assertRaises(OSError):publish_predictions(self.ledger,'fake',now=NOW,sender=fail)
        self.assertEqual(len(Ledger(REPO,'fake',call=self.api).load().forecasts),1)
        called=[]
        def send(payload,*args,**kwargs):called.append(payload);return self.sender(payload,*args,**kwargs)
        counts=publish_predictions(self.ledger,'fake',now=NOW,sender=send)
        self.assertEqual(counts['daily'],0)
        self.assertFalse(any(p['content'].startswith('Daily') for p in called))

    def test_final_grade_and_result_delivery_are_independent_idempotent(self):
        p=self.issue()['predictions'][0];original=copy.deepcopy(p);self.api.now=NOW+timedelta(hours=10)
        grade_issued(self.ledger,scoreboard=lambda l,d:final_feed(p),now=self.api.now)
        second=grade_issued(self.ledger,scoreboard=lambda l,d:(_ for _ in ()).throw(AssertionError('No refetch')),now=self.api.now)
        self.assertEqual(second['already_graded'],1)
        self.assertEqual(self.ledger.forecasts[0]['prediction'],original)
        self.assertEqual(publish_results(self.ledger,'fake',sender=self.sender),1)
        self.assertEqual(publish_results(self.ledger,'fake',sender=self.sender),0)

    def test_pending_postponed_canceled_abandoned_never_become_losses(self):
        p=prediction()
        for status,expected in [('STATUS_IN_PROGRESS','pending'),('STATUS_POSTPONED','postponed'),('STATUS_CANCELED','canceled'),('STATUS_ABANDONED','abandoned')]:
            result=verified_outcome(p,scoreboard=lambda l,d:final_feed(p,status=status,completed=False),now=NOW+timedelta(hours=10))
            self.assertEqual(result['status'],expected);self.assertNotIn('correct',result)
        changed=final_feed(p);changed['events'][0]['date']='2026-11-06T18:00:00Z'
        self.assertEqual(verified_outcome(p,scoreboard=lambda l,d:changed,now=NOW+timedelta(hours=10))['status'],'unconfirmed')

    def test_no_win_and_yes_loss_are_explicit_and_score_verified(self):
        for side,p_yes,hg,ag,correct in [('NO','.28',2,0,True),('NO','.28',1,1,False),('YES','.72',2,1,True),('YES','.72',0,0,False)]:
            p=prediction(p_yes=p_yes);out=verified_outcome(p,scoreboard=lambda l,d:final_feed(p,hg,ag),now=NOW+timedelta(hours=10))
            self.assertEqual(out['correct'],correct);self.assertEqual(out['side'],side)

    def test_long_names_special_characters_and_busy_pages_preserve_all_fixtures(self):
        data=slate(50)
        for p in data['fixtures']:p['home_team']='Fictional <@everyone> café 🚀 '+'A'*150;p['away_team']='Fictional Away & <script> '+p['espn_event_id']
        self.ledger.issue_slate(data,now=NOW);pages=prediction_pages(self.ledger.export()['records'],'FICTIONAL OFFLINE')
        self.assertEqual(sum(len(p['embeds']) for p in pages),50)
        for p in pages:validate_payload(p);self.assertEqual(p['allowed_mentions'],{'parse':[]})

    def test_daily_top_limit_remains_occupied_after_early_kickoffs(self):
        data=slate(6)
        for p in data['fixtures'][:3]:p['kickoff_utc']='2026-11-05T12:00:00+00:00'
        self.ledger.issue_slate(data,now=NOW)
        publish_predictions(self.ledger,'fake',now=NOW,sender=self.sender)
        counts=publish_predictions(self.ledger,'fake',now=NOW+timedelta(hours=2),sender=self.sender)
        self.assertEqual(counts['top'],0)

    def test_legacy_reservation_blocks_same_fixture_from_new_highlights(self):
        self.issue(3)
        self.ledger.issues.append({'number':99,'user':{'login':'github-actions[bot]'},
            'body':'statrally-beta-data:'+json.dumps({'league':'epl','espn_event_id':'1','kickoff_utc':'2026-11-05T18:00:00+00:00'})})
        counts=publish_predictions(self.ledger,'fake',now=NOW,sender=self.sender)
        self.assertEqual(counts,{'daily':3,'top':0})
        top_ids={e['prediction_id'] for events in self.ledger.comments.values() for event in events
                 if event['body'].startswith(DELIVERY) for e in [json.loads(event['body'][len(DELIVERY):])]
                 if e['kind']=='top'}
        self.assertNotIn(self.ledger.forecasts[0]['prediction']['prediction_id'],top_ids)

    def test_provider_outage_cannot_erase_predictions_or_override_side(self):
        issued=self.issue(3)['predictions']
        annotate(self.ledger,{'schema_version':1,'trades_placed':0,'markets':[{'prediction_id':p['prediction_id'],'provider':'polymarket_us','status':'provider_unavailable','checked_at':NOW.isoformat()} for p in issued]})
        records=self.ledger.export()['records'];self.assertEqual(len(records),3)
        self.assertTrue(all(r['prediction']['side']=='NO' and r['market']['status']=='provider_unavailable' for r in records))

    def test_provider_failure_invokes_existing_deduplicated_private_admin_alert(self):
        self.issue()
        with patch.dict('os.environ',{'STATRALLY_ADMIN_DISCORD_WEBHOOK':'https://discord.com/api/webhooks/fictional/offline'}), \
             patch('m18_admin_monitor.state',return_value=(99,{'alerts':{}})), \
             patch('m18_admin_monitor.alert',return_value=True) as alert:
            self.assertTrue(report_provider_outage(self.ledger,now=NOW))
            self.assertIn('predictions remain saved',alert.call_args.args[4].lower())
        self.assertEqual(len(self.ledger.forecasts),1)

    def test_league_coverage_projection_remains_strictly_aggregate_only(self):
        from prediction_public_export import public_metrics
        report={'schema_version':1,'status':'forward_recorded_experimental_no_trades','revision_policy':'test',
            'overall':{'n':0},'by_league':{'epl':{'n':0,'evaluated_prematch_fixtures':2,'prediction_coverage':.5},'ligue_1':{'n':0,'evaluated_prematch_fixtures':0,'prediction_coverage':None}},
            'by_model_version':{},'by_confidence':{k:{'all':{'n':0},'YES':{'n':0},'NO':{'n':0}} for k in
                ('0.50-0.55','0.55-0.60','0.60-0.65','0.65-0.70','0.70-0.75','0.75-1.01')},'by_month':{},
            'coverage':{'predicted_fixtures':1,'evaluated_prematch_fixtures':2,'fraction':.5},'no_model_promoted':True,'trades_placed':0,'note':'test'}
        self.assertEqual(public_metrics(report)['by_league']['epl']['prediction_coverage'],.5)
        report['by_league']['epl']['private_dataset']='never-export'
        with self.assertRaises(ValueError):public_metrics(report)


if __name__=='__main__':unittest.main()
