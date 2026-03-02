# port_agent

AI-powered tool for porting Linux kernel code directories to a downstream kernel tree (e.g. upstream Linux → ChromeOS kernel). Uses Claude to identify commits, apply cherry-picks, analyze conflicts, and validate each commit against kernel coding guidelines — while requiring user approval for every conflict resolution.

## How It Works

```
  UPSTREAM KERNEL                    DOWNSTREAM KERNEL
  (e.g. linux/main)                  (e.g. chromeos-6.6)
         │                                    │
         │   git format-patch | git am        │
         │◄───────────────────────────────────┤
         │                                    │
         ▼                                    ▼
  ┌──────────────────────────────────────────────────────────────┐
  │                        port_agent                            │
  │                                                              │
  │   main.py                                                    │
  │   ┌─────────────────────────────────────────────────────┐   │
  │   │ 1. Load project config (projects.yaml or CLI flags) │   │
  │   │ 2. Validate repos, branches, API key                │   │
  │   │ 3. Create work branch in downstream                 │   │
  │   │ 4. Warn if no --build-cmd supplied                  │   │
  │   │ 5. Load porting_session.json (resume if exists)     │   │
  │   └──────────────────────────┬──────────────────────────┘   │
  │                              │                               │
  │                              ▼                               │
  │   orchestrator.py  (Agentic Loop — claude-sonnet-4-6)        │
  │   ┌─────────────────────────────────────────────────────┐   │
  │   │                                                     │   │
  │   │  ┌─────────────────────────────────────────────┐   │   │
  │   │  │  list_commits_to_port                       │   │   │
  │   │  │  • git log upstream ^merge_base -- dirs     │   │   │
  │   │  │  • Filter already-ported SHAs (downstream   │   │   │
  │   │  │    branch + active work branch)             │   │   │
  │   │  │  • Return commits in oldest-first order     │   │   │
  │   │  └────────────────────┬────────────────────────┘   │   │
  │   │                       │                             │   │
  │   │          ┌────────────▼──────────────┐             │   │
  │   │          │  For each commit (loop)   │             │   │
  │   │          └────────────┬──────────────┘             │   │
  │   │                       │                             │   │
  │   │          ┌────────────▼──────────────┐             │   │
  │   │          │  get_commit_details       │             │   │
  │   │          │  Read diff + message      │             │   │
  │   │          └────────────┬──────────────┘             │   │
  │   │                       │                             │   │
  │   │          ┌────────────▼──────────────┐             │   │
  │   │          │  cherry_pick_commit       │             │   │
  │   │          │  format-patch | git am    │             │   │
  │   │          │  (no cross-repo fetch)    │             │   │
  │   │          └────────────┬──────────────┘             │   │
  │   │                       │                             │   │
  │   │          ┌────────────┴─────────────────────┐      │   │
  │   │          │            │                     │      │   │
  │   │       ✅ Clean   ❌ Conflict        ❌ Manual apply  │   │
  │   │          │            │              (.rej files)  │   │
  │   │          │     ┌──────▼───────┐          │        │   │
  │   │          │     │get_conflict_ │    Read file +    │   │
  │   │          │     │details       │    apply hunks    │   │
  │   │          │     └──────┬───────┘    manually       │   │
  │   │          │            │                │          │   │
  │   │          │     ╔══════▼═══════════════▼═════╗    │   │
  │   │          │     ║  ask_user_to_resolve        ║    │   │
  │   │          │     ║  ── LOOP PAUSED ──          ║    │   │
  │   │          │     ║  Show conflict + suggestion ║    │   │
  │   │          │     ║  User: [A]ccept [M]odify    ║    │   │
  │   │          │     ║        [P]rovide [S]kip [Q] ║    │   │
  │   │          │     ╚══════╤══════════════════════╝    │   │
  │   │          │            │                            │   │
  │   │          │     ┌──────▼───────┐   ┌─────────────┐ │   │
  │   │          │     │finalize_     │   │create_commit│ │   │
  │   │          │     │commit        │   │(manual path)│ │   │
  │   │          │     └──────┬───────┘   └──────┬──────┘ │   │
  │   │          │            └──────────┬────────┘        │   │
  │   │          └───────────────────────┘                 │   │
  │   │                       │                             │   │
  │   │          ┌────────────▼──────────────┐             │   │
  │   │          │  run_checkpatch           │             │   │
  │   │          │  scripts/checkpatch.pl    │             │   │
  │   │          └────────────┬──────────────┘             │   │
  │   │                       │                             │   │
  │   │          ┌────────────▼──────────────┐             │   │
  │   │          │  run_build (if provided)  │             │   │
  │   │          │  make -j$(nproc) <target> │             │   │
  │   │          └────────────┬──────────────┘             │   │
  │   └──────────────────────────────────────────────────  │   │
  │                              │                               │
  │                              ▼                               │
  │   ┌─────────────────────────────────────────────────────┐   │
  │   │  Save porting_session.json + Generate HTML report   │   │
  │   └─────────────────────────────────────────────────────┘   │
  └──────────────────────────────────────────────────────────────┘
         │
         ▼
  DOWNSTREAM KERNEL
  work branch with ported commits
  (one commit per upstream commit, BACKPORT: prefix)
```

