# Implementation Plan: Centralized Multi-Computer Production System

## Baseline Inspection & Test Status
- **Date**: 2026-10-14
- **Environment**: Linux (Ubuntu 24.04 LTS), Python 3.12.3, Docker 29.5.3, Docker Compose v5.1.4
- **Baseline Test Command**: `bash scripts/test.sh`
- **Baseline Execution Result**:
  - Ran 8 unit tests across `tests/test_desktop_app.py` and `tests/test_manager.py`.
  - All 8 tests passed in 0.465s (`OK`).
  - Baseline tests verify legacy single-PC SQLite state transitions, config round-trips, rclone mock download/upload/cleanup, conflict prevention, and unannotated image confirmation policy.

## Implementation Phases & Dependency Graph

### Phase 1: Baseline Inspection, Planning, Env/Security Cleanup & Project Structure
- **Objective**: Baseline verification, documentation, project layout, `.gitignore` / `.dockerignore` updates, security boundaries.
- **Dependencies**: None.
- **Acceptance Criteria**:
  - Baseline tests pass and are documented.
  - Complete architecture, schema, migration/rollback, and implementation plan documents written.
  - Sensitive files (`.env`, `secrets/`, local databases, logs) ignored in Git and Docker contexts.
  - Legacy workflow and scripts untouched and functioning.

### Phase 2: PostgreSQL Container, Docker Compose, Schema Migrations & Auth/RBAC
- **Objective**: Containerized PostgreSQL setup, Alembic migrations, database models, Argon2id authentication, RBAC, bootstrap CLI.
- **Dependencies**: Phase 1.
- **Acceptance Criteria**:
  - `docker-compose.yml` configures `controller`, `postgres`, `sync_worker`, `migrate`.
  - Setup script generates cryptographically secure secrets (`APP_SECRET_KEY`, `POSTGRES_PASSWORD`, `BOOTSTRAP_ADMIN_TOKEN`) with restrictive file permissions (chmod 600).
  - PostgreSQL health check passes; Alembic migrations execute cleanly.
  - User and device roles (`ADMIN`, `MANAGER`, `ANNOTATOR`) enforced via server-side dependencies.
  - CLI `python -m controller.app.cli create-admin` creates initial administrator with hidden password prompt and password hashing.

### Phase 3: NAS Inventory & Safe Catalog Versioning
- **Objective**: Centralized catalog adapter supporting Rclone and local/mock adapters, recursive folder traversal, case-insensitive classification of image/sidecar formats, snapshot versioning.
- **Dependencies**: Phase 2.
- **Acceptance Criteria**:
  - Discovers and categorizes file formats: images (`jpg`, `jpeg`, `png`, `bmp`, `webp`, `tif`, `tiff`), JSON, TXT, XML, others.
  - Distinguishes direct versus recursive counts per directory.
  - Path normalization protects against traversal (`..`, absolute paths, symlink escapes).
  - Generates immutable catalog snapshot versions and fingerprints.
  - Detects additions, modifications, renames, and removals.

### Phase 4: Atomic Count-Based Assignment & Active Image Claims
- **Objective**: Manager-directed atomic image allocation with PostgreSQL row locks and unique constraints.
- **Dependencies**: Phase 3.
- **Acceptance Criteria**:
  - Manager specifies dataset, folder/subtree scope (direct vs recursive), annotator, and exact count $N$.
  - Atomic transaction uses `SELECT ... FOR UPDATE SKIP LOCKED` and unique database constraints on active claims.
  - All-or-nothing guarantee: allocates exactly $N$ or rolls back completely (no partial allocations).
  - Idempotent request handling via client/request tokens.
  - Concurrent overlapping test: 7,000 eligible images; Assign 4,000 to A -> A gets 4,000; Attempt 4,000 for B -> rejected, 0 partial, 3,000 remain available; Assign 2,000 to B -> B gets 2,000, 1,000 remain available.
  - Concurrency verified with parallel threads/connections against PostgreSQL.

### Phase 5: Assignment Workspace Staging Worker
- **Objective**: Durable copy/staging to NAS assignment workspace without moving or modifying canonical source images.
- **Dependencies**: Phase 4.
- **Acceptance Criteria**:
  - Source dataset remains strictly read-only.
  - Selected images staged to `<WORKSPACE_ROOT>/<annotator_id>/assignment_<id>/` with `manifest.json`, `images/`, `annotations/`, `metadata/`.
  - Staging worker verifies count, relative paths, sizes, and hashes before marking assignment `READY`.
  - Partial transfer or network failure keeps assignment non-ready and retries with exponential backoff.

### Phase 6: Annotator Desktop Agent
- **Objective**: Secure client agent communicating with central controller over authenticated REST APIs.
- **Dependencies**: Phase 5.
- **Acceptance Criteria**:
  - Annotator logs in and receives authorized assignment manifest.
  - Downloads local working batches (default 100 images) to local SSD.
  - Launches XAnyLabeling against local SSD directory (`current/`).
  - Maintains local SQLite cache and backup store; never serves as global authority.
  - Validates ownership generation and fencing token; rejects stale/revoked assignments.

