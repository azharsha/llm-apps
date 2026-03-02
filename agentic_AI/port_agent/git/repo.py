"""
Low-level git subprocess wrappers for port_agent.

All functions raise RuntimeError on unexpected failures. Expected partial
failures (cherry-pick conflict, build error) return success=False with
details rather than raising.
"""
import re
import subprocess
from pathlib import Path


def _run(cmd: list[str], cwd: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
    )


# ---------------------------------------------------------------------------
# Commit discovery
# ---------------------------------------------------------------------------

def get_commits_to_port(
    upstream_path: str,
    downstream_path: str,
    upstream_branch: str,
    downstream_branch: str,
    dirs: list[str],
    max_commits: int = 50,
    since_tag: str | None = None,
) -> list[dict]:
    """
    Find commits in upstream/upstream_branch touching dirs that are NOT
    already present in downstream/downstream_branch.

    Strategy:
    1. If since_tag is given, use it as the exclusive lower bound:
         git log upstream_branch ^since_tag -- dirs
       This is the recommended approach when the two repos don't share
       git history (e.g. upstream linux vs chromeos kernel).
    2. Otherwise, try to detect the merge-base by SHA comparison and
       use that as the lower bound.
    3. Filter out commits already ported via cherry-pick -x attribution
       found in downstream commit messages.

    Returns list of {hash, subject, author, date} in oldest-first order
    (topological order for correct cherry-picking).
    """
    already_ported = _get_already_ported_shas(downstream_path, downstream_branch)

    # Also check the current branch (work_branch) — it may have commits from
    # an in-progress session that aren't on downstream_branch yet.
    current_branch = get_current_branch(downstream_path)
    if current_branch != downstream_branch:
        already_ported |= _get_already_ported_shas(downstream_path, current_branch)

    if since_tag:
        # Explicit lower bound — most reliable for cross-repo porting
        exclude_ref = f"^{since_tag}"
    else:
        # Attempt auto-detection via SHA comparison
        merge_base = _get_merge_base(
            upstream_path, upstream_branch, downstream_path, downstream_branch
        )
        exclude_ref = f"^{merge_base}" if merge_base else ""

    # Fetch commits newest-first (git default). We read more than needed so that
    # after filtering already-ported SHAs we still have enough. A safety cap
    # prevents reading millions of lines when no lower bound is known; users
    # should always set --since-tag for cross-repo porting.
    # IMPORTANT: do NOT use --reverse here. git log --max-count=N --reverse
    # selects the N *newest* commits and then reverses them, which is wrong —
    # it would skip the oldest unported commits. We reverse in Python below
    # after collection so we get the *oldest* commits first.
    _safety_cap = max(max_commits * 20, 2000)

    cmd = ["git", "log", upstream_branch]
    if exclude_ref:
        cmd.append(exclude_ref)
    cmd += [
        "--format=%H\x1f%s\x1f%an\x1f%ad",
        "--date=short",
        f"--max-count={_safety_cap}",
        "--",
    ] + dirs

    result = _run(cmd, cwd=upstream_path)
    # git log is newest-first; reverse to get oldest-first (correct cherry-pick order)
    raw_lines = [ln for ln in result.stdout.strip().splitlines() if ln.strip()]
    raw_lines.reverse()

    commits = []
    for line in raw_lines:
        parts = line.split("\x1f", 3)
        if len(parts) != 4:
            continue
        commit_hash, subject, author, date = parts
        short = commit_hash[:12]
        if short in already_ported or commit_hash in already_ported:
            continue
        commits.append({
            "hash": commit_hash,
            "subject": subject,
            "author": author,
            "date": date,
        })
        if len(commits) >= max_commits:
            break

    return commits


def _get_merge_base(
    upstream_path: str,
    upstream_branch: str,
    downstream_path: str,
    downstream_branch: str,
) -> str | None:
    """
    Find the common ancestor commit of upstream_branch and downstream_branch.
    Because they may be different repos, we find the merge-base by checking
    which upstream commits are also present in the downstream by SHA.
    Returns the upstream SHA of the divergence point, or None if not found.
    """
    # Cap history to a reasonable depth — full kernel history is millions of
    # commits and loading it all would be extremely slow.
    _MAX_HISTORY = 100_000

    ds_result = _run(
        ["git", "log", downstream_branch, "--format=%H", f"--max-count={_MAX_HISTORY}"],
        cwd=downstream_path,
        check=False,
    )
    downstream_shas: set[str] = set(ds_result.stdout.strip().splitlines())

    # Walk upstream commits newest-first to find the most recent shared commit.
    us_result = _run(
        ["git", "log", upstream_branch, "--format=%H", f"--max-count={_MAX_HISTORY}"],
        cwd=upstream_path,
        check=False,
    )
    for sha in us_result.stdout.strip().splitlines():
        if sha in downstream_shas:
            return sha

    return None


