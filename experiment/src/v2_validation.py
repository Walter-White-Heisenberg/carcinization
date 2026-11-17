"""Semantic guards for an independent CONVERGENCE study, not a STOPPING adapter."""
from __future__ import annotations
import json
import math
import hashlib
from pathlib import Path
from statistics import NormalDist

def strict_json_loads(text):
    def pairs(items):
        out={}
        for key,value in items:
            if key in out:raise ValueError('Duplicate JSON key: '+key)
            out[key]=value
        return out
    def invalid_constant(value):raise ValueError('Nonstandard JSON number: '+value)
    return json.loads(text,object_pairs_hook=pairs,parse_constant=invalid_constant)

def assert_origin(record):
    if record['namespace']!='CONVERGENCE' or record['study_id']!='conv_review_trajectory':raise ValueError('Wrong study identity')
    fake=record['data_origin'] in {'fixture','illustrative','synthetic'}
    if fake and (not record['fixture'] or not record['illustrative']):raise ValueError('Toy/fixture origin must remain visibly tagged')
    if fake and record['evidence_class'] not in {'engineering_validation','synthetic_identifiability','diagnostic_only'}:
        raise ValueError('Toy data cannot become pilot evidence')
    if record['data_origin']=='real' and (record['fixture'] or record['illustrative']):raise ValueError('Real and fixture flags conflict')
    if not record['label_source'].strip() or not record['rubric_version'].strip():raise ValueError('Missing label provenance')

def assert_generation_lineage(record,registry,allow_full_history=False,allow_reset=False):
    assert_origin(record)
    parents=record['parent_record_ids']
    if len(parents)!=len(set(parents)) or record['record_id'] in parents:raise ValueError('Duplicate or self parent')
    if not set(parents)<=set(registry):raise ValueError('Unknown parent IDs')
    if 'history_mode' not in record:return
    from generation_contracts import assert_source_bindings
    assert_source_bindings(record,registry)
    root=record['lineage_root_record_id']
    if root!=record['record_id'] and (root not in registry or registry[root].get('paper_id')!=record['paper_id']):
        raise ValueError('Unknown or cross-paper lineage root')
    ids=record['history_record_ids'];prefix=record['prefix_record_ids'];mode=record['history_mode']
    if len(ids)!=len(set(ids)) or not set(ids+prefix)<=set(parents):raise ValueError('History must be unique known lineage')
    if mode=='none' and (ids or prefix):raise ValueError('Independent context cannot contain review history')
    if mode=='previous_review_only' and (len(ids)>1 or prefix):raise ValueError('Only one prior review is permitted')
    expected='previous_review_only' if ((record['condition']=='A_LOOP' and record['round']>0) or
                    (record['condition']=='B_REVIEW' and record['stage']=='manuscript' and record['round']>0) or
                    (record['track']=='PERTURBATION_TRACK' and record['prompt_id']=='P01')) else 'none'
    if mode!=expected:raise ValueError('Context mode conflicts with registered condition/stage')
    if expected=='previous_review_only' and len(ids)!=1:raise ValueError('Required review context is missing')
    if mode=='full_critique_history' and not allow_full_history:raise ValueError('Full history is not registered in the default design')
    if record['intervention_type']=='RESET' and not allow_reset:raise ValueError('RESET is not part of the default CONVERGENCE design')
    if record['intervention_type'] in {'KEEP','PERTURB'} and not record['intervention_id']:
        raise ValueError('Perturbation branch must identify its intervention')
    for key in ids+prefix:
        parent=registry[key]
        if parent.get('paper_id')!=record['paper_id'] or parent.get('trajectory_id')!=record['trajectory_id']:
            raise ValueError('Cross-paper or cross-trajectory context leakage')
        if parent.get('document_kind',parent.get('stage'))!='review':raise ValueError('Review history must reference an actual review artifact')
        # U(s) reviews Q(s), and the writer consumes it to produce Q(s+1).
        prior_round=record['round'] if record['prompt_id']=='P08' else record['round']-1
        if parent.get('round')!=prior_round:raise ValueError('Wrong review generation/timepoint')
    expected_review=record['input_review_record_id']
    if mode=='previous_review_only' and ids!=[expected_review]:raise ValueError('History differs from bound review input')


