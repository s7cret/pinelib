"""Reverse only the reviewed 2026-09-18 layer; all earlier locks stay immutable."""
import json
import hashlib
from copy import deepcopy
from importlib.resources import files


def digest(value):
    return 'sha256:' + hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def restore_history_restoration(payload):
    """Remove only the exact restored RC6 history ABI, not builtin rows.

    Endpoints pin the reviewed additive contract; resealing a mutation cannot
    authorize it. The previous audit lock is never rewritten.
    """
    before = 'sha256:edd7499240e0ca738379a102569c867172c4c1ad3044916c485d70411814b685'
    after = 'sha256:3cc0e1b96e6f2822de25e2d097d26aaf754cae246705cab9392bad705f822dfb'
    assert digest({k: v for k, v in payload.items() if k != 'content_hash'}) == payload['content_hash']
    assert payload['content_hash'] in {before, after}
    restored = deepcopy(payload)
    if payload['content_hash'] == before:
        return restored
    del restored['compiled_history_reservation']
    operations = restored['compiler_operations']
    removed = [row for row in operations if row['name'] == 'state.reserve_history.v1']
    assert len(removed) == 1
    restored['compiler_operations'] = [row for row in operations if row['name'] != 'state.reserve_history.v1']
    restored['content_hash'] = before
    assert digest({k: v for k, v in restored.items() if k != 'content_hash'}) == before
    return restored


def restore_audit_repair(payload, name):
    if name == 'target_manifest.json' and 'compiled_history_reservation' in payload:
        payload = restore_history_restoration(payload)
    lock=json.loads(files('pinelib.abi').joinpath('stage2_audit_repair_delta_lock.json').read_text())
    assert digest({k:v for k,v in lock.items() if k!='content_hash'}) == lock['content_hash']
    item=lock['artifacts'][name]
    if payload.get('content_hash') == item['before_content_hash']:
        assert digest({k:v for k,v in payload.items() if k!='content_hash'}) == payload['content_hash']
        return deepcopy(payload)
    assert payload['content_hash'] == item['after_content_hash']
    assert digest({k:v for k,v in payload.items() if k!='content_hash'}) == payload['content_hash']
    assert {k:v for k,v in payload.items() if k!='rows'} == item['after_top_level']
    key=lambda row:'|'.join(row[n] for n in ('category','name','symbol_id'))
    rows={key(row):row for row in payload['rows']}
    assert len(rows)==len(payload['rows'])==item['row_count']
    changes={row['key']:row for row in item['changes']}
    assert set(changes)<=set(rows)
    assert digest([rows[k] for k in sorted(rows) if k not in changes])==item['unchanged_rows_hash']
    for k,row in changes.items():
        assert rows[k]==row['after']
        rows[k]=deepcopy(row['before'])
    restored=deepcopy(item['before_top_level'])
    restored['rows']=[rows[key(row)] for row in payload['rows']]
    assert digest({k:v for k,v in restored.items() if k!='content_hash'})==item['before_content_hash']
    return restored
