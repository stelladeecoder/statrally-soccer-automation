"""Descriptive probability, calibration and actual policy approval stay separate."""
import copy
import json
from pathlib import Path
import subprocess
import unittest

from prediction_quality import classify, describe_probability, eligible_ranked, load_policy
from prediction_platform import prediction_pages, publish_predictions
from prediction_ledger import Ledger,SELECTION
from test_prediction_platform import prediction,slate,FakeGitHub,NOW,REPO,verify_synthetic


def approved_example(p):
    """FICTIONAL policy-approved input, not a real model or deployable approval."""
    p=copy.deepcopy(p);p['probabilities_calibrated']=True;p['data_quality_status']='verified'
    p['model_version']='fictional-calibrated-fixture-v1'
    policy=load_policy()
    policy['approved_policies']=[{'approval_id':'fictional-unit-test-only','model_version':p['model_version'],
        'league':p['league'],'side':p['side'],'minimum_probability':'0.60','observations':300,'ece':.02,'coverage':.4,
        'deployment_gate_passed':True,'fresh_forward_evidence':True,'passed_conditions':policy['required_conditions'][:],
        'threshold_selected_on':'validation','selection_end':'2026-10-01T00:00:00Z','approved_at':'2026-11-01T00:00:00Z',
        'valid_until':'2026-12-01T00:00:00Z','evidence_sha256':'a'*64,'calibration_method':'sigmoid'}]
    return p,policy


