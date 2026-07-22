#!/usr/bin/env python3
"""
Find Python GitHub repositories matching:
  1) at least N stars (default 10)
  2) not a fork
  3) has at least one open issue
  4) has at least one open (active) pull request

Prints matching repos' GitHub URLs. Uses only the standard library.

Usage:
  export GITHUB_TOKEN=ghp_xxx   # recommended, raises rate limits a lot
  python3 find_python_repos.py --limit 50 --min-stars 10 --output repos.txt
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API_ROOT = "https://api.github.com"


def api_get(url: str, token: str | None) -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "find_python_repos-script",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    while True:
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            remaining = e.headers.get("X-RateLimit-Remaining")
            reset = e.headers.get("X-RateLimit-Reset")
            if e.code in (403, 429) and remaining == "0" and reset:
                wait = max(int(reset) - int(time.time()), 1) + 2
                print(f"Rate limited. Sleeping {wait}s ...", file=sys.stderr)
                time.sleep(wait)
                continue
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GitHub API error {e.code} for {url}: {body}") from e


def search_repositories(min_stars: int, max_stars: int | None, token: str | None, sleep_between: float):
    """Yields candidate repo dicts: Python, not a fork, stars in [min_stars, max_stars]."""
    if max_stars is not None:
        query = f"language:Python stars:{min_stars}..{max_stars} fork:false"
    else:
        query = f"language:Python stars:>={min_stars} fork:false"
    for page in range(1, 11):  # Search API caps at 1000 results (10 pages x 100)
        params = {
            "q": query,
            "sort": "stars",
            "order": "desc",
            "per_page": 100,
            "page": page,
        }
        url = f"{API_ROOT}/search/repositories?{urllib.parse.urlencode(params)}"
        data = api_get(url, token)
        items = data.get("items", [])
        if not items:
            return
        for item in items:
            yield item
        time.sleep(sleep_between)


def count_matching(full_name: str, issue_type: str, token: str) -> int:
    """Returns count of open issues/PRs for a repo. issue_type is 'issue' or 'pr'."""
    query = f"repo:{full_name} type:{issue_type} state:open"
    url = f"{API_ROOT}/search/issues?{urllib.parse.urlencode({'q': query, 'per_page': 1})}"
    data = api_get(url, token)
    return data.get("total_count", 0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-stars", type=int, default=10)
    parser.add_argument("--max-stars", type=int, default=None,
                         help="upper star bound, for paging past the Search API's 1000-result cap")
    parser.add_argument("--limit", type=int, default=50, help="number of NEW matching repos to find")
    parser.add_argument("--min-open-issues", type=int, default=1)
    parser.add_argument("--min-open-prs", type=int, default=1)
    parser.add_argument("--output", type=str, default=None, help="file to write URLs to (default: stdout)")
    parser.add_argument("--append", action="store_true",
                         help="append new matches to --output instead of overwriting, "
                              "skipping URLs already present in it")
    parser.add_argument("--sleep", type=float, default=2.2,
                         help="seconds to sleep between GitHub Search API calls (rate-limit friendly)")
    parser.add_argument("--token", type=str, default=os.environ.get("GITHUB_TOKEN"),
                         help="GitHub personal access token (or set GITHUB_TOKEN env var). "
                              "Strongly recommended: unauthenticated search is capped at 10 req/min.")
    args = parser.parse_args()

    if not args.token:
        print("WARNING: no GitHub token provided. Unauthenticated Search API is limited to "
              "10 requests/min, so this will be slow and may hit rate limits. "
              "Set --token or GITHUB_TOKEN.", file=sys.stderr)

    existing_urls = set()
    if args.append and args.output and os.path.exists(args.output):
        with open(args.output) as f:
            existing_urls = {line.strip() for line in f if line.strip()}
        print(f"Loaded {len(existing_urls)} existing URLs from {args.output} to skip as duplicates.",
              file=sys.stderr)

    matches = []
    checked = 0
    for repo in search_repositories(args.min_stars, args.max_stars, args.token, args.sleep):
        if len(matches) >= args.limit:
            break
        if repo["html_url"] in existing_urls:
            continue
        checked += 1
        full_name = repo["full_name"]

        open_issues = count_matching(full_name, "issue", args.token)
        time.sleep(args.sleep)
        if open_issues < args.min_open_issues:
            continue

        open_prs = count_matching(full_name, "pr", args.token)
        time.sleep(args.sleep)
        if open_prs < args.min_open_prs:
            continue

        matches.append(repo["html_url"])
        print(f"[{len(matches)}/{args.limit}] {repo['html_url']} "
              f"(stars={repo['stargazers_count']}, open_issues={open_issues}, open_prs={open_prs})",
              file=sys.stderr)

    print(f"\nChecked {checked} candidate repos, found {len(matches)} matching all 4 criteria.",
          file=sys.stderr)

    out = "\n".join(matches)
    if args.output:
        mode = "a" if args.append else "w"
        with open(args.output, mode) as f:
            if out:
                f.write(out + "\n")
        verb = "Appended" if args.append else "Wrote"
        print(f"{verb} {len(matches)} URLs to {args.output} "
              f"(total now: {len(existing_urls) + len(matches)}).", file=sys.stderr)
    else:
        print(out)


if __name__ == "__main__":
    main()
