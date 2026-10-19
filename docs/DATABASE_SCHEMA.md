# Central PostgreSQL Database Schema & Lifecycle State Machines

## 1. Relational Entities & Constraints

The central authority is a normalized PostgreSQL database managed through Alembic migrations.

### `users`
- `id` (UUID / BIGSERIAL, PRIMARY KEY)
- `username` (VARCHAR(64), UNIQUE NOT NULL)
- `password_hash` (VARCHAR(255), NOT NULL) — Argon2id
- `role` (VARCHAR(32), NOT NULL) — `ADMIN`, `MANAGER`, `ANNOTATOR`
- `is_active` (BOOLEAN, NOT NULL DEFAULT TRUE)
- `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL)
- `updated_at` (TIMESTAMP WITH TIME ZONE, NOT NULL)

### `devices`
- `id` (UUID / BIGSERIAL, PRIMARY KEY)
- `user_id` (BIGINT, REFERENCES `users(id)` ON DELETE RESTRICT)
- `device_identifier` (VARCHAR(128), UNIQUE NOT NULL)
- `name` (VARCHAR(128), NOT NULL)
- `token_hash` (VARCHAR(255), NOT NULL)
- `is_active` (BOOLEAN, NOT NULL DEFAULT TRUE)
- `last_seen_at` (TIMESTAMP WITH TIME ZONE)
- `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL)

### `datasets`
- `id` (UUID / BIGSERIAL, PRIMARY KEY)
- `name` (VARCHAR(128), UNIQUE NOT NULL)
- `remote_name` (VARCHAR(64), NOT NULL)
- `remote_path` (TEXT, NOT NULL)
- `catalog_state` (VARCHAR(32), NOT NULL DEFAULT 'IDLE') — `IDLE`, `SCANNING`, `READY`, `ERROR`
- `current_catalog_version` (VARCHAR(64))
- `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL)
- `updated_at` (TIMESTAMP WITH TIME ZONE, NOT NULL)

### `dataset_directories`
- `id` (BIGSERIAL, PRIMARY KEY)
- `dataset_id` (BIGINT, REFERENCES `datasets(id)` ON DELETE CASCADE)
- `normalized_path` (TEXT, NOT NULL)
- `parent_path` (TEXT)
- `direct_image_count` (INTEGER NOT NULL DEFAULT 0)
- `direct_json_count` (INTEGER NOT NULL DEFAULT 0)
- `direct_txt_count` (INTEGER NOT NULL DEFAULT 0)
- `direct_other_count` (INTEGER NOT NULL DEFAULT 0)
- `recursive_image_count` (INTEGER NOT NULL DEFAULT 0)
- `recursive_json_count` (INTEGER NOT NULL DEFAULT 0)
- `recursive_txt_count` (INTEGER NOT NULL DEFAULT 0)
- `recursive_other_count` (INTEGER NOT NULL DEFAULT 0)
- `updated_at` (TIMESTAMP WITH TIME ZONE, NOT NULL)
- **Constraint**: `UNIQUE(dataset_id, normalized_path)`

### `dataset_files`
- `id` (BIGSERIAL, PRIMARY KEY)
- `dataset_id` (BIGINT, REFERENCES `datasets(id)` ON DELETE CASCADE)
- `normalized_path` (TEXT, NOT NULL) — e.g., `folder/sub/img01.jpg`
- `basename` (VARCHAR(255), NOT NULL)
- `extension` (VARCHAR(32), NOT NULL) — lowercase without dot
- `category` (VARCHAR(32), NOT NULL) — `IMAGE`, `JSON`, `TXT`, `XML`, `OTHER`
- `size` (BIGINT NOT NULL DEFAULT 0)
- `remote_mtime` (TIMESTAMP WITH TIME ZONE)
- `fingerprint` (VARCHAR(64)) — hash or size+mtime
- `catalog_version` (VARCHAR(64), NOT NULL)
- `file_state` (VARCHAR(32), NOT NULL DEFAULT 'ELIGIBLE') — `ELIGIBLE`, `EXCLUDED`, `MISSING`, `CHANGED`
- `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL)
- `updated_at` (TIMESTAMP WITH TIME ZONE, NOT NULL)
- **Constraint**: `UNIQUE(dataset_id, normalized_path)`
- **Indexes**: `(dataset_id, category, file_state)`