def assert_lineage(record,registry,allow_full_history=False,allow_reset=False):
    assert_generation_lineage(record,registry,allow_full_history,allow_reset)
    usage=record['usage']
    if usage['cumulative_generation_call_count']<usage['generation_call_count']:raise ValueError('Invalid cumulative budget')
    if any(usage[k] is None for k in ['input_tokens','output_tokens','reasoning_tokens','cache_read_tokens','cache_write_tokens','cost_amount']) and not usage['unknown_reason']:
        raise ValueError('Unavailable budget fields require an explicit reason')
    if usage['critique_count_source']=='unknown' and usage['critique_count'] is not None:
        raise ValueError('Unknown critique count cannot silently become zero')
    if usage['critique_count_source']=='P11_human_validated' and not usage['critique_count_record_id']:
        raise ValueError('Validated critique count needs its actual annotation record')
    if record['status']=='success' and not record['raw_text'].strip():raise ValueError('Successful full review cannot be empty')
    if record['terminal_no_issue'] and (record['status']!='success' or usage['critique_count']!=0):
        raise ValueError('No-concern review must retain success, zero critique count and its call cost')
    if record['terminal_no_issue'] and record['document_kind']!='review':raise ValueError('No-concern flag applies only to full reviews')

    if record.get("prompt_id")!="INPUT" and record['usage']['generation_call_count']>0:
        from study_locks import utc
        if record.get("request_sent_at_utc") is None:raise ValueError("Missing actual request timestamp")
        utc(record["request_sent_at_utc"])
    if record['data_origin']=='real' and record['status']=='success' and record['prompt_id']!='INPUT' and record['usage']['generation_call_count']<1:
        raise ValueError('Real successful generation must retain its call count')

def _assert_adjudication_decision(payload,approved_human_decisions):
    if payload['resolution'] is None:
        if payload['adjudicator_id'] is not None or payload['human_approval_record_id'] is not None:
            raise ValueError('Unresolved proposal cannot impersonate an approved human decision')
        return
    approval=approved_human_decisions.get(payload['human_approval_record_id'])
    if not approval:raise ValueError('No actual human approval record')
    for key in ['unit_id','resolution','adjudicator_id']:
        if approval.get(key)!=payload.get(key):raise ValueError('Human approval does not match this resolution')
    if payload['requires_human_decision'] is not False:raise ValueError('Resolved and pending-human states conflict')

def fixed_major_recall(identified_ids,unknown_match_ids,frozen_reference_ids):
    refs=list(frozen_reference_ids)
    if len(refs)!=len(set(refs)):raise ValueError('Duplicate frozen reference IDs')
    r=set(refs);found=set(identified_ids);unknown=set(unknown_match_ids)
    if not (found|unknown)<=r or found&unknown:raise ValueError('Invalid fixed-denominator accounting')
    if not refs:return {'fixed_n':0,'confirmed_found':0,'unknown':0,'lower':None,'upper':None,'reason':'no_frozen_major_defects'}
    return {'fixed_n':len(refs),'confirmed_found':len(found),'unknown':len(unknown),
            'lower':len(found)/len(refs),'upper':len(found|unknown)/len(refs),'reason':None}

def _legacy_public_generation_payload(paper,previous_review='NONE',fact_constraints=None):
    """An allowlist constructor; G0/private evidence objects are not accepted."""
    if not isinstance(paper,str) or not isinstance(previous_review,str):raise ValueError('Use actual manuscript/review text')
    result={'paper':paper,'previous_review':previous_review}
    if fact_constraints is not None:
        if not isinstance(fact_constraints,str):raise ValueError('Only approved factual text; never pass a private ledger object')
        result['fact_constraints']=fact_constraints
    return result

def _legacy_assert_public_generation_payload(payload):
    if not set(payload)<={'paper','previous_review','fact_constraints'}:raise ValueError('Private/evaluation field in generation payload')
    if not {'paper','previous_review'}<=set(payload) or any(not isinstance(v,str) for v in payload.values()):
        raise ValueError('Invalid public generation payload')

