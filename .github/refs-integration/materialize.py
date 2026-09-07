"""Materialize a checked merge candidate, never update a release ref."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

REPOS = {'s7cret/pine2ast', 's7cret/pinelib', 's7cret/ast2python'}
FEATURE = 'refs/heads/stage2/reference-values-20260907'
OPS = 'refs/heads/ops/stage2-refs-integrate-20260907'

def git(*args, data=None):
    return subprocess.check_output(['git', *args], input=data).decode().strip()

def refs():
    return {ref: sha for sha, ref in (line.split() for line in git('ls-remote', '--refs', 'origin').splitlines())}

folder = Path(sys.argv[1]).resolve()
evidence = Path(os.environ['RUNNER_TEMP'])/'evidence'
evidence.mkdir(exist_ok=True)
plan = json.loads((folder/'plan.json').read_text())
repo = os.environ['GITHUB_REPOSITORY']
if repo not in REPOS or plan['repository'] != repo or os.environ['GITHUB_REF'] != OPS:
    raise SystemExit('wrong source or maintenance identity')
for key in ('base', 'head', 'tree', 'preimage'):
    if not re.fullmatch('[0-9a-f]{40}', plan[key]): raise ValueError('invalid source hash')
if not plan['parents'] or any(not re.fullmatch('[0-9a-f]{40}', p) for p in plan['parents']):
    raise ValueError('invalid parents')
raw = plan['raw'].encode()
headers = '\n'.join(['tree '+plan['tree'], *['parent '+p for p in plan['parents']]])+'\nauthor '
if not raw.startswith(headers.encode()) or hashlib.sha1(b'commit '+str(len(raw)).encode()+b'\0'+raw).hexdigest()!=plan['head']:
    raise ValueError('raw commit identity mismatch')
patch=(folder/'source.patch').read_bytes()
if len(patch)>2_000_000 or hashlib.sha256(patch).hexdigest()!=plan['patch_sha256']:
    raise ValueError('patch checksum mismatch')
for name in plan['format']:
    if not isinstance(name,str) or not name.endswith('.py') or Path(name).is_absolute() or '..' in Path(name).parts:
        raise ValueError('invalid formatter source')
(evidence/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
(evidence/'source.patch').write_bytes(patch)
before=refs()
if before.get(FEATURE) not in (plan['base'],plan['head']): raise ValueError('candidate changed concurrently')
git('checkout','--detach',plan['base'])
if plan['merge']:
    if not re.fullmatch('[0-9a-f]{40}',plan['merge']): raise ValueError('invalid merge head')
    git('merge','--no-commit','--no-ff',plan['merge'])
if plan['format']:
    subprocess.run([sys.executable,'-m','ruff','format',*plan['format']],check=True)
git('add','-A')
if git('write-tree')!=plan['preimage']: raise ValueError('merge/format preimage mismatch')
git('apply','--check','--index','-',data=patch)
git('apply','--index','--whitespace=nowarn','-',data=patch)
if git('write-tree')!=plan['tree']: raise ValueError('candidate tree mismatch')
if git('hash-object','-t','commit','-w','--stdin',data=raw)!=plan['head']: raise ValueError('candidate commit mismatch')
git('checkout','--detach',plan['head'])
for parent in plan['parents']: git('merge-base','--is-ancestor',parent,plan['head'])
git('merge-base','--is-ancestor',plan['base'],plan['head'])
git('push','origin',plan['head']+':'+FEATURE)
sha=os.environ['GITHUB_SHA'];tag=OPS.replace('refs/heads/','refs/tags/',1)
git('push','--atomic','--force-with-lease='+OPS+':'+sha,'--force-with-lease='+tag+':','origin',sha+':'+tag,':'+OPS)
after=refs();expected=dict(before);expected.pop(OPS);expected[tag]=sha;expected[FEATURE]=plan['head']
if after!=expected: raise ValueError('unexpected ref changes')
for label,data in [('before',before),('after',after)]: (evidence/(label+'.json')).write_text(json.dumps(data,indent=2)+'\n')
git('update-ref','refs/heads/materialized-source',plan['head'])
git('bundle','create',str(evidence/'source.bundle'),'refs/heads/materialized-source')
git('bundle','verify',str(evidence/'source.bundle'))
(evidence/'scope.txt').write_text('Source materialization only. No test or release acceptance is asserted.\n')
