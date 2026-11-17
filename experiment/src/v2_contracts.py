"""CONVERGENCE-only record and task contracts. No STOPPING adapter or API calls."""
from __future__ import annotations
import copy

EVIDENCE_CLASSES=['engineering_validation','synthetic_identifiability','unapproved_candidate_discovery',
                  'pilot_llm_judge_labeled','pilot_llm_judge_labeled_batch2','diagnostic_only']
CHANGE_TYPES=['numeric_error','scope_expansion','necessary_information_deletion','verified_finding_deletion',
              'meaning_preserving_paraphrase','content_preserving_reorder','style_edit','unchanged','negation_error']
STR={'type':'string'}
ID={'type':'string','minLength':1}
NS={'type':['string','null']}
NB={'type':['boolean','null']}
INT={'type':'integer','minimum':0}
NINT={'type':['integer','null'],'minimum':0}
NNUM={'type':['number','null'],'minimum':0}
STRINGS={'type':'array','items':ID}

def obj(properties,required=None):
    return {'type':'object','properties':properties,'required':list(properties) if required is None else required,
            'additionalProperties':False}
def arr(item):return {'type':'array','items':item}
def enum(*values):return {'enum':list(values)}

def envelope(schema):
    schema.setdefault('properties',{}).update({'schema_version':{'const':'2.3'},'namespace':{'const':'CONVERGENCE'},
        'study_id':{'const':'conv_review_trajectory'},'evidence_class':enum(*EVIDENCE_CLASSES),
        'record_id':{'type':'string','pattern':'^conv_[A-Za-z0-9_-]+$'},'label_source':ID,'rubric_version':ID,
        'fixture':{'type':'boolean'},'illustrative':{'type':'boolean'},'data_origin':enum('real','illustrative','fixture','synthetic'),'parent_record_ids':STRINGS})
    schema['required']=list(dict.fromkeys(schema.get('required',[])+[
        'schema_version','namespace','study_id','record_id','evidence_class','label_source','rubric_version','fixture','illustrative','data_origin','parent_record_ids']))
    schema['additionalProperties']=False
    return schema

def span_schema():
    return {'type':['object','null'],'properties':{'document_id':ID,'start':INT,'end':INT,'quote':STR},
            'required':['document_id','start','end','quote'],'additionalProperties':False}

def usage_schema():
    return obj({'input_tokens':NINT,'output_tokens':NINT,'reasoning_tokens':NINT,'cache_read_tokens':NINT,
                'cache_write_tokens':NINT,'cost_amount':NNUM,'currency':NS,'elapsed_seconds':NNUM,
                'critique_count':NINT,'cumulative_critique_count':NINT,
                'critique_count_source':enum('P11_human_validated','not_applicable','unknown'),
                'critique_count_record_id':NS,
                'generation_call_count':INT,'cumulative_generation_call_count':INT,'unknown_reason':NS})