def _legacy_assert_approved_generation_sources(payload,approved_artifact_hashes):
    """Prevent private labels being inserted under an otherwise allowed key.

    Hashes must come from coordinator-owned paper/generated-review/public-author-
    fact manifests, not from the LLM or a private G0/evaluation registry.
    """
    _legacy_assert_public_generation_payload(payload)
    if set(payload)!=set(approved_artifact_hashes):raise ValueError('Unexpected public input set')
    for field,text in payload.items():
        if hashlib.sha256(text.encode('utf-8')).hexdigest()!=approved_artifact_hashes[field]:
            raise ValueError('Generation source differs from the approved public artifact')

def assert_nonaggregated_metric_components(components,metric_id=None):
    from metric_contracts import COMPONENTS
    if metric_id not in COMPONENTS:raise ValueError('Metric ID outside registered catalog')
    for row in components:
        value=row['value']
        if value is not None and not math.isfinite(value):raise ValueError('Metric values must be finite')
        if row['name'] not in COMPONENTS[metric_id]:raise ValueError('Unregistered metric component; no quality aggregation')

def model_output_envelope(payload,task_schema,metadata,raw_output_sha256):
    """The orchestrator supplies blinded-task provenance outside the judge prompt."""
    result=dict(metadata)
    result.update({'task_schema':task_schema,'payload':payload,'raw_output_sha256':raw_output_sha256})
    return result


def conditional_major_recall(evaluable,found,unknown_found,unknown_not_found):
    """Partial-identification bounds; unknown applicability cannot disappear."""
    values=[evaluable,found,unknown_found,unknown_not_found]
    if any(not isinstance(x,int) or isinstance(x,bool) or x<0 for x in values) or found>evaluable:
        raise ValueError('Invalid conditional recall counts')
    low_n=evaluable+unknown_not_found; high_n=evaluable+unknown_found
    # If no definite applicable item exists, the empty applicable population is
    # possible. Bounds are NA rather than asserting a recall for that population.
    if evaluable==0:return {'lower':None,'upper':None,'reason':'no_confirmed_applicable_items',
                             'unknown_n':unknown_found+unknown_not_found}
    return {'lower':found/low_n,'upper':(found+unknown_found)/high_n,'reason':None,
            'unknown_n':unknown_found+unknown_not_found}


def assert_output_path(target,workspace_root,frozen_root):
    """Resolve existing symlinks/junctions, then restrict all scientific writes."""
    target=Path(target).resolve();allowed=Path(workspace_root).resolve();frozen=Path(frozen_root).resolve()
    if target==frozen or frozen in target.parents:raise ValueError('STOPPING repository is sealed read-only')
    if target!=allowed and allowed not in target.parents:raise ValueError('Output outside independent workspace')
    if any(part in {'.git','.maintainer','.aws'} for part in target.relative_to(allowed).parts):
        raise ValueError('Protected configuration is not a scientific output')
    if target.exists() and target.is_file() and target.stat().st_nlink!=1:
        raise ValueError('Multi-linked scientific output is not writable')
    return target


def plan_confirmatory_n(paper_effects,delta=.10,alpha=.05,power=.80):
    """Normal-approximation planning convention; never a six-paper test.

    Paper effects must be computed from reconciled human endpoints on independent
    pilot papers. Their observed between-paper SD includes residual measurement
    variability. No block/round labels are treated as independent papers.
    """
    import statistics
    if len(paper_effects)<6 or any(not math.isfinite(x) or not -1<=x<=1 for x in paper_effects):
        raise ValueError('At least six finite independent paper contrasts required')
    if not 0<alpha<1 or not .5<power<1 or not 0<delta<=1:raise ValueError('Invalid planning parameters')
    # Fixed inflation protects only against modest pilot SD instability; it does
    # not supply a distribution-free power guarantee.
    observed_sd=statistics.stdev(paper_effects);planning_sd=1.25*max(observed_sd,.05)
    z=NormalDist().inv_cdf(1-alpha/2)+NormalDist().inv_cdf(power)
    return {'n_papers':max(12,math.ceil((z*planning_sd/delta)**2)),
            'delta':delta,'alpha':alpha,'power':power,'observed_sd':observed_sd,
            'planning_sd':planning_sd,'sd_multiplier':1.25,'sd_floor':.05,
            'interpretation':'planning_approximation_not_a_power_guarantee'}


