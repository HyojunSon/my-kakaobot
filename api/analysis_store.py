"""Fresh Supabase reads; never silently use old Git drawings after DB errors."""
import os
from urllib.parse import urlparse
import requests


def source_mode():
    mode = os.environ.get("HTS_DATA_SOURCE", "").strip().lower()
    if not mode:
        return "supabase" if os.environ.get("SUPABASE_URL") else "snapshot"
    if mode not in {"snapshot", "supabase"}:
        raise ValueError("Unknown HTS_DATA_SOURCE")
    return mode


def fetch_analysis_rows():
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SECRET_KEY", "") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    parsed = urlparse(url)
    if (parsed.scheme != "https" or not (parsed.hostname or "").endswith(".supabase.co")
            or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment
            or parsed.port not in {None, 443} or not key):
        raise ValueError("Supabase server settings are incomplete or invalid")
    headers = {"apikey": key, "Prefer": "count=exact"}
    # New sb_secret keys are not JWTs; legacy service-role JWTs are.
    if key.startswith("eyJ"):
        headers["Authorization"] = "Bearer "+key
    rows, cursor = [], None
    while True:
        params = {"select": "symbol,name,drawings,revision,updated_at", "order": "symbol.asc", "limit": "500"}
        if cursor:
            params["symbol"] = "gt."+cursor
        response = requests.get(url+"/rest/v1/chart_analysis", params=params, headers=headers,
                                timeout=(1.5, 2), allow_redirects=False)
        if response.status_code not in {200, 206}:
            raise ValueError(f"Analysis database unavailable (HTTP {response.status_code})")
        page = response.json()
        if not isinstance(page, list):
            raise ValueError("Invalid analysis database response")
        if not page:
            break
        for row in page:
            if not isinstance(row.get("drawings"), list):
                raise ValueError("Invalid saved analysis")
        rows.extend(page)
        new_cursor = page[-1]["symbol"]
        if cursor is not None and new_cursor <= cursor:
            raise ValueError("Analysis pagination did not advance")
        cursor = new_cursor
        # Exact count is for the current cursor-filtered query. A short page
        # is not sufficient evidence of completeness if server limits differ.
        total = response.headers.get("Content-Range", "").rsplit("/", 1)[-1]
        if total.isdigit() and len(page) >= int(total):
            break
    return rows