### `assignments`
- `id` (BIGSERIAL, PRIMARY KEY)
- `dataset_id` (BIGINT, REFERENCES `datasets(id)` ON DELETE RESTRICT)
- `directory_scope` (TEXT, NOT NULL)
- `scope_type` (VARCHAR(16), NOT NULL) — `DIRECT`, `RECURSIVE`
- `annotator_id` (BIGINT, REFERENCES `users(id)` ON DELETE RESTRICT)
- `creator_id` (BIGINT, REFERENCES `users(id)` ON DELETE RESTRICT)
- `requested_count` (INTEGER NOT NULL)
- `allocated_count` (INTEGER NOT NULL)
- `status` (VARCHAR(32), NOT NULL DEFAULT 'PREPARING') — `PREPARING`, `READY`, `IN_PROGRESS`, `PAUSED`, `COMPLETED`, `CANCELLED`
- `catalog_version` (VARCHAR(64), NOT NULL)
- `workspace_path` (TEXT)
- `lease_generation` (BIGINT NOT NULL DEFAULT 1)
- `lease_expires_at` (TIMESTAMP WITH TIME ZONE)
- `idempotency_key` (VARCHAR(128), UNIQUE)
- `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL)
- `updated_at` (TIMESTAMP WITH TIME ZONE, NOT NULL)

### `assignment_items`
- `id` (BIGSERIAL, PRIMARY KEY)
- `assignment_id` (BIGINT, REFERENCES `assignments(id)` ON DELETE CASCADE)
- `file_id` (BIGINT, REFERENCES `dataset_files(id)` ON DELETE RESTRICT)
- `ordinal` (INTEGER NOT NULL)
- `item_state` (VARCHAR(32), NOT NULL DEFAULT 'PENDING') — see Lifecycle
- `error` (TEXT)
- `updated_at` (TIMESTAMP WITH TIME ZONE, NOT NULL)
- **Constraint**: `UNIQUE(assignment_id, file_id)`
- **Constraint**: `UNIQUE(assignment_id, ordinal)`

### `active_image_claims` (CRITICAL CONSTRAINT TABLE)
- `file_id` (BIGINT, PRIMARY KEY, REFERENCES `dataset_files(id)` ON DELETE CASCADE)
- `assignment_id` (BIGINT, NOT NULL, REFERENCES `assignments(id)` ON DELETE CASCADE)
- `annotator_id` (BIGINT, NOT NULL, REFERENCES `users(id)` ON DELETE RESTRICT)
- `claim_generation` (BIGINT NOT NULL DEFAULT 1)
- `claimed_at` (TIMESTAMP WITH TIME ZONE, NOT NULL)
- **Guarantee**: Primary key on `file_id` ensures at most **ONE** active claim across all users and assignments globally.

### `annotation_submissions`
- `id` (BIGSERIAL, PRIMARY KEY)
- `assignment_id` (BIGINT, REFERENCES `assignments(id)` ON DELETE RESTRICT)
- `file_id` (BIGINT, REFERENCES `dataset_files(id)` ON DELETE RESTRICT)
- `annotator_id` (BIGINT, REFERENCES `users(id)` ON DELETE RESTRICT)
- `ownership_generation` (BIGINT NOT NULL)
- `idempotency_key` (VARCHAR(128), UNIQUE NOT NULL)
- `content_hash` (VARCHAR(64), NOT NULL)
- `validation_state` (VARCHAR(32), NOT NULL) — `VALID`, `INVALID_SYNTAX`, `INVALID_SCHEMA`, `CONFLICT`
- `error` (TEXT)
- `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL)

