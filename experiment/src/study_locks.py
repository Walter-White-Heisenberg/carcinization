"""Read-only provenance anchored to a coordinator-approved activation digest.

The two bootstrap digests below come from the researcher/coordinator, never from
a model response. Hashes establish binding, not the authenticity of human evidence.
"""
from dataclasses import dataclass
from datetime import datetime,timezone
from pathlib import Path
import hashlib,json

@dataclass(frozen=True)
class ActivationRef:
    workspace_root:str
    manifest_path:str
    approved_sha256:str

@dataclass(frozen=True)
class AnalysisRef:
    manifest_path:str
    approved_sha256:str

def digest(data):return hashlib.sha256(data).hexdigest()
def utc(text):
    value=datetime.fromisoformat(text.replace('Z','+00:00'))
    if value.tzinfo is None:raise ValueError('Timestamp needs an explicit timezone')
    return value.astimezone(timezone.utc)

def _path(root,path):
    p=(Path(root)/path).resolve()
    if not p.is_relative_to(Path(root).resolve()):raise ValueError('Locked path escapes workspace')
    return p

def _json_bytes(data):
    from v2_validation import strict_json_loads
    return strict_json_loads(data.decode('utf-8-sig'))

def _read(root,path,sha):
    data=_path(root,path).read_bytes()
    if digest(data)!=sha:raise ValueError('Locked artifact SHA mismatch: '+str(path))
    return _json_bytes(data)

def _validate(root,name,value):
    from jsonschema import Draft202012Validator,FormatChecker
    schema=json.loads((Path(root)/'schemas'/(name+'.schema.json')).read_text(encoding='utf-8'))
    Draft202012Validator(schema,format_checker=FormatChecker()).validate(value)

def load_activation(ref):
    from v2_validation import assert_origin
    if not isinstance(ref,ActivationRef):raise ValueError('Coordinator-approved ActivationRef required')
    data=_read(ref.workspace_root,ref.manifest_path,ref.approved_sha256)
    _validate(ref.workspace_root,'activation_manifest',data);assert_origin(data)
    for name,expected in data['design_hashes'].items():
        if digest(_path(ref.workspace_root,name).read_bytes())!=expected:
            raise ValueError('Frozen design/configuration file changed: '+name)
    return data

def artifact_from_activation(ref,name):
    from v2_validation import assert_origin
    manifest=load_activation(ref);entry=manifest['artifacts'][name]
    value=_read(ref.workspace_root,entry['path'],entry['sha256']);assert_origin(value)
    if value['fixture']!=manifest['fixture']:raise ValueError('Fixture and real study artifacts cannot mix')
    return value,entry

def locked_inputs(ref,paper_id):
    licenses,_=artifact_from_activation(ref,'paper_licenses');facts,_=artifact_from_activation(ref,'public_fact_package')
    def select(rows):
        selected=[r for r in rows if r['paper_id']==paper_id]
        if len(selected)!=1:raise ValueError('Paper must have exactly one frozen input entry')
        return selected[0]
    return select(licenses['papers']),select(facts['papers'])

def assert_locked_generation_inputs(ref,record,bindings,registry):
    manifest=load_activation(ref)
    config=json.loads((Path(ref.workspace_root)/'config/pilot_config.json').read_text(encoding='utf-8'))
    from sampling_plan import verify_frozen_sampling
    selection=verify_frozen_sampling(ref,config)
    if record['track'] in {'A','B','PERTURBATION_TRACK'} and record['paper_id'] not in selection['pilot_paper_ids']:
        raise ValueError('Generated pilot paper is outside the frozen selection')
    if record['track']=='PERTURBATION_TRACK' and record['paper_id'] not in selection['c_paper_ids']:
        raise ValueError('C paper is outside the preselected three')
    if manifest['fixture']!=record['fixture']:raise ValueError('Fixture activation cannot prepare real study records')
    if record['activation_sha256'] not in {None,ref.approved_sha256}:raise ValueError('Record belongs to another activation')
    for rid in record['parent_record_ids']:
        parent=registry[rid]
        if parent.get('prompt_id') is not None and parent.get('activation_sha256')!=ref.approved_sha256:
            raise ValueError('Generated parent belongs to another activation')
    manuscript,facts=locked_inputs(ref,record['paper_id'])
    fixed_id=manuscript['manuscript_record_id'];fixed_sha=manuscript['manuscript_sha256']
    if record['track'] in {'A','PERTURBATION_TRACK'} or record['prompt_id'] in {'P02','INPUT'}:
        if record['prompt_id']=='P08':
            source=registry[record['input_review_record_id']]
            actual_id=source['input_manuscript_record_id']
        else:actual_id=record['input_manuscript_record_id']
        if actual_id!=fixed_id:raise ValueError('Fixed manuscript differs from activation')
        item=registry[fixed_id]
        if digest(item['text'].encode('utf-8'))!=fixed_sha:raise ValueError('Fixed manuscript content differs from activation')
    needs_facts=record['prompt_id'] in {'P02','P04','P05','P07'}
    if needs_facts:
        fid=facts['fact_record_id'];fsha=facts['fact_sha256']
        if record['input_fact_record_id']!=fid or record['input_fact_sha256']!=fsha or bindings.get('fact_constraints')!=fid:
            raise ValueError('Fact input differs from the pre-generation frozen package')
        if digest(registry[fid]['text'].encode('utf-8'))!=fsha:raise ValueError('Frozen facts were modified')
    elif record['input_fact_record_id'] is not None or record['input_fact_sha256'] is not None:
        raise ValueError('This template does not receive facts')

