"""Offline verification of pre-generation artifacts. Does not call any API."""
from __future__ import annotations
from datetime import datetime,timezone
import hashlib,json,os
from pathlib import Path

GENERATION_ARTIFACTS=['researcher_approval','preregistration_lock','environment_lock','paper_licenses',
    'g0_major_ledger','public_fact_package','fact_coverage_ledger','annotator_roster','human_approval_registry']
EVALUATION_ARTIFACTS=['p19_private_bank','necessary_items','reference_acus']

def utc(value):
    t=datetime.fromisoformat(value.replace('Z','+00:00'))
    if t.tzinfo is None:raise ValueError('UTC offset required')
    return t.astimezone(timezone.utc)

def locked_json(data,expected_sha256):
    from v2_validation import strict_json_loads
    if not isinstance(data,bytes) or hashlib.sha256(data).hexdigest()!=expected_sha256:
        raise ValueError('Locked artifact SHA mismatch')
    return strict_json_loads(data.decode('utf-8-sig'))

def approved_roster(data,expected_sha256):
    rows=locked_json(data,expected_sha256)['people'];result={}
    for row in rows:
        rid=row['person_id']
        if not isinstance(rid,str) or not rid.strip() or rid in result:raise ValueError('Invalid roster identity')
        if row.get('kind')!='human' or not isinstance(row.get('approval_evidence_id'),str) or not row['approval_evidence_id'].strip():raise ValueError('Human roster needs an actual approval provenance reference')
        if not isinstance(row.get('roles'),list) or not row['roles'] or any(not isinstance(r,str) for r in row['roles']):raise ValueError('Roles must be an explicit nonempty list')
        result[rid]=row
    return result

def _locked_coverage_from_bytes(frozen_ids,ledger_bytes,ledger_sha256,locked_at_utc,first_generation_at_utc,
                           roster_bytes,roster_sha256):
    from v2_validation import _coverage_counts
    if not utc(locked_at_utc)<utc(first_generation_at_utc):raise ValueError('Coverage was not locked before first generation')
    roster=approved_roster(roster_bytes,roster_sha256)
    rows=locked_json(ledger_bytes,ledger_sha256)['rows']
    for row in rows:
        ids=row['annotator_ids']
        if len(ids)!=2 or len(row['labels'])!=2 or len(set(ids))!=2:raise ValueError('Exactly two distinct people and two labels required')
        if not all(i in roster and 'scientific_annotation' in roster[i]['roles'] for i in ids):raise ValueError('Coverage annotator outside locked human roster')
    return _coverage_counts(frozen_ids,rows)

def _locked_adjudication_from_bytes(payload,registry_bytes,registry_sha256,roster_bytes,roster_sha256):
    from v2_validation import _assert_adjudication_decision
    registry=locked_json(registry_bytes,registry_sha256)['decisions'];roster=approved_roster(roster_bytes,roster_sha256)
    if payload['resolution'] is not None:
        person=roster.get(payload['adjudicator_id'])
        if not person or 'adjudication' not in person['roles']:raise ValueError('Adjudicator outside locked roster')
    _assert_adjudication_decision(payload,registry)

