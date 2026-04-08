#!/usr/bin/env python3
import argparse
import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path
import sys
from typing import Dict, List, Set, Tuple
import time
import requests
from datetime import datetime, timezone

# Dynamically add the parent directory (/home/cc/codex) to Python's path
current_dir = Path(__file__).resolve().parent
parent_dir = current_dir.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))
from stats.entry import StatsTool

def run_cmd(
    cmd: List[str],
    cwd: Path | None = None,
    env: Dict[str, str] | None = None,
    capture_output: bool = True,
) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            env=env,
            check=True,
            text=True,
            capture_output=capture_output,
        )
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "").strip()
        stdout = (e.stdout or "").strip()
        details = stderr or stdout or "No stderr/stdout output."
        cmd_text = " ".join(shlex.quote(part) for part in e.cmd)
        raise RuntimeError(
            f"Command failed (exit {e.returncode}): {cmd_text}\n{details}"
        ) from e
    except FileNotFoundError as e:
        missing = cmd[0] if cmd else "<unknown>"
        raise RuntimeError(
            f"Command not found: '{missing}'. Install it and make sure it is in PATH."
        ) from e


def load_map(path: Path) -> List[dict]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("issue_pr_map.json must be a JSON array.")
    return data


def parse_exports(path: Path) -> Dict[str, str]:
    env: Dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("export ") and "=" in stripped:
            _, body = stripped.split("export ", 1)
            key, val = body.split("=", 1)
            env[key.strip()] = val.strip().strip('"').strip("'")
    return env


def ensure_repo(repo_full_name: str, repos_root: Path) -> Tuple[Path, bool]:
    repo_name = repo_full_name.split("/")[-1]
    repo_dir = repos_root / repo_name
    if (repo_dir / ".git").exists():
        return repo_dir, False
    if repo_dir.exists() and not (repo_dir / ".git").exists():
        raise RuntimeError(
            f"Target path exists but is not a git repo: {repo_dir}. "
            "Delete/rename it or choose a different --repos-root."
        )
    try:
        run_cmd(["gh", "repo", "clone", repo_full_name, str(repo_dir)], cwd=repos_root)
    except RuntimeError:
        run_cmd(
            ["git", "clone", f"https://github.com/{repo_full_name}.git", str(repo_dir)],
            cwd=repos_root,
        )
    return repo_dir, True


def gh_api_json(endpoint: str) -> dict:
    out = run_cmd(["gh", "api", endpoint]).stdout
    return json.loads(out)


def gh_api_text(endpoint: str, accept: str) -> str:
    return run_cmd(["gh", "api", endpoint, "-H", f"Accept: {accept}"]).stdout


def parse_agent_template(path: Path) -> Tuple[Dict[str, str], List[str]]:
    text = path.read_text(encoding="utf-8")
    lines = [ln.rstrip() for ln in text.splitlines()]

    export_env = parse_exports(path)
    cmd_start = None
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        if stripped.startswith("claude "):
            cmd_start = i
            break
    if cmd_start is None:
        raise ValueError(f"No Claude command found in {path}.")

    merged = []
    for ln in lines[cmd_start:]:
        stripped = ln.strip()
        if not stripped:
            continue
        if stripped.endswith("\\"):
            merged.append(stripped[:-1].strip())
        else:
            merged.append(stripped)
            break

    cmd_str = " ".join(merged)
    cmd_tokens = shlex.split(cmd_str)
    if not cmd_tokens or cmd_tokens[0] != "claude":
        raise ValueError(f"Failed to parse Claude command: {cmd_str}")

    if cmd_tokens and not cmd_tokens[-1].startswith("-"):
        cmd_tokens = cmd_tokens[:-1]
    return export_env, cmd_tokens


def build_prompt(template: str, issue: dict, pr: dict) -> str:
    issue_title = issue.get("title", "")
    issue_body = issue.get("body", "") or "(empty)"
    pr_title = pr.get("title", "")
    pr_body = pr.get("body", "") or "(empty)"
    pr_url = pr.get("html_url", "")

    return (
        f"{template.strip()}\n\n"
        "## 3) Context from GitHub\n\n"
        f"### Issue: {issue_title}\n\n"
        f"{issue_body}\n\n"
        f"### PR: {pr_title}\n\n"
        f"{pr_body}\n\n"
        f"PR URL: {pr_url}\n"
    )


def parse_changed_paths(repo_dir: Path) -> Set[Path]:
    status = run_cmd(["git", "status", "--porcelain"], cwd=repo_dir).stdout
    changed: Set[Path] = set()
    for raw in status.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        payload = line[3:] if len(line) > 3 else ""
        if " -> " in payload:
            payload = payload.split(" -> ", 1)[1]
        rel_path = Path(payload.strip())
        if rel_path:
            changed.add(rel_path)
    return changed


def collect_special_files(repo_dir: Path) -> Set[Path]:
    keep: Set[Path] = set()
    for p in repo_dir.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(repo_dir)
        name = p.name
        lower = name.lower()
        if name == "Dockerfile" or name.startswith("Dockerfile."):
            keep.add(rel)
            continue
        if lower.startswith("test") and p.suffix == ".py":
            keep.add(rel)
            continue
        if rel.parts and rel.parts[0] == "tests" and p.suffix == ".py":
            keep.add(rel)
    return keep


