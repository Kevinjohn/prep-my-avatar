from __future__ import annotations

import argparse
from pathlib import Path

from .core import DEFAULT_TARGETS, export_packs, ingest, load_records
from .viewer import serve, write_viewer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="avatar-prep",
        description="Prepare imperfect photographs for reusable avatar-model training.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="ingest, score, crop and build a review run")
    run.add_argument("input", type=Path, help="folder containing source images")
    run.add_argument("--out", type=Path, required=True, help="output run directory")
    run.add_argument("--token", default="pm_subject", help="unique training concept token")
    run.add_argument("--annotations", type=Path, help="optional VLM annotation JSON")
    run.add_argument("--vision", choices=("auto", "local"), default="auto", help="vision mode reserved for local provider selection")

    review = subparsers.add_parser("review", help="serve the local HTML review viewer")
    review.add_argument("run", type=Path, help="output run directory created by run")
    review.add_argument("--port", type=int, default=8765)

    export = subparsers.add_parser("export", help="export captioned model-training packs")
    export.add_argument("run", type=Path, help="output run directory created by run")
    export.add_argument("--targets", default=",".join(DEFAULT_TARGETS), help="comma-separated target names")
    export.add_argument("--include-amber", action="store_true", help="include amber images after human review")

    status = subparsers.add_parser("status", help="print the current run summary")
    status.add_argument("run", type=Path)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        args.out.mkdir(parents=True, exist_ok=True)
        records = ingest(args.input, args.out, args.token, args.annotations, args.vision)
        write_viewer(args.out)
        print(f"Created run at {args.out}")
        print(f"Analysed {len(records)} image(s).")
        print(f"Review: avatar-prep review {args.out}")
        print(f"Coverage report: {args.out / 'reports' / 'coverage-report.md'}")
        return
    if args.command == "review":
        serve(args.run, args.port)
        return
    if args.command == "export":
        targets = [target.strip() for target in args.targets.split(",") if target.strip()]
        created = export_packs(args.run, targets, args.include_amber)
        for path in created:
            print(f"Exported {path}")
        return
    if args.command == "status":
        _, records = load_records(args.run)
        counts = {status: sum(record.status == status for record in records) for status in ("green", "amber", "red")}
        print(f"Images: {len(records)}")
        print(f"Green: {counts['green']} | Amber: {counts['amber']} | Red: {counts['red']}")
        return


if __name__ == "__main__":
    main()
