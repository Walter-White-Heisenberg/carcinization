"""Deterministic, platform-independent selections, frozen before pilot generation."""
import hashlib,json
ALGORITHM='CONVERGENCE_SAMPLING_V1'

def rank(seed,domain,*parts):
    raw=json.dumps([ALGORITHM,seed,domain,*parts],ensure_ascii=False,separators=(',',':')).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()

def derive_sampling_plan(config):
    papers=[p if isinstance(p,str) else p['paper_id'] for p in config['pilot_papers']]
    if len(papers)!=6 or len(set(papers))!=6 or any(not isinstance(p,str) or not p for p in papers):
        raise ValueError('Freeze six distinct pilot paper IDs before sampling')
    seed=config['sampling_seed']
    if type(seed) is not int:raise ValueError('Integer sampling seed required')
    ordered=sorted(papers,key=lambda p:p.encode('utf-8'))
    c_papers=sorted(papers,key=lambda p:(rank(seed,'C',p),p.encode('utf-8')))[:3]
    audit={p:min(range(1,4),key=lambda k:(rank(seed,'AUDIT_K',p,k),k)) for p in ordered}
    return {'algorithm':ALGORITHM,'seed':seed,'pilot_paper_ids':ordered,'c_paper_ids':c_papers,
            'quality_audit_trajectory_by_paper':audit,'audit_rounds':[0,5,10],
            'primary_structure_trajectories':[1,2,3],'primary_structure_rounds':[0,10]}

def verify_frozen_sampling(activation_ref,config):
    from study_locks import artifact_from_activation
    prereg,_=artifact_from_activation(activation_ref,'preregistration_lock')
    if prereg.get('sampling_plan')!=derive_sampling_plan(config):
        raise ValueError('Pre-generation sampling plan is missing or differs from the deterministic rule')
    return prereg['sampling_plan']
