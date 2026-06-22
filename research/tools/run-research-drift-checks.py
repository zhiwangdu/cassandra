#!/usr/bin/env python3
#
# Runner for research/tools/check-*.py source-only drift checkers.

import argparse
import fnmatch
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = REPO_ROOT / "research/tools"


@dataclass(frozen=True)
class RunResult:
    path: str
    command: list[str]
    exit_code: int
    duration_seconds: float
    stdout_tail: str
    stderr_tail: str
    timed_out: bool = False


def rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def discover_checkers() -> list[str]:
    return sorted(rel(path) for path in TOOLS_DIR.glob("check-*.py"))


def matches_any(path: str, patterns: list[str]) -> bool:
    if not patterns:
        return True
    name = Path(path).name
    return any(fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(name, pattern) or pattern in path for pattern in patterns)


def select_checkers(include: list[str], exclude: list[str]) -> list[str]:
    selected = [path for path in discover_checkers() if matches_any(path, include)]
    if not exclude:
        return selected
    return [path for path in selected if not matches_any(path, exclude)]


def tail(text: str, limit: int = 4000) -> str:
    return text if len(text) <= limit else text[-limit:]


def run_checker(path: str, timeout: int) -> RunResult:
    command = [sys.executable, path]
    started = time.monotonic()
    try:
        completed = subprocess.run(command,
                                   cwd=REPO_ROOT,
                                   text=True,
                                   capture_output=True,
                                   timeout=timeout)
        return RunResult(path=path,
                         command=command,
                         exit_code=completed.returncode,
                         duration_seconds=round(time.monotonic() - started, 3),
                         stdout_tail=tail(completed.stdout),
                         stderr_tail=tail(completed.stderr))
    except subprocess.TimeoutExpired as exc:
        return RunResult(path=path,
                         command=command,
                         exit_code=124,
                         duration_seconds=round(time.monotonic() - started, 3),
                         stdout_tail=tail(exc.stdout or ""),
                         stderr_tail=tail(exc.stderr or f"timed out after {timeout}s"),
                         timed_out=True)


def run_selected(paths: list[str], jobs: int, timeout: int) -> list[RunResult]:
    if jobs <= 1:
        return [run_checker(path, timeout) for path in paths]

    results: list[RunResult] = []
    with ThreadPoolExecutor(max_workers=jobs) as executor:
        future_to_path = {executor.submit(run_checker, path, timeout): path for path in paths}
        for future in as_completed(future_to_path):
            results.append(future.result())
    return sorted(results, key=lambda result: result.path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run research drift checkers.")
    parser.add_argument("--list", action="store_true", help="list selected checkers without running them")
    parser.add_argument("--pattern", action="append", default=[], help="include checker by glob, filename, or substring; repeatable")
    parser.add_argument("--exclude", action="append", default=[], help="exclude checker by glob, filename, or substring; repeatable")
    parser.add_argument("--jobs", type=int, default=1, help="number of checkers to run concurrently")
    parser.add_argument("--timeout", type=int, default=300, help="timeout in seconds for each checker")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()

    selected = select_checkers(args.pattern, args.exclude)
    if args.list:
        payload = {"count": len(selected), "checkers": selected}
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            for path in selected:
                print(path)
        return 0

    results = run_selected(selected, max(args.jobs, 1), args.timeout)
    failed = [result for result in results if result.exit_code != 0]
    payload = {
        "selected_count": len(selected),
        "passed_count": len(results) - len(failed),
        "failed_count": len(failed),
        "results": [asdict(result) for result in results],
    }

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for result in results:
            status = "PASS" if result.exit_code == 0 else "FAIL"
            print(f"{status} {result.path} ({result.duration_seconds}s)")
            if result.exit_code != 0:
                if result.stdout_tail:
                    print(result.stdout_tail.rstrip())
                if result.stderr_tail:
                    print(result.stderr_tail.rstrip(), file=sys.stderr)
        print(f"research drift checks: {payload['passed_count']} passed, {payload['failed_count']} failed, {payload['selected_count']} selected")

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