def apply_catalogs(config,prompts,schemas,metrics,references):
    from metric_contracts import COMPONENTS
    from generation_contracts import CONDITIONS
    from activation_contracts import GENERATION_ARTIFACTS,EVALUATION_ARTIFACTS
    config.update({'schema_version':'2.3','study':'conv_review_trajectory','namespace':'CONVERGENCE',
                   'status':'independent_design_candidate_not_executed','execution_enabled':False,
                   'quality_aggregation':'none','record_schema_version':'2.3',
                   'frozen_stopping_integration':'prohibited','primary_representation':'functional_role_sequence',
                   'primary_endpoint_label_source':'blinded_two_human_reconciled_roles',
                   'primary_structure_human_rounds':[0,10],'primary_structure_human_all_trajectories':True,
                   'primary_structure_human_documents_per_track':54,'quality_evidence_audit_documents_per_track':30,
                   'combined_unique_documents_per_track':66,
                   'primary_estimand':'extra_role_sequence_contraction_under_the_specified_context_protocol',
                   'mechanistic_exhaustion_vs_contamination_identified':False,
                   'human_activation_required':True,'confirmatory_p_values_enabled':False,
                   'per_paper_results_required':True,'bootstrap_interpretation':'exploratory_descriptive_only'})
    config.update({'candidate_revision':'2.3','activation_artifacts':{name:None for name in GENERATION_ARTIFACTS+EVALUATION_ARTIFACTS},
                   'activation_context':None,'api':{'credential_env_var':None}})
    config['evidence_class']='engineering_validation'
    config['runtime_required_before_generation']+=['activation_artifacts.'+name for name in GENERATION_ARTIFACTS]+['api.credential_env_var']
    config['runtime_required_before_evaluation']+=['activation_artifacts.'+name for name in GENERATION_ARTIFACTS+EVALUATION_ARTIFACTS]+['api.credential_env_var']
    for p in prompts:
        if p['id']=='P33':
            p['text']=p['text'].replace('style_edit, unchanged.','style_edit, unchanged, negation_error.')
            p['text']=p['text'].replace('For an error/deletion intervention','For negation_error, reverse exactly one designated negation while preserving other scientific content.\nFor an error/deletion intervention')
            p['text']=p['text'].replace('"changed_spans":[]','"changed_spans":[{"start":0,"end":0,"source_text":"...","variant_text":"..."}]')
            p['text']+='\nchanged_spans offsets are Python Unicode-code-point offsets into source_text; use an empty list for unchanged.\n'
        elif p['id']=='P24':
            p['text']=p['text'].replace('"resolution":null,','"resolution":null,"adjudicator_id":null,"human_approval_record_id":null,')
            p['text']+='\nA model-only proposal must keep resolution, adjudicator_id and human_approval_record_id null. Only the coordinator may attach an actually approved human resolution and its registry identity. Never invent a human approval.\n'
        elif p['id']=='P28':
            p['text']=p['text'].replace('Return a review plus an issue table: id, severity, artifact_location, problem, consequence, proposed_fix, verification_step.',
              'Return strict JSON: {"verdict":"changes_requested|no_unresolved_design_issues|cannot_assess","scope":[],"issues":[{"id":"...","severity":"blocking|major|minor","artifact_location":"...","problem":"...","consequence":"...","proposed_fix":"...","verification_step":"..."}],"limitations":[]}. No extra fields. Deferred or unknown actionable issues are not resolved.')
        elif p['id']=='P03':
            p['text']+='\nFor each changes entry use source_location, candidate_location, change_type (content|organization|uncertain), and description, all strings.\n'
        elif p['id']=='P32':
            p['text']+='''
Use the following exact fields for nonempty arrays:
facts: item_id, statement, verification_status="unverified", evidence_ids, locations, reason.
initial_defect_candidates: item_id, target, diagnosis, severity_candidate (major|minor|blocking|unknown), evidence_ids, locations, reason.
scientific_unit_candidates: acu_id, content, type (method|finding|theory|counterexample|boundary|resource|other), source_quotes, conditions, verification_status="unverified".
necessary_items: item_id, dependent_claim_ids, reproducibility_task, necessity_reason, acceptable_locations, applicability (applicable|not_applicable|uncertain), evidence_ids.
Empty arrays are permitted when no defensible candidates exist; do not fabricate entries to fill a schema.
'''
    for p in prompts:p['text']=p['text'].strip()
    for m in metrics:
        m['registered_components']=COMPONENTS[m['id']]
        if m['id']=='S01':m['inputs']=['全部正文功能序列；主要t0/T为盲化双人核验标签；自动全曲线单列']
        elif m['id']=='J02':
            m['formula']='A固定完整G0_major分母并报未知界限；B并列完整原始账本与条件区间[d/(e+u_n),(d+u_d)/(e+u_d)]，定义见§25.3。'
            m['edge_rules']='G0为空NA；e=0条件区间NA；unknown不直接删分母；B同时报已修复/不适用/unknown数。不可事后扩G0，不替代STOPPING冻结recall。'
            m['implementation']='v2_validation.fixed_major_recall / conditional_major_recall + 人工身份/适用性核验'
        elif m['id']=='V04':
            m['edge_rules']='自动标签分层误差仅辅助；主终点用全部人工端点。108份端点100%块覆盖、6/6论文可计算才报告完整pilot主均值；否则降为缺失界限/探索描述，见§25.2。'
        elif m['id'] in {'Q11','Q12'}:
            m['edge_rules']+=' 作者事实覆盖按生成前双人covered/uncovered/uncertain分层，固定各层分母；审稿增量解释只限uncovered，见§25.4。'
    fixes={'M01':'Position: Stop Automating Peer Review Without Rigorous Evaluation',
           'M21':'SciRepEval: A Multi-Format Benchmark for Scientific Document Representations',
           'M30':'Neighborhood Contrastive Learning for Scientific Document Representations with Citation Embeddings',
           'M31':'sentence-transformers/all-mpnet-base-v2'}
    for r in references:
        if r['id'] in fixes:r['title']=fixes[r['id']]
        r['source_check_date']='2026-11-15'
        if r['id']=='M05':
            r['venue']='TMLR 2023';r['official_code']='https://github.com/vertaix/Vendi-Score'
        # The audit distinguishes code, weights and datasets; no blanket reuse grant.
        r['license_note']='逐条核验状态见SOURCE_AUDIT.json；引用不等于获准再分发代码、数据或模型。外部工具默认未启用。'
    for s in schemas.values():envelope(s)
    run=schemas['run_record'];run['properties'].update({
        'prompt_id':enum('INPUT','P01','P02','P04','P05','P06','P07','P08'),
        'document_kind':enum('manuscript','review','description'),
        'input_state_record_id':NS,'substep':enum(None,1,2),
        'input_fact_record_id':NS,'input_fact_sha256':NS,
        'activation_sha256':NS,
        'request_sent_at_utc':{'type':['string','null'],'format':'date-time'},
        'input_manuscript_record_id':NS,'input_review_record_id':NS,'input_description_record_id':NS,
        'usage':usage_schema(),'history_mode':enum('previous_review_only','none','full_critique_history'),
        'history_record_ids':STRINGS,'prefix_record_ids':STRINGS,'lineage_root_record_id':ID,
        'intervention_type':enum('NONE','KEEP','PERTURB','RESET'),'intervention_id':NS,'reset_from_record_id':NS,
        'terminal_no_issue':{'type':'boolean'}})
    run['properties']['status']['enum'].append('initial_equivalence_failure')
    run['properties']['attempt']['maximum']=2
    run['required']=list(run['properties'])
    conditions=sorted(set().union(*CONDITIONS.values()))
    run['properties']['condition']=enum(*conditions)
    run['properties']['round']['description']='Index of the OUTPUT artifact: R(t), U(t), Q(t). B Q(t) consumes U(t-1) and Q(t-1). C uses absolute indices 10..13.'
    run['allOf']=[{'if':{'properties':{'track':{'const':track}},'required':['track']},
       'then':{'properties':{'condition':enum(*sorted(values)),
         'stage':enum(*({'A':['review'],'B':['review','manuscript','description'],'PERTURBATION_TRACK':['review','intervention'],'development':['review','manuscript','description','intervention']}[track]))}}} for track,values in CONDITIONS.items()]
    for condition,stages in {'B_INITIAL':['manuscript'],'B_REVIEW':['review','manuscript'],'B_DIRECT':['manuscript'],
            'B_DIRECT2':['manuscript'],'B_DESCRIPTIVE':['manuscript','description']}.items():
        run['allOf'].append({'if':{'properties':{'condition':{'const':condition}},'required':['condition']},
                            'then':{'properties':{'stage':enum(*stages)}}})
    run['allOf'].append({'if':{'properties':{'prompt_id':{'not':{'const':'INPUT'}}},'required':['prompt_id']},
      'then':{'properties':{'input_state_record_id':ID,'input_sha256':{'type':'string','pattern':'^[a-f0-9]{64}$'},
                           }}})
    run['allOf'].append({'if':{'properties':{'usage':{'properties':{'generation_call_count':{'minimum':1}}}}},
                        'then':{'properties':{'request_sent_at_utc':{'type':'string','format':'date-time'}}}})
    run['allOf'] += [
      {'if':{'properties':{'track':{'enum':['A','B','PERTURBATION_TRACK']}}},'then':{'properties':{'trajectory_id':{'maximum':3}}}},
      {'if':{'properties':{'track':{'const':'A'}}},'then':{'properties':{'round':{'maximum':10}}}},
      {'if':{'properties':{'track':{'const':'B'},'stage':{'enum':['review','description']}}},'then':{'properties':{'round':{'maximum':9}}}},
      {'if':{'properties':{'track':{'const':'B'},'stage':{'const':'manuscript'},'condition':{'not':{'const':'B_INITIAL'}}}},'then':{'properties':{'round':{'minimum':1,'maximum':10}}}},
      {'if':{'properties':{'condition':{'const':'B_INITIAL'}}},'then':{'properties':{'round':{'const':0},'prompt_id':enum('INPUT','P02')}}},
      {'if':{'properties':{'track':{'const':'PERTURBATION_TRACK'}}},'then':{'properties':{'round':{'minimum':10,'maximum':13}}}},
      {'if':{'properties':{'prompt_id':{'const':'INPUT'}}},'then':{'properties':{'track':{'const':'B'},'condition':{'const':'B_INITIAL'},'request_sent_at_utc':{'type':'null'}}}}]
    schemas['annotation']['properties']['annotator_id']={'type':'string','minLength':1}
    schemas['annotation']['properties']['source_span']=span_schema()
    schemas['annotation']['properties']['sampling_probability']={'type':['number','null'],'exclusiveMinimum':0,'maximum':1}
    metric=schemas['metric_record']
    metric['properties']['metric_id']=enum(*COMPONENTS)
    metric['properties']['condition']=enum(*conditions,None)
    metric['properties']['value']={'type':['number','null']}
    metric['properties']['components']=arr(obj({'name':ID,'value':{'type':['number','null']},'denominator':NNUM,'reason':NS}))
    metric['required'].append('components')
    metric['allOf']=[{'if':{'properties':{'metric_id':{'const':mid}},'required':['metric_id']},
        'then':{'properties':{'components':{'items':{'properties':{'name':enum(*names)}}}}}} for mid,names in COMPONENTS.items()]
    schemas['controlled_case']=envelope(obj({'case_id':ID,'kind':STR,'source_text':STR,'variant_text':STR,
        'change_type':enum(*CHANGE_TYPES),'possibly_affected_dimensions':STRINGS,'rationale':STR,'expert_validated':{'type':'boolean'}}))
    person=obj({'person_id':ID,'kind':enum('human'),'roles':arr(enum('scientific_annotation','structural_annotation','adjudication','researcher_activation','reader')),
                'approval_evidence_id':ID})
    schemas['annotator_roster']=envelope(obj({'people':arr(person)}))
    coverage=obj({'item_id':ID,'annotator_ids':{'type':'array','items':ID,'minItems':2,'maxItems':2,'uniqueItems':True},
        'labels':{'type':'array','items':enum('covered','uncovered','uncertain'),'minItems':2,'maxItems':2},'frozen_before_generation':{'const':True}})
    schemas['fact_coverage_ledger']=envelope(obj({'rows':arr(coverage)}))
    decision=obj({'unit_id':ID,'resolution':ID,'adjudicator_id':ID,'blind_document_id':ID,'rubric_version':ID,
                  'approved_at_utc':{'type':'string','format':'date-time'},'approval_evidence_id':ID})
    schemas['human_approval_registry']=envelope(obj({'decisions':{'type':'object','patternProperties':{'^conv_[A-Za-z0-9_]+$':decision},'additionalProperties':False}}))
    lock_item=obj({'path':ID,'sha256':{'type':'string','pattern':'^[a-f0-9]{64}$'},'locked_at_utc':ID})
    artifacts=obj({name:lock_item for name in GENERATION_ARTIFACTS+EVALUATION_ARTIFACTS},GENERATION_ARTIFACTS)
    schemas['activation_manifest']=envelope(obj({'artifacts':artifacts,'design_hashes':obj({name:ID for name in ['CONVERGENCE_SPEC.md','AGENTS.md','config/pilot_config.json']})}))
    analysis_file=obj({'path':ID,'sha256':{'type':'string','pattern':'^[a-f0-9]{64}$'}})
    schemas['analysis_lock']=envelope(obj({'activation_sha256':ID,'initial_registry_sha256':ID,'roster_sha256':ID,
        'run_log':analysis_file,'new_registry':analysis_file,
        'measurement_files':{'type':'array','minItems':5,'items':obj({'kind':enum('source_documents','blinding_map','segmentation','human_annotations','role_sequences','adjudication_tasks','metric_records','reader_responses','other_evidence'),
            'path':ID,'sha256':{'type':'string','pattern':'^[a-f0-9]{64}$'},'format':enum('json','jsonl','raw'),
            'schema_name':enum(None,'annotation','task_output_record','metric_record')})},'registry_approved_at_utc':{'type':'string','format':'date-time'},
        'analysis_locked_at_utc':{'type':'string','format':'date-time'}}))

