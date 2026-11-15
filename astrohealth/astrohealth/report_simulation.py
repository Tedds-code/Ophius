"""On-demand lab/dose fixtures, passed through the real validation/assessment path."""
from copy import deepcopy
from datetime import timedelta
import uuid
from .engine import Case


LAB_SCENARIOS = {'normal':'Normal panel', 'mixed':'Mixed abnormal panel', 'anemia':'Low hemoglobin / anemia',
    'polycythemia':'High hemoglobin', 'leukopenia':'Low white cells', 'leukocytosis':'High white cells',
    'thrombocytopenia':'Low platelets', 'd_dimer':'High D-dimer', 'febrile_neutropenia':'Low white cells with reported fever',
    'single':'One selected measurement'}
DOSE_SCENARIOS = {'normal':'Within configured limits', 'mixed':'Mixed dose results', 'high':'Above every configured limit',
                  'needs_context':'Missing exposure context', 'single':'One selected dose quantity'}


def normal_value(rule):
    low=rule.get('caution_below', rule.get('critical_below'))
    high=rule.get('caution_above', rule.get('critical_above'))
    low=low if low is not None else rule.get('critical_below')
    high=high if high is not None else rule.get('critical_above')
    if low is not None and high is not None:return (low+high)/2
    if high is not None:return high*.4
    if low is not None:return low*1.25
    return 0


def changed_value(rule,direction):
    if direction=='normal':return normal_value(rule)
    boundary=rule.get('caution_'+('below' if direction=='low' else 'above'))
    if boundary is None:boundary=rule.get('critical_'+('below' if direction=='low' else 'above'))
    if boundary is None:raise ValueError('This measurement has no configured '+direction+' limit')
    return max(0,boundary-max(abs(boundary)*.2,.01)) if direction=='low' else boundary+max(abs(boundary)*.2,.01)


def simulate_report(monitor,aid,payload):
    if not isinstance(payload,dict):raise ValueError('Report simulation must be an object')
    scope=payload.get('scope','labs');scenario=payload.get('scenario','normal')
    choices=LAB_SCENARIOS if scope=='labs' else DOSE_SCENARIOS if scope=='dose' else None
    if choices is None or scenario not in choices:raise ValueError('Unknown report scope or scenario')
    direction=payload.get('direction','high')
    if direction not in {'normal','low','high'}:raise ValueError('Direction must be normal, low or high')
    now=monitor._now();profile=monitor.snapshot(aid)['profile'];sex=profile['personal_information']['gender']
    scenario_id=uuid.uuid4().hex
    specs=[r for r in monitor.kb.reading_keys() if r['category']==('blood_panel' if scope=='labs' else 'radiation')]
    target=payload.get('key')
    if scenario=='single' and target not in {s['key'] for s in specs}:raise ValueError('Select a valid measurement')
    if scope=='labs':
        readings={}
        for spec in specs:
            key=spec['key'];rule=monitor.kb.signals[monitor.kb.signal_name(key,sex)]
            change='normal'
            if scenario=='single' and key==target:change=direction
            elif scenario=='mixed':change='low' if rule.get('caution_below') is not None else 'high'
            elif scenario in {'anemia','polycythemia'} and key in {'hemoglobin','hematocrit','rbc'}:change='low' if scenario=='anemia' else 'high'
            elif scenario in {'leukopenia','febrile_neutropenia'} and key in {'wbc','neutrophils','lymphocytes'}:change='low'
            elif scenario=='leukocytosis' and key in {'wbc','neutrophils'}:change='high'
            elif scenario=='thrombocytopenia' and key=='platelets':change='low'
            elif scenario=='d_dimer' and key=='d_dimer':change='high'
            readings[key]={'value':round(changed_value(rule,change),5),'unit':rule['unit']}
        monitor.import_lab(aid,{'format':'astro_health_blood_panel_v1','timestamp':now.isoformat(),
            'report_id':'lab-demo-'+scenario_id,'synthetic':True,'measurements':readings})
        if scenario=='febrile_neutropenia':monitor.update_symptoms(aid,{'readings':{'core_temperature':38.5}})
    else:
        grouped={}
        anchor=monitor.storage.get_anchor(aid,'simulation')
        if anchor:
            from .monitor import timestamp
            anchor=timestamp(anchor)
        for i,spec in enumerate(specs):
            key=spec['key'];rule=deepcopy(monitor.kb.signals[key]);window=rule['window']
            if rule.get('scales_with_mission_duration'):
                factor=profile['mission_details']['duration_days']/365
                for name in ['critical_above','caution_above']:
                    if rule.get(name) is not None:rule[name]*=factor
            change='high' if scenario=='high' or (scenario=='mixed' and i%2==0) else 'normal'
            if scenario=='single' and key==target:change=direction
            value=round(changed_value(rule,change),5)
            days={'30_days':30,'1_year':365,'career':730,'per_mission_year':1}[window]
            start=now-timedelta(days=days)
            if window=='per_mission_year' and anchor is not None:start=min(start,anchor)
            metadata={'kind':'reported_window','window':window,'verified':scenario!='needs_context',
                'career_complete':window=='career','synthetic_coverage':True,'synthetic_scenario_id':scenario_id,
                'note':'Independent synthetic dosimetry fixture; coverage is hypothetical, not observed acquisition'}
            if scenario!='needs_context':metadata.update(coverage_start=start.isoformat(),coverage_end=now.isoformat())
            grouped.setdefault(window,{})[key]={'value':value,'unit':rule['unit'],'metadata':metadata}
        for window,readings in grouped.items():
            monitor.ingest(aid,{'packet_id':'dose-demo-'+scenario_id+'-'+window,'timestamp':now.isoformat(),
                'source':'simulation','quality':'ok','readings':readings})
    snap=monitor.snapshot(aid)
    snap['report_simulation']={'scope':scope,'scenario':scenario,'scenario_id':scenario_id,
        'measurement_count':len(specs),'synthetic':True,'note':'Numerical test fixtures, not a physiological simulation'}
    return snap


def measurement_connections(monitor,aid,key):
    snap=monitor.snapshot(aid);row=next((r for r in snap['readings'] if r['key']==key),None)
    if row is None:raise ValueError('Unknown measurement')
    name=monitor.kb.signal_name(key,snap['profile']['personal_information']['gender'])
    rule=deepcopy(monitor.kb.signals[name])
    active={f['rule_id'] for f in snap['assessment']['findings']}
    def refers(node):
        if isinstance(node,dict):return node.get('signal') in {key,name} or any(refers(v) for v in node.values())
        if isinstance(node,list):return any(refers(x) for x in node)
        return False
    linked=[{'id':r['id'],'name':r['name'],'condition_id':r['condition_id'],'active':r['id'] in active,
             'logic':r.get('logic_description'),'confirmation':r.get('confirmation',[])}
            for r in monitor.kb.rules if refers(r.get('levels',{})) or refers(r.get('supporting_evidence'))]
    limits=monitor.kb.limits_for(name,Case(sex=snap['profile']['personal_information']['gender'],
        mission_duration_days=snap['profile']['mission_details']['duration_days']))
    return {'measurement':row,'threshold_key':name,'reference':rule,'effective_limits':limits,'linked_rules':linked,
        'interpretation':'Threshold/reference comparison only; no dedicated diagnostic rule is supplied for this quantity' if not linked else
                         'Linked rules are evaluated using the complete case; an abnormal number alone need not trigger every linked rule'}
