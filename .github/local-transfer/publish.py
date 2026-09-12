"""Restore exact source history from hash-bound transport; never update releases."""
import base64
import hashlib
import json
import lzma
import os
from pathlib import Path
import subprocess
import sys


def git(*args, data=None):
    return subprocess.check_output(['git', *args], input=data, stderr=subprocess.PIPE)


def text(*args):
    return git(*args).decode().strip()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False).encode()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def catalogue_lock(parser_root):
    sys.path.insert(0, str(parser_root))
    from pine2ast.catalog import CatalogRepository
    from pine2ast.semantic.signatures import SignatureResolver
    from pine2ast.versioning import PineVersionResolver
    def digest(value):
        return 'sha256:' + hashlib.sha256(canonical(value)).hexdigest()
    repo = CatalogRepository.default()
    rows = {}
    for version in range(1, 7):
        resolver = SignatureResolver(version_context=PineVersionResolver(
            repo.identity_tuple).resolve(f'//@version={version}\n').context)
        for category in ('functions', 'methods'):
            for spelling, entry in repo.view(version).get(category, {}).items():
                form = ('METHOD' if category == 'methods' else
                        'NAMESPACE_FUNCTION' if '.' in spelling else 'FUNCTION')
                for candidate in resolver.candidate_entries(entry):
                    key = (version, entry['symbol_id'], candidate['__overload_id'], form)
                    value = digest({k: candidate.get(k, [] if k == 'parameters' else None)
                        for k in ('parameters', 'returns', 'return_qualifier', 'receiver_type')})
                    require(key not in rows or rows[key] == value, 'conflicting catalogue row')
                    rows[key] = value
    body = {'schema_id': 'openpine.callable_denominator.v1',
        'denominator_kind': 'all_installed_frontend_callable_signatures',
        'catalogs': {str(v): repo.identity(v).catalog_hash for v in range(1, 7)},
        'rows': [{**dict(zip(('pine_version','symbol_id','overload_id','call_form'), k)),
                  'contract_hash': rows[k]} for k in sorted(rows)]}
    body['content_hash'] = digest(body)
    return canonical(body) + b'\n'


def restore(payload, parser_root=None):
    generated = catalogue_lock(parser_root) if payload['catalogue_lock_recipe'] else None
    parent = payload['base']
    for entry in payload['commits']:
        raw = entry['commit'].encode()
        headers = raw.split(b'\n\n', 1)[0].splitlines()
        parents = [line[7:].decode() for line in headers if line.startswith(b'parent ')]
        require(parents == [parent], 'unexpected source ancestry')
        expected_tree = next(line[5:].decode() for line in headers if line.startswith(b'tree '))
        git('read-tree', parent)
        if entry['patch']:
            git('apply', '--cached', '--binary', '-', data=entry['patch'].encode())
        if generated is not None:
            blob = git('hash-object', '-w', '--stdin', data=generated).decode().strip()
            git('update-index', '--add', '--cacheinfo',
                '100644,' + blob + ',verification/stage2-callable-lock.json')
        require(text('write-tree') == expected_tree, 'source tree differs from archived commit')
        actual = git('hash-object', '-t', 'commit', '-w', '--stdin', data=raw).decode().strip()
        require(actual == entry['sha'], 'original commit identity mismatch')
        parent = actual
    require(parent == payload['head'], 'head mismatch')
    require(text('rev-parse', parent + '^{tree}') == payload['tree'], 'final tree mismatch')
    require(int(text('rev-list','--count',payload['base']+'..'+parent)) == len(payload['commits']),
            'commit inventory mismatch')
    return parent


def refs():
    return {ref: sha for sha, ref in (line.split() for line in
            text('ls-remote', '--refs', 'origin').splitlines())}


def main():
    root = Path('.github/local-transfer')
    config = json.loads((root / 'config.json').read_text())
    names = [f'part{i:03}.b64' for i in range(config['parts'])]
    require(sorted(p.name for p in (root / 'parts').iterdir()) == names, 'part inventory mismatch')
    encoded = ''.join((root / 'parts' / name).read_text() for name in names)
    packed = base64.b64decode(encoded, validate=True)
    require(hashlib.sha256(packed).hexdigest() == config['sha256'], 'transport checksum mismatch')
    payload = json.loads(lzma.decompress(packed, memlimit=128*1024*1024))
    require(payload['repository'] == os.environ['GITHUB_REPOSITORY'], 'wrong repository')
    before = refs()
    release = 'refs/heads/release/5.0.0rc6'
    require(before.get(release) == payload['base'], 'release advanced; do not overwrite newer work')
    parser = None
    if payload['catalogue_lock_recipe']:
        parser = Path(os.environ['RUNNER_TEMP']) / 'locked-parser'
        subprocess.run(['git','clone','--quiet','https://github.com/s7cret/pine2ast.git',str(parser)],check=True)
        subprocess.run(['git','-C',str(parser),'checkout','--detach',
                        'bac8db4a012f37aa6d50770c2cc1be3cbe047c9b'],check=True)
    head = restore(payload, parser)
    output = Path(os.environ['RUNNER_TEMP']) / 'publication'
    output.mkdir(exist_ok=True)
    git('update-ref','refs/heads/restored-archive',head)
    git('bundle','create',str(output/'original-history.bundle'),
        'refs/heads/restored-archive','^'+payload['base'])
    receipt = {k:payload[k] for k in ('repository','base','head','tree')}
    receipt.update(original_commits=[e['sha'] for e in payload['commits']],
                   source_restore_verified=True, release_changed=False,
                   tests_run=False, full_stage2_accepted=False)
    (output/'restore.json').write_bytes(canonical(receipt)+b'\n')
    branch = 'refs/heads/stage2/cumulative-local-20260912'
    require(before.get(branch) in (None,head), 'candidate branch already contains other work')
    if branch not in before:
        result = subprocess.run(['git','push','--porcelain','origin',head+':'+branch],capture_output=True,text=True)
        (output/'push.log').write_text(result.stdout+result.stderr)
        if result.returncode:
            print(result.stdout+result.stderr)
            raise RuntimeError('source restored exactly but candidate push was rejected')
    after = refs()
    require(after.get(branch)==head, 'candidate readback mismatch')
    for ref, value in before.items():
        require(after.get(ref)==value, 'existing remote ref changed during publication: '+ref)
    receipt['candidate_branch']=branch
    receipt['published']=True
    (output/'publication.json').write_bytes(canonical(receipt)+b'\n')
    print(json.dumps(receipt,indent=2))


if __name__ == '__main__':
    main()
