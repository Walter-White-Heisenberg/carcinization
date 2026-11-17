"""Default-study source bindings and exact-template public rendering. No APIs."""
from __future__ import annotations
import hashlib
import re

GENERATION_SLOTS={
 'P01':{'manuscript':'manuscript','previous_review':'review_or_none'},
 'P02':{'structure_mode':'structure_mode','manuscript':'manuscript','fact_constraints':'public_facts'},
 'P04':{'manuscript':'manuscript','review':'review','fact_constraints':'public_facts'},
 'P05':{'manuscript':'manuscript','fact_constraints':'public_facts'},
 'P06':{'manuscript':'manuscript'},
 'P07':{'manuscript':'manuscript','description':'description','fact_constraints':'public_facts'},
 'P08':{'target_organization':'registered_control','review':'review'}}
CONDITIONS={'A':{'A_LOOP','A_INDEPENDENT'},
 'B':{'B_INITIAL','B_REVIEW','B_DIRECT','B_DIRECT2','B_DESCRIPTIVE'},
 'PERTURBATION_TRACK':{'C_KEEP','C_PERTURB'},'development':{'DEVELOPMENT'}}


def assert_source_bindings(record,registry):
    """Input state is distinct from review history and an analysis-only parent."""
    track=record['track'];condition=record['condition'];stage=record['stage'];t=record['round']
    if condition not in CONDITIONS.get(track,set()):raise ValueError('Unregistered track/condition')
    if type(t) is not int:raise ValueError('Round must be an integer index')
    if track in {'A','B','PERTURBATION_TRACK'} and (type(record['trajectory_id']) is not int or not 1<=record['trajectory_id']<=3):
        raise ValueError('The registered pilot has exactly three trajectory indices')
    if track=='A' and not 0<=t<=10:raise ValueError('A stops at R10')
    if track=='B' and stage in {'review','description'} and not 0<=t<=9:raise ValueError('B has only U0..U9 or D0..D9')
    if track=='B' and stage=='manuscript' and condition!='B_INITIAL' and not 1<=t<=10:raise ValueError('B writers emit Q1..Q10')
    manuscript_id=record['input_manuscript_record_id'];review_id=record['input_review_record_id']
    description_id=record['input_description_record_id'];kind=record['document_kind'];prompt=record['prompt_id']
    if condition!='B_DIRECT2' and record['substep'] is not None:raise ValueError('Substep is only registered for DIRECT2')
    for rid in [manuscript_id,review_id,description_id]:
        if rid is not None and (rid not in registry or rid not in record['parent_record_ids']):
            raise ValueError('Input must bind an existing explicit parent')
    for rid in [manuscript_id,review_id,description_id]:
        if rid is not None and registry[rid].get('prompt_id') is not None and registry[rid].get('status')!='success':
            raise ValueError('A failed or unresolved generated artifact cannot be consumed')
    if prompt=='INPUT':
        if track!='B' or condition!='B_INITIAL' or t!=0:raise ValueError('INPUT is only the original B Q0')
        if record['substep'] is not None:raise ValueError('Initial input has no DIRECT2 substep')
        if record['lineage_root_record_id']!=record['record_id']:
            raise ValueError('Initial artifact must be its own lineage root')
        if not manuscript_id or record['input_state_record_id']!=manuscript_id:raise ValueError('Original Q0 must bind its fixed manuscript source')
        source=registry[manuscript_id]
        if source.get('artifact_kind')!='fixed_manuscript_source' or source.get('paper_id')!=record['paper_id']:
            raise ValueError('INPUT source is not the registered original manuscript')
        if record['raw_text']!=source.get('text',source.get('raw_text')):raise ValueError('Imported Q0 must exactly preserve the original text')
        if review_id is not None or description_id is not None:raise ValueError('Original Q0 has no review or description input')
        expected_kind='manuscript' if track=='B' else 'review'
        if kind!=expected_kind or stage not in {expected_kind,'intervention'}:raise ValueError('Invalid imported artifact kind')
        return
    if prompt not in GENERATION_SLOTS:raise ValueError('Unregistered generation prompt')
    expected_state=review_id if prompt=='P08' else manuscript_id
    if record['input_state_record_id']!=expected_state or expected_state is None:
        raise ValueError('Primary state input is not bound')
    needed=GENERATION_SLOTS[prompt]
    for slot,rid,wanted in [('manuscript',manuscript_id,'manuscript'),('review',review_id,'review'),
                            ('description',description_id,'description')]:
        required=slot in needed or slot=='review' and prompt=='P01' and record['history_mode']=='previous_review_only'
        if required and rid is None:raise ValueError('Missing bound input '+slot)
        if not required and rid is not None:raise ValueError('Extraneous bound input '+slot)
        if rid is None:continue
        parent=registry[rid]
        if parent.get('paper_id')!=record['paper_id'] or parent.get('document_kind',parent.get('stage'))!=wanted:
            raise ValueError('Wrong input paper or document kind')
        shared_fixed=(wanted=='manuscript' and (track in {'A','PERTURBATION_TRACK'} or prompt=='P02') and parent.get('artifact_kind')=='fixed_manuscript_source')
        if track!='A' and not shared_fixed and parent.get('trajectory_id')!=record['trajectory_id']:
            raise ValueError('Cross-trajectory input state')
    if track=='A':
        if prompt!='P01' or kind!='review' or stage!='review':raise ValueError('Invalid A record stage/prompt')
        source=registry[manuscript_id]
        if source.get('artifact_kind')!='fixed_manuscript_source':raise ValueError('A must use its fixed source manuscript')
        if t==0 and (condition!='A_LOOP' or record['lineage_root_record_id']!=record['record_id']):
            raise ValueError('R0 is one shared A_LOOP seed, not a separately generated control baseline')
        if t>0:
            root=registry.get(record['lineage_root_record_id'])
            if not root or root.get('track')!='A' or root.get('condition')!='A_LOOP' or root.get('round')!=0:
                raise ValueError('A trajectory must point to its shared A R0')
            if root.get('trajectory_id')!=record['trajectory_id'] or root.get('input_manuscript_record_id')!=manuscript_id:
                raise ValueError('A seed trajectory or fixed manuscript changed')
        if condition=='A_INDEPENDENT' and review_id is not None:raise ValueError('Independent review cannot receive review context')
        if review_id is not None:
            parent=registry[review_id]
            if parent.get('track')!='A' or parent.get('condition')!='A_LOOP' or parent.get('input_manuscript_record_id')!=manuscript_id:
                raise ValueError('A review context must come from its own fixed-paper A_LOOP, including t1')
    elif track=='B':
        if condition=='B_INITIAL':
            if prompt!='P02' or t!=0:raise ValueError('Invalid controlled initial manuscript')
            return
        root=registry.get(record['lineage_root_record_id'])
        if not root or root.get('condition')!='B_INITIAL' or root.get('round')!=0 or root.get('document_kind')!='manuscript':
            raise ValueError('B trajectory must bind its shared admitted Q0')
        if root.get('trajectory_id')!=record['trajectory_id']:raise ValueError('B root belongs to another trajectory')
        allowed={'B_REVIEW':{'review':'P01','manuscript':'P04'},'B_DIRECT':{'manuscript':'P05'},'B_DIRECT2':{'manuscript':'P05'},
                 'B_DESCRIPTIVE':{'description':'P06','manuscript':'P07'}}
        if allowed[condition].get(stage)!=prompt or kind!=stage:raise ValueError('Invalid B stage/prompt')
        source=registry[manuscript_id];source_t=t if stage in {'review','description'} else t-1
        if condition=='B_DIRECT2':
            step=record['substep']
            if step not in {1,2}:raise ValueError('DIRECT2 needs substep1 or2')
            source_t=t-1 if step==1 else t
            expected_source_step=2 if step==1 and source_t>0 else 1 if step==2 else None
            if source.get('substep')!=expected_source_step:raise ValueError('Wrong DIRECT2 input substep')
        if source.get('round')!=source_t or source.get('condition') not in {condition,'B_INITIAL'}:
            raise ValueError('Wrong manuscript version/condition')
        if source_t==0 and manuscript_id!=record['lineage_root_record_id']:
            raise ValueError('A different admitted Q0 cannot replace the paired baseline')
        if source_t>0 and source.get('lineage_root_record_id')!=record['lineage_root_record_id']:
            raise ValueError('Input manuscript belongs to a different starting trajectory')
        if source.get('condition')=='B_INITIAL' and source_t!=0:raise ValueError('Initial source only at t0')
        if stage=='manuscript' and t<1:raise ValueError('Writer output starts at Q1')
        if condition=='B_REVIEW' and stage=='manuscript':
            review=registry[review_id]
            if review.get('condition')!='B_REVIEW' or review.get('round')!=t-1:
                raise ValueError('Q(t) requires U(t-1) from its own workflow')
            if review.get('input_manuscript_record_id')!=manuscript_id:
                raise ValueError('Review and writer must bind the identical manuscript version')
        if condition=='B_DESCRIPTIVE' and stage=='manuscript':
            desc=registry[description_id]
            if desc.get('condition')!=condition or desc.get('round')!=t-1 or desc.get('input_manuscript_record_id')!=manuscript_id:
                raise ValueError('Description and writer must bind the identical manuscript version')
    elif track=='PERTURBATION_TRACK':
        if kind!='review' or record['intervention_type'] not in {'KEEP','PERTURB'}:raise ValueError('Invalid C review branch')
        if record['intervention_type']!=('KEEP' if condition=='C_KEEP' else 'PERTURB'):raise ValueError('C branch and intervention label disagree')
        if prompt=='P08':
            if t!=10 or condition!='C_PERTURB':raise ValueError('P08 only constructs the perturbation baseline')
        elif prompt!='P01' or not 11<=t<=13:raise ValueError('C continuation has exactly three updates')
        parent=registry[review_id]
        if prompt=='P08' and (parent.get('round')!=10 or parent.get('condition')!='A_LOOP'):
            raise ValueError('P08 state must be the registered A_LOOP endpoint')
        keep_start=condition=='C_KEEP' and t==11 and parent.get('condition')=='A_LOOP' and parent.get('round')==10
        if prompt=='P01' and not keep_start and (parent.get('intervention_id')!=record['intervention_id'] or parent.get('condition')!=condition):
            raise ValueError('Cross-branch perturbation history')
        if prompt=='P01':
            fixed_source=parent
            if parent.get('prompt_id')=='P08':
                fixed_source=registry.get(parent.get('input_review_record_id'),{})
            if fixed_source.get('input_manuscript_record_id')!=manuscript_id:
                raise ValueError('C continuation changed the fixed paper used at the endpoint')


