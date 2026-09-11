"""Publish exact reviewed Git objects to a candidate branch, never a release.

This job verifies source preservation only. It does not run functional tests,
merge a release, change permissions, or assert completion of Stage 2.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

TARGET = 'refs/heads/stage2/qualifier-boundary-20260911'
RELEASE = 'refs/heads/release/5.0.0rc6'
UPLOAD = 'refs/heads/ops/publish-qualifiers-api-20260911'
ARCHIVE = 'refs/tags/archive/20260911/qualifier-api-upload'
BUNDLE_REF = 'refs/heads/work/target-qualifiers-20260911'


def git(*args: str) -> str:
    return subprocess.check_output(['git', *args], text=True).strip()


def refs() -> dict[str, str]:
    return {ref: sha for sha, ref in
            (line.split() for line in git('ls-remote', '--refs', 'origin').splitlines())}


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def main() -> None:
    plan = json.loads(Path('.github/qualifier-upload/plan.json').read_text())
    repo = plan['repository']
    if repo not in {'s7cret/pinelib', 's7cret/ast2python', 's7cret/openpine'}:
        raise ValueError('unexpected repository')
    if os.environ['GITHUB_REPOSITORY'] != repo or os.environ['GITHUB_REF'] != UPLOAD:
        raise ValueError('wrong execution context')
    head, base, tree = (plan[key] for key in ('head', 'base', 'tree'))
    if any(not re.fullmatch('[0-9a-f]{40}', value) for value in (head, base, tree)):
        raise ValueError('invalid source identity')
    data = Path('.github/qualifier-upload/source.bundle').read_bytes()
    if len(data) > 2000000 or hashlib.sha256(data).hexdigest() != plan['bundle_sha256']:
        raise ValueError('original bundle checksum mismatch')
    evidence = Path(os.environ['RUNNER_TEMP']) / 'qualifier-publication'
    evidence.mkdir()
    bundle = evidence / 'source.bundle'
    bundle.write_bytes(data)
    git('bundle', 'verify', str(bundle))
    git('fetch', '--no-tags', str(bundle), BUNDLE_REF)
    if git('rev-parse', 'FETCH_HEAD') != head or git('rev-parse', head + '^{tree}') != tree:
        raise ValueError('original source head/tree mismatch')
    commits = git('rev-list', '--reverse', base + '..' + head).splitlines()
    if commits != plan['commits']:
        raise ValueError('original commit series mismatch')
    previous = base
    for commit in commits:
        if git('rev-list', '--parents', '-n', '1', commit).split() != [commit, previous]:
            raise ValueError('unexpected commit parent')
        previous = commit
    git('merge-base', '--is-ancestor', base, head)
    git('diff', '--check', base, head)
    before = refs()
    upload_sha = os.environ['GITHUB_SHA']
    if before.get(RELEASE) != base or before.get(UPLOAD) != upload_sha:
        raise ValueError('release or upload changed; do not overwrite')
    if before.get(TARGET) not in (None, head) or ARCHIVE in before:
        raise ValueError('candidate/tag conflict; do not overwrite')
    write(evidence / 'before.json', before)
    write(evidence / 'plan.json', plan)
    args = ['push', '--atomic', '--force-with-lease=' + UPLOAD + ':' + upload_sha,
            '--force-with-lease=' + ARCHIVE + ':']
    updates = [upload_sha + ':' + ARCHIVE, ':' + UPLOAD]
    if TARGET not in before:
        args.append('--force-with-lease=' + TARGET + ':')
        updates.append(head + ':' + TARGET)
    # Empty expected values above mean create-only, not overwrite. Release refs
    # are deliberately absent from the entire atomic ref update.
    git(*args, 'origin', *updates)
    after = refs()
    expected = {key: value for key, value in before.items() if key != UPLOAD}
    expected.update({TARGET: head, ARCHIVE: upload_sha})
    write(evidence / 'after.json', after)
    if after != expected:
        raise ValueError('remote refs changed concurrently; inspect evidence, no rollback')
    receipt = {'repository': repo, 'published': True, 'candidate': TARGET,
               'head': head, 'tree': tree, 'commits': commits,
               'bundle_sha256': plan['bundle_sha256'], 'release_before': base,
               'release_after': after[RELEASE], 'release_changed': False,
               'merged': False, 'functional_tests_run': False,
               'full_stage2_accepted': False}
    write(evidence / 'receipt.json', receipt)
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
