"""Synthetic presentation, transport limits, and calendar/receipt compatibility."""
import copy
from datetime import datetime, timezone
from io import StringIO
import json
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from m13_beta_signals import render_beta, signal_proof, signal_identity
from m13_beta_dispatch import process
from m13_beta_grade_issues import delivered_record, DELIVERED
from m13_discord_publish import publish, render_watchlist_pages, NoRedirect
from m13_discord_embeds import (YES_COLOR, NO_COLOR, NEUTRAL_COLOR, payload_text,
    validate_payload, units, render_paper_result)
from m13_design_preview import previews, deliver, LABEL, ROLES
from m13_watchlist_dispatch import process as process_watchlist
from test_m13_beta_grade_issues import paper_record

NOW=datetime(2026,11,3,15,tzinfo=timezone.utc)


def envelope(side="YES",kickoff="2026-11-04T05:30:00Z"):
    return {"schema_version":1,"status":"experimental_paper","trades_placed":0,"signals":[{
        "home_team":"Fictional Northbridge","away_team":"Fictional Riverside","side":side,
        "league":"epl","market_ticker":"astatc-SYNTHETIC","espn_event_id":"999999999",
        "kickoff_utc":kickoff,"observed_at_utc":NOW.isoformat(),"model_probability":"0.61",
        "market_price":"0.55","fixture_verified":True,"quote_verified":True}]}