def strict_output_schemas(original,base_schemas):
    result=copy.deepcopy(original)
    result['equivalence']['properties']['changes']=arr(obj({'source_location':STR,'candidate_location':STR,
        'change_type':enum('content','organization','uncertain'),'description':STR}))
    result['adjudication']['properties'].update({'adjudicator_id':NS,'human_approval_record_id':NS})
    result['adjudication']['required']+=['adjudicator_id','human_approval_record_id']
    result['adjudication']['allOf']=[{'if':{'properties':{'resolution':{'type':'string'}},'required':['resolution']},
        'then':{'properties':{'adjudicator_id':ID,'human_approval_record_id':ID,'requires_human_decision':{'const':False}}}}]
    fact=obj({'item_id':ID,'statement':STR,'verification_status':enum('unverified'),'evidence_ids':STRINGS,'locations':STRINGS,'reason':STR})
    defect=obj({'item_id':ID,'target':STR,'diagnosis':STR,'severity_candidate':enum('major','minor','blocking','unknown'),
                'evidence_ids':STRINGS,'locations':STRINGS,'reason':STR})
    acu=obj({'acu_id':ID,'content':STR,'type':enum('method','finding','theory','counterexample','boundary','resource','other'),
             'source_quotes':STRINGS,'conditions':STRINGS,'verification_status':enum('unverified')})
    necessary=obj({'item_id':ID,'dependent_claim_ids':STRINGS,'reproducibility_task':STR,'necessity_reason':STR,
                   'acceptable_locations':STRINGS,'applicability':enum('applicable','not_applicable','uncertain'),'evidence_ids':STRINGS})
    result['ledger_draft']['properties'].update({'facts':arr(fact),'initial_defect_candidates':arr(defect),
         'scientific_unit_candidates':arr(acu),'necessary_items':arr(necessary)})
    result['controlled_variant']['properties']['changed_spans']=arr(obj({'start':INT,'end':INT,'source_text':STR,'variant_text':STR}))
    result['human_annotation']=arr(copy.deepcopy(base_schemas['annotation']))
    issue=obj({'id':ID,'severity':enum('blocking','major','minor'),'artifact_location':ID,'problem':STR,
               'consequence':STR,'proposed_fix':STR,'verification_step':STR})
    result['independent_review']=obj({'verdict':enum('changes_requested','no_unresolved_design_issues','cannot_assess'),
        'scope':STRINGS,'issues':arr(issue),'limitations':STRINGS})
    result['independent_review']['allOf']=[
        {'if':{'properties':{'verdict':{'const':'no_unresolved_design_issues'}},'required':['verdict']},
         'then':{'properties':{'issues':{'maxItems':0}}}},
        {'if':{'properties':{'verdict':{'const':'changes_requested'}},'required':['verdict']},
         'then':{'properties':{'issues':{'minItems':1}}}}]
    def close(node):
        if isinstance(node,dict):
            if 'properties' in node and 'type' in node:
                node['additionalProperties']=False
            for child in node.values():close(child)
        elif isinstance(node,list):
            for child in node:close(child)
    for s in result.values():
        close(s);s['$schema']='https://json-schema.org/draft/2020-12/schema'
    # The coordinator, not the blinded model, supplies the outer provenance record.
    task_record=envelope(obj({'task_schema':enum(*result),'payload':{},'raw_output_sha256':ID,'blind_document_id':ID}))
    task_record['allOf']=[{'if':{'properties':{'task_schema':{'const':name}},'required':['task_schema']},
                           'then':{'properties':{'payload':copy.deepcopy(schema)}}} for name,schema in result.items()]
    task_record['$schema']='https://json-schema.org/draft/2020-12/schema'
    result['task_output_record']=task_record
    return result

