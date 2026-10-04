import datetime
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path('/home/sejong/workspace/inference-engine-test')
REPORT = Path(__file__).resolve().parent
KUBE = [str(ROOT / 'scripts/local-k8s-gpu.sh'), 'kubectl']

def kube(*args, **kwargs):
    return subprocess.run([*KUBE, *args], check=True, text=True, **kwargs)

def save_command(path, command):
    path.write_text(subprocess.check_output(command, text=True))

for variant in ['base', 'enhanced-batch', 'enhanced-cache']:
    directory = REPORT / variant
    result_path = directory / 'results.json'
    if result_path.exists() and json.loads(result_path.read_text()).get('complete'):
        continue
    print(f'START {variant} {datetime.datetime.now(datetime.timezone.utc).isoformat()}', flush=True)
    kube('apply', '-f', str(directory / 'inference.yaml'))
    kube('rollout', 'status', 'deployment/transformers-base', '--timeout=300s')
    save_command(directory/'inference-pods.json', [*KUBE,'get','pods','-l','app=transformers-base','-o','json'])
    save_command(directory/'image.json', ['docker','image','inspect',f'local/transformers-{variant}-gpu:0.1.0'])
    save_command(directory/'versions.json', [*KUBE,'exec','deployment/transformers-base','--','python','-c',
        'import json,torch,transformers; print(json.dumps({"torch":torch.__version__,"transformers":transformers.__version__,"cuda":torch.version.cuda}))'])
    server_log = (directory/'server.log').open('w')
    log_process = subprocess.Popen([*KUBE,'logs','-f','deployment/transformers-base'],text=True,stdout=server_log,stderr=subprocess.STDOUT)
    command = [sys.executable,str(ROOT/'scripts/run-mmlu.py'),'--backend','transformers','--device','gpu',
               '--few-shot','0','--max-tokens','128','--timeout','60','--job-timeout','43200','--output',str(result_path)]
    (directory/'command.json').write_text(json.dumps(command,indent=2)+'\n')
    try:
        with (directory/'runner.log').open('w') as log:
            process = subprocess.run(command,cwd=ROOT,text=True,stdout=log,stderr=subprocess.STDOUT)
        if not result_path.exists() or not json.loads(result_path.read_text()).get('complete'):
            raise RuntimeError(f'{variant}: evaluation incomplete, see {directory}/runner.log')
        result=json.loads(result_path.read_text())
        print(json.dumps({'variant':variant,'exit_code':process.returncode,'summary':result['summary']}),flush=True)
        save_command(directory/'runtime.json', [*KUBE,'exec','deployment/transformers-base','--','python','-c',
            'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8000/runtime").read().decode())'])
    finally:
        kube('scale','deployment/transformers-base','--replicas=0')
        kube('wait','--for=delete','pod','-l','app=transformers-base','--timeout=120s')
        try:
            log_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            log_process.terminate()
            log_process.wait(timeout=10)
        server_log.close()
print('ALL_VARIANTS_COMPLETE',flush=True)
