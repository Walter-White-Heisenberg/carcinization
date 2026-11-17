"""Engineering-only fixture factory. Never authorizes or invokes a model."""
from pathlib import Path
import copy,hashlib,json,shutil
from study_locks import ActivationRef,AnalysisRef

def raw(value):return json.dumps(value,ensure_ascii=False,sort_keys=True).encode('utf-8')
def sha(data):return hashlib.sha256(data).hexdigest()

def make_fixture(root,source_root,config,example):
    root=Path(root);root.mkdir(exist_ok=True);(root/'schemas').mkdir();(root/'config').mkdir()
    for p in (source_root/'schemas').glob('*.json'):shutil.copyfile(p,root/'schemas'/p.name)
    for name in ['CONVERGENCE_SPEC.md','AGENTS.md']:shutil.copyfile(source_root/name,root/name)
    keys=['schema_version','namespace','study_id','record_id','evidence_class','label_source','rubric_version',
          'fixture','illustrative','data_origin','parent_record_ids']
    meta={k:example[k] for k in keys}
    def env(name,**payload):return dict(meta,record_id='conv_fixture_'+name,**payload)
    registry={};licenses=[];facts=[]
    for pid in ['D1','D2','P1','P2','P3','P4','P5','P6']:
        mid='conv_'+pid+'_source';fid='conv_'+pid+'_facts';mt='Fixture fixed manuscript '+pid;ft='Fixture fixed facts '+pid
        registry[mid]={'record_id':mid,'paper_id':pid,'document_kind':'manuscript','artifact_kind':'fixed_manuscript_source',
          'kind':'manuscript','text':mt,'raw_text':mt,'sha256':sha(mt.encode()),'approved_for_generation':True,'private':False}
        registry[fid]={'record_id':fid,'paper_id':pid,'kind':'public_facts','text':ft,'sha256':sha(ft.encode()),'approved_for_generation':True,'private':False}
        licenses.append({'paper_id':pid,'manuscript_record_id':mid,'manuscript_sha256':sha(mt.encode()),'license_evidence_id':'fixture_not_real_permission'})
        facts.append({'paper_id':pid,'fact_record_id':fid,'fact_sha256':sha(ft.encode())})
    control='Reorder existing topics'
    registry['conv_control']={'kind':'registered_control','paper_id':None,'text':control,'sha256':sha(control.encode()),'approved_for_generation':True,'private':False}
    people=[{'person_id':who,'kind':'human','roles':['scientific_annotation','structural_annotation','adjudication','researcher_activation'],
             'approval_evidence_id':'fixture_not_real_human_authority'} for who in ['h1','h2']]
    old={'unit_id':'old_unit','blind_document_id':'blind_old','rubric_version':'fixture_rubric','resolution':'S','adjudicator_id':'h1',
         'approved_at_utc':'2026-01-01T00:00:00Z','approval_evidence_id':'fixture_old_approval'}
    from activation_contracts import GENERATION_ARTIFACTS,EVALUATION_ARTIFACTS
    payloads={name:env(name,artifact_kind=name) for name in GENERATION_ARTIFACTS+EVALUATION_ARTIFACTS}
    payloads.update({'paper_licenses':env('paper_licenses',papers=licenses),
       'public_fact_package':env('public_fact_package',papers=facts),
       'annotator_roster':env('annotator_roster',people=people),
       'human_approval_registry':env('human_approval_registry',decisions={'conv_old_approval':old}),
       'g0_major_ledger':env('g0_major_ledger',item_ids=['g1']),
       'fact_coverage_ledger':env('fact_coverage_ledger',rows=[{'item_id':'g1','annotator_ids':['h1','h2'],
            'labels':['uncovered','uncovered'],'frozen_before_generation':True}]),
       'researcher_approval':env('researcher_approval',researcher_id='h1',approved=True,budget_currency='USD',budget_cap=1)})
    cfg=copy.deepcopy(config)
    for dotted in cfg['runtime_required_before_generation']+cfg['runtime_required_before_evaluation']:
        p=cfg;parts=dotted.split('.')
        for part in parts[:-1]:p=p[part]
        p[parts[-1]]='fixture_only'
    cfg['development_papers']=['D1','D2'];cfg['pilot_papers']=['P1','P2','P3','P4','P5','P6']
    cfg['generation']['context_limit']=100000;cfg['budget'].update({'currency':'USD','hard_cap':1})
    cfg['execution_enabled']=True;cfg['api']['credential_env_var']='CONV_VALIDATION_DUMMY_TOKEN'
    from sampling_plan import derive_sampling_plan
    payloads['preregistration_lock']['sampling_plan']=derive_sampling_plan(cfg)
    activation=env('activation',artifacts={},design_hashes={})
    for name,payload in payloads.items():
        data=raw(payload);(root/(name+'.json')).write_bytes(data)
        activation['artifacts'][name]={'path':name+'.json','sha256':sha(data),'locked_at_utc':'2026-01-01T12:00:00Z'}
        cfg['activation_artifacts'][name]=sha(data)
    (root/'config/pilot_config.json').write_bytes(raw(cfg))
    activation['design_hashes']={name:sha((root/name).read_bytes()) for name in ['CONVERGENCE_SPEC.md','AGENTS.md','config/pilot_config.json']}
    activation_raw=raw(activation);(root/'activation.json').write_bytes(activation_raw)
    (root/'run.jsonl').write_bytes(b'')
    ref=ActivationRef(str(root),str(root/'activation.json'),sha(activation_raw))
    return {'root':root,'env':env,'registry':registry,'config':cfg,'activation':activation,'activation_ref':ref,
            'context':{'workspace_root':str(root),'activation_path':str(root/'activation.json'),
             'approved_activation_sha256':sha(activation_raw),'run_log_path':str(root/'run.jsonl')},'old_decision':old}