class PredictionQualityTests(unittest.TestCase):
    def test_503_forecast_is_kept_visible_but_cannot_be_a_top_selection(self):
        p=prediction(p_yes='.503');q=classify(p)
        self.assertEqual(q['probability_category'],'Low confidence')
        self.assertFalse(q['selection_eligible']);self.assertIn('below_descriptive_screen',q['selection_reasons'])
        pages=prediction_pages([{'prediction':p,'market':{'status':'not_found'}}],'Fictional offline test')
        self.assertIn('50.3%',json.dumps(pages));self.assertIn('Low confidence',json.dumps(pages));self.assertIn('Not an approved selection',json.dumps(pages))

    def test_no_72_is_high_probability_but_not_validated_confidence(self):
        p=prediction(p_yes='.28');q=classify(p)
        self.assertEqual(p['side'],'NO');self.assertEqual(q['probability_category'],'Very high model probability')
        self.assertEqual(q['calibration_status'],'uncalibrated')
        self.assertFalse(q['category_is_validated_reliability']);self.assertFalse(q['selection_eligible'])

    def test_every_display_boundary_is_descriptive_only(self):
        for p,label in (('.5','Low confidence'),('.5499','Low confidence'),('.55','Moderate confidence'),('.5999','Moderate confidence'),
                        ('.6','Higher model probability'),('.6999','Higher model probability'),('.7','Very high model probability'),('1','Very high model probability')):
            self.assertEqual(describe_probability(p),label)

    def test_eligible_list_can_have_zero_one_or_two_not_forced_three(self):
        p,policy=approved_example(prediction(p_yes='.72'))
        p2=copy.deepcopy(p);p2['fixture_id']='espn:epl:2';p2['confidence']='.65';p2['p_yes']='.65';p2['p_no']='.35'
        weak=prediction(3,p_yes='.503')
        self.assertEqual(len(eligible_ranked([{'prediction':weak}],policy)),0)
        self.assertEqual(len(eligible_ranked([{'prediction':p},{'prediction':weak}],policy)),1)
        self.assertEqual(len(eligible_ranked([{'prediction':p},{'prediction':p2},{'prediction':weak}],policy)),2)

    def test_failed_no_gate_or_overall_gate_forbids_selection(self):
        for condition in ('no_precision','no_recall','accuracy_above_prevalence','brier','log_loss'):
            p,policy=approved_example(prediction(p_yes='.72'))
            policy['approved_policies'][0]['passed_conditions'].remove(condition)
            self.assertFalse(classify(p,policy)['selection_eligible'])

    def test_missing_calibration_fresh_evidence_samples_or_validation_threshold_fails(self):
        for field,value in (('deployment_gate_passed',False),('fresh_forward_evidence',False),('observations',12),('ece',.2),('coverage',.01),('threshold_selected_on','final_test')):
            p,policy=approved_example(prediction(p_yes='.72'));policy['approved_policies'][0][field]=value
            self.assertFalse(classify(p,policy)['selection_eligible'],field)
        p,policy=approved_example(prediction(p_yes='.72'));p['probabilities_calibrated']=False
        self.assertFalse(classify(p,policy)['selection_eligible'])

    def test_current_policy_records_successful_zero_selections_without_hiding_forecasts(self):
        api=FakeGitHub();ledger=Ledger(REPO,'fictional-offline',call=api).load();issued=ledger.issue_slate(slate(4),now=NOW);verify_synthetic(ledger,issued['predictions'])
        posted=[]
        def sender(payload,*a,**kw):posted.append(payload);return {'message_id':'123456789012345678','channel_id':'223456789012345678'}
        self.assertEqual(publish_predictions(ledger,'fictional-offline',now=NOW,sender=sender),{'daily':4,'starred':4})
        self.assertEqual(publish_predictions(ledger,'fictional-offline',now=NOW,sender=sender),{'daily':0,'starred':4})
        self.assertEqual(len(ledger.forecasts),4);self.assertTrue(all('BTTS model picks' in p['content'] for p in posted))
        decisions=ledger.events(1,SELECTION);self.assertEqual(len(decisions),1);self.assertEqual(decisions[0]['status'],'descriptive_only_not_validated_bet_selection')
        self.assertEqual(len(decisions[0]['highlighted_prediction_ids']),4)

    def test_star_highlights_are_not_policy_approved_or_capped(self):
        from prediction_ledger import DELIVERY
        api=FakeGitHub()
        ledger=Ledger(REPO,'offline',call=api).load()
        issued=ledger.issue_slate(slate(6),now=NOW);verify_synthetic(ledger,issued['predictions'])
        sent=[]
        def sender(payload,*args,**kwargs):
            sent.append(payload)
            return {'message_id':'123456789012345678','channel_id':'223456789012345678'}
        result=publish_predictions(ledger,'offline',now=NOW,sender=sender)
        self.assertEqual(result,{'daily':6,'starred':6})
        self.assertEqual(sum(len(p['embeds']) for p in sent),6)
        self.assertTrue(all('🟨' in str(p) for p in sent))
        self.assertFalse(any(e['kind']=='top' for e in ledger.events(1,DELIVERY)))
        self.assertFalse(classify(ledger.forecasts[0]['prediction'])['selection_eligible'])

    def test_python_and_javascript_classification_match(self):
        root=Path(__file__).resolve().parents[1];p,approved=approved_example(prediction(p_yes='.72'))
        cases=[{'prediction':prediction(p_yes=n),'policy':load_policy()} for n in ('.503','.55','.28','.61','.3','.4','0.54999999999999999','0.59999999999999998','0.69999999999999996')]+[{'prediction':p,'policy':approved}]
        for value in ('0.54999999999999999','0.59999999999999998','0.69999999999999996'):
            row={'prediction':copy.deepcopy(p),'policy':copy.deepcopy(approved)};row['prediction']['confidence']=value;cases.append(row)
        script=f"import {{classifyPrediction}} from {json.dumps((root/'discord-app/prediction-quality.mjs').as_uri())};let s='';for await(const c of process.stdin)s+=c;console.log(JSON.stringify(JSON.parse(s).map(r=>classifyPrediction(r.prediction,r.policy))));"
        result=subprocess.run(['node','--input-type=module','-e',script],input=json.dumps(cases),text=True,capture_output=True,check=True)
        self.assertEqual(json.loads(result.stdout),[classify(c['prediction'],c['policy']) for c in cases])


if __name__=='__main__':unittest.main()