class EmbedPresentationTests(unittest.TestCase):
    def test_yes_and_no_use_native_side_accents_and_compact_fields(self):
        for side,color in (("YES",YES_COLOR),("NO",NO_COLOR)):
            p=render_beta(envelope(side),now=NOW,require_current_day=True)
            e=p['embeds'][0]
            self.assertEqual(e['color'],color)
            self.assertIn('BTTS '+side,e['fields'][0]['value'])
            self.assertIn('11:30 PM CT',e['description'])
            self.assertIn('Premier League',e['description'])
            self.assertEqual(e['fields'][1]['value'],'61%')
            self.assertEqual(e['fields'][2]['value'],'$0.55')
            self.assertEqual(e['footer']['text'],'Experimental paper pick')
            self.assertTrue(all(f['inline'] for f in e['fields']))
            validate_payload(p)

    def test_result_accents_identify_side_not_win_or_loss(self):
        for side,outcome,hg,ag,color in (('YES','WIN',2,1,YES_COLOR),('YES','LOSS',0,2,YES_COLOR),
                                       ('NO','WIN',0,0,NO_COLOR),('NO','LOSS',1,1,NO_COLOR)):
            p=render_paper_result(envelope(side)['signals'][0],{'status':'graded','result':outcome,'home_goals':hg,'away_goals':ag})
            e=p['embeds'][0]
            self.assertEqual(e['color'],color)
            self.assertEqual(e['fields'][1]['value'],'**'+outcome+'**')
            self.assertEqual(e['fields'][2]['value'],f'{hg}–{ag}')
            self.assertEqual(e['footer']['text'],'Verified full-time · Paper result')

    def test_pending_and_unconfirmed_results_have_no_published_card(self):
        for status in ('pending','unconfirmed','cancelled','postponed'):
            self.assertIsNone(render_paper_result(envelope()['signals'][0],{'status':status}))

    def test_contradictory_result_does_not_get_formatted_as_verified(self):
        with self.assertRaises(ValueError):render_paper_result(envelope()['signals'][0],{'status':'graded','result':'WIN','home_goals':0,'away_goals':0})

    def test_long_match_names_are_preserved_beyond_title_limit(self):
        data=envelope();s=data['signals'][0];s['home_team']='Fictional '+('Northbridge '*20);s['away_team']='Fictional '+('Riverside '*20)
        p=render_beta(data,now=NOW)
        self.assertLessEqual(units(p['embeds'][0]['title']),256)
        self.assertIn(' '.join(s['home_team'].split()),payload_text(p))
        self.assertIn(' '.join(s['away_team'].split()),payload_text(p))

    def test_special_characters_and_mentions_are_safe(self):
        data=envelope();data['signals'][0]['home_team']='Fictional São & Atlético [N] *United* @everyone'
        p=render_beta(data,now=NOW)
        self.assertIn('São & Atlético',payload_text(p));self.assertEqual(p['allowed_mentions'],{'parse':[]})
        scan={'status':'fixture_schedule','date_central':'2026-11-03','fixtures':[{'league':'Sample [League]','home_team':'Club *A*','away_team':'Club _B_','kickoff_utc':'2026-11-03T20:00:00Z'}]}
        text=payload_text(render_watchlist_pages(scan)[0])
        self.assertIn(r'Club \*A\*',text);self.assertIn(r'Club \_B\_',text)

    def test_missing_optional_metadata_is_safe_but_required_quote_stays_required(self):
        p=render_beta(envelope(),now=NOW);validate_payload(p)
        signal=envelope()['signals'][0];signal.pop('market_price');signal.pop('model_probability')
        result=render_paper_result(signal,{'status':'graded','result':'LOSS','home_goals':0,'away_goals':0})
        validate_payload(result)
        with self.assertRaises(ValueError):render_beta(dict(envelope(),signals=[signal]),now=NOW)

    def test_quote_precision_is_not_silently_displayed_as_zero(self):
        data=envelope();data['signals'][0]['market_price']='0.000001'
        self.assertEqual(render_beta(data,now=NOW)['embeds'][0]['fields'][2]['value'],'$0.000001')

    def test_busy_watchlist_preserves_all_competitions_and_fixtures(self):
        scan={'status':'fixture_schedule','date_central':'2026-11-03','fixtures':[
            {'league':f'Competition {i//5:02d}','home_team':f'Fictional Home {i}','away_team':f'Fictional Away {i}',
             'kickoff_utc':'2026-11-04T05:30:00Z'} for i in range(400)]}
        pages=render_watchlist_pages(scan)
        self.assertGreater(len(pages),1)
        text='\n'.join(payload_text(p) for p in pages)
        for i in range(400):self.assertEqual(text.count(f'Fictional Home {i} vs Fictional Away {i}**'),1)
        for p in pages:
            validate_payload(p)
            self.assertEqual(p['embeds'][0]['color'],NEUTRAL_COLOR)
            self.assertLessEqual(len(p['embeds'][0]['fields']),25)
            self.assertIn('All times Central',payload_text(p))

    def test_message_and_aggregate_limits_use_utf16_units(self):
        validate_payload({'content':'🟢'*1000})
        with self.assertRaises(ValueError):validate_payload({'content':'🟢'*1001})
        pair=[{'title':'T','description':'x'*2999,'color':NEUTRAL_COLOR} for _ in range(2)]
        validate_payload({'embeds':pair})
        pair[0]['description']+='x'
        with self.assertRaises(ValueError):validate_payload({'embeds':pair})

    def test_all_native_embed_limits_fail_before_delivery(self):
        base={'title':'T','description':'D','color':YES_COLOR,'footer':{'text':'F'}}
        cases=[{'embeds':[dict(base,title='x'*257)]},{'embeds':[dict(base,description='x'*4097)]},
               {'embeds':[dict(base,footer={'text':'x'*2049})]}, {'embeds':[base]*11},
               {'embeds':[dict(base,fields=[{'name':'N','value':'x'*1025}])]},
               {'embeds':[dict(base,fields=[{'name':'x'*257,'value':'V'}])]},
               {'embeds':[dict(base,fields=[{'name':'N','value':'V'}]*26)]}]
        for p in cases:
            with self.subTest(p=list(p)),self.assertRaises(ValueError):validate_payload(p)

    def test_signal_proof_does_not_depend_on_presentation(self):
        s=envelope()['signals'][0];before=signal_proof(s)
        render_beta(envelope(),now=NOW)
        self.assertEqual(signal_proof(s),before)
        issue,receipt,signal=paper_record()
        signal['kickoff_utc']='2026-11-08T16:30:00Z'
        issue['body']='statrally-beta-id:'+signal_identity(signal)+'\nstatrally-beta-data:'+json.dumps(signal)
        receipt['body']=DELIVERED+'\nstatrally-beta-delivery-proof:'+signal_proof(signal)
        self.assertEqual(delivered_record(issue,[receipt]),signal)

    def test_new_picks_reject_tomorrow_before_any_reservation(self):
        with patch('m13_beta_dispatch.github') as api,patch('m13_beta_dispatch.publish') as send:
            with self.assertRaises(ValueError):process(envelope(kickoff='2026-11-04T06:00:00Z'),'owner/repo','token','synthetic',now=NOW)
        api.assert_not_called();send.assert_not_called()

    def test_watchlist_delivery_rejects_stale_or_future_day_before_reserving(self):
        for day in ('2026-11-02','2026-11-04'):
            with patch('m13_watchlist_dispatch.records') as records,patch('m13_watchlist_dispatch.publish') as send:
                with self.assertRaises(ValueError):process_watchlist({'date_central':day},'owner/repo','token','synthetic',now=NOW)
            records.assert_not_called();send.assert_not_called()

    def test_spring_fall_and_midnight_pick_boundaries(self):
        for now,last,next_day in (('2026-03-08T06:30:00Z','2026-03-09T04:59:00Z','2026-03-09T05:00:00Z'),
                                 ('2026-11-01T05:30:00Z','2026-11-02T05:59:00Z','2026-11-02T06:00:00Z')):
            clock=datetime.fromisoformat(now.replace('Z','+00:00'))
            data=envelope(kickoff=last);data['signals'][0]['observed_at_utc']=now
            validate_payload(render_beta(data,now=clock,require_current_day=True))
            data['signals'][0]['kickoff_utc']=next_day
            with self.assertRaises(ValueError):render_beta(data,now=clock,require_current_day=True)

    def test_wait_receipt_preserves_query_and_extracts_no_message_body(self):
        requests=[]
        class Response:
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,size):return b'{"id":"1234","channel_id":"5678","content":"FICTIONAL"}'
        def opener(request,timeout):requests.append(request);return Response()
        receipt=publish({'content':'DESIGN TEST'},'https://discord.com/api/webhooks/1/SYNTHETIC?thread_id=9&wait=false',opener=opener,wait=True)
        self.assertEqual(receipt,{'message_id':'1234','channel_id':'5678'})
        self.assertEqual(parse_qs(urlsplit(requests[0].full_url).query),{'thread_id':['9'],'wait':['true']})
        self.assertIsNone(NoRedirect().redirect_request(None,None,302,'',{},'https://example.invalid'))

    def test_design_previews_are_labeled_and_fit_one_message_per_role(self):
        payloads=previews();self.assertEqual(set(payloads),set(ROLES))
        for p in payloads.values():
            validate_payload(p);self.assertIn(LABEL,p['content'])
            self.assertTrue(all(LABEL in e['footer']['text'] for e in p['embeds']))

    def test_design_send_attempts_each_role_once_and_stops_on_uncertainty(self):
        channels=iter(('10','20','30'));sent=[]
        class Response:
            status=200
            def __init__(self):self.channel=next(channels)
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,size):return json.dumps({'guild_id':'1','channel_id':self.channel}).encode()
        def sender(payload,url,wait):
            sent.append(url)
            if len(sent)==2:raise OSError('uncertain')
            return {'message_id':'100','channel_id':'10'}
        bindings={role:'https://discord.com/api/webhooks/'+str(i)+'/SYNTHETIC' for i,role in enumerate(ROLES)}
        with patch('sys.stdout',StringIO()),self.assertRaises(OSError):
            deliver(previews(),bindings,sender=sender,opener=lambda *a,**k:Response())
        self.assertEqual(len(sent),2)
