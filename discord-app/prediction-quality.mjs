// Public display/approval policy only. No prediction calculation or market input.
export const requiredConditions=["accuracy_above_prevalence","no_precision","no_recall","brier","log_loss","calibration","test_sample","calibration_sample","both_sides","coverage","high_confidence","paired_accuracy_evidence","high_confidence_stability","stability","data_quality","fresh_forward_evidence","regression_and_leakage_checks"];
const sameKeys=(v,keys)=>v&&typeof v==="object"&&!Array.isArray(v)&&Object.keys(v).sort().join(",")===[...keys].sort().join(",");
export function validPolicy(p) {
 return sameKeys(p,["schema_version","policy_version","descriptive_minimum","maximum_selections","minimum_validation_observations","maximum_calibration_ece","minimum_validated_coverage","required_conditions","approved_policies","note"])&&
  p.schema_version===1&&/^[A-Za-z0-9_.-]{1,100}$/.test(p.policy_version)&&p.descriptive_minimum==="0.55"&&p.maximum_selections===3&&
  Number.isInteger(p.minimum_validation_observations)&&p.minimum_validation_observations>=200&&
  typeof p.maximum_calibration_ece==="number"&&p.maximum_calibration_ece>=0&&p.maximum_calibration_ece<=.08&&
  typeof p.minimum_validated_coverage==="number"&&p.minimum_validated_coverage>=.1&&p.minimum_validated_coverage<=1&&
  Array.isArray(p.approved_policies)&&Array.isArray(p.required_conditions)&&[...p.required_conditions].sort().join(",")===[...requiredConditions].sort().join(",");
}
export function probabilityCategory(value) {
 const n=Number(value);if(!Number.isFinite(n)||n<.5||n>1)throw new Error("Invalid selected-side probability");
 return n<.55?"Low confidence":n<.6?"Moderate confidence":n<.7?"Higher model probability":"Very high model probability";
}
export function classifyPrediction(p,policy=null,now=null) {
 const confidence=Number(p.confidence),reasons=[];
 if(confidence<.55)reasons.push("below_descriptive_screen");
 if(p.probabilities_calibrated!==true)reasons.push("uncalibrated");
 if(p.data_quality_status!=="verified")reasons.push("unverified_data_quality");
 let approved=null;
 if(!validPolicy(policy))reasons.push("selection_policy_invalid");
 else {
  for(const rule of policy.approved_policies) {
   const keys=["approval_id","model_version","league","side","minimum_probability","observations","ece","coverage","deployment_gate_passed","fresh_forward_evidence","passed_conditions","threshold_selected_on","selection_end","approved_at","valid_until","evidence_sha256","calibration_method"];
   if(!sameKeys(rule,keys)||rule.model_version!==p.model_version||rule.league!==p.league||rule.side!==p.side)continue;
   const cutoff=Number(rule.minimum_probability),created=Date.parse(p.created_at),selection=Date.parse(rule.selection_end),approval=Date.parse(rule.approved_at),expiry=Date.parse(rule.valid_until);
   if(!Number.isFinite(cutoff)||cutoff<.55||cutoff>confidence||rule.deployment_gate_passed!==true||rule.fresh_forward_evidence!==true||
    !Array.isArray(rule.passed_conditions)||[...rule.passed_conditions].sort().join(",")!==[...requiredConditions].sort().join(",")||
    rule.threshold_selected_on!=="validation"||!["sigmoid","isotonic"].includes(rule.calibration_method)||
    !Number.isInteger(rule.observations)||rule.observations<policy.minimum_validation_observations||
    typeof rule.ece!=="number"||!(rule.ece>=0&&rule.ece<=policy.maximum_calibration_ece)||
    typeof rule.coverage!=="number"||!(rule.coverage>=policy.minimum_validated_coverage&&rule.coverage<=1)||
    !/^[a-f0-9]{64}$/.test(rule.evidence_sha256)||!(selection<approval&&approval<=created)||
    !(expiry>Math.max(Date.parse(p.kickoff_utc),now?new Date(now).getTime():created)))continue;
   approved=rule.approval_id;break;
  }
  if(approved===null)reasons.push("no_applicable_validated_policy");
 }
 const eligible=reasons.length===0&&approved!==null;
 return {probability_category:probabilityCategory(p.confidence),category_is_validated_reliability:false,
  calibration_status:p.probabilities_calibrated===true?"calibrated_model_output":"uncalibrated",
  selection_eligible:eligible,selection_status:eligible?"validated_policy_eligible":"experimental_forecast",
  selection_reasons:reasons,approval_id:eligible?approved:null,policy_version:policy?.policy_version??"invalid"};
}
export function filterForecasts(items,filter,policy=null) {
 return items.filter(r=>filter==="yes"?r.prediction.side==="YES":filter==="no"?r.prediction.side==="NO":
  filter==="low"?classifyPrediction(r.prediction,policy).probability_category==="Low confidence":
  filter==="top"?classifyPrediction(r.prediction,policy).selection_eligible:
  filter==="pending"?["pending","unconfirmed","provider_unavailable"].includes(r.grade?.status||"pending"):
  filter==="graded"?r.grade?.status==="graded":true);
}
