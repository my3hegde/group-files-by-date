# Group files by date added

Python script that finds files of given extensions added between two dates (inclusive) and puts them in one folder.

On macOS it uses Finder **Date Added**. On other systems it uses the file birth/creation time.

Files are **copied** by default. The script prints each planned action and asks `y/n` before doing anything.

## Usage

```bash
python3 group_files.py ~/Documents 2026-11-01 2026-11-03 -e pdf
```

That copies matching PDFs into `~/Documents/pdf-2026-11-01-to-2026-11-03`. Use the same date twice for a single day.

```bash
# Several extensions at once
python3 group_files.py ~/Downloads 2026-11-01 2026-11-03 -e pdf txt csv

# Move instead of copy
python3 group_files.py ~/Downloads 2026-11-01 2026-11-03 -e pdf --move

# Pick the destination
python3 group_files.py ~/Downloads 2026-11-01 2026-11-03 -e pdf -o ~/Documents/nov-pdfs

# Also scan subfolders
python3 group_files.py ~/Downloads 2026-11-01 2026-11-03 -e txt --recursive

# Undo the last grouping (reads undo_file_move.txt)
python3 group_files.py --undo
```

`-e` / `--ext` is required unless you pass `--undo`. Pass `pdf` or `.pdf`; matching is case-insensitive.

After a grouping run, the script writes `undo_file_move.txt` with one line per file, for example:

`--undo` reads that file and moves each file from dest back to source. You can pass another log path with `--undo path/to/file.txt`.