### Commit message format after porting

```
BACKPORT: drm/i915: fix vblank timestamp calculation

Fixes incorrect timestamps reported by the hardware counter
when display refresh rate changes during active scanning.

Conflicts:
  drivers/gpu/drm/i915/display/intel_vblank.c: Kept downstream
    platform-specific register offset; applied upstream logic.

(cherry picked from commit a3f8d21b9c04 in linux/main)
```

## Project Structure

```
port_agent/
├── main.py                  # CLI entry point
├── config.py                # Model and iteration config
├── projects.py              # Project registry loader
├── projects.yaml.example    # Template — copy to projects.yaml and edit
├── requirements.txt
├── agents/
│   ├── orchestrator.py      # Claude agentic loop
│   └── tools.py             # Tool schemas + dispatch_tool()
├── git/
│   ├── repo.py              # Git subprocess wrappers
│   └── conflict.py          # Conflict parsing + interactive prompt
└── report/
    └── generator.py         # Jinja2 HTML report
```

## Setup

```bash
cd agentic_AI/port_agent
pip install -r requirements.txt
cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY=sk-ant-...
```

## Usage

There are two ways to run port_agent: **named projects** (recommended for repeated use) or **explicit CLI flags** (for one-off runs).

---

### Option 1 — Named Projects (projects.yaml)

Define your downstream targets once in `projects.yaml`, then refer to them by name on every run.

**Step 1 — Create your projects file:**

```bash
cp projects.yaml.example projects.yaml
```

**Step 2 — Edit `projects.yaml` with your real paths:**

```yaml
projects:

  chromeos-6.6:
    upstream_path:      /home/user/linux          # upstream kernel repo
    upstream_branch:    main
    downstream_path:    /home/user/chromeos-kernel
    downstream_branch:  chromeos-6.6
    dirs:
      - drivers/gpu/drm
      - drivers/gpu/drm/i915
    work_branch_prefix: port/chromeos-6.6         # branch = prefix-YYYYMMDD
    build_cmd:          "make -j$(nproc) drivers/gpu/drm/"

  android-6.1:
    upstream_path:      /home/user/linux
    upstream_branch:    main
    downstream_path:    /home/user/android-kernel
    downstream_branch:  android13-6.1
    dirs:
      - drivers/usb
    work_branch_prefix: port/android-6.1-usb
    build_cmd:          "make -j$(nproc) drivers/usb/"
    since_tag:          v6.1                      # only commits after this tag
```

**Step 3 — Run:**

```bash
# List all defined projects
python main.py --list-projects

# Port using a named project
python main.py --project chromeos-6.6

# Override any field on the fly — CLI always wins over projects.yaml
python main.py --project chromeos-6.6 --dirs drivers/net/wireless --max-commits 20

# Point at a projects file in a different location
python main.py --projects-file /etc/port_agent/projects.yaml --project android-6.1
```