def _get_already_ported_shas(downstream_path: str, downstream_branch: str) -> set[str]:
    """
    Parse downstream commit messages for cherry-pick attribution lines:
      (cherry picked from commit <sha> ...)
    Returns a set of upstream SHAs (both full and 12-char prefix).
    """
    result = _run(
        ["git", "log", downstream_branch,
         "--grep=cherry picked from commit",
         "--format=%B"],
        cwd=downstream_path,
        check=False,
    )
    shas: set[str] = set()
    for line in result.stdout.splitlines():
        m = re.search(r"cherry picked from commit ([0-9a-f]{7,40})", line)
        if m:
            sha = m.group(1)
            shas.add(sha)
            shas.add(sha[:12])
    return shas


# ---------------------------------------------------------------------------
# Commit details
# ---------------------------------------------------------------------------

def get_commit_details(
    repo_path: str,
    commit_hash: str,
    max_diff_chars: int = 12000,
) -> dict:
    """
    Return full commit message + diff for a single commit.
    """
    _SENTINEL = "XPORT_AGENT_MSG_END_4f9a2b1c8e3d7f6x"
    show = _run(
        ["git", "show", "--stat=200", f"--format=COMMIT_MSG_START%n%H%n%an%n%ae%n%ad%n%n%s%n%n%b%n{_SENTINEL}", commit_hash],
        cwd=repo_path,
    )
    raw = show.stdout

    # Split header from diff
    if _SENTINEL in raw:
        header_part, _, diff_part = raw.partition(_SENTINEL)
    else:
        header_part, diff_part = raw, ""

    lines = header_part.strip().splitlines()
    # Skip "COMMIT_MSG_START" sentinel
    idx = 0
    if lines and lines[0] == "COMMIT_MSG_START":
        idx = 1

    commit_sha = lines[idx] if idx < len(lines) else commit_hash
    author = lines[idx + 1] if idx + 1 < len(lines) else ""
    date = lines[idx + 3] if idx + 3 < len(lines) else ""
    subject = lines[idx + 5] if idx + 5 < len(lines) else ""
    body = "\n".join(lines[idx + 7:]) if idx + 7 < len(lines) else ""

    truncated = len(diff_part) > max_diff_chars
    diff_snippet = diff_part[:max_diff_chars]

    # Count changed files from stat lines
    files_changed = [
        ln.strip().split()[0]
        for ln in diff_part.splitlines()
        if ln.strip() and "|" in ln
    ]

    return {
        "hash": commit_sha,
        "subject": subject.strip(),
        "author": author.strip(),
        "date": date.strip(),
        "body": body.strip(),
        "diff": diff_snippet,
        "files_changed": files_changed,
        "truncated": truncated,
    }


# ---------------------------------------------------------------------------
# Setup: no cross-repo fetch needed
# ---------------------------------------------------------------------------

def setup_upstream_remote(
    downstream_path: str,
    upstream_path: str,
    upstream_branch: str,
) -> dict:
    """
    No-op: port_agent uses format-patch|am instead of cherry-pick, so no
    cross-repo object fetch is required. Kept for API compatibility.
    """
    return {"success": True, "output": "patch-based mode — no remote fetch needed"}


# ---------------------------------------------------------------------------
# Patch directory for format-patch/am workflow
# ---------------------------------------------------------------------------

import tempfile as _tempfile

_PATCH_DIR = Path(_tempfile.gettempdir()) / "port_agent_patches"


def _patch_path(commit_hash: str) -> Path:
    _PATCH_DIR.mkdir(exist_ok=True)
    return _PATCH_DIR / f"{commit_hash[:12]}.patch"


# ---------------------------------------------------------------------------
# Cherry-pick operations (implemented as format-patch + git am --3way)
# ---------------------------------------------------------------------------

def create_work_branch(repo_path: str, branch_name: str, base_branch: str) -> None:
    """Create and checkout a new work branch from base_branch."""
    _run(["git", "checkout", "-b", branch_name, base_branch], cwd=repo_path)


