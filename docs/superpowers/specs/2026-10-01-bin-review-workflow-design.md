# PartDB Bin-Review Workflow Design

**Date:** 2026-10-01
**Status:** Approved for planning

## Purpose

Make the attended, photo-driven bin review piloted on 2026-09-27/28 repeatable by any agent session in this repository, and make each approved review apply to the database atomically and completely.

In the pilot, Dan photographed bins at the shelf, an agent proposed corrections in one table per photo, and Dan's approval meant "apply and verify". Two sessions verified 71 of 197 bins at about two minutes per non-empty bin. The loop works, but it lives in one session's memory and an external notes file, each approved table took several separate CLI calls with partial-apply risk, and photo filing was ad hoc. This phase codifies the loop before the remaining 126 bins are reviewed.

## Success Criteria

The phase is complete when:

1. A fresh Claude Code session in this repository, with no project memory, can run an attended batch using the `bin-review` skill alone.
2. One command applies an approved table covering one or more bins as a single transaction, optionally marking those bins verified in the same transaction.
3. A bin cannot be marked verified while any of its recorded parts is unaccounted for, either by `apply` or by a declared-empty range verification.
4. Every review photo is filed by bin with a manifest row as part of the loop, using a tested script.
5. CI covers the new command, CLI changes, and photo script.

## Non-Goals

This phase will not:

- Store photos or photo references in the database. Photo retention stays file-based until a permanent design is chosen.
- Add an order-history database, a "pending research" location state, or new audit rules.
- Build web, mobile, or other interfaces, or select broader product direction.
- Make `apply` the interface Dan types; it is designed for agents.
- Create locations implicitly. A missing location is created only by an explicit `create` request made after Dan approves it.
- Schedule backups or decide the database's permanent host.

## Component 1: `partdb apply`

### Invocation

```bash
partdb apply PLAN            # PLAN is a JSON file path, or - for stdin
partdb apply PLAN --dry-run  # print the diff, change nothing
partdb apply PLAN --yes      # skip the confirmation prompt
```

Without `--dry-run` or `--yes`, the command prints the diff and asks for confirmation, matching existing destructive-command behavior. Agents run it with `--yes` only after Dan approves the table in conversation.

### Plan Format

A plan declares the complete intended contents of each listed bin:

```json
{
  "verify": true,
  "bins": {
    "4A3": {
      "parts": [
        {"id": 72, "description": "104K100V film capacitors, green"},
        {"id": 80},
        {"id": 211},
        {"description": "M3 nylon standoffs"}
      ],
      "remove": {"73": "delete", "74": {"move": "1D1"}}
    },
    "4A7": {"create": true, "parts": []}
  }
}
```

Top level:

- `bins` (required): an object mapping location names to bin entries. It must contain at least one bin.
- `verify` (optional, default `false`): when `true`, every bin listed in `bins` is marked verified in the same transaction.

Bin entry:

- `parts` (required): the bin's complete intended contents.
  - `{"id": N}` keeps part N unchanged.
  - `{"id": N, "description": "..."}` keeps part N and sets its description. A description identical to the current one is a keep.
  - `{"description": "..."}` adds a new part.
  - An `id` currently recorded in a different location moves that part into this bin, with an optional description change.
  - `[]` declares the bin empty.
- `remove` (optional): an object mapping part IDs (as strings) currently recorded in this bin to `"delete"` or `{"move": "<location>"}`.
- `create` (optional, default `false`): create the location if it does not exist. If it already exists, `create` has no effect.

Location names match existing locations case-insensitively, consistent with range endpoints, and resolve to their canonical recorded name. Unknown keys anywhere in the plan are rejected so typos cannot silently change meaning.

### Validation

The entire plan is validated before any change. Any of these failures rejects the plan without modifying data and reports every problem found:

- Malformed JSON, missing `bins` or `parts`, wrong types, or unknown keys.
- A listed bin that does not exist and lacks `create: true`.
- A part recorded in a listed bin that appears in neither its `parts` nor its `remove`, and is not listed in another bin's `parts` in the same plan. Listing a part in another plan bin's `parts` moves it there and accounts for it in its source bin.
- A part ID that does not exist.
- A part ID listed in more than one bin's `parts`, or removed by more than one bin.
- A part ID that is listed in some bin's `parts` and also removed with `"delete"`.
- A part ID removed with a move to one bin but listed in a different bin's `parts`.
- A `remove` move to the same bin the part is removed from.
- Two plan bins that name the same location, including names differing only in case, or a JSON object with a duplicated key.
- A `remove` entry for a part not recorded in that bin.
- A `remove` move to a location that neither exists nor is created by the same plan.
- A `remove` move to a bin listed in the same plan that does not list that part in its `parts`.
- A blank or whitespace-only description.

