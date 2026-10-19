# End-to-end workflow

```text
                         CENTRAL NAS
                     complete dataset
                           |
                           | one-time metadata catalog
                           v
                 +-----------------------+
                 | Local SQLite catalog  |
                 +-----------+-----------+
                             |
                     select next <=200
                             |
                             v
                 +-----------------------+
                 | Controlled Rclone/SFTP |
                 | 1 transfer / 1 checker |
                 | rate limited           |
                 +-----------+-----------+
                             |
                             v
                 +-----------------------+
                 | LOCAL CURRENT BATCH   |
                 | batch_000001          |
                 | images + JSONs        |
                 +-----------+-----------+
                             |
                             v
                       XAnyLabeling
                             |
                       local edits
                             |
                             v
                 +-----------------------+
                 | Local JSON + backup   |
                 | SQLite state          |
                 +-----------+-----------+
                             |
                     all 200 JSONs stable
                             |
                             v
                 +-----------------------+
                 | Remote conflict check |
                 +-----------+-----------+
                             |
                             v
                 +-----------------------+
                 | Rclone upload JSON    |
                 | only / controlled     |
                 +-----------+-----------+
                             |
                             v
                           NAS
                             |
                         verify
                             |
                             v
                 close XAnyLabeling batch
                             |
                             v
                 remove local batch
                             |
                             v
                 download next <=200
```

## States

```text
DOWNLOADING
    -> ANNOTATING
    -> UPLOAD_PENDING
    -> SYNCED
    -> CLEANED
```

Failures return to a persisted state rather than deleting data.

```text
DOWNLOAD failure -> DOWNLOADING + backoff
UPLOAD failure   -> UPLOAD_PENDING + backoff
Conflict         -> CONFLICT
```

`CONFLICT` requires an explicit resolution.

## Why this is smooth

The foreground application only sees local storage. The slow part of the workflow is moved outside the GUI:

```text
XAnyLabeling critical path: local disk only
NAS critical path: background batch transfer only
```


## Configuration

All runtime settings come from the single project-level `config.env`. Do not edit generated systemd units for normal changes. The manager reads `config.env` on every run.


## Unannotated/background-image approval

A batch may intentionally contain images with no annotation JSON. After XAnyLabeling is closed, the manager counts: total images, valid annotations, unannotated images, invalid JSON files and conflicts.

If every image has a valid annotation, the batch proceeds automatically to upload.

If some images have no annotation but there are no invalid JSON files, the batch enters `AWAITING_APPROVAL`. The interactive annotation launcher shows the count and asks whether to proceed.

- **Yes:** upload only the annotation JSONs that exist; unannotated images are accepted as intentional background/negative images; then verify and move to the next batch.
- **No:** do not upload or delete anything; keep the batch locally and reopen the same batch later.

Invalid JSON files are never silently treated as background images; they require correction first.
