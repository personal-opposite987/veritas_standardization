# Veritas Claims — Clinical Data Pipeline

A four-stage pipeline that ingests messy, multi-format clinical JSON
(lab reports and discharge summaries from different source systems),
deduplicates and standardises it, validates lab results and dates, and
loads the result into a queryable SQLite database with a FastAPI +
React operational dashboard on top.

## Project structure

```
nivues_assignment/
├── ingestion_module/
│   └── GCS_BUCKET/
│       ├── dedup.py              # File discovery + content-hash deduplication
│       └── Sample_JSON_file*.json
│
├── standardization_module/
│   └── standardize.py            # Classifier-aware extraction into a fixed schema
│
├── validation_module/
│   ├── validate.py                # Lab result + date validation
│   └── test_validate.py           # Unit tests (real + synthetic cases)
│
├── DB_LOADER_module/
│   ├── loader.py                  # SQLite schema + idempotent batch loading
│   └── veritas.db                 # Generated on first run
│
├── UI_module/
│   ├── api.py                     # FastAPI read-only query layer
│   └── frontend/                  # React/Vite operational dashboard
│
└── test_pipeline.py               # End-to-end runner: chains all four stages
```

## Running it

### 1. Install dependencies

```bash
pip install fastapi uvicorn
cd UI_module/frontend && npm install
```

### 2. Run the pipeline (Ingestion → Standardisation → Validation → DB Loader)

From the project root:

```bash
python test_pipeline.py
```

This reads every `*.json` file in `ingestion_module/GCS_BUCKET/`, deduplicates,
standardises, validates, and writes the result into
`DB_LOADER_module/veritas.db`. Run it again without touching the input
files or the DB — the second run should report `Encounters inserted: 0,
Encounters skipped (duplicate): N`, proving idempotency: re-running the
pipeline never doubles up data already loaded.

### 3. Start the API

```bash
cd UI_module
uvicorn api:app --reload --port 8000
```

Visit `http://localhost:8000/docs` for interactive API documentation, or
hit `http://localhost:8000/api/health` to confirm it can see the DB file.

### 4. Start the dashboard

```bash
cd UI_module/frontend
npm run dev
```

Visit the printed local URL (typically `http://localhost:5173`).

## What the pipeline actually does

### Ingestion (`dedup.py`)

Reads each source JSON file and walks its `data.responseDetails[]` array.
Each entry in that array — not each file — is treated as the atomic unit
of work, because a single file can bundle multiple unrelated clinical
records (a `lab_report` and a `discharge_summary` together).

**Deduplication** is content-based, not ID-based. Every file carries
transport metadata (`traceId`, `correlationId`, `documentId`, `claim_no`)
that is freshly generated on every transmission — proven directly against
the provided samples, where two files (`Sample_JSON_file1.json` and
`Sample_JSON_file3.json`) contain a byte-for-byte identical clinical
payload but four different ID fields. Matching on those IDs would have
missed the duplicate entirely. Instead, each block's clinical `data`
payload is canonicalised (`json.dumps(..., sort_keys=True)`) and hashed
with SHA-256; the hash becomes the record's identity for everything
downstream. This same approach also caught a second, unexpected
duplicate: `Sample_JSON_file5.json` contains the same discharge summary
twice *within itself* — a case that block-level (rather than file-level)
hashing was specifically designed to catch.

### Standardisation (`standardize.py`)

`lab_report` and `discharge_summary` blocks share zero top-level field
names (verified directly against the sample data), so they're handled by
two dedicated extractor functions behind a classifier dispatch, rather
than one generic mapper:

- **`lab_report`** → one row per test, plus its own lightweight
  `encounters` row (see "Why lab_report gets its own encounter" below).
- **`discharge_summary`** → one `encounters` row, plus one row per
  medicine in `dischargeMedications`.

Two FR-2.5/2.6 normalisers are included:
- **Age parsing** (`parse_age`): real sample values are fully redacted
  (`"[AGE REDACTED]"`), so this is validated against synthetic inputs in
  the test suite, not real data — documented as a known limitation.
- **Medicine-to-generic mapping** (`map_medicine_to_generic`): a small
  static dictionary seeded only from medicine names actually present in
  the sample discharge summaries. Explicitly not exhaustive — a
  production system would integrate something like RxNorm.

A real data-quality bug was found and fixed here: the same medicine
sometimes appears twice in one encounter's medication list, once with
blank dose/frequency and once with real values (verified in
`Sample_JSON_file1.json`, where `Tab. miso` appears both ways).
`_dedupe_medications` keeps the populated row and drops the blank stub.

