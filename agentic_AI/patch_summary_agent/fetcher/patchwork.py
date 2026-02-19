"""
Patchwork REST API client for patchwork.kernel.org.

API reference: https://patchwork.kernel.org/api/
"""
import time
import requests
from datetime import datetime, timezone, timedelta
from config import PATCHWORK_BASE_URL, REQUEST_TIMEOUT

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "lkml-patch-summary-agent/1.0"})


def _get(url: str, params: dict = None, retries: int = 3) -> dict | list:
    """GET with simple exponential backoff on transient failures."""
    for attempt in range(retries):
        try:
            resp = _SESSION.get(url, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as e:
            if e.response.status_code in (429, 503) and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
        except requests.RequestException:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise


def fetch_patches(limit: int = 15, days_back: float = 1, project: str = None) -> list:
    """
    Fetch recent patches from Patchwork, ordered newest-first.

    Args:
        limit:     Maximum number of patches to return.
        days_back: How many days back to look.
        project:   Optional project name or numeric ID to filter by.

    Returns:
        List of patch dicts (metadata only, no diff).
    """
    # Patchwork rejects timezone-offset strings — use a plain YYYY-MM-DD date.
    since = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")

    params = {
        "order": "-date",
        "per_page": min(limit, 100),
        "since": since,
    }
    if project:
        params["project"] = project

    data = _get(f"{PATCHWORK_BASE_URL}/patches/", params=params)

    # API may return a dict with 'results' key (DRF pagination)
    if isinstance(data, dict):
        return data.get("results", [])
    return data


def fetch_patch_by_id(patch_id: int) -> dict:
    """
    Fetch a single patch with full content and diff.

    The individual endpoint includes `content` (commit message) and `diff`
    fields that are not present in list responses.
    """
    return _get(f"{PATCHWORK_BASE_URL}/patches/{patch_id}/")


def fetch_series_by_id(series_id: int) -> dict:
    """Fetch a series object, which includes its list of patches."""
    return _get(f"{PATCHWORK_BASE_URL}/series/{series_id}/")


def fetch_projects(limit: int = 50) -> list:
    """Fetch the list of Patchwork projects (kernel subsystem queues)."""
    data = _get(f"{PATCHWORK_BASE_URL}/projects/", params={"per_page": limit})
    if isinstance(data, dict):
        return data.get("results", [])
    return data
