#!/usr/bin/env python3
"""Group files of given extensions added between two dates into a folder.

On macOS this uses Finder's Date Added (kMDItemDateAdded). Elsewhere it
falls back to the file's birth/creation time, then ctime.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

DEFAULT_UNDO_FILE = "undo_file_move.txt"
ACTION_SEPARATOR = " -> "

def parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Date must be YYYY-MM-DD, got {value!r}"
        ) from exc


def parse_extension(value: str) -> str:
    ext = value.strip().lower()
    if ext.startswith("."):
        ext = ext[1:]
    if not ext or "/" in ext or "\\" in ext:
        raise argparse.ArgumentTypeError(
            f"Extension must look like pdf or .txt, got {value!r}"
        )
    return f".{ext}"


def extensions_label(extensions: set[str] | list[str]) -> str:
    names = [ext.lstrip(".") for ext in sorted(extensions)]
    if len(names) == 1:
        return f"{names[0]} file(s)"
    return "file(s) with extensions " + ", ".join(f".{name}" for name in names)


def date_range_label(start: date, end: date) -> str:
    if start == end:
        return start.isoformat()
    return f"{start.isoformat()}-to-{end.isoformat()}"


def in_date_range(added: date | None, start: date, end: date) -> bool:
    return added is not None and start <= added <= end


def added_date(path: Path) -> date | None:
    try:
        result = subprocess.run(
            ["mdls", "-name", "kMDItemDateAdded", "-raw", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        raw = result.stdout.strip()
        if result.returncode == 0 and raw and raw != "(null)":
            added = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S %z")
            return added.astimezone().date()
    except (FileNotFoundError, ValueError):
        pass

    try:
        stat = path.stat()
    except OSError:
        return None

    timestamp = getattr(stat, "st_birthtime", None) or stat.st_ctime
    return datetime.fromtimestamp(timestamp).date()


def iter_files(source: Path, extensions: set[str], recursive: bool):
    if recursive:
        paths = source.rglob("*")
    else:
        paths = source.iterdir()

    for path in paths:
        if not path.is_file():
            continue
        if path.suffix.lower() in extensions:
            yield path


def confirm(prompt: str) -> bool:
    while True:
        try:
            answer = input(prompt).strip().lower()
        except EOFError:
            print()
            return False
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("Please enter y or n")


def format_action(action: str, src: Path, dest: Path) -> str:
    return f"{action} {src}{ACTION_SEPARATOR}{dest}"


def parse_action_line(line: str) -> tuple[str, Path, Path] | None:
    text = line.strip()
    if not text or text.startswith("#"):
        return None
    if not (text.startswith("move ") or text.startswith("copy ")):
        return None
    action, rest = text.split(" ", 1)
    if ACTION_SEPARATOR not in rest:
        return None
    src_text, dest_text = rest.rsplit(ACTION_SEPARATOR, 1)
    src_text, dest_text = src_text.strip(), dest_text.strip()
    if not src_text or not dest_text:
        return None
    return action, Path(src_text), Path(dest_text)


def unique_destination(
    folder: Path, name: str, reserved: set[Path] | None = None
) -> Path:
    reserved = reserved or set()
    candidate = folder / name
    if not candidate.exists() and candidate not in reserved:
        return candidate

    stem = candidate.stem
    suffix = candidate.suffix
    index = 1
    while True:
        candidate = folder / f"{stem}_{index}{suffix}"
        if not candidate.exists() and candidate not in reserved:
            return candidate
        index += 1


def group_files(
    source: Path,
    start: date,
    end: date,
    dest: Path,
    extensions: set[str],
    *,
    recursive: bool,
    move: bool,
) -> int:
    dest = dest.resolve()
    matches: list[Path] = []
    type_text = extensions_label(extensions)
    if start == end:
        range_text = start.isoformat()
    else:
        range_text = f"{start.isoformat()} and {end.isoformat()}"

    for path in iter_files(source, extensions, recursive):
        resolved = path.resolve()
        if dest in resolved.parents or resolved == dest:
            continue
        if in_date_range(added_date(path), start, end):
            matches.append(path)

    if not matches:
        print(f"No {type_text} added between {range_text} in {source}")
        return 0

    action = "move" if move else "copy"
    planned: list[tuple[Path, Path]] = []
    reserved: set[Path] = set()
    for path in matches:
        target = unique_destination(dest, path.name, reserved)
        reserved.add(target)
        planned.append((path, target))

    print(f"Found {len(planned)} {type_text} added between {range_text}")
    print(f"Will {action} into {dest}:")
    for path, target in planned:
        print(f"  {action} {path} -> {target}")

    if not confirm("Proceed? [y/n] "):
        print("Cancelled")
        return 0

    dest.mkdir(parents=True, exist_ok=True)
    performed: list[str] = []
    for path, target in planned:
        if move:
            shutil.move(str(path), str(target))
        else:
            shutil.copy2(path, target)
        line = format_action(action, path, target)
        performed.append(line)
        print(line)

    Path(DEFAULT_UNDO_FILE).write_text("\n".join(performed) + "\n")
    print(f"Grouped {len(planned)} {type_text} into {dest}")
    print(f"Wrote undo log to {DEFAULT_UNDO_FILE}")
    return len(planned)


def undo_from_file(log_path: Path) -> int:
    if not log_path.is_file():
        print(f"Undo file not found: {log_path}", file=sys.stderr)
        return 1

    planned: list[tuple[Path, Path]] = []
    for line_number, line in enumerate(log_path.read_text().splitlines(), start=1):
        parsed = parse_action_line(line)
        if parsed is None:
            if line.strip():
                print(f"Skipping unrecognized line {line_number}: {line.strip()}")
            continue
        _action, original_source, dest = parsed
        planned.append((dest, original_source))

    if not planned:
        print(f"No copy/move lines found in {log_path}")
        return 0

    print(f"Will move {len(planned)} file(s) back to their original paths:")
    for dest, original_source in planned:
        print(f"  {format_action('move', dest, original_source)}")

    if not confirm("Proceed? [y/n] "):
        print("Cancelled")
        return 0

    restored = 0
    for dest, original_source in planned:
        if not dest.is_file():
            print(f"Skip, destination file missing: {dest}", file=sys.stderr)
            continue
        if original_source.exists():
            print(
                f"Skip, original path already exists: {original_source}",
                file=sys.stderr,
            )
            continue
        original_source.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(dest), str(original_source))
        print(format_action("move", dest, original_source))
        restored += 1

    print(f"Restored {restored} file(s)")
    return 0 if restored == len(planned) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Group files of given extensions added between two dates into one folder."
    )
    parser.add_argument(
        "source",
        nargs="?",
        type=Path,
        help="Folder to scan",
    )
    parser.add_argument(
        "start",
        nargs="?",
        type=parse_date,
        help="Start of date-added range, as YYYY-MM-DD (inclusive)",
    )
    parser.add_argument(
        "end",
        nargs="?",
        type=parse_date,
        help="End of date-added range, as YYYY-MM-DD (inclusive)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Destination folder (default: SOURCE/EXT-START-to-END)",
    )
    parser.add_argument(
        "-e",
        "--ext",
        dest="extensions",
        metavar="EXT",
        nargs="+",
        type=parse_extension,
        help="File extension(s) to group, e.g. pdf txt or .pdf",
    )
    parser.add_argument(
        "--move",
        action="store_true",
        help="Move files instead of copying them",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Also look in subfolders of SOURCE",
    )
    parser.add_argument(
        "--undo",
        nargs="?",
        const=DEFAULT_UNDO_FILE,
        default=None,
        metavar="FILE",
        help=f"Move files back using FILE (default: {DEFAULT_UNDO_FILE})",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.undo is not None:
        return undo_from_file(Path(args.undo).expanduser())

    if args.source is None or args.start is None or args.end is None or not args.extensions:
        build_parser().error("source, start, end, and -e/--ext are required unless --undo is used")

    source = args.source.expanduser().resolve()

    if not source.is_dir():
        print(f"Source is not a directory: {source}", file=sys.stderr)
        return 1

    if args.start > args.end:
        print(
            f"Start date {args.start.isoformat()} is after end date {args.end.isoformat()}",
            file=sys.stderr,
        )
        return 1

    extensions = set(args.extensions)
    dest = args.output
    if dest is None:
        ext_prefix = "-".join(ext.lstrip(".") for ext in sorted(extensions))
        dest = source / f"{ext_prefix}-{date_range_label(args.start, args.end)}"
    else:
        dest = dest.expanduser()

    group_files(
        source,
        args.start,
        args.end,
        dest,
        extensions,
        recursive=args.recursive,
        move=args.move,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
