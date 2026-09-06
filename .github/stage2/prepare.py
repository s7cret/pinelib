"""Encode only transport; keep reviewed patch/tree/commit hashes mandatory."""
import base64, gzip, hashlib, json
from pathlib import Path
import urllib.request
root=Path(__file__).resolve().parent
plan=json.loads((root/'plan.json').read_text())
patch=b''.join(p.read_bytes() for p in sorted(root.glob('diff.*.txt')))
if hashlib.sha256(patch).hexdigest()!=plan['patch_sha256']:
    raise ValueError('readable patch checksum mismatch')
compressed=gzip.compress(patch,mtime=0)
encoded=base64.b64encode(compressed)
name='source.001.b64'
(root/name).write_bytes(encoded)
plan['compressed_sha256']=hashlib.sha256(compressed).hexdigest()
plan['chunks']={name:hashlib.sha1(b'blob '+str(len(encoded)).encode()+b'\0'+encoded).hexdigest()}
(root/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
url='https://raw.githubusercontent.com/s7cret/pine2ast/894efd45b7779d393ac43199f1fb3b13b1a28efd/.github/stage2/restore.py'
with urllib.request.urlopen(url,timeout=30) as response:
    helper=response.read(100000)
if hashlib.sha256(helper).hexdigest()!='4ed3a05f0ac6754a079d266d4cd8c68eb31a028f65c507df7384c5aafffb8a10':
    raise ValueError('publisher helper checksum mismatch')
(root/'restore.py').write_bytes(helper)
