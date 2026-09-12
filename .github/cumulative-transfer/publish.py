"""Restore exact original source commits; publish candidate, never a release."""
from pathlib import Path
import hashlib
import json
import lzma
import os
import subprocess


def git(*args, data=None):
    return subprocess.check_output(['git', *args], input=data).decode().strip()


def refs():
    return {ref: sha for sha, ref in (line.split() for line in git('ls-remote', '--refs', 'origin').splitlines())}


def require(ok, message):
    if not ok:
        raise SystemExit(message)


plan = json.loads(Path('.github/cumulative-transfer/plan.json').read_text())
require(os.environ['GITHUB_REPOSITORY'] == plan['repository'], 'wrong repository')
ops = 'refs/heads/ops/stage2-cumulative-upload-20260912'
require(os.environ['GITHUB_REF'] == ops, 'wrong upload ref')
sha = os.environ['GITHUB_SHA']
candidate = 'refs/heads/stage2/cumulative-language-20260912'
archive = 'refs/tags/archive/20260912/cumulative-upload'
before = refs()
require(before.get(ops) == sha, 'upload ref advanced')
require(before.get('refs/heads/release/5.0.0rc6') == plan['base'], 'release advanced; reconcile first')
require(before.get(candidate) in (None, plan['head']), 'candidate already differs')
require(before.get(archive) in (None, sha), 'archive tag already differs')
compressed = Path('.github/cumulative-transfer/source.pack.xz').read_bytes()
require(hashlib.sha256(compressed).hexdigest() == plan['pack_xz_sha256'], 'transport checksum mismatch')
pack = lzma.decompress(compressed, memlimit=268435456)
require(hashlib.sha256(pack).hexdigest() == plan['pack_sha256'], 'uncompressed pack checksum mismatch')
git('index-pack', '--stdin', '--fix-thin', data=pack)
require(git('rev-parse', plan['head'] + '^{tree}') == plan['tree'], 'original tree differs')
git('merge-base', '--is-ancestor', plan['base'], plan['head'])
require(int(git('rev-list', '--count', plan['base'] + '..' + plan['head'])) == plan['commits'], 'original commit count differs')
require(git('rev-list', '--reverse', plan['base'] + '..' + plan['head']).splitlines() == plan['commit_ids'], 'original commit identities differ')
evidence = Path(os.environ['RUNNER_TEMP']) / 'publication'
evidence.mkdir(exist_ok=True)
(evidence / 'before.json').write_text(json.dumps(before, indent=2) + '\n')
(evidence / 'plan.json').write_text(json.dumps(plan, indent=2) + '\n')
updates = []
leases = ['--force-with-lease=' + ops + ':' + sha]
if candidate not in before:
    leases.append('--force-with-lease=' + candidate + ':')
    updates.append(plan['head'] + ':' + candidate)
if archive not in before:
    leases.append('--force-with-lease=' + archive + ':')
    updates.append(sha + ':' + archive)
updates.append(':' + ops)
git('push', '--atomic', *leases, 'origin', *updates)
after = refs()
expected = {k: v for k, v in before.items() if k != ops}
expected.update({candidate: plan['head'], archive: sha})
(evidence / 'after.json').write_text(json.dumps(after, indent=2) + '\n')
require(after == expected, 'remote ref readback differs')
receipt = dict(plan, publication='verified', release_changed=False, tests_run=False, full_stage2_accepted=False)
(evidence / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt, indent=2))
