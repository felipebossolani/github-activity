# github-activity

Audit a GitHub user's activity (commits + pull requests) over a given year, grouped by repository → month → PR. Output is Markdown, ready to paste into a vault, ticket, or report.

Built for org admins who need to consolidate one person's contributions across many repos without clicking through the GitHub UI.

## What it does

For a given `--user` and `--year`:

1. Fetches all commits authored by the user in that year (optionally scoped to an `--org`)
2. Fetches all PRs authored by the user in that year
3. For each PR, fetches the list of commit SHAs that belong to it
4. Cross-references SHAs to attach commits to their PR
5. Renders a Markdown report grouped by `repo → month → PR`, with a `_no PR_` bucket for direct pushes

When `--org` is omitted, the search runs across every repo the authenticated user can see (public + private with access).

## Requirements

- [`gh` CLI](https://cli.github.com/) authenticated (`gh auth status` should show an active account)
- Token scopes: `repo`, `read:org`
- Python 3.10+ (stdlib only, no `pip install` needed)

For private repos in an org, the active `gh` account needs read access to those repos.

## Install

```bash
git clone https://github.com/felipebossolani/github-activity.git
cd github-activity
chmod +x main.py
```

Optionally symlink to your `$PATH`:

```bash
ln -s "$(pwd)/main.py" ~/.local/bin/gh-activity
```

## Usage

```bash
# Org-scoped audit (most common case)
./main.py --user felipebossolani --org my-org --year 2026

# Global audit (all repos the authenticated account can see)
./main.py --user felipebossolani --year 2026

# Print to stdout instead of writing a file
./main.py --user felipebossolani --org my-org --year 2026 --stdout

# Custom output path
./main.py --user felipebossolani --org my-org --year 2026 --out ./reports/activity.md
```

### Arguments

| Flag        | Required | Description                                                         |
| ----------- | -------- | ------------------------------------------------------------------- |
| `--user`    | yes      | GitHub handle of the target user                                    |
| `--year`    | yes      | Calendar year to audit (e.g. `2026`)                                |
| `--org`     | no       | Restrict search to a single org. Omit for global search             |
| `--stdout`  | no       | Print to stdout instead of writing a file                           |
| `--out`     | no       | Custom output file path (default: `./output/<user>-<year>-activity.md`) |

## Output format

```markdown
# Activity of @felipebossolani in 2026

**Scope:** my-org
**Total commits:** 312
**Total PRs authored:** 47
**Generated at:** 2026-04-28 13:15

---

## my-org/some-repo
_47 commits_

### January

#### [#998](https://github.com/my-org/some-repo/pull/998) — Release into Main _(merged)_

- `abc1234` 2026-01-15 — fix: validation on input X
- `def5678` 2026-01-16 — refactor: extract service Y

#### _no PR_

- `9876543` 2026-01-22 — hotfix on main
```

> The actual report uses Portuguese month names (`Janeiro`, `Fevereiro`, …) and Portuguese labels (`sem PR`). Adjust the `PT_MONTHS` constant and the literal strings in `build_report()` if you need English output.

## Limits and caveats

- **Search API caps results at 1000** per query. If a user has more than 1000 commits or 1000 PRs in a single year, the report will be truncated. The script prints the totals it found — compare against the GitHub UI if you suspect truncation. Workaround: run multiple narrower windows (e.g. by quarter) and concatenate.
- **Authorship is GitHub-username based.** Commits where the Git author email doesn't map to the target GitHub user won't appear. This is unusual for org members with verified emails, but possible.
- **Rate limit.** The Search API allows 30 requests/minute when authenticated. `gh --paginate` waits automatically when the limit is hit.
- **PR commit mapping cost.** The script makes one extra API call per PR to fetch its commits. ~100 PRs ≈ 30–60 seconds.
- **Forks and mirrors.** A commit can appear under multiple repos if force-pushed or cherry-picked. The script trusts what the Search API returns and doesn't deduplicate across repos.

## Why not just use the GitHub contribution graph?

The public contribution graph only counts commits on the default branch or in PRs. Direct pushes to feature branches that never become PRs don't show up. The audit log shows administrative events but not commit content. This script combines `search/commits` + `search/issues` + per-PR commit lookups to give the most complete picture available without org-level streaming infrastructure.

## License

MIT — see [LICENSE](./LICENSE).

## Contributing

Issues and PRs welcome. Suggested improvements:

- Quarterly auto-pagination when totals exceed 1000
- CSV / JSON output formats
- English/i18n locale flag
- PRs reviewed (not just authored)
- Commits as committer (not just author)
