"""Record safe synthetic scenarios through the actual Python fusion engine."""
from pathlib import Path
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fusion_compliance_loop.scenarios import scenario_normal_matching,scenario_missing_timestamp,scenario_camera_side_blocked_independently

def generate():
    scenarios=[]
    for fn in [scenario_normal_matching,scenario_missing_timestamp,scenario_camera_side_blocked_independently]:
        name,engine,camera,result=fn()
        trace=result.model_dump(mode='json')
        scenarios.append({'name':name.replace('_',' ').title(),'summary':result.explanation,
                          'rows':[['Camera permitted',result.camera_approved],['Contributing records',len(result.contributing_data_ids)],['Blocked fields',', '.join(result.blocked_fields) or 'None'],['Policy rule',result.camera_policy_rule or 'Recorded in trace']],
                          'trace':trace})
    return {'kind':'fusion','input_type':'generated sensor fixtures; no operational sensor data','scenarios':scenarios}

if __name__=='__main__':
    Path(__file__).with_name('evidence.json').write_text(json.dumps(generate(),indent=2,default=str)+'\n')
    print('evidence.json')
