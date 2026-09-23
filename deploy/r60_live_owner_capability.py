#!/usr/bin/env python3
"""Read-only live owner capability inspection. No Zigbee/MQTT commands or secrets output."""
import importlib.util
import json
from pathlib import Path
import shlex

HELPER = Path(r'C:\Workspace\repos\config\skills\home-assistant-readonly\ha_readonly.py')
spec = importlib.util.spec_from_file_location('ha_readonly', HELPER)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
REMOTE = r'''import json, subprocess
p = subprocess.run(['docker','ps','--filter','name=zigbee2mqtt','--format','{{.ID}}'],capture_output=True,text=True,timeout=5)
ids = [s.strip() for s in p.stdout.splitlines() if s.strip()]
out = {'one_owner':len(ids)==1, 'docker_ok':p.returncode==0}
if len(ids)==1:
 script = "const fs=require('fs'); let p={}; for(const n of ['mqtt','yaml','js-yaml']) {try{p[n]=require.resolve(n)}catch{p[n]=null}}; p.cwd=process.cwd(); p.config_candidates=['/app/data/configuration.yaml','/data/configuration.yaml','/config/zigbee2mqtt/configuration.yaml'].filter(x=>fs.existsSync(x)); console.log(JSON.stringify(p))"
 x = subprocess.run(['docker','exec',ids[0],'node','-e',script],capture_output=True,text=True,timeout=8)
 try: out['node']=json.loads(x.stdout)
 except ValueError: out['node_error']='node_inspection_unavailable'
print(json.dumps(out))'''
client = module.connect('ha')
try:
    _, stdout, stderr = client.exec_command('python3 -c '+shlex.quote(REMOTE), timeout=18)
    result = stdout.read().decode('utf-8', 'replace')
    error = stderr.read().decode('utf-8', 'replace')
    if stdout.channel.recv_exit_status()!=0: raise RuntimeError('HA capability query failed: '+error[:160])
    print(result[:2500])
finally:
    client.close()
