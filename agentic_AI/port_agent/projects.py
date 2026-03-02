"""
Project registry for port_agent.

Loads named downstream-project definitions from a YAML file so users
don't have to spell out full paths on every invocation.

Search order for the YAML file:
  1. Explicit --projects-file PATH from the CLI
  2. ./projects.yaml in the current working directory
  3. ~/.config/port_agent/projects.yaml (user-wide config)

Example projects.yaml:
  See projects.yaml.example in this directory.
"""
import sys
from pathlib import Path
from typing import NamedTuple

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

DEFAULT_PROJECTS_FILE = "projects.yaml"
USER_PROJECTS_FILE = Path.home() / ".config" / "port_agent" / "projects.yaml"


class ProjectConfig(NamedTuple):
    name: str
    downstream_path: str
    downstream_branch: str
    upstream_path: str
    upstream_branch: str
    dirs: list
    work_branch_prefix: object  # str | None
    build_cmd: object           # str | None
    since_tag: object           # str | None


def load_projects(projects_file: object) -> dict:
    """
    Load project definitions from a YAML file.

    Returns a dict mapping project name → ProjectConfig.
    Returns {} if no projects file is found (not an error —
    the user may be using explicit CLI flags).
    """
    if yaml is None:
        print(
            "Error: PyYAML is required for --project / --list-projects support.\n"
            "Install it with:  pip install pyyaml"
        )
        sys.exit(1)

    path = _resolve_projects_file(projects_file)
    if path is None:
        return {}

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        print(f"Error parsing {path}: {exc}")
        sys.exit(1)
    except OSError as exc:
        print(f"Error reading {path}: {exc}")
        sys.exit(1)

    if not isinstance(data, dict) or "projects" not in data:
        return {}

    raw = data.get("projects") or {}
    if not isinstance(raw, dict):
        print(f"Error: 'projects' key in {path} must be a mapping, got {type(raw).__name__}.")
        sys.exit(1)

    result: dict = {}
    for name, cfg in raw.items():
        try:
            result[name] = _parse_project(name, cfg)
        except (KeyError, TypeError, ValueError) as exc:
            print(f"Error in project '{name}': {exc}")
            sys.exit(1)

    return result


def _resolve_projects_file(projects_file: object) -> object:
    """
    Resolve the projects file path.
    Returns a Path, or None if no file was found and none was explicitly requested.
    """
    if projects_file:
        p = Path(str(projects_file))
        if not p.exists():
            print(f"Projects file not found: {projects_file}")
            sys.exit(1)
        return p

    cwd_file = Path(DEFAULT_PROJECTS_FILE)
    if cwd_file.exists():
        return cwd_file

    if USER_PROJECTS_FILE.exists():
        return USER_PROJECTS_FILE

    return None


def _parse_project(name: str, cfg: object) -> ProjectConfig:
    if not isinstance(cfg, dict):
        raise TypeError(f"expected a mapping, got {type(cfg).__name__}")

    for key in ("downstream_path", "downstream_branch", "upstream_path", "upstream_branch", "dirs"):
        if key not in cfg:
            raise KeyError(f"missing required key '{key}'")

    dirs = cfg["dirs"]
    if isinstance(dirs, str):
        dirs = [dirs]
    if not isinstance(dirs, list) or not dirs:
        raise ValueError("'dirs' must be a non-empty list of strings")

    return ProjectConfig(
        name=name,
        downstream_path=str(cfg["downstream_path"]),
        downstream_branch=str(cfg["downstream_branch"]),
        upstream_path=str(cfg["upstream_path"]),
        upstream_branch=str(cfg["upstream_branch"]),
        dirs=[str(d) for d in dirs],
        work_branch_prefix=cfg.get("work_branch_prefix") or None,  # empty string → None (intentional)
        build_cmd=cfg.get("build_cmd") or None,
        since_tag=cfg.get("since_tag") or None,
    )
