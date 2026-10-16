"""One factual query builder for life decisions and replies, no activity priority."""
from .clock import utc
from .config import canonical

def build_query(state,config,now,*,message=None,commitments=(),planning_reference=None):
    pending={key:{'goal':config['work_items'][key]['goal'],'responsibility':config['work_items'][key]['responsibility'],
        'deadline':config['work_items'][key]['deadline'],
        'seconds_until_deadline':(utc(config['work_items'][key]['deadline'])-utc(now)).total_seconds(),
        'progress':value['progress'],'status':value['status']}
        for key,value in state.get('work_items',{}).items() if value['status']!='completed'}
    basis={'message':message,'current_place':state['place'],
        'unfinished_activities':[{k:a[k] for k in ('id','kind','target','status','progress')} for a in state['activities'].values()
            if a['status'] in {'running','interrupted'}],
        'pending_work':pending,'retained_reading_progress':state['reading'],'sleep':state.get('sleep',{}).get('status'),
        'commitments':list(commitments),'planning_reference':planning_reference if planning_reference is not None else config.get('planning_reference'),
        'resources':{'inventory':state['inventory'],'meals':state['meals'],
            'available_tools':state.get('available_tools',config['initial']['available_tools'])}}
    # Message and current matters precede numeric context so short encoders see intent.
    query='\n'.join(x for x in [message or '',canonical(basis['unfinished_activities']),canonical(pending),
        canonical(basis['commitments']),canonical({k:v for k,v in basis.items() if k not in {'message','unfinished_activities','pending_work','commitments'}})] if x)
    return basis,query
