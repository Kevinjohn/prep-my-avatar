# Local pilot bank boundary

The bank is separate from corpus preparation and provider execution. Its API is
scoped to the current local user's character dataset at
`/api/dataset/<id>/pilot-bank`. The existing application CSRF boundary applies to
mutations. No endpoint makes a provider request, fetches a URL or loads model code.

| Operation | Route beneath the bank |
| --- | --- |
| Read records, completed exports, recipe starting points and tool availability | `GET` at the bank root |
| Capture an attempt and immutable inputs/settings | `POST /attempts` |
| Reconcile status, request ID, cost, errors, notes and control evidence | `PATCH /attempts/<attempt>` |
| Import a local returned file | `POST /attempts/<attempt>/files` (multipart) |
| Read/download an imported file | `GET /attempts/<attempt>/files/<file>` |
| Update asset compatibility and rights/storage/backup evidence | `PATCH /attempts/<attempt>/files/<file>/metadata` |
| Record an individual output review | `POST /attempts/<attempt>/files/<file>/review` |
| Create and inspect a silent derivative | `POST /attempts/<attempt>/files/<file>/silent` |
| Read pinned reference/evaluation images for comparison | `GET /exports/<revision>/files/<relative>?manifest_sha256=<hash>` |
| Download the bank and linked export evidence | `GET /download` |

Mutations carry the last observed integer `version`; multipart imports carry it
as a form field alongside `file` and JSON `metadata`. A stale version is a conflict,
not permission to overwrite or replay a request. Successful mutations return a
new bank snapshot. Attempt IDs and file IDs are generated locally.

## Immutable inputs and retained evidence

An attempt pins its export revision and manifest hash, process, recipe/settings,
ordered reference paths/hashes/purposes, optional first-frame asset and any learned
asset inputs. Generation references must be reference entries in that export;
held-out entries cannot become inputs. First frames must be accepted stills from
the same subject scope. Recipe changes create another attempt; reconciliation
does not rewrite the captured inputs.

Each imported file retains exact original bytes and a SHA-256. File kind describes
its storage/media role; model/base and learned asset-kind declarations describe
compatibility separately. Declared compatibility is checked before reuse, but is
not evidence of real loading or application. Configuration, rights/storage/backup
records and paired-control evidence belong with the relevant attempt or asset.
None of those records is a place for credentials or signed URLs.

Reviews apply to one output, not the entire attempt. Video silence is derived from
server-side inspection of the exact stored bytes. Accepted clips also require a
human likeness and whole-clip review. A silent derivative retains its parent hash
and starts with its own unaccepted review.

## Storage, limits and recovery

Bank records and generated file names live in a private dataset-local directory.
Writes publish complete optimistic revisions; interrupted staging files are not
served as outputs. Reads/downloads verify recorded hashes, and path boundaries
reject traversal and symlinks. File contents are treated as data; weights are never
deserialised as executable objects.

The API returns local file limits. The application's overall upload limit can
further constrain a request. Large media/model files and export archives are
hashed and copied in chunks. FFmpeg/FFprobe are optional bounded local subprocesses
with network protocols excluded. A missing tool does not disable still-image or
asset-record workflows.

The dedicated ZIP includes retained bank media/records and linked export evidence.
It is distinct from ordinary corpus backup and is not fed to the dataset-import
route. Dataset deletion remains within the existing recoverable Trash lifecycle.

## Extension and verification

Manual generation recipe starting points are maintained separately from training
export formatters. Their model, provider, endpoint, capability declarations and
settings are captured with the attempt. Editing a definition does not reinterpret
old records. Adding a provider execution adapter is a separate responsibility;
this bank has no SDK, request scheduler, credential store or paid health check.

Local synthetic fixtures verify storage, roles, compatibility, concurrency,
inspection failure and browser lifecycle behaviour. Real service acceptance,
private provider loading, likeness and useful movement must still be evaluated in
actual authorised pilots. Passing these local contracts never sets those claims
true automatically.
