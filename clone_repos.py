#!/usr/bin/env python3
"""
Clone repositories listed in repos.txt (one GitHub URL per line).

Usage:
  python3 clone_repos.py --num 100                       # clone the first 100
  python3 clone_repos.py --num 100 --dest python_repos    # custom destination dir
  python3 clone_repos.py                                 # clone all repos in the list
  python3 clone_repos.py --num 50 --jobs 8 --depth 0      # 8 parallel, full clone (no shallow)
"""

import argparse
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

print_lock = Lock()


def load_urls(list_file: Path) -> list[str]:
    urls = []
    with open(list_file) as f:
        for line in f:
            line = line.strip()
            if line:
                urls.append(line)
    return urls


def repo_dir_name(url: str) -> str:
    return url.rstrip("/").split("/")[-1]


def clone_one(url: str, dest_dir: Path, depth: int) -> tuple[str, bool, str]:
    target = dest_dir / repo_dir_name(url)
    if target.exists():
        return url, True, "already exists, skipped"

    cmd = ["git", "clone"]
    if depth > 0:
        cmd += ["--depth", str(depth)]
    cmd += [url, str(target)]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        return url, True, "cloned"
    return url, False, result.stderr.strip().splitlines()[-1] if result.stderr else "unknown error"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", type=str, default="repos.txt",
                         help="file with one GitHub repo URL per line (default: repos.txt)")
    parser.add_argument("--num", type=int, default=None,
                         help="number of repos to clone from the top of the list (default: all)")
    parser.add_argument("--dest", type=str, default="repos",
                         help="destination directory to clone into (default: ./repos)")
    parser.add_argument("--depth", type=int, default=1,
                         help="shallow clone depth; 0 means full clone with history (default: 1)")
    parser.add_argument("--jobs", type=int, default=4,
                         help="number of repos to clone in parallel (default: 4)")
    args = parser.parse_args()

    if shutil.which("git") is None:
        sys.exit("ERROR: git is not installed or not on PATH.")

    list_file = Path(args.list)
    if not list_file.exists():
        sys.exit(f"ERROR: list file not found: {list_file}")

    urls = load_urls(list_file)
    if args.num is not None:
        urls = urls[: args.num]

    dest_dir = Path(args.dest)
    dest_dir.mkdir(parents=True, exist_ok=True)

    print(f"Cloning {len(urls)} repos into {dest_dir}/ "
          f"(depth={'full' if args.depth == 0 else args.depth}, jobs={args.jobs}) ...")

    ok_count = 0
    fail_count = 0
    failures = []

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(clone_one, url, dest_dir, args.depth): url for url in urls}
        for i, future in enumerate(as_completed(futures), start=1):
            url, success, message = future.result()
            with print_lock:
                status = "OK" if success else "FAIL"
                print(f"[{i}/{len(urls)}] {status} {url} - {message}")
            if success:
                ok_count += 1
            else:
                fail_count += 1
                failures.append((url, message))

    print(f"\nDone. {ok_count} succeeded, {fail_count} failed.")
    if failures:
        fail_log = dest_dir.parent / "clone_failures.txt"
        with open(fail_log, "w") as f:
            for url, message in failures:
                f.write(f"{url}\t{message}\n")
        print(f"Failure details written to {fail_log}")


if __name__ == "__main__":
    main()
