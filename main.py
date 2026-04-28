#!/usr/bin/env python3
"""
main.py — Audits a GitHub user's activity (commits + PRs)
grouped by repo / month / PR.

Requires: gh CLI authenticated (gh auth status).
No external dependencies (stdlib only).

Usage:
    ./main.py --user felipebossolani --org my-org --year 2026
    ./main.py --user felipebossolani --year 2026          # no org = global
    ./main.py --user felipebossolani --year 2026 --stdout
    ./main.py --user felipebossolani --year 2026 --detailed  # full analytical report
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

MONTHS = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def gh_api(endpoint: str, paginate: bool = True) -> list | dict:
    cmd = ["gh", "api", "-H", "Accept: application/vnd.github+json"]
    if paginate:
        cmd.append("--paginate")
        cmd += ["--slurp"]  # merges pages into a single array
    cmd.append(endpoint)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        sys.stderr.write(f"[error] gh api failed: {endpoint}\n{e.stderr}\n")
        sys.exit(1)

    return json.loads(result.stdout) if result.stdout.strip() else []


def search_commits(user: str, org: str | None, year: int) -> list[dict]:
    q_parts = [f"author:{user}", f"author-date:{year}-01-01..{year}-12-31"]
    if org:
        q_parts.append(f"org:{org}")
    q = "+".join(q_parts)

    pages = gh_api(f"/search/commits?q={q}&per_page=100", paginate=True)
    commits = []
    for page in pages:
        commits.extend(page.get("items", []))
    return commits


def search_prs(user: str, org: str | None, year: int) -> list[dict]:
    q_parts = [
        f"author:{user}",
        "type:pr",
        f"created:{year}-01-01..{year}-12-31",
    ]
    if org:
        q_parts.append(f"org:{org}")
    q = "+".join(q_parts)

    pages = gh_api(f"/search/issues?q={q}&per_page=100", paginate=True)
    prs = []
    for page in pages:
        prs.extend(page.get("items", []))
    return prs


def pr_commit_shas(repo_full_name: str, pr_number: int) -> set[str]:
    pages = gh_api(f"/repos/{repo_full_name}/pulls/{pr_number}/commits?per_page=100", paginate=True)
    shas = set()
    for page in pages:
        for c in page:
            shas.add(c["sha"])
    return shas


def repo_from_pr_url(pr: dict) -> str:
    return pr["repository_url"].replace("https://api.github.com/repos/", "")


def repo_from_commit(commit: dict) -> str:
    return commit["repository"]["full_name"]


def build_sha_index(prs: list[dict]) -> dict[str, dict]:
    """Maps SHA -> PR metadata. Makes one API call per PR."""
    sha_to_pr: dict[str, dict] = {}

    sys.stderr.write(f"[info] Mapping commits across {len(prs)} PRs...\n")
    for i, pr in enumerate(prs, 1):
        repo = repo_from_pr_url(pr)
        pr_number = pr["number"]
        sys.stderr.write(f"  [{i}/{len(prs)}] {repo}#{pr_number}\r")
        try:
            shas = pr_commit_shas(repo, pr_number)
        except SystemExit:
            sys.stderr.write(f"\n[warn] failed to fetch commits for {repo}#{pr_number}, skipping\n")
            continue
        for sha in shas:
            sha_to_pr[sha] = {
                "number": pr_number,
                "title": pr["title"],
                "url": pr["html_url"],
                "state": pr["state"],
                "merged": pr.get("pull_request", {}).get("merged_at") is not None,
                "repo": repo,
            }
    sys.stderr.write("\n")
    return sha_to_pr


def build_grouped(commits: list[dict], sha_to_pr: dict[str, dict]) -> dict:
    """Groups commits by repo -> month -> {prs, no_pr}."""
    grouped: dict[str, dict[int, dict]] = defaultdict(
        lambda: defaultdict(lambda: {"prs": defaultdict(list), "no_pr": []})
    )

    for c in commits:
        repo = repo_from_commit(c)
        sha = c["sha"]
        date = datetime.fromisoformat(c["commit"]["author"]["date"].replace("Z", "+00:00"))
        month = date.month

        commit_entry = {
            "sha": sha[:7],
            "date": date.strftime("%Y-%m-%d"),
            "message": c["commit"]["message"].split("\n")[0],
            "url": c["html_url"],
        }

        bucket = grouped[repo][month]
        if sha in sha_to_pr:
            pr = sha_to_pr[sha]
            pr_key = (pr["number"], pr["title"], pr["url"], pr["state"], pr["merged"])
            bucket["prs"][pr_key].append(commit_entry)
        else:
            bucket["no_pr"].append(commit_entry)

    return grouped


def build_summary(
    user: str, org: str | None, year: int, commits: list[dict], prs: list[dict],
    sha_to_pr: dict[str, dict], grouped: dict,
) -> str:
    """Management report: one row per month with key metrics."""
    monthly: dict[int, dict] = defaultdict(lambda: {
        "commits": 0,
        "prs": set(),
        "merged": set(),
        "repos": set(),
        "direct": 0,
    })

    for repo, months in grouped.items():
        for month, data in months.items():
            m = monthly[month]
            for pr_key, pr_commits in data["prs"].items():
                number, title, url, state, merged = pr_key
                m["commits"] += len(pr_commits)
                m["prs"].add(number)
                if merged:
                    m["merged"].add(number)
                m["repos"].add(repo)
            direct = data["no_pr"]
            m["commits"] += len(direct)
            m["direct"] += len(direct)
            if direct:
                m["repos"].add(repo)

    org_label = org if org else "all orgs/repos"
    lines = [
        f"# Activity report — @{user} ({year})",
        "",
        f"**Scope:** {org_label}  ",
        f"**Total commits:** {len(commits)}  ",
        f"**Total PRs:** {len(prs)}  ",
        f"**Generated at:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "---",
        "",
        "| Month | Commits | PRs | Merged | Repos | Direct push |",
        "| ----- | ------: | --: | -----: | ----: | ----------: |",
    ]

    for month in sorted(monthly.keys()):
        m = monthly[month]
        lines.append(
            f"| {MONTHS[month]} "
            f"| {m['commits']} "
            f"| {len(m['prs'])} "
            f"| {len(m['merged'])} "
            f"| {len(m['repos'])} "
            f"| {m['direct']} |"
        )

    total_commits = sum(m["commits"] for m in monthly.values())
    total_prs = len({n for m in monthly.values() for n in m["prs"]})
    total_merged = len({n for m in monthly.values() for n in m["merged"]})
    total_repos = len(grouped)
    total_direct = sum(m["direct"] for m in monthly.values())

    lines += [
        f"| **Total** | **{total_commits}** | **{total_prs}** | **{total_merged}** | **{total_repos}** | **{total_direct}** |",
        "",
    ]

    return "\n".join(lines)


def build_detailed(
    user: str, org: str | None, year: int, commits: list[dict], prs: list[dict],
    grouped: dict,
) -> str:
    """Full analytical report: repo -> month -> PR -> commits."""
    org_label = org if org else "all orgs/repos"
    lines = [
        f"# Activity report — @{user} ({year})",
        "",
        f"**Scope:** {org_label}",
        f"**Total commits:** {len(commits)}",
        f"**Total PRs authored:** {len(prs)}",
        f"**Generated at:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "---",
        "",
    ]

    for repo in sorted(grouped.keys()):
        repo_commits = sum(
            len(commits_list)
            for month_data in grouped[repo].values()
            for commits_list in [*month_data["prs"].values(), month_data["no_pr"]]
        )
        lines.append(f"## {repo}")
        lines.append(f"_{repo_commits} commits_")
        lines.append("")

        for month in sorted(grouped[repo].keys()):
            month_data = grouped[repo][month]
            lines.append(f"### {MONTHS[month]}")
            lines.append("")

            for pr_key, pr_commits in sorted(month_data["prs"].items()):
                number, title, url, state, merged = pr_key
                status = "merged" if merged else state
                lines.append(f"#### [#{number}]({url}) — {title} _({status})_")
                lines.append("")
                for c in sorted(pr_commits, key=lambda x: x["date"]):
                    lines.append(f"- `{c['sha']}` {c['date']} — {c['message']}")
                lines.append("")

            if month_data["no_pr"]:
                lines.append("#### _no PR_")
                lines.append("")
                for c in sorted(month_data["no_pr"], key=lambda x: x["date"]):
                    lines.append(f"- `{c['sha']}` {c['date']} — {c['message']}")
                lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--user", required=True, help="Target GitHub username")
    parser.add_argument("--org", default=None, help="Restrict to a single org (omit for global search)")
    parser.add_argument("--year", required=True, type=int, help="Year to audit (e.g. 2026)")
    parser.add_argument("--stdout", action="store_true", help="Print to stdout instead of writing a file")
    parser.add_argument("--out", default=None, help="Output file path (default: ./output/<user>-<year>-activity.md)")
    parser.add_argument("--detailed", action="store_true", help="Full analytical report (repo → month → PR → commits)")

    args = parser.parse_args()

    sys.stderr.write(f"[info] Fetching commits for @{args.user} in {args.year}")
    if args.org:
        sys.stderr.write(f" (org: {args.org})")
    sys.stderr.write("...\n")
    commits = search_commits(args.user, args.org, args.year)
    sys.stderr.write(f"[info] {len(commits)} commits found\n")

    sys.stderr.write(f"[info] Fetching PRs for @{args.user} in {args.year}...\n")
    prs = search_prs(args.user, args.org, args.year)
    sys.stderr.write(f"[info] {len(prs)} PRs found\n")

    if not commits and not prs:
        sys.stderr.write("[warn] No activity found. Exiting.\n")
        sys.exit(0)

    sha_to_pr = build_sha_index(prs)
    grouped = build_grouped(commits, sha_to_pr)

    if args.detailed:
        report = build_detailed(args.user, args.org, args.year, commits, prs, grouped)
    else:
        report = build_summary(args.user, args.org, args.year, commits, prs, sha_to_pr, grouped)

    if args.stdout:
        print(report)
    else:
        suffix = "-detailed" if args.detailed else ""
        out_path = Path(args.out) if args.out else Path(f"./output/{args.user}-{args.year}-activity{suffix}.md")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        sys.stderr.write(f"[ok] Report saved to: {out_path.resolve()}\n")


if __name__ == "__main__":
    main()