def _render_catalog_slots(prompt_id,bindings,approved_artifacts,record):
    """Resolve actual P01/P02/P04-P08 slots from a coordinator-owned registry.

    The registry is frozen outside model outputs. Each entry includes kind,
    approved_for_generation=True, text and SHA. Private ledgers never enter it.
    This function accepts IDs, not arbitrary caller-supplied manuscript strings.
    """
    from spec_data import PROMPTS
    if not isinstance(prompt_id,str):raise ValueError('Select a frozen catalog prompt ID')
    prompt=next((p for p in PROMPTS if p['id']==prompt_id),None)
    if prompt is None:raise ValueError('Unknown prompt ID')
    pid=prompt_id
    if not isinstance(record,dict) or record.get('prompt_id')!=pid:raise ValueError('A matching planned run record is required')
    assert_source_bindings(record,approved_artifacts)
    if pid not in GENERATION_SLOTS:raise ValueError('Not a registered generation template')
    slots=GENERATION_SLOTS[pid]
    if set(bindings)!=set(slots):raise ValueError('Exact actual template slots required')
    if set(re.findall(r'\{\{([a-z_]+)\}\}',prompt['text']))!=set(slots):raise ValueError('Template/contract drift')
    values={}
    for slot,kind in slots.items():
        rid=bindings[slot]
        if slot=='structure_mode':
            if rid not in {'method_led','evidence_led'}:raise ValueError('Unregistered structure mode')
            values[slot]=rid;continue
        if slot=='previous_review' and rid=='NONE':values[slot]='NONE';continue
        artifact=approved_artifacts.get(rid)
        if not artifact or artifact.get('approved_for_generation') is not True or artifact.get('private') is not False:
            raise ValueError('Unapproved or private generation source')
        expected='review' if kind=='review_or_none' else kind
        if artifact.get('kind')!=expected:raise ValueError('Wrong approved artifact role')
        text=artifact.get('text')
        if not isinstance(text,str) or hashlib.sha256(text.encode('utf-8')).hexdigest()!=artifact.get('sha256'):
            raise ValueError('Approved source content changed')
        if record is not None:
            if artifact.get('paper_id') not in {record['paper_id'],None} or (expected!='registered_control' and artifact.get('paper_id')!=record['paper_id']):
                raise ValueError('Cross-paper generation binding')
            expected_id={'manuscript':record['input_manuscript_record_id'],'review':record['input_review_record_id'],
                         'previous_review':record['input_review_record_id'],'description':record['input_description_record_id']}.get(slot,rid)
            if rid!=expected_id:raise ValueError('Rendered input differs from recorded state/history binding')
        values[slot]=text
    if record is not None and pid=='P01':
        if (bindings['previous_review']=='NONE')!=(record['input_review_record_id'] is None):
            raise ValueError('NONE and review provenance disagree')
    text=re.sub(r'\{\{([a-z_]+)\}\}',lambda m:values[m.group(1)],prompt['text'])
    input_sha=hashlib.sha256(text.encode('utf-8')).hexdigest()
    if record.get('input_sha256') is not None and record['input_sha256']!=input_sha:
        raise ValueError('Run input SHA differs from the actual rendered request')
    # Persist this returned record with the exact returned text before calling an
    # external model. The old record with an unset SHA is not an execution record.
    return {'text':text,'record':dict(record,input_sha256=input_sha),
            'input_sha256':input_sha,'bindings':dict(bindings)}


