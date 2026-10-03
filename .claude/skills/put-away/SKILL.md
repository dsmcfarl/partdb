---
name: put-away
description: Use when Dan has a part on his bench and asks where to put it ("where do I put this?", a photo with that question, "where do I put some resistors?") or says he needs to put away some parts. Recommend PartDB bins and record where things went.
---

# Putting Parts Away

Dan has parts on his bench and wants to know where they go. Recommend a bin from the PartDB inventory, and once he says `ok`, record the change if one is needed. These requests are impromptu and often interrupt other work: answer concisely, then return to what you were doing.

The local database is the real, authoritative inventory. This repository is public: never write real inventory into it.

## Ways In

- **A photo already sent** ("just sent you a photo, where do I put this?"): take the newest image in `~/Downloads`. Filed photos are moved out of Downloads, so any image still there is unfiled; skip ones you have already handled this session. Note the photo's time, and if it is more than about ten minutes old, confirm it is the right one in one line before working on it.
- **Several photos already sent** ("just sent 5 photos, where do I put those?"): take the N newest unfiled images and reply with one table covering all of them (see Several Items).
- **A description only** ("where do I put a couple of random resistors?"): work from the words.
- **A put-away session** ("I need to put away some parts"): start the photo watcher with the Monitor tool, using a state file in your scratchpad:

  ```bash
  bash .claude/skills/bin-review/scripts/watch_downloads.sh ~/Downloads <scratchpad>/seen-photos.txt
  ```

  Each `NEW PHOTO: <path>` line is an item. Dan may send photos, descriptions, or a mix. Restart an expired monitor with the same state file. When he says `done`, stop the monitor.

## For Each Item

1. **Identify it.** For a photo, downscale a copy for viewing (`sips -Z 2000 <photo> --out <scratchpad>/preview.jpg`; for HEIC add `-s format jpeg`). For small markings, crop the full-resolution original with Pillow (`uv run --with pillow python ...`), opening it with `ImageOps.exif_transpose(Image.open(path))` first: iPhone JPEGs are stored rotated, and an unrotated crop lands on the wrong region. Ask only if you can't tell what it is well enough to place it. If a photo isn't of a part, say so in one line and leave it unfiled.
2. **Find candidate bins.** When identifying and searching several items will take a while, first send one line such as `Identified 4 of 5; checking bins.`
   - Start with semantic search, `uv run partdb search "<description>"`, which finds the right neighbourhood even when wording differs. Use `uv run partdb search --full-text "<terms>"` for exact part numbers and values (`100R`, `pico`). Run several queries in one Bash loop to save round trips.
   - `uv run partdb inventory --from <bin> --through <bin>` to see a candidate bin's full contents. Range endpoints must be existing bins: shelf rows have different lengths, so check `uv run partdb list --locations` rather than assuming a row ends at 8.
   - Each search result's `nearest empty: <before> ↑ <after> ↓` label names the closest empty bins on either side of related parts.
3. **Recommend**, best option first, in one table and nothing after it:

   | # | Bin | Why | Record change |
   |---|---|---|---|
   | 1 | 4C1 | same part already recorded (id 77) | none |
   | 2 | 4C5 | other through-hole resistors | add "47R resistors (yellow-purple-black)" |

   - Use one row when the answer is obvious, and at most three rows when there is a real choice.
   - Prefer, in order: the bin where the same part is already recorded; a bin holding the same kind of part; an empty bin next to related parts; the nearest empty bin.
   - `Record change` is `none` when an existing record already covers the item, such as an "assorted resistors" record for a few random resistors. Otherwise it is `add "<description>"`, or `update <id> "<description>"` when the item carries an identifying marking the covering record lacks, so that searching for the marking finds it: a part number, or a different colour-band scheme, as in `100R resistors (4-band brown-black-brown; 5-band brown-black-black-black-brown)`.
4. **Dan replies.** `ok` means he put the item where the first option said; `ok 2` (or naming a bin) means he chose that option. Then:
   - Apply the record change with `uv run partdb add <bin> "<description>"` or `uv run partdb update <id> "<description>"`. Make no change for `none`.
   - After an add or update, run `uv run partdb embeddings refresh` so semantic search finds the item. It resolves its own OpenAI key through `PARTDB_OPENAI_API_KEY_CMD`; never read the key or run the helper yourself.
   - File a photo under the destination bin with the part ID it shows (the new ID from `partdb add`, or the covering record's ID):

     ```bash
     uv run --script .claude/skills/bin-review/scripts/file_photo.py <photo> --bin 4C1=77 --note "put-away"
     ```

   - Reply in one line, such as `Recorded: 47R resistors added to 4C5; photo filed.`

## Several Items

When several photos or items arrive together, reply with one table and an Item column. Number rows per item, with letters for alternatives:

| # | Item | Bin | Why | Record change |
|---|---|---|---|---|
| 1 | USB-C charger cable | 2B4 | other USB cables | add "USB-C charging cable, 1 m" |
| 2a | 100R resistors | 4C2 | same part already recorded (id 78) | none |
| 2b | 100R resistors | 4C5 | other resistors | add "100R resistors (brown-black-brown)" |

`ok` takes every item's first option; a row number such as `2b` overrides that item. Apply and file each item as above, then confirm all of them in one line.

## Rules

- Be concise. Put each option's details in its row; no bullets after the table.
- Never ask about quantities (they are not tracked) or whether a bag is empty, and never put counts in descriptions.
- Describe the item type, not its packaging state. A marking on the part outranks a stale packaging label.
- Write specific, searchable descriptions: type, value or size, part number. Omit a size rather than guess.
- Give no speculative guidance before a photo arrives.
- Never change a record before Dan says `ok`.
- Never verify bins unless Dan explicitly asks ("verify 2B4"); then run `uv run partdb verify mark <bin> --yes`. Putting a part away records where it went; it does not confirm the rest of the bin, and adding a part leaves a bin's verified status unchanged.
- If Dan says an item won't fit in the recommended bin, recommend the next option.