### `background_declarations`
- `id` (BIGSERIAL, PRIMARY KEY)
- `assignment_id` (BIGINT, REFERENCES `assignments(id)` ON DELETE RESTRICT)
- `file_id` (BIGINT, REFERENCES `dataset_files(id)` ON DELETE RESTRICT)
- `annotator_id` (BIGINT, REFERENCES `users(id)` ON DELETE RESTRICT)
- `reason` (TEXT)
- `approval_state` (VARCHAR(32), NOT NULL DEFAULT 'PENDING_APPROVAL') — `PENDING_APPROVAL`, `APPROVED`, `REJECTED`
- `approved_by` (BIGINT, REFERENCES `users(id)`)
- `approved_at` (TIMESTAMP WITH TIME ZONE)
- `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL)

### `sync_jobs` (POSTGRESQL-BACKED TASK QUEUE)
- `id` (BIGSERIAL, PRIMARY KEY)
- `job_type` (VARCHAR(64), NOT NULL) — `CATALOG_SCAN`, `PREPARE_ASSIGNMENT`, `UPLOAD_ANNOTATION`, `CLEANUP_EXPIRED`
- `status` (VARCHAR(32), NOT NULL DEFAULT 'QUEUED') — `QUEUED`, `CLAIMED`, `RETRYING`, `FAILED`, `COMPLETED`
- `payload` (JSONB NOT NULL DEFAULT '{}'::jsonb)
- `attempts` (INTEGER NOT NULL DEFAULT 0)
- `max_retries` (INTEGER NOT NULL DEFAULT 5)
- `error` (TEXT)
- `next_attempt_at` (TIMESTAMP WITH TIME ZONE, NOT NULL DEFAULT NOW())
- `claimed_worker` (VARCHAR(64))
- `claimed_at` (TIMESTAMP WITH TIME ZONE)
- `idempotency_key` (VARCHAR(128), UNIQUE)
- `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL)
- `updated_at` (TIMESTAMP WITH TIME ZONE, NOT NULL)
- **Index**: `(status, next_attempt_at)`

### `audit_events`
- `id` (BIGSERIAL, PRIMARY KEY)
- `user_id` (BIGINT, REFERENCES `users(id)`)
- `action` (VARCHAR(64), NOT NULL)
- `resource_type` (VARCHAR(64), NOT NULL)
- `resource_id` (VARCHAR(64), NOT NULL)
- `details` (JSONB NOT NULL DEFAULT '{}'::jsonb)
- `ip_address` (VARCHAR(45))
- `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL)

---

## 2. State Machines & Allowed Lifecycle Transitions

### Assignment Lifecycle
```
[CREATING]
    │  (Atomic transaction commits N reserved items)
    ▼
[PREPARING]
    │  (sync_worker completes staging & manifest verification)
    ▼
[READY] ◄───────────────┐
    │                   │
    │ (Agent heartbeat  │ (Manager resumes
    │  & begins batch)  │  paused assignment)
    ▼                   │
[IN_PROGRESS] ──────────┼───────────────┐
    │                   │               │
    │ (Manager pauses)  │               │ (All items terminal)
    ▼                   │               ▼
 [PAUSED] ──────────────┘          [COMPLETED]
    │
    │ (Manager cancels)
    ▼
[CANCELLED] (Claims released, history preserved)
```

### Assignment Item Lifecycle
```
[PENDING]
    │ (Agent requests batch download)
    ▼
[DOWNLOADING]
    │ (Agent confirms local batch ready)
    ▼
[ANNOTATING]
    │
    ├── (Annotator submits JSON) ──► [VALIDATING]
    │                                     │
    │                                     ├── (Syntax/Schema Error) ──► [FAILED]
    │                                     ├── (Remote modified)     ──► [CONFLICT]
    │                                     └── (Valid)               ──► [UPLOAD_PENDING]
    │                                                                          │
    │                                                                          ▼
    │                                                                     [UPLOADING]
    │                                                                          │
    │                                                                          ▼
    │                                                                 [VERIFIED_COMPLETE]
    │
    └── (Explicit background declaration) ──► [BACKGROUND_REVIEW]
                                                    │
                                                    ├── (Manager approves) ──► [VERIFIED_COMPLETE]
                                                    └── (Manager rejects)  ──► [ANNOTATING]
```

