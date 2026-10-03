"""GPU cluster lifecycle, MPS admission, and cleanup without a live runtime."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MOCK = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
name = Path(sys.argv[0]).name
args = sys.argv[1:]
path = Path(os.environ['MOCK_STATE'])
state = json.loads(path.read_text())
with open(os.environ['MOCK_TRACE'], 'a') as f:
    f.write(json.dumps([name, args]) + '\n')
def option(flag, default=''):
    return args[args.index(flag)+1] if flag in args else default
def save(): path.write_text(json.dumps(state))
cluster = os.environ.get('CLUSTER_NAME', 'local-k8s-gpu')
current = state.setdefault('clusters', {}).get(cluster, {})
if name == 'sleep': pass
elif name == 'nvidia-smi':
    if '-L' in args: print('GPU 0: test GPU')
    elif '--query-compute-apps=pid' in args: print(state.get('active_pid', ''), end='')
elif name == 'docker':
    if args[:1] == ['inspect']: print(os.environ['LOCAL_K8S_MODELS_DIR'] + ':false')
    elif args[:1] == ['info']:
        if option('--format') == '{{json .Runtimes}}': print('{"nvidia":{}}')
    elif args[:1] == ['run']: print('GPU 0: test GPU')
    elif args[:2] == ['image','save']: Path(option('--output')).touch()
elif name == 'kind':
    if args[:2] == ['get','clusters']:
        if state.get('fail_list'): sys.exit(1)
        print('\n'.join(state['clusters']))
    elif args[:2] == ['get','nodes']:
        print(option('--name')+'-control-plane\n'+option('--name')+'-worker')
    elif args[:2] == ['export','kubeconfig']: Path(option('--kubeconfig')).write_text('isolated')
    elif args[:2] == ['delete','cluster']:
        state['clusters'].pop(option('--name'), None); save()
elif name == 'nvkind':
    if os.environ.get('KIND_EXPERIMENTAL_PROVIDER'):
        raise RuntimeError('Provider diagnostic corrupts nvkind node parsing')
    state['clusters'][option('--name')] = {'mode': os.environ.get('GPU_SHARING','none'), 'count':0,
        'replicas':os.environ.get('MPS_REPLICAS','2')}
    Path(option('--kubeconfig')).write_text('isolated'); save()
elif name == 'helm':
    if args[:1] == ['upgrade']:
        current['count'] = int(os.environ.get('MPS_REPLICAS','2')) if current['mode'] == 'mps' else 1
        save()
elif name == 'kubectl':
    args = args[4:]
    text = ' '.join(args)
    if args[:2] == ['get','node']:
        if not current: sys.exit(1)
        fmt = option('-o')
        if 'gpu-sharing' in fmt: print(current.get('mode',''), end='')
        elif 'mps-replicas' in fmt: print(current.get('replicas',''), end='')
        elif 'mps\.capable' in fmt: print('true' if current.get('mps') else '', end='')
        elif 'gpu\.shared' in fmt: print(current.get('count',0) if current.get('mode')=='mps' else 0, end='')
        elif 'allocatable' in fmt: print(current.get('count',0) if current.get('mode')=='none' else 0, end='')
    elif args[:2] == ['get','pods']:
        if '-n' in args and option('-n') == 'nvidia':
            if current.get('mps'): print('nvidia-device-plugin-mps-control-daemon-test ')
        elif state.get('job'): print('\n'.join('pod/smoke-'+str(i) for i in range(state.get('job_replicas',2))))
    elif args[:2] == ['label','node']:
        current['mps'] = 'nvidia.com/mps.capable=true' in args
        save()
    elif args[:1] == ['apply']:
        if option('-f') == '-':
            body=sys.stdin.read()
            if body.startswith('{'):
                state['job']=True; state['job_replicas']=json.loads(body)['spec']['parallelism']; save()
        else: state['job']=True; save()
    elif args[:1] == ['patch'] and '--local' in args: print(option('-p'))
    elif args[:2] == ['create','configmap']:
        state['configmap']=True; save()
    elif args[:2] == ['delete','job']:
        state['job']=False; save()
    elif args[:2] == ['delete','configmap']:
        state['configmap']=False; save()
    elif args[:1] == ['exec'] and 'nvidia-cuda-mps-control' in args:
        cmd = sys.stdin.read().strip()
        with open(os.environ['MOCK_TRACE'],'a') as f: f.write(json.dumps(['mps',cmd])+'\n')
        if cmd == 'get_default_active_thread_percentage': print(state.get('percentage',str(100/int(current['replicas']))))
        elif cmd == 'get_default_device_pinned_mem_limit 0': print(str(8//int(current['replicas']))+'G')
        elif cmd == 'get_server_list': print('123')
        elif cmd.startswith('get_client_list'): print('\n'.join(str(i) for i in range(state.get('clients',int(current['replicas'])))))
    elif args[:1] == ['wait'] and '--for=condition=Ready' in args and any(a.startswith('pod/') for a in args):
        if state.get('fail_ready'): sys.exit(1)
    elif args[:1] == ['logs']: print('CUDA MPS smoke passed')
else: raise RuntimeError((name,args))
'''


class GPUClusterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="gpu cluster test ")
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.bin = self.work / "bin"
        self.bin.mkdir()
        self.state = self.work / "state.json"
        self.trace = self.work / "trace.jsonl"
        self.state.write_text(json.dumps({'clusters': {}}))
        self.trace.touch()
        mock = self.bin / "mock"
        mock.write_text(MOCK)
        mock.chmod(0o755)
        for name in ('docker', 'kind', 'kubectl', 'nvkind', 'helm', 'nvidia-smi', 'sleep'):
            (self.bin / name).symlink_to(mock)
        self.env = {**os.environ, 'PATH': str(self.bin)+os.pathsep+os.environ['PATH'],
                    'MOCK_STATE': str(self.state), 'MOCK_TRACE': str(self.trace),
                    'LOCAL_K8S_BIN_DIR': str(self.bin), 'LOCAL_K8S_STATE_DIR': str(self.work/'state'),
                    'LOCAL_K8S_MODELS_DIR': str(self.work/'models'), 'GPU_SHARING': 'mps',
                    'MPS_REPLICAS': '2',
                    'KIND_EXPERIMENTAL_PROVIDER': 'docker', 'KUBECONFIG': str(self.work/'unrelated')}
        self.env.pop('CLUSTER_NAME', None)
        Path(self.env['KUBECONFIG']).write_text('untouched')

    def run_script(self, *args, script='local-k8s-gpu.sh', ok=True):
        result = subprocess.run(['sh', str(ROOT/'scripts'/script), *args], env=self.env,
                                cwd=self.work, capture_output=True, text=True, timeout=20)
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout+result.stderr)
        return result

    def update(self, **values):
        state = json.loads(self.state.read_text()); state.update(values)
        self.state.write_text(json.dumps(state))

    def calls(self, tool):
        return [v[1] for line in self.trace.read_text().splitlines()
                if (v := json.loads(line))[0] == tool]

    def test_mps_creation_reuse_and_isolated_context(self):
        result = self.run_script('up')
        self.assertIn('nvidia.com/gpu.shared=2', result.stdout)
        self.assertIn('2 concurrent CUDA clients', result.stdout)
        self.assertEqual(Path(self.env['KUBECONFIG']).read_text(), 'untouched')
        kubeconfig = self.work/'state/local-k8s-gpu-mps/kubeconfig'
        self.assertEqual(kubeconfig.stat().st_mode & 0o777, 0o600)
        helm = next(a for a in self.calls('helm') if a[0]=='upgrade')
        self.assertIn('config.default=mps', helm)
        self.assertIn(f'config.map.mps={ROOT}/config/cluster/mps.yaml', helm)
        self.assertIn('get_client_list 123', self.calls('mps'))
        before = len(self.calls('nvkind'))
        self.update(active_pid='888\n')
        self.run_script('up')
        self.assertEqual(len(self.calls('nvkind')), before)
        self.assertEqual(sum(a[0]=='upgrade' for a in self.calls('helm')), 1)
        for args in self.calls('kubectl'):
            self.assertEqual(args[:4], ['--kubeconfig', str(kubeconfig), '--context', 'kind-local-k8s-gpu-mps'])

    def test_exclusive_mode_keeps_single_gpu_without_mps(self):
        self.env['GPU_SHARING']='none'
        self.assertIn('nvidia.com/gpu=1', self.run_script('up').stdout)
        self.assertEqual(self.calls('mps'), [])
        self.assertNotIn('config.default=mps', str(self.calls('helm')))
        self.assertIn('local-k8s-gpu', json.loads(self.state.read_text())['clusters'])

    def test_four_slot_profile_keeps_two_slot_cluster_and_selects_own_images(self):
        self.run_script('up')
        original = json.loads(self.state.read_text())['clusters']['local-k8s-gpu-mps']
        self.env['MPS_REPLICAS']='4'
        result = self.run_script('up')
        self.assertIn('nvidia.com/gpu.shared=4', result.stdout)
        self.assertIn('4 concurrent CUDA clients', result.stdout)
        self.assertIn('thread limit 25.0%', result.stdout)
        self.assertEqual(json.loads(self.state.read_text())['clusters']['local-k8s-gpu-mps'], original)
        self.assertTrue(any(f'config.map.mps={ROOT}/config/cluster/mps-4.yaml' in a for a in self.calls('helm')))
        self.env['DEVICE']='gpu'
        self.run_script('transformers-pd', script='load-inference-images.sh')
        self.run_script(script='load-benchmark-images.sh')
        self.assertTrue(all('local-k8s-gpu-mps4' in a for a in self.calls('kind') if a[0]=='load'))
        self.assertTrue(all('local-k8s-gpu-mps4-worker' in a for a in self.calls('kind') if a[0]=='load'))
        self.run_script('down')
        self.assertEqual(set(json.loads(self.state.read_text())['clusters']), {'local-k8s-gpu-mps'})

    def test_replica_mismatch_does_not_reconfigure_or_delete_existing_cluster(self):
        self.run_script('up')
        self.env.update(MPS_REPLICAS='4', CLUSTER_NAME='local-k8s-gpu-mps')
        self.trace.write_text('')
        self.assertIn('uses MPS_REPLICAS=2', self.run_script('up', ok=False).stderr)
        self.run_script('down', ok=False)
        self.assertFalse(self.calls('helm'))
        self.assertFalse(any(a[:2]==['delete','cluster'] for a in self.calls('kind')))

    def test_busy_gpu_rejected_before_cluster_creation(self):
        self.update(active_pid='4321\n')
        result = self.run_script('up', ok=False)
        self.assertIn('active CUDA processes', result.stderr)
        self.assertEqual(self.calls('nvkind'), [])
        self.assertEqual(self.calls('helm'), [])

    def test_failed_cluster_listing_does_not_create_cluster(self):
        self.update(fail_list=True)
        self.run_script('up', ok=False)
        self.assertEqual(self.calls('nvkind'), [])

    def test_mode_mismatch_rejects_mutation(self):
        self.env['CLUSTER_NAME']='custom-gpu'
        self.env['GPU_SHARING']='none'
        self.run_script('up')
        self.env['GPU_SHARING']='mps'
        self.env['MPS_REPLICAS']='8'
        self.run_script('up', ok=False)
        self.env['MPS_REPLICAS']='2'
        self.assertIn('uses GPU_SHARING=none', self.run_script('up', ok=False).stderr)
        self.run_script('down', ok=False)
        self.assertFalse(any(a[:2]==['delete','cluster'] for a in self.calls('kind')))

    def test_smoke_rejects_missing_second_client_and_cleans_resources(self):
        self.run_script('up')
        self.update(clients=1)
        self.assertIn('same MPS server', self.run_script('test', ok=False).stderr)
        state = json.loads(self.state.read_text())
        self.assertFalse(state['job'])
        self.assertFalse(state['configmap'])

    def test_smoke_readiness_failure_cleans_resources(self):
        self.run_script('up')
        self.update(fail_ready=True)
        self.run_script('test', ok=False)
        self.assertFalse(json.loads(self.state.read_text())['job'])

    def test_unexpected_compute_limit_is_rejected(self):
        self.run_script('up')
        self.update(percentage='100.0')
        self.assertIn('Unexpected MPS thread percentage', self.run_script('test', ok=False).stderr)

    def test_down_stops_daemon_before_deleting_cluster(self):
        self.run_script('up')
        self.trace.write_text('')
        self.run_script('down')
        trace = self.trace.read_text()
        self.assertLess(trace.index('"drain"'), trace.index('nvidia.com/mps.capable-'))
        self.assertLess(trace.index('nvidia.com/mps.capable-'), trace.index('"delete", "cluster"'))
        self.assertFalse(json.loads(self.state.read_text())['clusters'])

    def test_image_loaders_select_mps_cluster(self):
        self.run_script('up')
        self.env['DEVICE']='gpu'
        self.run_script('transformers-base', script='load-inference-images.sh')
        self.run_script(script='load-benchmark-images.sh')
        loads = [a for a in self.calls('kind') if a[0]=='load']
        self.assertTrue(loads)
        self.assertTrue(all('local-k8s-gpu-mps' in a for a in loads))
        self.assertTrue(all('local-k8s-gpu-mps-worker' in a for a in loads))

    def test_exclusive_image_loaders_follow_inference_and_client_placement(self):
        self.env.update(GPU_SHARING='none', DEVICE='gpu')
        self.run_script('up')
        self.trace.write_text('')
        self.run_script('transformers-base', script='load-inference-images.sh')
        self.run_script(script='load-benchmark-images.sh')
        loads = [a for a in self.calls('kind') if a[0]=='load']
        self.assertEqual(len(loads), 2)
        self.assertIn('local-k8s-gpu-worker', loads[0])
        self.assertIn('local-k8s-gpu-control-plane', loads[1])

    def test_invalid_mode_and_cluster_name_are_rejected(self):
        self.env['GPU_SHARING']='invalid'
        self.run_script('up', ok=False)
        self.env['GPU_SHARING']='mps'
        self.env['CLUSTER_NAME']='../escape'
        self.run_script('up', ok=False)
        self.assertEqual(self.calls('nvkind'), [])


if __name__ == '__main__':
    unittest.main()