def verify_activation(config,phase,context):
    """context is coordinator-owned, never supplied by a model.

    It binds a separately approved activation file digest, actual first-call
    timestamp (or planned call time before any calls), and the independent root.
    This validates provenance structure, not the authenticity of human signatures.
    """
    if config.get('execution_enabled') is not True:raise ValueError('execution_enabled must be true')
    if context is None:raise ValueError('No researcher-approved activation context')
    credential_name=config.get('api',{}).get('credential_env_var')
    if not credential_name or not os.environ.get(credential_name):raise ValueError('Required API credential is unavailable')
    root=Path(context['workspace_root']).resolve();path=Path(context['activation_path']).resolve()
    if json.loads((root/'config/pilot_config.json').read_text(encoding='utf-8'))!=config:
        raise ValueError('In-memory config differs from the locked file')
    if not path.is_relative_to(root):raise ValueError('Activation file outside independent workspace')
    from study_locks import ActivationRef,load_activation,read_run_log,first_generation_time
    activation_ref=ActivationRef(str(root),str(path),context['approved_activation_sha256'])
    activation=load_activation(activation_ref)
    from sampling_plan import verify_frozen_sampling
    verify_frozen_sampling(activation_ref,config)
    from jsonschema import Draft202012Validator
    def validate(name,value):
        schema=json.loads((root/'schemas'/(name+'.schema.json')).read_text(encoding='utf-8'))
        Draft202012Validator(schema).validate(value)
    validate('activation_manifest',activation)
    if activation['study_id']!='conv_review_trajectory':raise ValueError('Wrong activation study')
    required=GENERATION_ARTIFACTS+(EVALUATION_ARTIFACTS if phase=='evaluation' else [])
    artifacts=activation['artifacts'];loaded={}
    pilot_ids={p if isinstance(p,str) else p['paper_id'] for p in config['pilot_papers']}
    run_records=read_run_log(root,context['run_log_path'])
    first=first_generation_time(run_records,pilot_ids,allow_empty=True).isoformat()
    if utc(first)>datetime.now(timezone.utc):raise ValueError('First-call timestamp cannot be in the future')
    for name in required:
        item=artifacts[name];p=(root/item['path']).resolve()
        if not p.is_relative_to(root):raise ValueError('Locked artifact outside independent workspace')
        raw=p.read_bytes();loaded[name]=(raw,item['sha256']);locked_json(raw,item['sha256'])
        from v2_validation import assert_origin
        assert_origin(locked_json(raw,item['sha256']))
        if config['activation_artifacts'][name]!=item['sha256']:raise ValueError('Config artifact hash does not match activation')
        if utc(item['locked_at_utc'])>datetime.now(timezone.utc):raise ValueError('Artifact lock timestamp cannot be in the future')
        if not utc(item['locked_at_utc'])<utc(first):raise ValueError('Artifact frozen after first generation')
    for name in ['annotator_roster','fact_coverage_ledger','human_approval_registry']:
        value=locked_json(*loaded[name]);validate(name,value)
    for name in ['CONVERGENCE_SPEC.md','AGENTS.md','config/pilot_config.json']:
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=activation['design_hashes'][name]:
            raise ValueError('Activation design/config lock mismatch')
    roster=approved_roster(*loaded['annotator_roster'])
    approval=locked_json(*loaded['researcher_approval']);researcher=roster.get(approval['researcher_id'])
    if approval.get('approved') is not True or not researcher or 'researcher_activation' not in researcher['roles']:
        raise ValueError('Missing actual researcher activation authority')
    if approval.get('budget_currency')!=config['budget']['currency'] or approval.get('budget_cap')!=config['budget']['hard_cap']:
        raise ValueError('Budget differs from researcher approval')
    g0=locked_json(*loaded['g0_major_ledger'])
    # The ledger is the entire frozen major-defect population, not a model-selected subset.
    _locked_coverage_from_bytes(g0['item_ids'],*loaded['fact_coverage_ledger'],
        artifacts['fact_coverage_ledger']['locked_at_utc'],first,*loaded['annotator_roster'])
    registry=locked_json(*loaded['human_approval_registry'])
    for decision in registry['decisions'].values():
        if decision['adjudicator_id'] not in roster:raise ValueError('Unregistered human decision')
    for name,value in [('activation',activation)]+[(name,locked_json(*loaded[name])) for name in required]:
        if value.get('fixture') is not False or value.get('illustrative') is not False or value.get('data_origin')!='real':raise ValueError('Fixture/illustrative data cannot authorize actual execution: '+name)
    return {'activation_verified':True,'locked_artifacts':required,'first_generation_at_utc':first}

def guarded_preflight(config,phase,metadata_result,context=None):
    errors=list(metadata_result['missing_or_invalid']);activation=None
    try:activation=verify_activation(config,phase,context)
    except Exception as e:errors.append(type(e).__name__+': '+str(e).splitlines()[0])
    return {'ready':not errors,'metadata_ready':metadata_result['ready'],'missing_or_invalid':errors,
            'activation':activation,'network_calls_made':False}
