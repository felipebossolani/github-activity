# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-file Python CLI (`main.py`) that audits a GitHub user's commits and PRs for a given year, producing a Markdown report grouped by `repo → month → PR`. No external dependencies — stdlib only.

## Running the script

```bash
# Org-scoped audit
./main.py --user <handle> --org <org> --year 2026

# Global audit (all repos the authenticated account can see)
./main.py --user <handle> --year 2026

# Print to stdout instead of writing a file
./main.py --user <handle> --org <org> --year 2026 --stdout
```

Prerequisites: `gh` CLI authenticated (`gh auth status`) with scopes `repo` and `read:org`.

## Architecture

Everything lives in `gh-activity.py`. The flow is:

1. `search_commits()` / `search_prs()` — hit GitHub Search API via `gh api --paginate --slurp`
2. `pr_commit_shas()` — one extra API call per PR to map SHA → PR
3. `build_report()` — cross-references the SHA map, groups into `repo → month → pr_key`, renders Markdown

Key data shape: `grouped[repo][month] = {"prs": {pr_key: [commits]}, "no_pr": [commits]}` where `pr_key = (number, title, url, state, merged)`.

## Known limits

- GitHub Search API caps at 1000 results per query — truncation is silent beyond that. Workaround: run per-quarter and concatenate.
- ~1 extra API call per PR for commit mapping; 100 PRs ≈ 30–60 s.
- Output month names are in Portuguese (`PT_MONTHS`). To change to English, edit `PT_MONTHS` and the `_sem PR_` literal in `build_report()`.
