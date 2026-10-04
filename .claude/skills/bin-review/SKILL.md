---
name: bin-review
description: Use when Dan is physically reviewing PartDB bins at the shelf: he sends photos or describes bin contents, and you propose corrections, apply approved changes, verify bins, and file the photos. Also use when he asks to see one bin's contents to check it ("show everything in 2B4", "what's in that bin?").
---

# Attended Bin Review

Dan stands at the shelves and sends photos, or describes what a bin holds. You compare that with the database, propose corrections in one table per photo, and once he approves, apply them, mark the bins verified, and file the photos. Dan does not type `partdb` commands; you run them.

The local database is the real, authoritative inventory. This repository is public: never write real inventory into it. Plans go in your scratchpad; photos, notes, and the research queue live under `~/Documents`.

## Start of Batch

1. Run `just up`, then `just backup`. Tell Dan the backup path.
2. Run `uv run partdb verify status --unverified` to see which bins remain.
3. Start the photo watcher with the Monitor tool, using a state file in your scratchpad:

   ```bash
   bash .claude/skills/bin-review/scripts/watch_downloads.sh ~/Downloads <scratchpad>/seen-photos.txt
   ```

   Each `NEW PHOTO: <path>` line is a photo to process. When the monitor expires, restart it with the same state file; photos that arrived meanwhile are reported then.
4. Tell Dan you are ready. Don't tell him what to photograph; assume he knows which bin is next.

## The Loop

1. **A photo arrives**, usually unannounced. Read the bin labels in the frame, then run `uv run partdb inventory --from <first> --through <last>` (or one bin twice) for those bins. If no label is visible, ask which bin it is. If the photo is not of a bin (a screenshot, an instrument screen), say so in one line and leave it in Downloads unfiled.
   - **Photo sets.** When Dan says he is sending N photos of a bin, wait for all N, then reply with one table for the set. When he doesn't give a count ("sending some photos"), ask him to say `done` when finished, and wait for it.
2. **Look closely.** Downscale a copy for viewing (`sips -Z 2000 <photo> --out <scratchpad>/preview.jpg`; for HEIC add `-s format jpeg`). For colour bands, small markings, and part numbers, crop the full-resolution original with Pillow (`uv run --with pillow python ...`), opening it with `ImageOps.exif_transpose(Image.open(path))` first: iPhone JPEGs are stored rotated, and an unrotated crop lands on the wrong region. `sips` previews are already oriented correctly. Never file previews or crops.
3. **Reply with one table per photo** (or per photo set), and nothing after it that repeats or extends the rows:

   | Bin | ID | Action | Description | Confidence | Question |
   |---|---|---|---|---|---|

   One row per record, including `keep` rows, so each bin's full picture is in one place. Actions: `keep`, `update`, `add`, `move in`, `move to <bin>`, `delete`, `create bin`.
4. **Dan replies** `approve`, approves with an amendment ("otherwise approve"), or answers a question.
5. **Apply.** Write the approved plan to `<scratchpad>/plan-<n>.json` and run `uv run partdb apply <scratchpad>/plan-<n>.json --yes`. Set `"verify": true` when every bin in the plan is fully approved; when any bin still has an open question or an amendment you need confirmed, leave that bin out of the plan (or apply with `"verify": false` and verify later). Compare every `<`, `-`, `>`, `~`, and `+` line `apply` prints with the approved table and tell Dan immediately if anything differs; a mistyped ID on a move-in row can silently pull an unrelated part out of another bin, which accounting cannot catch.
6. **File the photo** with the part IDs it shows, using IDs from the `apply` output for newly added parts. File it even when one of its bins was left unverified for an open question or queued research:

   ```bash
   uv run --script .claude/skills/bin-review/scripts/file_photo.py <photo> \
     --bin 4A3=72,80 --bin 4A4= --note "4A3 and 4A4 side by side"
   ```

7. **Confirm** with one line, such as `4A3, 4A4 applied and verified; photo filed.`
8. **Idle check.** If the research queue has items, start a two-minute timer after confirming (`sleep 120` with Bash `run_in_background`). If it fires and no photo or message has arrived since, ask: `OK if I perform research for the items in the queue?` A long pause usually means Dan stepped away or forgot to say he is finished. Skip the timer when the queue is empty.

### Moving Parts Into a Bin Outside the Review

`"verify": true` verifies every bin listed in the plan, so never list a destination bin Dan has not reviewed in this batch just to receive moved parts. Send parts out from the reviewed bin with `"remove": {"<id>": {"move": "<bin>"}}`, adding `"description"` to rename the part as it moves: `{"move": "1D1", "description": "60/40 rosin-core solder"}`. The destination is never verified this way. To add a brand-new part to a bin outside the review, run `uv run partdb add <bin> "<description>"`, which verifies nothing.

### Plan Format

A plan lists each bin's complete intended contents:

```json
{"verify": true,
 "bins": {
   "4A3": {"parts": [
             {"id": 72, "description": "104K100V film capacitors, green"},
             {"id": 80},
             {"description": "M3 nylon standoffs"}],
           "remove": {"73": "delete", "74": {"move": "1D1"}}},
   "4A7": {"create": true, "parts": []}}}
```

- `{"id": N}` keeps a part; adding `description` updates it; no `id` adds a part.
- Listing an `id` that is recorded in another bin moves it into this bin. Listing it in another bin of the same plan is enough to account for it in its source bin.
- `remove` deletes a part or moves it to a bin outside the review, optionally renaming it with `"description"`.
- `"parts": []` means the bin must be empty.
- `"create": true` creates a missing bin. Use it only after Dan approves creating that bin in the Question column.
- Every recorded part in a listed bin must be accounted for, or `apply` rejects the whole plan and changes nothing. Use `--dry-run` if you want to check a plan first.

### Declared-Empty Ranges

When Dan says a range is empty ("4B1–4B8 empty"), run:

```bash
uv run partdb verify mark --from 4B1 --through 4B8 --expect-empty --yes
```

If it reports recorded parts and Dan said **"empty (used up)"**, that is his approval to delete them: apply a plan for those bins with `"parts": []`, each leftover record under `"remove"` as `"delete"`, and `"verify": true`, then confirm in one line listing what was deleted. If he said only "empty", put a delete row for each leftover record in your next table with the question "used up or moved?", and apply nothing until he answers. If a bin he names is missing from the database, propose creating it.

## Ad-hoc Bin Check

Dan often checks a single bin when it is convenient, such as while putting parts away: "show everything in 2B4", "what's in 2B4?", or "show me what's in that bin" when the bin is clear from context (for example, the bin just recommended). If it isn't clear, ask which bin in one line. There is no batch setup: no backup and no watcher.

Run `uv run partdb inventory --from <bin> --through <bin>` and reply with one heading line and one table, nothing after:

**2B4** · unverified (or `verified 2026-10-03`)

| ID | Description |
|---|---|
| 98 | USB-C charging cable, 1 m |

Show `(empty)` for an empty bin. Then:

- **"verified"**: run `uv run partdb verify mark <bin> --yes` and confirm in one line.
- **Corrections** ("98 is actually USB-A", "add M3 nuts", "the fuse isn't here"): write an `apply` plan for that bin with its complete contents and apply it with `"verify": false`, unless Dan also verifies ("fix 98, otherwise verified"), in which case use `"verify": true`. Confirm in one line with the changes. If a correction is ambiguous, ask in one table row before applying.
- **A photo**: handle it like any photo in The Loop.

## Dan's Rules

- Be concise. Put every detail of an item in its table row. Ask questions only in the Question column, and only when uncertainty remains after examining the photo.
- Never ask about quantities (they are not tracked) or whether a bag is empty, and never put counts in descriptions, including when describing mixed contents: write "glass and ceramic fuses", not "2 glass, 1 ceramic fuse".
- Give no speculative guidance before a photo arrives.
- Describe the item type, not its packaging state.
- A marking on the part outranks a stale packaging label.
- Write specific, searchable descriptions: type, value or size, part number. Use the ruler in the frame for sizes; omit a size rather than guess.
- Suggesting a better home for a misplaced item is welcome; keep it brief.
- Approving a proposal means apply and verify, with no second confirmation, for exactly what was approved.
- Never verify a bin Dan has not reviewed, and never apply corrections he has not approved.

## Deferred Research

Reading labels and markings from photos is inline work. External lookups (vendor order histories, datasheets, web searches) are not: queue them so Dan never waits at the shelf. The exception is a quick lookup Dan asks for at the shelf, such as decoding a short manufacturer code; do that inline.

- Append the bin, what is known, the photo filename, and what to look up to `$WORKING_DIR/Interests/Workshop/PartDB/research-queue.md`, creating the file if it is missing. Record the archived path `file_photo.py` prints (the archive renames files to `<date>_<name>`), not the Downloads name. Leave that bin unverified and move on.
- At the end of the batch, do one research pass through claude-in-chrome using Dan's logged-in browser. Vendors he orders from include Adafruit, Pololu, 18650batterystore, liionwholesale, Digi-Key, Mouser, McMaster-Carr, and Amazon.
- Present one table of proposed updates with confidence. If research finds several candidates, flag the row for a physical recheck instead of choosing. Approved rows are applied and verified like any other plan; then remove them from the queue.

## End of Batch

1. Do the research pass.
2. Run `uv run partdb embeddings refresh` so edited and added parts are searchable by meaning. It resolves its own OpenAI key through `PARTDB_OPENAI_API_KEY_CMD`; never read the key or run the helper yourself.
3. Run `just backup` and tell Dan the path.
4. Report progress from `uv run partdb verify status`.
5. Append what slowed the batch down, workarounds, and ideas to `$WORKING_DIR/Interests/Workshop/PartDB/bin-review-pilot-notes.md`.