def augment_run_example(example):
    value=copy.deepcopy(example)
    value.update({'schema_version':'2.3','namespace':'CONVERGENCE','study_id':'conv_review_trajectory',
        'prompt_id':'P01','document_kind':'review','input_manuscript_record_id':'conv_demo_paper','input_review_record_id':None,'input_description_record_id':None,
        'input_state_record_id':'conv_demo_paper','substep':None,'input_fact_record_id':None,'input_fact_sha256':None,
        'activation_sha256':None,
        'request_sent_at_utc':'2026-01-02T00:00:00Z',
        'record_id':'conv_demo_only_01','evidence_class':'engineering_validation','label_source':'fixture_not_model',
        'rubric_version':'CONV-v2-fixture','fixture':True,'data_origin':'illustrative',
        'history_mode':'none','history_record_ids':[],'prefix_record_ids':[],
        'lineage_root_record_id':'conv_demo_only_01','intervention_type':'NONE','intervention_id':None,
        'reset_from_record_id':None,'terminal_no_issue':False,
        'usage':{k:None for k in ['input_tokens','output_tokens','reasoning_tokens','cache_read_tokens','cache_write_tokens',
                                'cost_amount','currency','elapsed_seconds','critique_count','cumulative_critique_count','unknown_reason']}})
    value['usage'].update({'critique_count_source':'unknown','generation_call_count':0,'cumulative_generation_call_count':0,
                          'critique_count_record_id':None,
                          'unknown_reason':'illustrative schema fixture; no model call'})
    value.update({'model_snapshot':None,'input_sha256':None,'output_sha256':None,'attempt':0})
    value['parent_record_ids']=['conv_demo_paper']
    import hashlib
    from spec_data import PROMPTS
    template=next(p['text'] for p in PROMPTS if p['id']=='P01')
    rendered=template.replace('{{manuscript}}','Illustrative fixed manuscript.').replace('{{previous_review}}','NONE')
    value['input_sha256']=hashlib.sha256(rendered.encode()).hexdigest()
    return value

def style_case():
    source='On dataset D, method A scored 82% and method B scored 80%, using a batch size of 32. On dataset E, A did not outperform B. Only these datasets were tested.'
    return {'case_id':'TOY09','illustrative':True,'kind':'illustrative_unit_test_not_validation_data','source_text':source,
        'variant_text':'Dataset D (batch size 32): A scored 82%; B scored 80%. On E, A did not outperform B. Evaluation covered only D and E.',
        'change_type':'style_edit','possibly_affected_dimensions':['Q5','structure'],
        'rationale':'Style change does not imply improvement. Humans independently verify meaning preservation and rate expression.',
        'expert_validated':False}

def augment_case(case):
    out=copy.deepcopy(case)
    out.update({'schema_version':'2.3','namespace':'CONVERGENCE','study_id':'conv_review_trajectory',
        'record_id':'conv_'+out['case_id'].lower(),'evidence_class':'engineering_validation',
        'label_source':'fixture_author_not_expert','rubric_version':'CONV-v2-controlled-fixture',
        'fixture':True,'data_origin':'illustrative','illustrative':True,'parent_record_ids':[]})
    return out
