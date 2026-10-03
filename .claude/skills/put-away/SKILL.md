---
name: put-away
description: Use when Dan has a part on his bench and asks where to put it ("where do I put this?", a photo with that question, "where do I put some resistors?") or says he needs to put away some parts. Recommend PartDB bins and record where things went.
---

# Putting Parts Away

Dan has parts on his bench and wants to know where they go. Recommend a bin from the PartDB inventory, and once he says `ok`, record the change if one is needed. These requests are impromptu and often interrupt other work: answer concisely, then return to what you were doing.

The local database is the real, authoritative inventory. This repository is public: never write real inventory into it.

## Ways In

- **A photo already sent** ("just sent you a photo, where do I put this?"): take the newest image in `~/Downloads`.
- **A description only** ("where do I put a couple of random resistors?"): work from the words.
- **A put-away session** ("I need to put away some parts"): start the photo watcher with the Monitor tool, using a state file in your scratchpad:

  ```bash
  bash .claude/skills/bin-review/scripts/watch_downloads.sh ~/Downloads <scratchpad>/seen-photos.txt
  ```

  Each `NEW PHOTO: <path>` line is an item. Dan may send photos, descriptions, or a mix. Restart an expired monitor with the same state file. When he says `done`, stop the monitor.

## For Each Item

1. **Identify it.** For a photo, downscale a copy for viewing (`sips -Z 2000 <photo> --out <scratchpad>/preview.jpg`; for HEIC add `-s format jpeg`) and crop the full-resolution original with Pillow for small markings (`uv run --with pillow python ...`). Ask only if you can't tell what it is well enough to place it. If a photo isn't of a part, say so in one line and leave it unfiled.
2. **Find candidate bins.**
   - `uv run partdb search --full-text "<key terms>"` and `uv run partdb search "<description>"` for records of the same part or the same kind of part.
   - `uv run partdb inventory --from <bin> --through <bin>` to see a candidate bin's full contents.
   - Each search result's `nearest empty: <before> ↑ <after> ↓` label names the closest empty bins on either side of related parts.
3. **Recommend**, best option first, in one table and nothing after it:

   | # | Bin | Why | Record change |
   |---|---|---|---|
   | 1 | 4C1 | same part already recorded (id 77) | none |
   | 2 | 4C5 | other through-hole resistors | add "47R resistors (yellow-purple-black)" |

   - Use one row when the answer is obvious, and at most three rows when there is a real choice.
   - Prefer, in order: the bin where the same part is already recorded; a bin holding the same kind of part; an empty bin next to related parts; the nearest empty bin.
   - `Record change` is `none` when an existing record already covers the item, such as an "assorted resistors" record for a few random resistors. Otherwise it is `add "<description>"`, or `update <id> "<description>"` when the item adds detail, such as a part number, to a record that already covers it.
4. **Dan replies.** `ok` means he put the item where the only option said; `ok 2` (or naming a bin) means he chose that option. If there were several options and he says just `ok`, ask which one in one line. Then:
   - Apply the record change with `uv run partdb add <bin> "<description>"` or `uv run partdb update <id> "<description>"`. Make no change for `none`.
   - After an add or update, run `uv run partdb embeddings refresh` so semantic search finds the item. It resolves its own OpenAI key through `PARTDB_OPENAI_API_KEY_CMD`; never read the key or run the helper yourself.
   - File a photo under the destination bin with the part ID it shows (the new ID from `partdb add`, or the covering record's ID):

     ```bash
     uv run --script .claude/skills/bin-review/scripts/file_photo.py <photo> --bin 4C1=77 --note "put-away"
     ```

   - Reply in one line, such as `Recorded: 47R resistors added to 4C5; photo filed.`

## Rules

- Be concise. Put each option's details in its row; no bullets after the table.
- Never ask about quantities (they are not tracked) or whether a bag is empty, and never put counts in descriptions.
- Describe the item type, not its packaging state. A marking on the part outranks a stale packaging label.
- Write specific, searchable descriptions: type, value or size, part number. Omit a size rather than guess.
- Give no speculative guidance before a photo arrives.
- Never change a record before Dan says `ok`.
- Never verify bins. Putting a part away records where it went; it does not confirm the rest of the bin, and adding a part leaves a bin's verified status unchanged.
- If Dan says an item won't fit in the recommended bin, recommend the next option.