def cherry_pick(
    downstream_path: str,
    commit_hash: str,
    upstream_path: str | None = None,
) -> dict:
    """
    Apply an upstream commit to the downstream work branch.

    Strategy: format-patch in the upstream repo, then git am --3way in
    the downstream repo. This works without any cross-repo git fetch,
    making it fast regardless of repo sizes.

    If upstream_path is None, falls back to plain git cherry-pick (for
    same-repo usage).

    Returns:
        {"success": True} on clean apply
        {"success": False, "conflicted_files": [...], "error_output": str} on conflict
    """
    if upstream_path:
        return _am_apply(downstream_path, commit_hash, upstream_path)
    # Same-repo fallback
    result = _run(
        ["git", "cherry-pick", "-x", commit_hash],
        cwd=downstream_path,
        check=False,
    )
    if result.returncode == 0:
        return {"success": True}
    conflicted = _get_conflicted_files(downstream_path)
    return {
        "success": False,
        "conflicted_files": conflicted,
        "error_output": (result.stderr + result.stdout)[:3000],
    }


def _am_apply(downstream_path: str, commit_hash: str, upstream_path: str) -> dict:
    """
    Export the commit as a patch from upstream_path and apply it into downstream_path.

    Attempt order:
    1. git am --3way  (works when repos share objects)
    2. git am         (plain patch apply against working tree)
    3. git apply --reject  (apply what can; produce .rej for mismatched hunks)
       → Claude will manually apply the failed hunks using file content + patch diff.
    """
    patch_file = _patch_path(commit_hash)

    # 1. Generate the patch
    fmt = _run(
        ["git", "format-patch", "-1", "--stdout", "--no-numbered", commit_hash],
        cwd=upstream_path,
        check=False,
    )
    if fmt.returncode != 0:
        return {
            "success": False,
            "error": f"git format-patch failed: {fmt.stderr.strip()}",
            "conflicted_files": [],
        }
    patch_file.write_text(fmt.stdout, encoding="utf-8")

    # 2a. Try --3way first
    am = _run(
        ["git", "am", "--3way", "--keep-cr", str(patch_file)],
        cwd=downstream_path, check=False,
    )
    if am.returncode == 0:
        patch_file.unlink(missing_ok=True)
        return {"success": True}
    _run(["git", "am", "--abort"], cwd=downstream_path, check=False)

    # 2b. Try plain am
    am = _run(
        ["git", "am", "--keep-cr", str(patch_file)],
        cwd=downstream_path, check=False,
    )
    if am.returncode == 0:
        patch_file.unlink(missing_ok=True)
        return {"success": True}
    _run(["git", "am", "--abort"], cwd=downstream_path, check=False)

    # 2c. git apply --reject — writes .rej files for failed hunks, applies the rest
    _run(
        ["git", "apply", "--reject", "--ignore-whitespace", str(patch_file)],
        cwd=downstream_path, check=False,
    )

    # Collect files that need manual resolution (have .rej counterparts)
    affected_files = _files_from_patch(fmt.stdout)
    manual_files = []
    for f in affected_files:
        rej_path = Path(downstream_path) / (f + ".rej")
        if rej_path.exists():
            manual_files.append({
                "file": f,
                "rej_content": rej_path.read_text(encoding="utf-8", errors="replace")[:3000],
            })

    patch_file.unlink(missing_ok=True)
    return {
        "success": False,
        "mode": "manual_apply_needed",
        "conflicted_files": manual_files,   # files needing manual hunk application
        "affected_files": affected_files,
        "patch_content": fmt.stdout[:8000],
        "error_output": (am.stderr + am.stdout)[:2000],
    }


def _files_from_patch(patch_text: str) -> list[str]:
    """Extract the list of files modified by a patch."""
    return [line[6:].strip() for line in patch_text.splitlines()
            if line.startswith("+++ b/")]


def create_commit(repo_path: str, message: str) -> dict:
    """
    Commit all staged changes with the given message.
    Used after manual patch application (when git am is not in progress).
    """
    result = _run(["git", "commit", "-m", message], cwd=repo_path, check=False)
    return {
        "success": result.returncode == 0,
        "output": (result.stdout + result.stderr)[:1000],
        "commit_hash": get_last_commit_hash(repo_path) if result.returncode == 0 else None,
    }



def abort_cherry_pick(repo_path: str) -> None:
    """Abort an in-progress am or cherry-pick."""
    _run(["git", "am", "--abort"], cwd=repo_path, check=False)
    _run(["git", "cherry-pick", "--abort"], cwd=repo_path, check=False)


def _get_conflicted_files(repo_path: str) -> list[str]:
    """Return list of files with conflict markers from git status."""
    status = _run(["git", "status", "--short", "--porcelain"], cwd=repo_path)
    conflicted = []
    for line in status.stdout.splitlines():
        xy = line[:2]
        path = line[3:].strip()
        if "U" in xy or xy in ("AA", "DD"):
            conflicted.append(path)
    return conflicted


