#!/usr/bin/env python3
"""
main.py — Audita atividade de um usuário no GitHub (commits + PRs)
agrupada por repo / mês / PR.

Requer: gh CLI autenticado (gh auth status).
Sem dependências externas (stdlib only).

Uso:
    ./main.py --user felipebossolani --org my-org --year 2026
    ./main.py --user felipebossolani --year 2026          # sem org = global
    ./main.py --user felipebossolani --year 2026 --stdout
    ./main.py --user felipebossolani --year 2026 --detailed  # relatório analítico completo
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

PT_MONTHS = [
    "", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]


def gh_api(endpoint: str, paginate: bool = True) -> list | dict:
    """Chama `gh api` e retorna JSON parseado."""
    cmd = ["gh", "api", "-H", "Accept: application/vnd.github+json"]
    if paginate:
        cmd.append("--paginate")
        cmd += ["--slurp"]  # combina páginas em um array único
    cmd.append(endpoint)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        sys.stderr.write(f"[erro] gh api falhou: {endpoint}\n{e.stderr}\n")
        sys.exit(1)

    return json.loads(result.stdout) if result.stdout.strip() else []


def search_commits(user: str, org: str | None, year: int) -> list[dict]:
    """Busca commits do user no ano. Se org=None, busca global."""
    q_parts = [f"author:{user}", f"author-date:{year}-01-01..{year}-12-31"]
    if org:
        q_parts.append(f"org:{org}")
    q = "+".join(q_parts)

    endpoint = f"/search/commits?q={q}&per_page=100"
    pages = gh_api(endpoint, paginate=True)

    # --slurp envolve cada página num array; cada página é um dict com .items
    commits = []
    for page in pages:
        commits.extend(page.get("items", []))
    return commits


def search_prs(user: str, org: str | None, year: int) -> list[dict]:
    """Busca PRs autorados pelo user no ano."""
    q_parts = [
        f"author:{user}",
        "type:pr",
        f"created:{year}-01-01..{year}-12-31",
    ]
    if org:
        q_parts.append(f"org:{org}")
    q = "+".join(q_parts)

    endpoint = f"/search/issues?q={q}&per_page=100"
    pages = gh_api(endpoint, paginate=True)

    prs = []
    for page in pages:
        prs.extend(page.get("items", []))
    return prs


def pr_commit_shas(repo_full_name: str, pr_number: int) -> set[str]:
    """Retorna set de SHAs dos commits de um PR específico."""
    endpoint = f"/repos/{repo_full_name}/pulls/{pr_number}/commits?per_page=100"
    pages = gh_api(endpoint, paginate=True)

    shas = set()
    for page in pages:
        for c in page:
            shas.add(c["sha"])
    return shas


def repo_from_pr_url(pr: dict) -> str:
    """Extrai 'owner/repo' do PR (search/issues não traz repository diretamente)."""
    # repository_url vem como https://api.github.com/repos/owner/repo
    return pr["repository_url"].replace("https://api.github.com/repos/", "")


def repo_from_commit(commit: dict) -> str:
    return commit["repository"]["full_name"]


def build_sha_index(prs: list[dict]) -> dict[str, dict]:
    """Mapeia SHA -> metadados do PR. Faz uma chamada de API por PR."""
    sha_to_pr: dict[str, dict] = {}

    sys.stderr.write(f"[info] Mapeando commits de {len(prs)} PRs...\n")
    for i, pr in enumerate(prs, 1):
        repo = repo_from_pr_url(pr)
        pr_number = pr["number"]
        sys.stderr.write(f"  [{i}/{len(prs)}] {repo}#{pr_number}\r")
        try:
            shas = pr_commit_shas(repo, pr_number)
        except SystemExit:
            sys.stderr.write(f"\n[warn] falha ao buscar commits de {repo}#{pr_number}, pulando\n")
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
    """Agrupa commits por repo -> mês -> {prs, no_pr}."""
    grouped: dict[str, dict[int, dict]] = defaultdict(
        lambda: defaultdict(lambda: {"prs": defaultdict(list), "no_pr": []})
    )

    for c in commits:
        repo = repo_from_commit(c)
        sha = c["sha"]
        date = datetime.fromisoformat(c["commit"]["author"]["date"].replace("Z", "+00:00"))
        month = date.month
        msg_first_line = c["commit"]["message"].split("\n")[0]

        commit_entry = {
            "sha": sha[:7],
            "date": date.strftime("%Y-%m-%d"),
            "message": msg_first_line,
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
    """Relatório gerencial: uma linha por mês, colunas de métricas."""
    # Agrega por mês (flat, independente de repo)
    monthly: dict[int, dict] = defaultdict(lambda: {
        "commits": 0,
        "prs": set(),       # pr numbers
        "merged": set(),    # pr numbers merged
        "repos": set(),     # repos distintos
        "direct": 0,        # commits sem PR
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

    org_label = org if org else "todas as orgs/repos"
    lines = [
        f"# Atividade de @{user} em {year}",
        "",
        f"**Escopo:** {org_label}  ",
        f"**Total de commits:** {len(commits)}  ",
        f"**Total de PRs:** {len(prs)}  ",
        f"**Gerado em:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "---",
        "",
        "| Mês | Commits | PRs | Merged | Repos | Push direto |",
        "| --- | ------: | --: | -----: | ----: | ----------: |",
    ]

    for month in sorted(monthly.keys()):
        m = monthly[month]
        lines.append(
            f"| {PT_MONTHS[month]} "
            f"| {m['commits']} "
            f"| {len(m['prs'])} "
            f"| {len(m['merged'])} "
            f"| {len(m['repos'])} "
            f"| {m['direct']} |"
        )

    # Totais
    total_commits = sum(m["commits"] for m in monthly.values())
    total_prs = len({n for m in monthly.values() for n in m["prs"]})
    total_merged = len({n for m in monthly.values() for n in m["merged"]})
    total_repos = len({r for repo, months in grouped.items() for r in [repo]})
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
    """Relatório analítico completo: repo -> mês -> PR -> commits."""
    org_label = org if org else "todas as orgs/repos"
    lines = [
        f"# Atividade de @{user} em {year}",
        "",
        f"**Escopo:** {org_label}",
        f"**Total de commits:** {len(commits)}",
        f"**Total de PRs autorados:** {len(prs)}",
        f"**Gerado em:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
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
            lines.append(f"### {PT_MONTHS[month]}")
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
                lines.append("#### _sem PR_")
                lines.append("")
                for c in sorted(month_data["no_pr"], key=lambda x: x["date"]):
                    lines.append(f"- `{c['sha']}` {c['date']} — {c['message']}")
                lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--user", required=True, help="GitHub username alvo")
    parser.add_argument("--org", default=None, help="Org pra filtrar (omita = global)")
    parser.add_argument("--year", required=True, type=int, help="Ano (ex: 2026)")
    parser.add_argument("--stdout", action="store_true", help="Imprime no stdout em vez de salvar arquivo")
    parser.add_argument("--out", default=None, help="Caminho do arquivo de saída (default: ./output/<user>-<year>-activity.md)")
    parser.add_argument("--detailed", action="store_true", help="Relatório analítico completo (repo → mês → PR → commits)")

    args = parser.parse_args()

    sys.stderr.write(f"[info] Buscando commits de @{args.user} em {args.year}")
    if args.org:
        sys.stderr.write(f" (org: {args.org})")
    sys.stderr.write("...\n")
    commits = search_commits(args.user, args.org, args.year)
    sys.stderr.write(f"[info] {len(commits)} commits encontrados\n")

    sys.stderr.write(f"[info] Buscando PRs de @{args.user} em {args.year}...\n")
    prs = search_prs(args.user, args.org, args.year)
    sys.stderr.write(f"[info] {len(prs)} PRs encontrados\n")

    if not commits and not prs:
        sys.stderr.write("[warn] Nenhuma atividade encontrada. Encerrando.\n")
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
        sys.stderr.write(f"[ok] Relatório salvo em: {out_path.resolve()}\n")


if __name__ == "__main__":
    main()