def render_generation_prompt(prompt_id,bindings,approved_artifacts,record,activation_ref,execution_log_path):
    from v2_validation import assert_generation_lineage
    from study_locks import assert_locked_generation_inputs
    # The exact same condition-derived context checks run before sending and
    # after receiving. A record cannot declare itself history-free to bypass them.
    assert_generation_lineage(record,approved_artifacts)
    assert_locked_generation_inputs(activation_ref,record,bindings,approved_artifacts)
    result=_render_catalog_slots(prompt_id,bindings,approved_artifacts,record)
    result['record']['activation_sha256']=activation_ref.approved_sha256
    from execution_audit import assert_next_attempt
    from study_locks import read_run_log
    prior=read_run_log(activation_ref.workspace_root,execution_log_path)
    if any(r['activation_sha256']!=activation_ref.approved_sha256 or r['fixture']!=record['fixture'] for r in prior):
        raise ValueError('Execution history belongs to another activation or origin')
    assert_next_attempt(result['record'],prior)
    return result


def import_original_manuscript(record,approved_artifacts,activation_ref):
    from v2_validation import assert_generation_lineage
    from study_locks import assert_locked_generation_inputs,digest
    if record['prompt_id']!='INPUT':raise ValueError('Only an original B baseline can be imported')
    assert_generation_lineage(record,approved_artifacts)
    assert_locked_generation_inputs(activation_ref,record,{},approved_artifacts)
    text=approved_artifacts[record['input_manuscript_record_id']]['text']
    return dict(record,input_sha256=digest(text.encode()),output_sha256=digest(text.encode()),request_sent_at_utc=None,
                activation_sha256=activation_ref.approved_sha256)