**projects.yaml field reference:**

| Field | Required | Description |
|-------|----------|-------------|
| `upstream_path` | yes | Absolute path to the upstream Linux kernel repo |
| `upstream_branch` | yes | Branch to read commits from |
| `downstream_path` | yes | Absolute path to the downstream kernel repo |
| `downstream_branch` | yes | Base branch in the downstream repo |
| `dirs` | yes | List of subdirectory paths to port |
| `work_branch_prefix` | no | Prefix for the auto-generated work branch name (`prefix-YYYYMMDD`) |
| `build_cmd` | no | Shell command to validate compilation after each commit |
| `since_tag` | no | Only consider upstream commits after this git tag (useful for cross-repo porting) |

The projects file is searched in this order:
1. `--projects-file PATH` (explicit)
2. `./projects.yaml` (current directory)
3. `~/.config/port_agent/projects.yaml` (user-wide config)

---

### Option 2 — Explicit CLI Flags

For one-off runs or when you don't need a projects file:

```bash
python main.py \
  --upstream        /path/to/linux \
  --downstream      /path/to/chromeos-kernel \
  --upstream-branch main \
  --downstream-branch chromeos-6.6 \
  --dirs drivers/gpu/drm drivers/gpu/drm/intel \
  --work-branch port/drm-sync-$(date +%Y%m%d) \
  --build-cmd "make -j$(nproc) drivers/gpu/drm/" \
  --max-commits 30
```

---

### All CLI Options

| Flag | Description |
|------|-------------|
| `--project NAME` | Load settings from a named entry in projects.yaml |
| `--projects-file FILE` | Path to the projects YAML file |
| `--list-projects` | Print all defined projects and exit |
| `--upstream PATH` | Upstream Linux kernel repo path |
| `--downstream PATH` | Downstream kernel repo path |
| `--upstream-branch BRANCH` | Branch in upstream repo (default: `main`) |
| `--downstream-branch BRANCH` | Branch in downstream repo (default: `main`) |
| `--dirs DIR [DIR...]` | Subdirectories to port |
| `--work-branch BRANCH` | Name for the new porting branch |
| `--build-cmd CMD` | Build command run after each commit |
| `--max-commits N` | Cap on commits per session (default: 50) |
| `--since-tag TAG` | Only consider upstream commits after this tag |
| `--dry-run` | List commits to port without applying them |
| `--non-interactive` | Auto-accept Claude's conflict resolutions |

CLI flags always override values from `projects.yaml` when both are supplied.

---

## Available Claude Tools

| Tool | What it does |
|------|-------------|
| `list_commits_to_port` | Find upstream commits not yet in downstream (checks both base branch and active work branch) |
| `get_commit_details` | Read full diff + message for a commit |
| `cherry_pick_commit` | Apply commit via `format-patch \| git am --3way` (no cross-repo fetch) |
| `get_conflict_details` | Parse `<<<<<<<`/`=======`/`>>>>>>>` markers |
| `apply_conflict_resolution` | Write resolved file content + stage it |
| `ask_user_to_resolve_conflict` | **Pause loop** — show conflict and Claude's suggestion to user |
| `run_checkpatch` | Run `scripts/checkpatch.pl --strict` on HEAD |
| `run_build` | Run user-supplied build command |
| `finalize_commit` | `git am --continue` + amend message with BACKPORT prefix |
| `create_commit` | Commit staged files after manual patch application |
| `skip_commit` | Abort current cherry-pick and record the reason |

## Session Resume

The tool saves `porting_session.json` in the downstream repo root after each run. On the next run with the same arguments, already-ported commits are automatically skipped — detected from `cherry picked from commit` lines in git log across both the base branch and the active work branch.

## Requirements

- Python 3.12+
- Git 2.x
- `ANTHROPIC_API_KEY` in `.env`
- For `--project` support: `pyyaml` (included in `requirements.txt`)
- For `run_checkpatch`: `perl` and `scripts/checkpatch.pl` in the downstream repo
- For `run_build`: a configured kernel build tree