def continue_cherry_pick(repo_path: str) -> dict:
    """
    Run git am --continue (or cherry-pick --continue) after all conflicts
    are resolved and staged.
    """
    result = _run(
        ["git", "am", "--continue"],
        cwd=repo_path,
        check=False,
    )
    if result.returncode != 0:
        # Fall back to cherry-pick --continue for same-repo case
        result = _run(
            ["git", "-c", "core.editor=true", "cherry-pick", "--continue"],
            cwd=repo_path,
            check=False,
        )
    return {
        "success": result.returncode == 0,
        "output": (result.stdout + result.stderr)[:2000],
    }


def stage_file(repo_path: str, file_path: str) -> None:
    """Stage a single file after conflict resolution."""
    _run(["git", "add", file_path], cwd=repo_path)


def amend_commit_message(repo_path: str, message: str) -> dict:
    """Amend the last commit's message."""
    result = _run(
        ["git", "commit", "--amend", "-m", message],
        cwd=repo_path,
        check=False,
    )
    return {"success": result.returncode == 0, "output": result.stdout[:1000]}


def get_last_commit_hash(repo_path: str) -> str:
    """Return the current HEAD commit hash."""
    r = _run(["git", "rev-parse", "HEAD"], cwd=repo_path)
    return r.stdout.strip()


def get_last_commit_message(repo_path: str) -> str:
    """Return the last commit message."""
    r = _run(["git", "log", "-1", "--format=%B"], cwd=repo_path)
    return r.stdout.strip()


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def run_checkpatch(
    repo_path: str,
    mode: str = "commit",
    target: str = "HEAD",
) -> dict:
    """
    Run scripts/checkpatch.pl.

    mode="commit": checks git format-patch output of target commit
    mode="patch":  target is a path to a .patch file

    Returns:
        {passed, errors, warnings, checks, raw_output}
    """
    checkpatch = Path(repo_path) / "scripts" / "checkpatch.pl"
    if not checkpatch.exists():
        return {
            "passed": True,
            "errors": [],
            "warnings": [],
            "checks": [],
            "raw_output": "checkpatch.pl not found — skipped",
        }

    if mode == "commit":
        patch_proc = subprocess.run(
            ["git", "format-patch", "-1", "--stdout", target],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        if patch_proc.returncode != 0:
            return {
                "passed": False,
                "errors": [f"git format-patch failed: {patch_proc.stderr.strip()}"],
                "warnings": [],
                "checks": [],
                "raw_output": patch_proc.stderr[:3000],
            }
        check_proc = subprocess.run(
            ["perl", str(checkpatch), "--no-tree", "--strict", "-"],
            input=patch_proc.stdout,
            capture_output=True,
            text=True,
            cwd=repo_path,
        )
        raw = check_proc.stdout + check_proc.stderr
    else:
        check_proc = subprocess.run(
            ["perl", str(checkpatch), "--no-tree", "--strict", target],
            capture_output=True,
            text=True,
            cwd=repo_path,
        )
        raw = check_proc.stdout + check_proc.stderr

    return _parse_checkpatch_output(raw)


def _parse_checkpatch_output(raw: str) -> dict:
    errors, warnings, checks = [], [], []
    for line in raw.splitlines():
        if line.startswith("ERROR:"):
            errors.append(line[6:].strip())
        elif line.startswith("WARNING:"):
            warnings.append(line[8:].strip())
        elif line.startswith("CHECK:"):
            checks.append(line[6:].strip())

    return {
        "passed": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "raw_output": raw[:3000],
    }


def run_build(repo_path: str, build_cmd: str, timeout: int = 600) -> dict:
    """
    Run an arbitrary build command and parse compiler errors.
    """
    try:
        result = subprocess.run(
            build_cmd,
            shell=True,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "errors": [f"Build timed out after {timeout}s"],
            "warnings": [],
            "output": f"Build command exceeded timeout of {timeout} seconds.",
        }
    raw = result.stdout + result.stderr
    errors = [ln for ln in raw.splitlines() if ": error:" in ln or "Error " in ln]
    warnings_list = [ln for ln in raw.splitlines() if ": warning:" in ln]
    return {
        "success": result.returncode == 0,
        "errors": errors[:50],
        "warnings": warnings_list[:20],
        "output": raw[-3000:],
    }


# ---------------------------------------------------------------------------
# Branch helpers
# ---------------------------------------------------------------------------

def checkout_branch(repo_path: str, branch_name: str) -> None:
    """Checkout an existing branch."""
    _run(["git", "checkout", branch_name], cwd=repo_path)


def get_current_branch(repo_path: str) -> str:
    r = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path)
    return r.stdout.strip()


def branch_exists(repo_path: str, branch_name: str) -> bool:
    result = _run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"],
        cwd=repo_path,
        check=False,
    )
    return result.returncode == 0
