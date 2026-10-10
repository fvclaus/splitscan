#!/usr/bin/env python3
"""Resolve and validate versions used for native builds and releases."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from photo_splitter.version import DEVELOPMENT_VERSION, validate_version

TAG_PATTERN = re.compile(r"v((?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))\Z")
RELEASE_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")


def release_version(tag: str) -> str:
    match = TAG_PATTERN.fullmatch(tag)
    if not match:
        raise ValueError(f"Invalid release tag {tag!r}; expected vMAJOR.MINOR.PATCH")
    return validate_version(match.group(1))


def candidate_version(value: str) -> str:
    normalized = value[1:] if value.startswith("v") else value
    if not RELEASE_PATTERN.fullmatch(normalized):
        raise ValueError(f"Invalid candidate version {value!r}; expected MAJOR.MINOR.PATCH")
    return validate_version(normalized)


def resolve_version(tag: str | None, candidate: str | None, run_number: str | None) -> str:
    if tag:
        version = release_version(tag)
        if candidate and candidate_version(candidate) != version:
            raise ValueError(
                f"Candidate version {candidate!r} does not match release tag {tag!r}"
            )
        return version
    if candidate:
        return candidate_version(candidate)
    if run_number:
        if not run_number.isdecimal() or int(run_number) < 1:
            raise ValueError(f"Invalid Actions run number {run_number!r}")
        base = DEVELOPMENT_VERSION.split(".dev", maxsplit=1)[0]
        return validate_version(f"{base}.dev{int(run_number)}")
    return DEVELOPMENT_VERSION


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate-tag")
    validate.add_argument("--tag", required=True)
    validate.add_argument("--candidate")
    resolve = subparsers.add_parser("resolve")
    resolve.add_argument("--tag")
    resolve.add_argument("--candidate")
    resolve.add_argument("--run-number")
    args = parser.parse_args()

    try:
        if args.command == "validate-tag":
            version = release_version(args.tag)
            if args.candidate and candidate_version(args.candidate) != version:
                raise ValueError(
                    f"Candidate version {args.candidate!r} does not match release tag {args.tag!r}"
                )
        else:
            version = resolve_version(args.tag, args.candidate, args.run_number)
    except ValueError as error:
        parser.error(str(error))

    print(version)
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a", encoding="utf-8") as stream:
            print(f"version={version}", file=stream)
    environment = os.environ.get("GITHUB_ENV")
    if environment:
        with Path(environment).open("a", encoding="utf-8") as stream:
            print(f"SPLITSCAN_VERSION={version}", file=stream)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