def first_generation_time(records,pilot_ids,allow_empty=False):
    times=[];ids=set()
    for record in records:
        if record['record_id'] in ids:raise ValueError('Duplicate execution-log record ID')
        ids.add(record['record_id'])
        if record['paper_id'] not in pilot_ids or record['prompt_id']=='INPUT' or record['usage']['generation_call_count']==0:continue
        stamp=record['request_sent_at_utc']
        if stamp is None:raise ValueError('Generated record lacks request_sent_at_utc')
        time=utc(stamp)
        if time>datetime.now(timezone.utc):raise ValueError('Future request timestamp')
        times.append(time)
    if not times:
        if allow_empty:return datetime.now(timezone.utc)
        raise ValueError('Analysis requires at least one recorded pilot request')
    return min(times)

def read_run_log(root,path,expected_sha=None):
    from v2_validation import strict_json_loads,assert_origin
    raw=_path(root,path).read_bytes()
    if expected_sha is not None and digest(raw)!=expected_sha:raise ValueError('Run-log SHA mismatch')
    records=[strict_json_loads(line) for line in raw.decode('utf-8').splitlines() if line.strip()]
    for row in records:
        _validate(root,'run_record',row);assert_origin(row)
        if row['data_origin']=='real' and row['status']=='success' and row['prompt_id']!='INPUT' and row['usage']['generation_call_count']<1:
            raise ValueError('Real successful generation cannot be an unsent zero-call slot')
    from execution_audit import validate_execution_history
    validate_execution_history(records)
    return records

def verify_analysis_lock(activation_ref,analysis_ref,engineering=False):
    from v2_validation import assert_origin
    from activation_contracts import approved_roster
    activation=load_activation(activation_ref);root=activation_ref.workspace_root
    if not isinstance(analysis_ref,AnalysisRef):raise ValueError('Coordinator-approved AnalysisRef required')
    lock=_read(root,analysis_ref.manifest_path,analysis_ref.approved_sha256)
    _validate(root,'analysis_lock',lock);assert_origin(lock)
    if lock['activation_sha256']!=activation_ref.approved_sha256:raise ValueError('Analysis is anchored to another activation')
    entries=activation['artifacts']
    for field,name in [('initial_registry_sha256','human_approval_registry'),('roster_sha256','annotator_roster')]:
        if lock[field]!=entries[name]['sha256']:raise ValueError('Analysis replaced a pre-generation authority artifact')
    config=json.loads((Path(root)/'config/pilot_config.json').read_text(encoding='utf-8'))
    from sampling_plan import verify_frozen_sampling
    verify_frozen_sampling(activation_ref,config)
    pilot_ids={p if isinstance(p,str) else p['paper_id'] for p in config['pilot_papers']}
    measurements=verify_measurement_files(root,lock['measurement_files'],activation['fixture'])
    records=read_run_log(root,lock['run_log']['path'],lock['run_log']['sha256'])
    if any(r['paper_id'] in pilot_ids and r['activation_sha256']!=activation_ref.approved_sha256 for r in records):
        raise ValueError('Run log mixes activation instances')
    if any(r['paper_id'] in pilot_ids and r['fixture']!=activation['fixture'] for r in records):
        raise ValueError('Run log mixes real and fixture observations')
    first=first_generation_time(records,pilot_ids)
    for name,entry in entries.items():
        if not utc(entry['locked_at_utc'])<first:raise ValueError('A pre-generation artifact was locked after the first request: '+name)
    initial,_=artifact_from_activation(activation_ref,'human_approval_registry')
    roster_data,roster_entry=artifact_from_activation(activation_ref,'annotator_roster')
    roster_raw=_path(root,roster_entry['path']).read_bytes();roster=approved_roster(roster_raw,roster_entry['sha256'])
    for item in measurements:
        if item['kind']=='human_annotations':
            rows=_json_bytes(item['bytes']) if item['format']=='json' else [_json_bytes(line) for line in item['bytes'].splitlines() if line.strip()]
            if isinstance(rows,dict):rows=[rows]
            for row in rows:
                person=roster.get(row['annotator_id']);role='structural_annotation' if row['dimension']=='structure' else 'reader' if row['dimension']=='Q5' else 'scientific_annotation'
                if not person or role not in person['roles']:raise ValueError('Measurement annotator is outside the frozen role roster')
    new_entry=lock['new_registry'];new=_read(root,new_entry['path'],new_entry['sha256'])
    _validate(root,'human_approval_registry',new);assert_origin(new)
    if any(new['decisions'].get(k)!=v for k,v in initial['decisions'].items()):raise ValueError('Initial decisions were deleted or edited')
    approved=utc(lock['registry_approved_at_utc']);locked=utc(lock['analysis_locked_at_utc'])
    if not first<approved<locked<=datetime.now(timezone.utc):raise ValueError('Invalid analysis approval/freeze chronology')
    for key,decision in new['decisions'].items():
        person=roster.get(decision['adjudicator_id'])
        if not person or 'adjudication' not in person['roles']:raise ValueError('Unregistered adjudicator')
        if key not in initial['decisions'] and not first<utc(decision['approved_at_utc'])<=approved:
            raise ValueError('New decision approval predates generation or follows registry approval')
        if not decision['approval_evidence_id'].strip():raise ValueError('Missing actual approval evidence reference')
    if any(value['fixture']!=activation['fixture'] for value in [lock,new,roster_data]):raise ValueError('Mixed fixture authority')
    if activation['fixture'] and not engineering:raise ValueError('Fixture cannot support experimental analysis')
    return {'activation':activation,'analysis_lock':lock,'registry':new,'roster':roster,'first_generation_utc':first,
            'run_records':records,'measurement_files':measurements,
            'fixture':activation['fixture'],'evidence_class':'engineering_validation' if activation['fixture'] else 'diagnostic_only'}

