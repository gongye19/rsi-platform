# Vendored harness documentation cache

The Harness Query stage feeds official harness documentation to the analyst
models as `local_documentation` evidence. Fetching it live would make a run
depend on the network and on whatever the upstream docs say that day, so the
exact snapshots used by the reported experiments are frozen here.

| Directory | Upstream | Snapshot |
| --- | --- | --- |
| `opencode/` | official repository `v1.18.32` (see `opencode/SOURCE.txt`) | 11 pages from the exact runtime tag, fetched 2026-11-24 |
| `codex/` | <https://developers.openai.com/codex/config-reference> | fetched 2026-06-09 |

Pi documentation is *not* vendored: it ships inside the `pi-coding-agent` npm
package and is read from
`<repo>/.pi-agent/node_modules/@earendil-works/pi-coding-agent/docs/`.
Install the pi runtime (see the README) to make that evidence available.

To refresh a snapshot, re-fetch the pages listed in the corresponding
`SOURCE.txt` and record the new version and date there.

OpenCode page URLs and SHA-256 hashes are recorded in `opencode/SOURCE-1.18.32.json`.
The older `config.schema.json` remains archived from 2026-06-06 and is excluded
from current OpenCode query evidence; the tagged configuration docs and actual
runtime probes provide the current configuration evidence.
