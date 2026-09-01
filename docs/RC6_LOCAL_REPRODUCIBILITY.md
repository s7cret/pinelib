# RC6 local reproducibility commands

Run all commands from the source root with a selected Python 3.11–3.13 interpreter.

## Forbidden-source scan

The scan root is deliberately the package tree, not the delivery/source root. The JSON report records this exact canonical invocation in its `command` and `scan_root` fields.

```bash
python tools/forbidden_scan.py --root pinelib > forbidden-scan.json
```

A zero exit status and `"pass": true` are both required.

## Deterministic source distribution

```bash
python tools/build_deterministic_sdist.py \
  --root . \
  --output dist/pinelib-5.0.0rc6.tar.gz \
  --epoch 1700000000
sha256sum dist/pinelib-5.0.0rc6.tar.gz
```

The builder rejects symlinks, emits only regular files in sorted path order, strips host uid/gid/name metadata, normalizes modes to `0644` or `0755`, and binds both tar and gzip timestamps to the supplied epoch. Generated build/cache directories are excluded.

To prove reproducibility, run the command twice from byte-identical source trees and compare SHA-256 digests. To prove usability, install the resulting archive into a clean environment and run `pip check` plus the test suite.