def _coverage_counts(frozen_ids,coverage_rows):
    """Require two pre-generation judgments; disagreements stay unknown."""
    frozen=list(frozen_ids)
    if len(set(frozen))!=len(frozen):raise ValueError('Duplicate frozen G0 item')
    rows={}
    for row in coverage_rows:
        key=row['item_id']
        if key in rows or key not in frozen:raise ValueError('Duplicate or unknown coverage item')
        if len(row['annotator_ids'])!=2 or len(set(row['annotator_ids']))!=2 or len(row['labels'])!=2:
            raise ValueError('Two distinct actual annotators required')
        if not set(row['labels'])<={'covered','uncovered','uncertain'}:raise ValueError('Unknown coverage label')
        if row['frozen_before_generation'] is not True:raise ValueError('Post-generation coverage is not admissible')
        labels=row['labels'];rows[key]=labels[0] if labels[0]==labels[1] else 'uncertain'
    if set(rows)!=set(frozen):raise ValueError('Coverage ledger must retain every frozen G0 item')
    return {label:[i for i in frozen if rows[i]==label] for label in ['covered','uncovered','uncertain']}


def fact_coverage_strata(activation_ref,analysis_ref,engineering=False):
    from study_locks import coverage_from_analysis
    return coverage_from_analysis(activation_ref,analysis_ref,engineering)


def assert_adjudication_authority(task_record,activation_ref,analysis_ref,engineering=False):
    from study_locks import adjudication_from_analysis
    return adjudication_from_analysis(task_record,activation_ref,analysis_ref,engineering)



def human_endpoint_summary(paper_contrasts,planned_papers=6,endpoint_distances=None):
    """Shared-start ΔC equals terminal control-D minus terminal loop-D.

    Missing papers remain in the planned denominator. Optional terminal distances
    tighten the bound when exactly one arm is observed.
    """
    if len(paper_contrasts)!=planned_papers:raise ValueError('Retain every planned paper')
    if endpoint_distances is not None and len(endpoint_distances)!=planned_papers:raise ValueError('Endpoint alignment mismatch')
    lows=[];highs=[];observed=[]
    for i,value in enumerate(paper_contrasts):
        if endpoint_distances is not None:
            e=endpoint_distances[i]
            if any(x is not None and (not isinstance(x,(int,float)) or isinstance(x,bool) or not math.isfinite(x) or not 0<=x<=1) for x in [e['loop'],e['control']]):
                raise ValueError('Invalid endpoint D')
            if value is None and e['loop'] is not None and e['control'] is not None:
                raise ValueError('Known endpoint pair cannot be declared missing')
        if value is not None:
            if not math.isfinite(value) or not -1<=value<=1:raise ValueError('Shared-start contrast outside [-1,1]')
            lows.append(value);highs.append(value);observed.append(value)
            if endpoint_distances is not None:
                e=endpoint_distances[i]
                if e['loop'] is None or e['control'] is None or not math.isclose(value,e['control']-e['loop'],abs_tol=1e-12):
                    raise ValueError('Contrast does not match the two human endpoints')
            continue
        if endpoint_distances is None:lows.append(-1);highs.append(1);continue
        e=endpoint_distances[i];loop=e['loop'];control=e['control']
        if any(x is not None and (not math.isfinite(x) or not 0<=x<=1) for x in [loop,control]):raise ValueError('Invalid endpoint D')
        lows.append((control if control is not None else 0)-(loop if loop is not None else 1))
        highs.append((control if control is not None else 1)-(loop if loop is not None else 0))
    missing=planned_papers-len(observed)
    return {'status':'complete_human_pilot_endpoint' if not missing else 'measurement_missing_exploratory_only',
            'planned_papers':planned_papers,'observed_papers':len(observed),'missing_papers':missing,
            'complete_pilot_mean':sum(observed)/planned_papers if not missing else None,
            'lower_bound':sum(lows)/planned_papers,'upper_bound':sum(highs)/planned_papers}
