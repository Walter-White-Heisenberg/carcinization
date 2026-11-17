"""Audit complete coordinator-owned request logs. No network or API execution.
This detects violations present in the log; it cannot detect deliberately hidden calls.
"""
from collections import defaultdict

SLOT_FIELDS=('paper_id','track','condition','trajectory_id','round','stage','substep','intervention_id')
RETRY_BINDINGS=('prompt_id','input_sha256','model_snapshot','input_state_record_id',
 'input_manuscript_record_id','input_review_record_id','input_description_record_id',
 'input_fact_record_id','input_fact_sha256','history_mode','history_record_ids')

def slot_key(row):return tuple(row[k] for k in SLOT_FIELDS)

def _assert_group(group):
    first=group[0]
    if [r['attempt'] for r in group]!=list(range(len(group))):
        raise ValueError('A slot must start at attempt 0 and preserve every attempt once')
    limit=1 if first['prompt_id'] in {'INPUT','P08'} else 3
    if len(group)>limit:raise ValueError('Retry cap exceeded; P08 is generated once only')
    for old,new in zip(group,group[1:]):
        allowed={'transient_api_error'} | ({'initial_equivalence_failure'} if first['prompt_id']=='P02' else set())
        if old['status'] not in allowed:raise ValueError('Cannot rerun a successful or nonretryable slot')
        if any(old[k]!=new[k] for k in RETRY_BINDINGS):raise ValueError('Retry changed its frozen request')
        root_slot=old['round']==0 and (old['track']=='A' or old['condition']=='B_INITIAL')
        if not root_slot and old['lineage_root_record_id']!=new['lineage_root_record_id']:
            raise ValueError('Retry changed its trajectory root')
        if old['request_sent_at_utc'] and new['request_sent_at_utc']:
            from study_locks import utc
            if utc(new['request_sent_at_utc'])<=utc(old['request_sent_at_utc']):raise ValueError('Retry chronology is reversed')

def validate_execution_history(records):
    groups=defaultdict(list);ids=set()
    for r in records:
        if r['record_id'] in ids:raise ValueError('Duplicate execution record ID')
        ids.add(r['record_id'])
        if r['status']=='initial_equivalence_failure' and r['prompt_id']!='P02':
            raise ValueError('Only controlled Q0 construction has equivalence-admission failure')
        if r['prompt_id']=='INPUT' and (r['attempt']!=0 or r['usage']['generation_call_count']!=0):
            raise ValueError('Original manuscript import is not a model call')
        if r['usage']['generation_call_count']>1:raise ValueError('Each row represents one attempt, never hidden internal retries')
        groups[slot_key(r)].append(r)
    for group in groups.values():_assert_group(group)
    # Once a lower round has terminally failed, this branch cannot silently restart.
    for key,group in groups.items():
        last=group[-1]
        if last['status']=='success':continue
        if any(other[:4]==key[:4] and other[4]>key[4] for other in groups):
            raise ValueError('A failed trajectory cannot continue at a later round')
    return groups

def assert_next_attempt(planned,records):
    groups=validate_execution_history(records)
    if any(r['record_id']==planned['record_id'] for r in records):raise ValueError('Request record already exists')
    group=groups.get(slot_key(planned),[])
    # Pre-send record status is a placeholder; all earlier entries are completed observations.
    _assert_group(group+[planned])
    for key,prior in groups.items():
        if key[:4]==slot_key(planned)[:4] and key[4]<planned['round'] and prior[-1]['status']!='success':
            raise ValueError('A failed trajectory cannot continue')