**Why `lab_report` gets its own `encounters` row:** nothing in the
source data ties a `lab_report` block to a `discharge_summary` block in
the same file as the same patient visit — there's no shared patient or
visit ID (`basic_info.uhid` is itself redacted). Assuming same-file
co-location implies same-encounter would be an unverified, risky
assumption in a healthcare pipeline, so each block gets its own
independently-scoped encounter row instead.

### Validation (`validate.py`)

- **Lab results**: `test_analytics` looks like a ready-made
  normal/abnormal classification field, but inspecting its actual value
  distribution across all 363 real lab rows showed it's mostly *not*
  that — it holds lab methodology names (`"Calculated"`,
  `"Spectrophotometer"`), template placeholders (`"low/normal/high"`,
  the single largest value at 70 rows), and even a leaked timestamp. Only
  an explicit allow-list of genuine classifications
  (`normal/low/high/positive/negative/present/absent`) is trusted
  directly; everything else falls through to numeric range-parsing.
  Numeric extraction strips embedded units and thousand-separator commas
  (`"4,290 cells/cu.mm"` → `4290.0`); range parsing handles both
  `"low-high"` spans and comparison bounds (`"<50"`, `">1.15"`). Anything
  that still can't be resolved is marked `Unparseable` rather than
  guessed — given the source data's actual messiness, roughly 41% of
  rows land here, and that's reported honestly rather than hidden.
- **Dates**: handles both date formats observed in the real samples
  (`"09-10-2025"` and `"07-Oct-2025"`), and flags `admissionDate >
  dischargeDate` as `Invalid`. No real sample has a bad date, so this
  path is proven with synthetic test cases instead, clearly labelled as
  such in `test_validate.py`.

### DB Loader (`loader.py`)

SQLite, four tables: `encounters`, `lab_results`, `medications`,
`error_log`. `encounter_id` is the content hash itself, not a separate
auto-increment integer — this lets Standardisation assign a valid foreign
key before any database exists, with no later ID-remapping step.

**Idempotency** is enforced by a `UNIQUE` constraint on
`encounters.encounter_id` (= content hash). On a duplicate, the loader
skips the *entire* unit — the encounter row and all of its lab_results
and medications — never just the parent, to avoid orphaning or
re-duplicating child rows under an encounter that already exists.
Duplicates and unhandled-classifier errors are written into `error_log`
so they stay visible to the dashboard instead of only existing in a
transient local file.

The database file (`veritas.db`) persists across runs by design — the
clearest way to demonstrate idempotency is running the pipeline twice
against the same input and watching the second run skip everything.

### Operational UI (`api.py` + `frontend/`)

The API is **read-only**. It never triggers the pipeline itself — it
only queries whatever's already in `veritas.db`. This keeps the API
simple and mirrors a realistic production split: a batch job that runs
on its own schedule, and a dashboard that reads the result.

The dashboard shows: top-line counts, a single stacked bar visualising
the full lab-result validation breakdown as one proportional shape
(chosen deliberately so the ~41% Unparseable rate is immediately
visible, not buried in a table), a per-source-file breakdown, a
searchable/filterable encounter list with click-through detail, and an
errors/duplicates panel.

## Known limitations / explicit scope exclusions

- **Clinic identity**: the sample data has no folder-based clinic
  structure, so `clinic_id` falls back to `source_system` metadata
  (`FASTTRACK` / `ARTEMIS`) or the source filename. In production,
  clinic identity would come from the GCS object path, not be inferred
  from file content.
- **List-order duplicates**: content hashing sorts dict keys but not
  list contents, so a re-transmission with `dischargeMedications`
  reordered (but otherwise identical) would not be detected as a
  duplicate. Not observed in the provided samples; noted as a real edge
  case rather than silently assumed away.
- **Medicine dictionary** and **age parser** are deliberately small /
  synthetically tested, not production-grade — see Standardisation
  section above.
- **Deep semantic validation** (e.g. "this diagnosis is inconsistent
  with this lab panel") is out of scope. Validation here is limited to
  range/date/format checks, not clinical reasoning.

## Running the tests

```bash
cd validation_module
python test_validate.py
```

Expect `12 passed, 0 failed`. Tests are split into two groups: those run
against real values extracted from the provided sample data (numeric
parsing, range checks), and those marked `SYNTHETIC` for code paths the
real samples never exercise (invalid/malformed dates).