def coverage_from_analysis(activation_ref,analysis_ref,engineering=False):
    from activation_contracts import _locked_coverage_from_bytes
    verified=verify_analysis_lock(activation_ref,analysis_ref,engineering)
    coverage,entry=artifact_from_activation(activation_ref,'fact_coverage_ledger')
    g0,_=artifact_from_activation(activation_ref,'g0_major_ledger')
    _,roster_entry=artifact_from_activation(activation_ref,'annotator_roster')
    root=activation_ref.workspace_root
    return _locked_coverage_from_bytes(g0['item_ids'],_path(root,entry['path']).read_bytes(),entry['sha256'],
       entry['locked_at_utc'],verified['first_generation_utc'].isoformat(),
       _path(root,roster_entry['path']).read_bytes(),roster_entry['sha256'])

def adjudication_from_analysis(task_record,activation_ref,analysis_ref,engineering=False):
    from v2_validation import _assert_adjudication_decision
    from v2_validation import assert_origin
    _validate(activation_ref.workspace_root,'task_output_record',task_record);assert_origin(task_record)
    verified=verify_analysis_lock(activation_ref,analysis_ref,engineering);payload=task_record['payload']
    if task_record['fixture']!=verified['fixture']:raise ValueError('Mixed fixture adjudication')
    if task_record['task_schema']!='adjudication':raise ValueError('Expected adjudication task envelope')
    if payload['resolution'] is not None:
        decision=verified['registry']['decisions'].get(payload['human_approval_record_id'])
        if not decision or decision['blind_document_id']!=task_record['blind_document_id'] or decision['rubric_version']!=task_record['rubric_version']:
            raise ValueError('Human decision belongs to another document or rubric')
    _assert_adjudication_decision(payload,verified['registry']['decisions'])


def verify_measurement_files(root,entries,fixture):
    from v2_validation import assert_origin,strict_json_loads
    required={'source_documents','blinding_map','segmentation','human_annotations','role_sequences'}
    if not required<={e['kind'] for e in entries}:raise ValueError('Missing primary measurement provenance files')
    seen=set();result=[]
    for item in entries:
        path=_path(root,item['path'])
        if path in seen:raise ValueError('A measurement file was registered twice')
        seen.add(path);data=path.read_bytes()
        if digest(data)!=item['sha256']:raise ValueError('Frozen measurement file changed: '+item['path'])
        if item['kind']=='human_annotations' and item['schema_name']!='annotation':
            raise ValueError('Human annotations require their formal record schema')
        rows=None
        if item['format']=='json':
            value=strict_json_loads(data.decode('utf-8-sig'));rows=value if isinstance(value,list) else [value]
        elif item['format']=='jsonl':rows=[strict_json_loads(line) for line in data.decode('utf-8-sig').splitlines() if line.strip()]
        if item['schema_name']:
            if rows is None:raise ValueError('Schema-tagged records must be JSON or JSONL')
            if not rows:raise ValueError('A registered measurement record file cannot be empty')
            for row in rows:
                _validate(root,item['schema_name'],row);assert_origin(row)
                if row['fixture']!=fixture:raise ValueError('Mixed real and fixture measurements')
        result.append(dict(item,bytes=data))
    return result

def load_analysis_measurements(activation_ref,analysis_ref,engineering=False):
    """Only approved file bytes enter a scientific recomputation; no free arrays here.
    Completeness, blind-map joins and scientific adjudication still require the
    checks in the normative human protocol. Hash agreement alone proves none of those.
    """
    return verify_analysis_lock(activation_ref,analysis_ref,engineering)['measurement_files']
