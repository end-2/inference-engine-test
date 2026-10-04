import csv
import json
import re
from pathlib import Path
from collections import Counter
from datetime import datetime

root=Path(__file__).resolve().parent
reports={name:json.loads((root/name/'results.json').read_text()) for name in ['base','enhanced-batch','enhanced-cache']}
def choice_prediction(result):
    if result['status']=='ERROR':
        return None
    if result.get('prediction'):
        return result['prediction']
    match=re.match(r'^(?:Answer:\s*)?([ABCD])[.)]\s+', result.get('answer','').strip())
    return match[1] if match else None

rows=[]
for name,report in reports.items():
    assert report['complete'] and report['summary']['total']==14042
    assert report['dataset']['file_sha256']==reports['base']['dataset']['file_sha256']
    assert report['settings']==reports['base']['settings']
    results=report['results']
    assert len(results)==14042
    assert sum(r['status']=='CORRECT' for r in results)==report['summary']['correct']
    row={'variant':name,**report['summary'],'accuracy_percent':report['summary']['accuracy']*100,
         'elapsed_seconds':(datetime.fromisoformat(report['finished_at'])-datetime.fromisoformat(report['started_at'])).total_seconds(),
         'output_limit_errors':sum(r.get('finish_reason')=='length' for r in results),
         'mean_completion_tokens':sum(r.get('response',{}).get('usage',{}).get('completion_tokens',0) for r in results)/len(results)}
    row['choice_text_correct']=sum(choice_prediction(r)==r['expected'] for r in results)
    row['choice_text_accuracy']=row['choice_text_correct']/len(results)
    row['choice_text_accuracy_percent']=row['choice_text_accuracy']*100
    row['choice_text_unparsed']=sum(choice_prediction(r) is None and r['status']!='ERROR' for r in results)
    rows.append(row)
with (root/'summary.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
comparisons={}
for name,report in reports.items():
    if name=='base':continue
    differences=[]
    for base,other in zip(reports['base']['results'],report['results']):
        assert (base['subject'],base['index'],base['expected'],base['prompt'])==(other['subject'],other['index'],other['expected'],other['prompt'])
        if (base.get('answer'),base['status'])!=(other.get('answer'),other['status']):
            differences.append({'subject':base['subject'],'index':base['index'],'expected':base['expected'],
                                'base_answer':base.get('answer'),'candidate_answer':other.get('answer'),
                                'base_status':base['status'],'candidate_status':other['status']})
    comparisons[name]={'response_differences':len(differences),
                       'base_correct_candidate_wrong':sum(d['base_status']=='CORRECT' and d['candidate_status']!='CORRECT' for d in differences),
                       'base_wrong_candidate_correct':sum(d['base_status']!='CORRECT' and d['candidate_status']=='CORRECT' for d in differences)}
    pairs=list(zip(reports['base']['results'],report['results']))
    comparisons[name]['choice_text_prediction_differences']=sum(choice_prediction(a)!=choice_prediction(b) for a,b in pairs)
    comparisons[name]['choice_text_base_correct_candidate_wrong']=sum(choice_prediction(a)==a['expected'] and choice_prediction(b)!=b['expected'] for a,b in pairs)
    comparisons[name]['choice_text_base_wrong_candidate_correct']=sum(choice_prediction(a)!=a['expected'] and choice_prediction(b)==b['expected'] for a,b in pairs)
    assert comparisons[name]['base_wrong_candidate_correct']-comparisons[name]['base_correct_candidate_wrong']==report['summary']['correct']-reports['base']['summary']['correct']
    (root/name/'differences.json').write_text(json.dumps(differences,ensure_ascii=False,indent=2)+'\n')
subject_rows=[]
for subject in reports['base']['per_subject']:
    for name,report in reports.items():
        subject_results=[result for result in report['results'] if result['subject']==subject]
        correct=sum(choice_prediction(result)==result['expected'] for result in subject_results)
        subject_rows.append({'subject':subject,'variant':name,**report['per_subject'][subject],
                             'choice_text_correct':correct,'choice_text_accuracy':correct/len(subject_results)})
with (root/'summary-subjects.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(subject_rows[0]));w.writeheader();w.writerows(subject_rows)
summary={'dataset_file_sha256':reports['base']['dataset']['file_sha256'],'conditions':json.loads((root/'conditions.json').read_text()),'results':rows,'comparison_with_base':comparisons,'posthoc_rule':'Normal stop responses also accept an initial A., B., C., D. or closing parenthesis followed by whitespace, with optional Answer: prefix. Error responses remain incorrect. Original generated-choice-v1 reports are preserved.'}
summary['implementation_evidence']={}
for name in reports:
    image=json.loads((root/name/'image.json').read_text())[0]
    run=json.loads((root/name/'results-run/run.json').read_text())
    summary['implementation_evidence'][name]={
        'image_id':image['Id'],'source_sha256':image['Config']['Labels']['io.local.inference.source-sha256'],
        'versions':json.loads((root/name/'versions.json').read_text()),
        'runtime':json.loads((root/name/'runtime.json').read_text()),
        'evaluator_image_id':run['image']['id'],
        'error_types':dict(Counter(result.get('error') for result in reports[name]['results'] if result['status']=='ERROR'))}
(root/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(summary,ensure_ascii=False,indent=2))