def copy_repo_files(repo_dir: Path, rel_paths: Set[Path], dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    for rel in sorted(rel_paths):
        src = repo_dir / rel
        if not src.exists() or not src.is_file():
            continue
        dst = dest_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def create_checker_bundle(export_dir: Path, issue: dict, pr: dict, patch_text: str) -> Dict[str, str]:
    bundle_dir = export_dir / "bundle"
    files_dir = export_dir / "files"
    bundle_dir.mkdir(parents=True, exist_ok=True)

    issue_number = int(issue.get("number"))
    issue_url = issue.get("html_url") or issue.get("url") or ""
    base_sha = pr.get("base", {}).get("sha", "")
    head_sha = pr.get("head", {}).get("sha", "")
    bundle_issue = {
        "number": issue_number,
        "url": issue_url,
        "linked_prs": [{"base_sha": base_sha, "head_sha": head_sha, "patch": patch_text}],
    }
    issue_json_path = bundle_dir / f"issue_{issue_number}.json"
    issue_json_path.write_text(json.dumps(bundle_issue, ensure_ascii=False, indent=2), encoding="utf-8")

    docker_src = files_dir / "Dockerfile"
    docker_dst = bundle_dir / "claude.dockerfile"
    docker_root_dst = export_dir / "claude.dockerfile"
    if docker_src.exists() and docker_src.is_file():
        shutil.copy2(docker_src, docker_dst)
        shutil.copy2(docker_src, docker_root_dst)

    copied_tests = 0
    seen_names: Set[str] = set()
    for test_file in sorted(files_dir.rglob("test*.py")):
        if not test_file.is_file():
            continue
        name = test_file.name
        if name in seen_names:
            continue
        seen_names.add(name)
        shutil.copy2(test_file, bundle_dir / name)
        shutil.copy2(test_file, export_dir / name)
        copied_tests += 1

    issue_root_path = export_dir / f"issue_{issue_number}.json"
    shutil.copy2(issue_json_path, issue_root_path)

    return {
        "bundle_dir": str(bundle_dir),
        "bundle_issue_json": str(issue_json_path),
        "bundle_dockerfile": str(docker_dst) if docker_dst.exists() else "",
        "bundle_test_count": str(copied_tests),
        "root_issue_json": str(issue_root_path),
        "root_dockerfile": str(docker_root_dst) if docker_root_dst.exists() else "",
        "root_test_count": str(copied_tests),
    }


def main() -> None:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description="Batch-fetch issues/PRs, run Claude command, and export baseline outputs."
    )
    parser.add_argument("--map-file", default=str(here / "issue_pr_map.json"), help="Path to issue_pr_map.json")
    parser.add_argument("--prompt-file", default=str(here / "prompt.md"), help="Path to prompt template file")
    parser.add_argument("--agent-template", default=str(here / "cc"), help="Path to Claude command template")
    parser.add_argument(
        "--env-file",
        default=str(here.parent / "start_claude_code.sh"),
        help="Shell file with export KEY=VALUE lines",
    )
    parser.add_argument("--repos-root", default=os.getcwd(), help="Root path for cloned repos")
    parser.add_argument("--result-root", default=os.path.join(os.getcwd(), "output"), help="Output root")
    parser.add_argument("--baseline-dir-name", default="Baseline", help="Baseline directory name in each repo")
    parser.add_argument("--dry-run", action="store_true", help="Generate files only; do not invoke Claude")
    args = parser.parse_args()

    if shutil.which("gh") is None:
        raise RuntimeError("Missing required dependency: 'gh'. Install it and run: gh auth login")
    if shutil.which("claude") is None and not args.dry_run:
        raise RuntimeError("Missing required dependency: 'claude'.")

    map_file = Path(args.map_file).expanduser().resolve()
    prompt_file = Path(args.prompt_file).expanduser().resolve()
    agent_template = Path(args.agent_template).expanduser().resolve()
    env_file = Path(args.env_file).expanduser().resolve()
    repos_root = Path(args.repos_root).expanduser().resolve()
    result_root = Path(args.result_root).expanduser().resolve()
    repos_root.mkdir(parents=True, exist_ok=True)
    result_root.mkdir(parents=True, exist_ok=True)

    items = load_map(map_file)
    prompt_template = prompt_file.read_text(encoding="utf-8")
    template_env, agent_base_cmd = parse_agent_template(agent_template)
    start_env = parse_exports(env_file)
    base_env = os.environ.copy()
    base_env.update(start_env)
    base_env.update(template_env)

    for idx, item in enumerate(items, start=1):
        instance_start_time = datetime.now(timezone.utc)
        start_time_sec = time.time()
        repo = item["repo"]
        issue_number = int(item["issue_number"])
        pr_number = int(item["pr_number"])
        print(f"[{idx}/{len(items)}] Processing {repo} issue#{issue_number} pr#{pr_number}")

        repo_dir, cloned_now = ensure_repo(repo, repos_root)
        if not cloned_now:
            print(f"  - Cleaning repository {repo.split('/')[-1]} for a pristine run...")
            run_cmd(["git", "reset", "--hard"], cwd=repo_dir)
            run_cmd(["git", "clean", "-fd"], cwd=repo_dir)
        baseline_dir = repo_dir / args.baseline_dir_name
        baseline_dir.mkdir(parents=True, exist_ok=True)

        issue = gh_api_json(f"repos/{repo}/issues/{issue_number}")
        pr = gh_api_json(f"repos/{repo}/pulls/{pr_number}")
        patch_text = gh_api_text(f"repos/{repo}/pulls/{pr_number}", "application/vnd.github.v3.patch")

        (baseline_dir / "issue.json").write_text(json.dumps(issue, ensure_ascii=False, indent=2), encoding="utf-8")
        (baseline_dir / "pr.json").write_text(json.dumps(pr, ensure_ascii=False, indent=2), encoding="utf-8")
        (baseline_dir / f"pr_{pr_number}.patch").write_text(patch_text, encoding="utf-8")
        (baseline_dir / f"issue_{issue_number}.md").write_text(issue.get("body", "") or "", encoding="utf-8")

        agent_prompt = build_prompt(prompt_template, issue, pr)
        agent_prompt_file = baseline_dir / f"claude_prompt_{issue_number}.md"
        agent_prompt_file.write_text(agent_prompt, encoding="utf-8")

        # print("  - Starting native Forge stats tracker...")
        # stats_tool = StatsTool(verbose=True)
        # stats_tool.record_session_start()
        # print("  - Waiting 10 seconds for Forge API metrics to sync...")
        # time.sleep(10)

        if not args.dry_run:
            cmd = agent_base_cmd + [agent_prompt]
            print(f"  - running Claude in {repo_dir} ...")
            run_cmd(cmd, cwd=repo_dir, env=base_env, capture_output=False)

        # print("  - Ending native Forge stats tracker...")
        # stats_tool.record_session_end()
        # print("  - Waiting 25 seconds for Forge API metrics to sync...")
        # time.sleep(25)

        repo_name = repo.split("/")[-1]
        export_dir = result_root / repo_name / str(issue_number)
        meta_dir = export_dir / "metadata"
        files_dir = export_dir / "files"
        meta_dir.mkdir(parents=True, exist_ok=True)

        shutil.copy2(baseline_dir / "issue.json", meta_dir / "issue.json")
        shutil.copy2(baseline_dir / "pr.json", meta_dir / "pr.json")
        shutil.copy2(baseline_dir / f"pr_{pr_number}.patch", meta_dir / f"pr_{pr_number}.patch")
        shutil.copy2(baseline_dir / f"issue_{issue_number}.md", meta_dir / f"issue_{issue_number}.md")
        shutil.copy2(agent_prompt_file, meta_dir / agent_prompt_file.name)

        changed_paths = parse_changed_paths(repo_dir)
        keep_paths = changed_paths | collect_special_files(repo_dir)
        copy_repo_files(repo_dir, keep_paths, files_dir)

        instance_end_time = datetime.now(timezone.utc)
        duration_seconds = round(time.time() - start_time_sec, 2)

         # move stats.json to the instance's output directory
        stats_source = parent_dir / "baseline"/ "envgym" / "stat.json"
        stats_dest = export_dir / "stat.json"

        forge_stats_data = {}
        if stats_source.exists():
            shutil.move(str(stats_source), str(stats_dest))
            print(f"  -> Moved stat.json to {stats_dest}")

            # Extract the data so it can be added to the summary.json below
            try:
                with open(stats_dest, "r", encoding="utf-8") as f:
                    full_data = json.load(f)
                    # Isolate just the cost of this specific instance run
                    forge_stats_data = full_data.get("usage_delta", full_data)
                    print(f"  -> Extracted Cost: ${forge_stats_data.get('cost', 0):.6f}")
            except Exception as e:
                print(f"  -> Warning: Could not read stat.json: {e}")
        else:
            print(f"  -> Warning: {stats_source} was not found. Looked in: {stats_source}")

        summary = {
            "repo": repo,
            "issue_number": issue_number,
            "pr_number": pr_number,
            "export_dir": str(export_dir),
            "changed_files_count": len(changed_paths),
            "kept_files_count": len(keep_paths),
            "repo_removed": cloned_now,
            "instance_timing": {
                "start_time": instance_start_time.isoformat(),
                "end_time": instance_end_time.isoformat(),
                "duration_seconds": duration_seconds
            },
            "forge_stats": forge_stats_data,
        }
        summary.update(create_checker_bundle(export_dir, issue, pr, patch_text))
        (export_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

        if cloned_now:
            shutil.rmtree(repo_dir)
            print(f"  - exported to {export_dir} and removed cloned repo")
        else:
            print(f"  - exported to {export_dir}; repo kept because it existed before this run")

    print("All repositories processed.")


if __name__ == "__main__":
    main()