### Execution

Validated changes run in one database transaction: create requested locations first, then apply each bin's changes in plan order, then mark verification. A failure at any point rolls back the whole plan.

Verification applies only to bins listed in `bins`. A location that only receives a part through a `remove` move is not verified.

Updated, moved-with-new-description, and added parts have no embedding afterward, preserving the existing stale-vector rule. Unchanged and description-preserving moved parts keep their embeddings.

### Output

The diff is printed per bin in plan order, one line per change, using the part ID:

```text
4A3
  = 80 "existing description"
  ~ 72 "old description" -> "104K100V film capacitors, green"
  < 211 "regulator description" <- 5A6
  + 215 "M3 nylon standoffs"
  - 73 "deleted description"
  > 74 "moved description" -> 1D1
  verified
4A7 (created)
  (empty)
  verified
```

In dry-run output, added parts display `+ new` in place of an ID. After a real apply, added parts show their assigned IDs, so photo manifest rows can reference them.

### Code Structure

- `src/partdb/apply.py`: parses and structurally validates plan JSON into typed plan objects, with no database access.
- `InventoryService`: gains methods that validate a plan against current data and compute the diff, and that execute a computed diff within the caller's transaction, reusing existing CRUD, location, and verification helpers.
- `cli.py`: adds the `apply` command, reads the file or stdin, prints the diff, and confirms.

## Component 2: CLI Refinements

### Declared-Empty Verification

`partdb verify mark` gains `--expect-empty`. Before marking, it checks every selected location. If any has recorded parts, the command fails, lists those locations and parts, and marks nothing. It combines with explicit names, `--from`/`--through`, and `--yes`.

Missing locations are not created by `verify mark`; they are added with `partdb add <location>` or an `apply` plan's `create` after Dan approves.

### Search Output Labels

The search output's nearest-empty-location suffix keeps the same data with a clearer label:

```text
1A2: STM32 development board (id=3, nearest empty: none ↑ 2B8 ↓)
4H4: PIC16F88 microcontroller (id=138, distance=0.471, nearest empty: 4F8 ↑ 5A4 ↓)
```

### Verification Status

`partdb verify status` prints only the summary line by default. `--unverified` lists remaining unverified locations as now. A new `--all` prints every location with its status, the previous default.

### Documentation

The README documents `apply`, `--expect-empty`, the search label, and the `verify status` options, and briefly points to the `bin-review` skill. Examples use invented inventory, never real records.

## Component 3: The `bin-review` Skill

### Location

`.claude/skills/bin-review/SKILL.md` in this repository, loaded by Claude Code sessions working in the repo. Because the repository is public, the skill contains no real inventory data.

### Contents

**When to use:** any attended physical bin review in which Dan reports bin contents by message or photo.

**Batch start:**

1. `just up`, then `just backup`; report the backup path.
2. `partdb verify status --unverified` to see remaining bins.
3. Start the `~/Downloads` photo watcher with the Monitor tool, running the skill's `scripts/watch_downloads.sh` with a state file in the scratchpad. The script polls every second for new image files and reports each one once, after its size settles. Restarting it with the same state file when the monitor expires reports photos that arrived meanwhile and never repeats one. HEIC files get a JPEG preview in the scratchpad. Previews and crops are never filed.

**Loop:**

1. A photo arrives, usually unannounced. Read the bin labels in the frame and run `partdb inventory` for those bins. If no label is visible, ask which bin it is.
2. Crop at full resolution for small markings such as colour bands and part numbers.
3. Reply with one table per photo: Bin | ID | Action | Description | Confidence | Question. Include `keep` rows so each bin's full picture is in one place. Add nothing after the table that repeats or extends its rows.
4. Dan replies `approve`, approves with amendments, or answers questions.
5. Write the approved plan JSON to the session scratchpad. Run `partdb apply PLAN --yes` with `verify: true` for every bin with no open question or amendment needing confirmation; leave other bins out or unverified.
6. File the photo with `file_photo.py`, using part IDs from the `apply` output.
7. Reply with one line confirming what was applied and verified.

**Declared-empty ranges:** `partdb verify mark --from X --through Y --expect-empty --yes`.

**Dan's rules:**

- Be concise. Put every detail of an item in its table row; ask questions only in the Question column, and only when uncertainty remains after examining the photo.
- Never ask about quantities, which are not tracked, or whether a bag is empty.
- Give no speculative guidance before a photo arrives.
- Describe the item type, not its packaging state.
- A marking on the part outranks a stale packaging label.
- Write specific, searchable descriptions (type, value or size, part number). Use a ruler in the frame for sizes; omit sizes rather than guess.
- Suggesting a better home for a misplaced item is welcome but brief.
- Approval of a proposal means apply and verify, with no second confirmation, for exactly what was approved.
- Never verify a bin Dan has not reviewed, and never apply corrections he has not approved.

