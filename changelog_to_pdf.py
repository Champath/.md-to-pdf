#!/usr/bin/env python3

import argparse
import re
import sys
from pathlib import Path



def safe_filename(value: str) -> str:
    """Convert a path into a filename that works on Windows."""
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", value)
    value = re.sub(r"\s+", "-", value.strip())
    value = re.sub(r"-+", "-", value)
    return value.strip(" .-_") or "repository"


def find_all_changelogs(root: Path, output_dir: Path) -> list[Path]:
    """Recursively find every CHANGELOG.md, ignoring the output directory."""
    results = []
    output_dir = output_dir.resolve()

    for path in root.rglob("*"):
        try:
            resolved = path.resolve()

            # Ignore generated output if it is inside the search directory.
            if resolved == output_dir or output_dir in resolved.parents:
                continue

            if path.is_file() and path.name.casefold() == "changelog.md":
                results.append(path)

        except OSError:
            continue

    return sorted(results, key=lambda p: str(p).casefold())


def get_pdf_path(changelog: Path, root: Path, output_dir: Path) -> Path:
    """Create a PDF filename based on the changelog's relative path."""
    relative_path = changelog.relative_to(root)
    parent = relative_path.parent

    if str(parent) == ".":
        name = safe_filename(root.name)
    else:
        name = safe_filename("-".join(parent.parts))

    return output_dir / f"{name}-changelog.pdf"


def markdown_to_plain_text(markdown: str) -> str:
    """Convert common Markdown syntax to readable plain text."""
    text = markdown.replace("\r\n", "\n").replace("\r", "\n")

    # Fenced code block markers.
    text = re.sub(r"(?m)^\s*(```|~~~)[^\n]*\n", "", text)
    text = re.sub(r"(?m)^\s*(```|~~~)\s*$", "", text)

    # Images and links.
    text = re.sub(
        r"!\[([^\]]*)\]\(([^)]+)\)",
        r"[Image: \1] (\2)",
        text,
    )
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)
    text = re.sub(r"<(https?://[^>]+)>", r"\1", text)

    # Headings.
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", text)

    # Bold, italic and inline-code markers.
    text = re.sub(r"(\*\*|__)(.*?)\1", r"\2", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.*?)\*(?!\*)", r"\1", text)
    text = re.sub(r"(?<!_)_(?!_)(.*?)_(?!_)", r"\1", text)
    text = text.replace("`", "")

    # Horizontal rules.
    text = re.sub(
        r"(?m)^\s*([-*_]\s*){3,}$",
        "----------------------------------------",
        text,
    )

    return text.strip() + "\n"


def wrap_line(text: str, max_chars: int = 100) -> list[str]:
    """Wrap long lines to fit on an A4 page."""
    if not text:
        return [""]

    wrapped = []
    remaining = text

    while len(remaining) > max_chars:
        split_at = remaining.rfind(" ", 0, max_chars + 1)

        if split_at <= 0:
            split_at = max_chars

        wrapped.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip()

    wrapped.append(remaining)
    return wrapped


def create_pdf(markdown_path: Path, pdf_path: Path) -> None:
    """Render a changelog as a paginated PDF."""
    markdown = markdown_path.read_text(
        encoding="utf-8-sig",
        errors="replace",
    )

    text = markdown_to_plain_text(markdown)

    document = pymupdf.open()

    page_width, page_height = pymupdf.paper_size("a4")

    margin = 54
    font_size = 10
    line_height = 14

    usable_width = page_width - (2 * margin)
    max_chars = max(40, int(usable_width / (font_size * 0.52)))

    page = document.new_page(
        width=page_width,
        height=page_height,
    )

    y = margin

    # Document title.
    for line in wrap_line(markdown_path.name, max_chars):
        if y + line_height > page_height - margin:
            page = document.new_page(
                width=page_width,
                height=page_height,
            )
            y = margin

        page.insert_text(
            (margin, y),
            line,
            fontsize=14,
            fontname="helv",
        )
        y += 20

    y += 6

    # Document contents.
    for source_line in text.splitlines():
        for line in wrap_line(source_line, max_chars):
            if y + line_height > page_height - margin:
                page = document.new_page(
                    width=page_width,
                    height=page_height,
                )
                y = margin

            is_list_or_code = source_line.startswith(
                ("    ", "\t", "- ", "* ", "+ ", "• ")
            )

            page.insert_text(
                (margin, y),
                line,
                fontsize=font_size,
                fontname="cour" if is_list_or_code else "helv",
                color=(0, 0, 0),
            )

            y += line_height

        y += 2

    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    document.save(
        str(pdf_path),
        garbage=4,
        deflate=True,
    )
    document.close()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Recursively convert CHANGELOG.md files to PDFs."
    )

    parser.add_argument(
        "root",
        type=Path,
        help="Repository or parent directory to search.",
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("generated-pdfs"),
        help="PDF output directory (default: ./generated-pdfs).",
    )

    parser.add_argument(
        "--no-overwrite",
        action="store_true",
        help="Skip PDFs that already exist.",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    root = args.root.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()

    if not root.exists():
        print(f"ERROR: Input directory does not exist: {root}")
        return 2

    if not root.is_dir():
        print(f"ERROR: Input path is not a directory: {root}")
        return 2

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"ERROR: Cannot create output directory: {exc}")
        return 2

    changelogs = find_all_changelogs(root, output_dir)

    if not changelogs:
        print(f"No CHANGELOG.md files found under: {root}")
        return 0

    print(f"Found {len(changelogs)} CHANGELOG.md file(s).\n")

    converted = 0
    skipped = 0
    failed = 0
    used_paths = set()

    for changelog in changelogs:
        pdf_path = get_pdf_path(changelog, root, output_dir)

        # Avoid collisions when different paths produce the same safe name.
        candidate = pdf_path
        suffix = 2

        while str(candidate).casefold() in used_paths:
            candidate = pdf_path.with_name(
                f"{pdf_path.stem}-{suffix}{pdf_path.suffix}"
            )
            suffix += 1

        pdf_path = candidate
        used_paths.add(str(pdf_path).casefold())

        if args.no_overwrite and pdf_path.exists():
            print(f"SKIPPED: {changelog.relative_to(root)}")
            skipped += 1
            continue

        try:
            create_pdf(changelog, pdf_path)

            print(
                f"SUCCESS: {changelog.relative_to(root)}"
                f" -> {pdf_path.name}"
            )
            converted += 1

        except Exception as exc:
            print(
                f"FAILED: {changelog}\n  Reason: {exc}",
                file=sys.stderr,
            )
            failed += 1

    print("\n========== SUMMARY ==========")
    print(f"Found:     {len(changelogs)}")
    print(f"Converted: {converted}")
    print(f"Skipped:   {skipped}")
    print(f"Failed:    {failed}")
    print(f"Output:    {output_dir}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())