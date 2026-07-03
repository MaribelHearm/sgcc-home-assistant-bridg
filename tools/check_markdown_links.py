#!/usr/bin/env python3
"""Check local links in Markdown files.

This intentionally stays lightweight: it validates repository-relative files and
folders referenced by Markdown links or simple HTML href/src attributes. Remote
URLs, anchors-only links, HA `/local/...` resource URLs, and other schemes are
ignored.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", ".workflow", "__pycache__", ".pytest_cache", ".mypy_cache"}
SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
MD_LINK_RE = re.compile(r"!?\[[^\]\n]*\]\(([^)\n]+)\)")
HTML_LINK_RE = re.compile(r"(?:href|src)=[\"']([^\"']+)[\"']", re.IGNORECASE)


def markdown_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*.md"):
        if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        files.append(path)
    return sorted(files)


def strip_title(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("<") and raw.endswith(">"):
        raw = raw[1:-1].strip()
    # Markdown titles appear after whitespace: (path "title"). Paths in this
    # repo do not contain literal spaces; keep the checker simple and explicit.
    return raw.split()[0] if raw else raw


def is_ignored_url(url: str) -> bool:
    if not url or url.startswith("#"):
        return True
    if SCHEME_RE.match(url):
        return True
    if url.startswith("//"):
        return True
    # HA dashboard resources and absolute runtime paths are not repo files.
    if url.startswith("/"):
        return True
    return False


def target_path(source: Path, url: str) -> Path | None:
    url = strip_title(url)
    if is_ignored_url(url):
        return None
    parsed = urlsplit(url)
    path = unquote(parsed.path)
    if not path:
        return None
    return (source.parent / path).resolve()


def iter_links(text: str):
    in_fence = False
    for lineno, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("```") or line.lstrip().startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for match in MD_LINK_RE.finditer(line):
            yield lineno, match.group(1)
        for match in HTML_LINK_RE.finditer(line):
            yield lineno, match.group(1)


def main() -> int:
    errors: list[str] = []
    for md in markdown_files():
        rel = md.relative_to(ROOT)
        for lineno, raw in iter_links(md.read_text(encoding="utf-8")):
            target = target_path(md, raw)
            if target is None:
                continue
            try:
                target.relative_to(ROOT)
            except ValueError:
                errors.append(f"{rel}:{lineno}: link escapes repository: {raw}")
                continue
            if not target.exists():
                errors.append(f"{rel}:{lineno}: missing local link: {raw}")
    if errors:
        print("Markdown local link check failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print("Markdown local link check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