def make_analysis_fixture(study,run_records):
    root=study['root'];env=study['env'];ref=study['activation_ref']
    log=b''.join(raw(r)+b'\n' for r in run_records);(root/'run.jsonl').write_bytes(log)
    added={'unit_id':'new_unit','blind_document_id':'blind_new','rubric_version':'fixture_rubric','resolution':'N',
           'adjudicator_id':'h2','approved_at_utc':'2026-01-03T00:00:00Z','approval_evidence_id':'fixture_new_approval'}
    new=env('new_registry',decisions={'conv_old_approval':study['old_decision'],'conv_new_approval':added})
    new_raw=raw(new);(root/'new_registry.json').write_bytes(new_raw)
    measurements=[]
    annotation=env('measurement',annotation_id='fixture_annotation',blind_document_id='blind_new',unit_id='fixture_unit',
        dimension='structure',label='O',evidence_ids=[],reason='engineering fixture only',annotator_id='h1')
    for kind in ['source_documents','blinding_map','segmentation','human_annotations','role_sequences']:
        value=[annotation] if kind=='human_annotations' else {'fixture':True,'kind':kind,'meaning':'engineering placeholder, not a completed human endpoint'}
        data=raw(value);name=kind+'.json';(root/name).write_bytes(data)
        measurements.append({'kind':kind,'path':name,'sha256':sha(data),'format':'json','schema_name':'annotation' if kind=='human_annotations' else None})
    lock=env('analysis',measurement_files=measurements,activation_sha256=ref.approved_sha256,
       initial_registry_sha256=study['activation']['artifacts']['human_approval_registry']['sha256'],
       roster_sha256=study['activation']['artifacts']['annotator_roster']['sha256'],
       run_log={'path':'run.jsonl','sha256':sha(log)},new_registry={'path':'new_registry.json','sha256':sha(new_raw)},
       registry_approved_at_utc='2026-01-03T12:00:00Z',analysis_locked_at_utc='2026-01-04T00:00:00Z')
    lock_raw=raw(lock);(root/'analysis.json').write_bytes(lock_raw)
    return AnalysisRef(str(root/'analysis.json'),sha(lock_raw)),new,lock