### Phase 7: Annotation Validation, Remote Sync & Conflict Management
- **Objective**: Structured validation of submitted annotations, controlled upload, remote verification, and explicit background declarations.
- **Dependencies**: Phase 6.
- **Acceptance Criteria**:
  - Validates JSON structure, coordinates, and image association against XAnyLabeling format.
  - Detects remote conflicts before uploading; never silently overwrites existing annotations.
  - Enforces explicit declaration for unannotated/background images; no empty JSON files fabricated.
  - Controlled upload to designated location and verification of size/hash before marking `VERIFIED_COMPLETE`.
  - Cleans local batch files only after verified durable storage.

### Phase 8: Web Dashboard & Monitoring
- **Objective**: Server-rendered admin web dashboard for dataset explorer, user/device management, assignment wizard, sync job monitor, and audit trail.
- **Dependencies**: Phases 2–7.
- **Acceptance Criteria**:
  - Responsive web interface with zero external CDN dependencies.
  - Role-based views: Overview, Dataset Explorer (with direct/recursive counts), User/Device Management, Assignment Wizard, Sync Job Queue, Review Queue, Audit Trail.
  - Disabling an annotator pauses their work without deleting history.

### Phase 9: Security Hardening, Backup/Restore, Operations
- **Objective**: Production operational readiness, backup/restore scripts, doctor/health CLI.
- **Dependencies**: Phase 8.
- **Acceptance Criteria**:
  - PostgreSQL logical backup (`pg_dump`) and restore procedures verified.
  - Liveness (`/healthz`) and readiness (`/readyz`) endpoints.
  - Secure headers, rate-limiting on authentication, strict input validation.
  - Doctor command validates configuration, database connection, storage access.

### Phase 10: Verification, Test Gates & Final Delivery
- **Objective**: Comprehensive test suite run (legacy unit tests, new unit/integration tests, PostgreSQL concurrency tests), end-to-end simulated lifecycle.
- **Dependencies**: Phases 1–9.
- **Acceptance Criteria**:
  - Legacy `bash scripts/test.sh` passes 100%.
  - Pytest suite passes all catalog, assignment, workspace, transfer, security, and lifecycle tests.
  - Multi-threaded PostgreSQL concurrency test passes.
  - Complete documentation and operational guide delivered.

## Phase Execution & Verification Records

### 1. Legacy Unit Tests
- **Command**: `bash scripts/test.sh`
- **Result**: `Ran 8 tests in 0.448s - OK`
- **Details**:
  - `tests/test_desktop_app.py`: State transitions, active batch detection, manifest parsing, unannotated image confirmation policy.
  - `tests/test_manager.py`: Config round-trips, conflict prevention, mock rclone download/upload/cleanup, local SQLite isolation.

### 2. Central Platform Pytest Suite
- **Command**: `bash scripts/test_central.sh` (`.venv/bin/pytest tests_central -v`)
- **Result**: `19 passed in 9.33s`
- **Details**:
  - `test_catalog.py`: Path traversal sanitization, recursive vs direct directory counts, case-insensitive format detection (JPG/PNG/BMP/WEBP/TIFF/JSON/TXT/XML), catalog snapshot fingerprinting.
  - `test_assignment_concurrency.py`: Single-owner claim enforcement, count-based atomic allocation, all-or-nothing rollback on insufficient eligible files, idempotency tokens.
  - `test_workspace_staging.py`: Non-destructive staging copy to `<WORKSPACE_ROOT>/<user_slug>/assignment_<id>/`, manifest and hash validation, retry on failure.
  - `test_transfer_validation.py`: XAnyLabeling JSON schema validation, remote conflict detection, background declaration handling without empty JSON file fabrication.
  - `test_security_api.py`: Argon2id password hashing, JWT token expiration and claim verification, RBAC endpoint protection, secret masking in config.
  - `test_e2e_lifecycle.py`: Complete simulation from dataset registration, catalog scan, manager assignment, staging, annotator fetch, local launch, submission review, background declaration, and completion verification.

### 3. Real PostgreSQL Multi-Threaded Concurrency Test
- **Command**: `.venv/bin/pytest tests_central/test_postgres_concurrency.py -v`
- **Environment**: Real PostgreSQL container (`postgres:16-alpine`), Alembic initial schema applied.
- **Dataset Size**: 5,000 eligible cataloged images.
- **Workload**: 5 concurrent threads/sessions requesting 1,500 images simultaneously (total demand 7,500 > 5,000 available).
- **Result**: `1 passed in 2.90s`
- **Verification Metrics**:
  - Exactly 3 threads succeeded ($3 \times 1,500 = 4,500$ images allocated).
  - Exactly 2 threads were safely rejected due to insufficient eligible images.
  - Exactly 4,500 rows created in `active_image_claims` with 0 duplicate allocations.
  - Exactly 500 images remained unallocated in the pool.
  - Zero partial allocations observed (all-or-nothing rollback verified).

