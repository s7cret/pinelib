"""Restore original Git objects from a hash-bound transfer, never change releases."""
import base64
import hashlib
import io
import json
import lzma
import os
from pathlib import Path
import struct
import subprocess


def git(*args, data=None):
    return subprocess.check_output(['git', *args], input=data).strip()


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def refs():
    return {r: h for h, r in (l.split() for l in git('ls-remote', '--refs', 'origin').decode().splitlines())}


def store(kind, data, expected):
    require(kind in ('blob', 'tree', 'commit'), 'unexpected object type')
    identity = hashlib.sha1((kind+' '+str(len(data))+'\0').encode()+data).hexdigest()
    require(identity == expected, 'object content differs: '+expected)
    require(git('hash-object', '-t', kind, '-w', '--stdin', data=data).decode() == expected, 'object write differs')


root = Path('.github/stage2-transfer')
plan = json.loads((root/'plan.json').read_text())
require(os.environ['GITHUB_REPOSITORY'] == 's7cret/'+plan['repo'], 'wrong repository')
ops = 'refs/heads/ops/cumulative-source-transfer-20260912'
candidate = 'refs/heads/stage2/cumulative-language-20260912'
archive = 'refs/tags/archive/20260912/cumulative-source-transfer'
current = os.environ['GITHUB_SHA']
require(os.environ['GITHUB_REF'] == ops, 'wrong branch')
before = refs()
require(before.get(ops) == current, 'concurrent upload')
require(before.get('refs/heads/release/5.0.0rc6') == plan['base'], 'release changed; reconcile first')
require(before.get(candidate) in (None, plan['head']), 'candidate already differs')
require(before.get(archive) in (None, current), 'archive already differs')
parts = [root/f'{i:02}.b64' for i in range(plan['parts'])]
data = base64.b64decode(''.join(p.read_text() for p in parts), validate=True)
require(hashlib.sha256(data).hexdigest() == plan['payload_sha256'], 'payload checksum mismatch')
evidence = Path(os.environ['RUNNER_TEMP'])/'publication'
evidence.mkdir(exist_ok=True)
(evidence/'before.json').write_text(json.dumps(before, indent=2)+'\n')
if plan['format'] == 'git-pack':
    git('index-pack', '--fix-thin', '--stdin', data=data)
else:
    require(plan['format'] == 'records-v1-xz', 'unknown transfer format')
    if plan.get('derived_catalog'):
        # Recreate only transport bytes from the exact archived installed surface.
        # This is not regeneration of tests, expectations, or acceptance status.
        surface = json.loads((Path(os.environ['RUNNER_TEMP'])/'baseline-evidence/builtin-array-operations-surface.json').read_text())
        keys = ('pine_version','symbol_id','overload_id','call_form')
        document = {'schema_id':'openpine.callable_denominator.v1','denominator_kind':surface['denominator_kind'],'catalogs':surface['catalogs'],
                    'rows':[{**{k:r[k] for k in keys},'contract_hash':r['contract_hash']} for r in sorted(surface['rows'],key=lambda r:tuple(r[k] for k in keys))]}
        compact = lambda d: json.dumps(d,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
        document['content_hash'] = 'sha256:'+hashlib.sha256(compact(document)).hexdigest()
        store('blob',compact(document)+b'\n',plan['derived_catalog'])
    stream = io.BytesIO(lzma.decompress(data))
    def read(n):
        b = stream.read(n)
        require(len(b)==n, 'truncated object record')
        return b
    def integer():
        return struct.unpack('>I',read(4))[0]
    while marker := stream.read(1):
        kind = read(marker[0]).decode()
        identity = read(20).hex()
        mode = read(1)
        if mode == b'F':
            content = read(integer())
        else:
            require(mode == b'D' and kind == 'blob', 'invalid delta')
            base = read(20).hex()
            # Do not strip bytes: whitespace is part of the original blob.
            old = subprocess.check_output(['git','cat-file','blob',base]).splitlines(keepends=True)
            chunks = []
            for _ in range(integer()):
                mode = read(1)
                if mode == b'C':
                    lo, hi = integer(), integer()
                    require(0 <= lo <= hi <= len(old), 'invalid copy range')
                    chunks.append(b''.join(old[lo:hi]))
                else:
                    require(mode == b'I', 'invalid insertion')
                    chunks.append(read(integer()))
            content = b''.join(chunks)
        store(kind,content,identity)
require(git('rev-parse',plan['head']+'^{tree}').decode()==plan['tree'], 'final tree mismatch')
git('merge-base','--is-ancestor',plan['base'],plan['head'])
require(int(git('rev-list','--count',plan['base']+'..'+plan['head']))==plan['commits'], 'commit count mismatch')
git('fsck','--connectivity-only','--no-dangling',plan['head'])
# Publish only the new candidate and archive/delete this exact maintenance ref.
args = ['push','--atomic','--force-with-lease='+ops+':'+current]
updates = [':'+ops]
for ref, tip in ((candidate,plan['head']), (archive,current)):
    if ref not in before:
        args.append('--force-with-lease='+ref+':')
        updates.append(tip+':'+ref)
git(*args,'origin',*updates)
after = refs()
require(after.get(candidate)==plan['head'] and ops not in after and after.get(archive)==current, 'publication readback mismatch')
require(all(after.get(k)==v for k,v in before.items() if k.startswith('refs/heads/') and k!=ops), 'pre-existing branch changed')
receipt = {**{k:plan[k] for k in ('repo','base','head','tree','commits')},'candidate':candidate,'archive':archive,'release_changed':False,'functional_tests_run':False,'full_stage2_accepted':False}
for name, value in (('after',after),('receipt',receipt)):
    (evidence/(name+'.json')).write_text(json.dumps(value,indent=2)+'\n')
print(json.dumps(receipt,indent=2))
