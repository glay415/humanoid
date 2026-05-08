#!/usr/bin/env python3
"""Promote `[Unreleased]` → `[vX.Y.Z]` in CHANGELOG.md and prepare release artifacts.

Usage:
    python scripts/release.py X.Y.Z [--dry-run] [--no-tag]

Steps (default mode):
    1. Verify current branch is `main` and tree is clean.
    2. Locate the `## [Unreleased]` section in CHANGELOG.md.
    3. If empty (only whitespace / "(empty …)" placeholder), abort.
    4. Promote it to `## [X.Y.Z] — YYYY-MM-DD` and insert a fresh empty
       `[Unreleased]` block above.
    5. Save the promoted section's body to `.release-notes/vX.Y.Z.md` so the
       annotated tag and (optional) GitHub Release can pull from a single source.
    6. `git add CHANGELOG.md .release-notes/vX.Y.Z.md` + commit.
    7. `git checkout release && git merge --ff-only main`.
    8. `git tag -a vX.Y.Z -F .release-notes/vX.Y.Z.md`.
    9. Print push commands (we do NOT push automatically — user confirms).

Flags:
    --dry-run   Don't write or commit; just show what would happen.
    --no-tag    Stop after committing the CHANGELOG promotion. Useful when
                you want to amend before tagging.

Reference: ADR-008 (branch + SemVer policy), `docs/development.md` releases.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import re
import subprocess
import sys
from pathlib import Path

# Windows default stdout is cp949 (mbcs) which can't encode the unicode glyphs
# we use in status lines. Force utf-8 so prints don't crash mid-promotion.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass


REPO_ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
RELEASE_NOTES_DIR = REPO_ROOT / ".release-notes"

VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
UNRELEASED_HEADER = re.compile(r"^## \[Unreleased\]\s*$", re.MULTILINE)
NEXT_RELEASE_HEADER = re.compile(r"^## \[\d+\.\d+\.\d+\]", re.MULTILINE)


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kwargs)


def assert_clean_main(dry_run: bool) -> None:
    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    if branch != "main":
        sys.exit(f"error: must be on `main` branch, got `{branch}`")
    status = run(["git", "status", "--porcelain"]).stdout.strip()
    if status:
        if dry_run:
            print(f"[dry-run] tree not clean (would normally abort):\n{status}")
        else:
            sys.exit(f"error: tree not clean. Commit or stash first.\n{status}")


def split_changelog(text: str) -> tuple[str, str, str, str]:
    m = UNRELEASED_HEADER.search(text)
    if not m:
        sys.exit("error: no `## [Unreleased]` section found in CHANGELOG.md")

    # head ends just before `## [Unreleased]` so the new block can replace it
    # cleanly without leaving a duplicate header behind.
    head = text[: m.start()]
    after = text[m.end() :].lstrip("\n")

    next_match = NEXT_RELEASE_HEADER.search(after)
    if not next_match:
        sys.exit("error: no version section after [Unreleased]")

    body_with_sep = after[: next_match.start()]
    rest = after[next_match.start() :]

    sep_match = re.search(r"(\n---\n+)$", body_with_sep)
    if sep_match:
        body = body_with_sep[: sep_match.start()].strip()
    else:
        body = body_with_sep.strip()

    sep = "\n\n---\n\n"
    return head, body, sep, rest


def is_empty_unreleased(body: str) -> bool:
    if not body or not body.strip():
        return True
    placeholder_patterns = [r"^_?\(empty", r"^N/A$", r"^TBD$"]
    for line in body.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        if any(re.match(p, line, re.IGNORECASE) for p in placeholder_patterns):
            continue
        return False
    return True


def write_release_notes(version: str, today: str, body: str) -> Path:
    RELEASE_NOTES_DIR.mkdir(exist_ok=True)
    path = RELEASE_NOTES_DIR / f"v{version}.md"
    content = f"# v{version} — {today}\n\n{body.strip()}\n"
    path.write_text(content, encoding="utf-8")
    return path


def promote_changelog(version: str, today: str, dry_run: bool) -> str:
    text = CHANGELOG.read_text(encoding="utf-8")
    head, body, sep, rest = split_changelog(text)

    if is_empty_unreleased(body):
        sys.exit("error: [Unreleased] is empty — nothing to release")

    new_unreleased = (
        "## [Unreleased]\n\n"
        "_(empty — populated as new changes land on `main`)_\n"
    )
    promoted = f"## [{version}] — {today}\n\n{body.strip()}\n"
    new_text = head + new_unreleased + sep + promoted + sep + rest

    if dry_run:
        print(f"[dry-run] would promote [Unreleased] → [{version}] — {today}")
        print(f"[dry-run] body length: {len(body)} chars")
    else:
        CHANGELOG.write_text(new_text, encoding="utf-8")
        print(f"✓ CHANGELOG.md promoted to [{version}] — {today}")

    return body


def main() -> int:
    p = argparse.ArgumentParser(description="Promote and tag a release.")
    p.add_argument("version", help="X.Y.Z (no leading v)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-tag", action="store_true")
    args = p.parse_args()

    if not VERSION_PATTERN.match(args.version):
        sys.exit(f"error: version must match X.Y.Z, got `{args.version}`")

    version = args.version
    today = _dt.date.today().isoformat()

    assert_clean_main(args.dry_run)
    body = promote_changelog(version, today, args.dry_run)

    if args.dry_run:
        print(f"\n[dry-run] would write .release-notes/v{version}.md, commit, tag, push.")
        return 0

    notes_path = write_release_notes(version, today, body)
    print(f"✓ release notes saved to {notes_path.relative_to(REPO_ROOT)}")

    run(["git", "add", "CHANGELOG.md", str(notes_path.relative_to(REPO_ROOT))])
    run(
        [
            "git", "commit", "-m",
            f"release: promote [Unreleased] → [v{version}]",
        ]
    )
    print("✓ committed CHANGELOG promotion")

    if args.no_tag:
        print("\n--no-tag: stop here. Review, then ff release and tag manually.")
        return 0

    run(["git", "checkout", "release"])
    run(["git", "merge", "--ff-only", "main"])
    run(["git", "tag", "-a", f"v{version}", "-F", str(notes_path)])
    print(f"✓ release ff-merged; tag v{version} created with annotated notes.")

    print()
    print("Push when ready:")
    print(f"  git push origin main release v{version}")
    print()
    print("Return to main:")
    print(f"  git checkout main")
    print()
    print("(Optional) GitHub Release page:")
    print(f"  gh release create v{version} -F {notes_path.relative_to(REPO_ROOT)}")
    print(f"  # or web UI: https://github.com/glay415/humanoid/releases/new?tag=v{version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