**Deferred research:** Label reading from photos stays inline. External lookups, such as vendor order histories and datasheets, are queued in `$WORKING_DIR/Interests/Workshop/PartDB/research-queue.md` with the bin, known facts, photo, and what to look up, and the bin stays unverified. At batch end, perform one research pass through claude-in-chrome with Dan's logged-in browser, then present one table of proposed updates. If research yields several candidates, flag the row for a physical recheck rather than choosing.

**Batch end:** research pass, `partdb embeddings refresh`, `just backup`, a progress summary, and friction notes appended to `$WORKING_DIR/Interests/Workshop/PartDB/bin-review-pilot-notes.md`.

**Privacy:** photos, plans, research queues, and notes never enter the repository.

**Secrets:** semantic commands resolve `PARTDB_OPENAI_API_KEY` through its credential helper. Never read the key or run the helper directly.

### Memory Consolidation

After the skill is committed, the pilot's project memories for loop style, approve-implies-verify, deferred research, and photo filing are removed, so the skill is the single source of these rules.

## Component 4: Photo Filing Script

### Location and Runtime

`.claude/skills/bin-review/scripts/file_photo.py`, a PEP 723 script run with `uv run --script`. It declares Pillow inline, so partdb gains no runtime dependency.

### Invocation

```bash
uv run --script .claude/skills/bin-review/scripts/file_photo.py \
  ~/Downloads/IMG_6501.JPG \
  --bin 4A3=72,80,211 --bin 4A4= \
  --note "4A3 and 4A4 side by side"
```

- `--bin LOCATION=IDS` (repeatable, at least one): IDS is a comma-separated list of part IDs the photo shows or was used to decide, possibly empty.
- `--note TEXT` (optional): a short description of the shot.
- `--keep-original` (optional): do not remove the source file.

### Archive Layout

The root is `~/Documents/Archive/Interests/Workshop/PartDB/photos/`, overridable with `PARTDB_PHOTO_ROOT` for testing.

- Each copy is stored at `<root>/<LOCATION>/<YYYY-MM-DD>_<original filename>`. A photo covering several bins is copied into each bin's directory.
- `<root>/manifest.csv` has the header `file,original_name,taken_at,bin,part_ids,reviewed_on,note`, with one row per photo and bin. `file` is relative to the root, `part_ids` is semicolon-separated, `taken_at` is ISO 8601, and `reviewed_on` is the filing date.

The pilot's existing photos and manifest already follow this layout.

### Behavior

1. Read `taken_at` from EXIF `DateTimeOriginal` with Pillow, falling back to file modification time.
2. Copy into each bin directory, creating it if needed, then verify each copy's SHA-256 against the source.
3. If an identical file already exists at the destination, skip the copy. If a different file exists there, fail without changes.
4. Append manifest rows, writing the header first if the manifest does not exist. Skip a row that exactly matches an existing row, so reruns are idempotent.
5. Remove the original only after every copy is verified and the manifest is written, unless `--keep-original` is given.

The script prints the destination paths and exits nonzero on any failure, leaving the original in place.

## Testing

**Unit tests:**

- Plan parsing: valid plans, each structural rejection, unknown keys, and blank descriptions.
- Diff rendering for every change type, dry-run and applied.
- Search label formatting.

**Integration tests** against the ephemeral pgvector database:

- `apply` keep, update, add, move in, remove move, delete, create, and empty-bin plans.
- Each validation failure, confirming no data changed.
- Mid-plan database failure rolls back the whole plan.
- Verification is applied only to listed bins and only in the same transaction.
- Embeddings are cleared only for changed descriptions.
- `apply` from stdin, confirmation behavior, and `--dry-run`.
- `verify mark --expect-empty` success and failure.
- `verify status` default, `--unverified`, and `--all`.

**Photo script tests** with temporary directories and a generated JPEG containing EXIF data:

- Dating from EXIF and from the mtime fallback.
- Multi-bin copies, manifest creation and appending, and rerun idempotency.
- Collision with a different file.
- The original is removed only after successful verification, and retained with `--keep-original` or on failure.

Pillow is added to the `dev` dependency group so pytest can import and exercise the photo script. CI runs all tests, including the photo script tests, from the locked environment.

## Delivery

After acceptance, the remaining 126 bins are reviewed using the skill. Shutdown of the Euclid `partdb` database follows completion of physical verification, per the revival spec's post-acceptance decisions.
