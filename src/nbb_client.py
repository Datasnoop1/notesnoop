"""NBB CBSO API client.

Wraps the Authentic Data Query and Daily Extract endpoints.
JSON format only — available for XBRL filings since April 2022.

Configuration via .env:
    NBB_AUTHENTIC_KEY — subscription key for /authentic/ endpoints (company filings)
    NBB_EXTRACT_KEY   — subscription key for /extracts/ endpoints (daily batch)
    NBB_API_KEY       — fallback key used for both if specific keys not set
    NBB_BASE_URL      — base URL (default: UAT2 test environment)

Usage:
    from src.nbb_client import NBBClient
    client = NBBClient()
    refs = client.get_references("0403101811")
    filing = client.get_filing_json(refs[0]["depositKey"])
"""

import os
import time
import uuid
from datetime import datetime

import requests
from dotenv import load_dotenv

load_dotenv()

UAT2_URL = "https://ws.uat2.cbso.nbb.be"
PROD_URL = "https://ws.cbso.nbb.be"

DEFAULT_DELAY = 0.3      # seconds between requests
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0      # multiplier per retry


def log(msg):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


class NBBError(Exception):
    """Raised when the NBB API returns an unexpected error."""
    def __init__(self, status_code, message):
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}: {message}")


class NBBClient:
    """Client for the NBB CBSO REST API.

    Args:
        api_key:  NBB subscription key. Falls back to NBB_API_KEY env var.
        base_url: API base URL. Falls back to NBB_BASE_URL env var, then UAT2.
        delay:    Seconds to wait between requests (default 1.5s).
    """

    def __init__(self, api_key=None, base_url=None, delay=DEFAULT_DELAY,
                 authentic_key=None, extract_key=None):
        # Support separate keys per subscription type, with fallback to api_key
        fallback = api_key or os.getenv("NBB_API_KEY", "")
        self.authentic_key = authentic_key or os.getenv("NBB_AUTHENTIC_KEY", fallback)
        self.extract_key   = extract_key   or os.getenv("NBB_EXTRACT_KEY",   fallback)
        self.base_url = (base_url or os.getenv("NBB_BASE_URL", UAT2_URL)).rstrip("/")
        self.delay = delay
        self._last_request_time = 0.0
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        })

    def _request(self, method, path, accept, **kwargs):
        """Execute a request with rate limiting and retry on 429/5xx."""
        url = f"{self.base_url}{path}"
        # Route the correct subscription key based on endpoint group
        key = self.extract_key if path.startswith("/extracts/") else self.authentic_key
        headers = {
            "X-Request-Id": str(uuid.uuid4()),
            "Accept": accept,
            "NBB-CBSO-Subscription-Key": key,
        }

        for attempt in range(1, MAX_RETRIES + 1):
            # Enforce minimum delay between requests
            elapsed = time.time() - self._last_request_time
            if elapsed < self.delay:
                time.sleep(self.delay - elapsed)

            try:
                resp = self.session.request(method, url, headers=headers, **kwargs)
                self._last_request_time = time.time()
            except requests.RequestException as e:
                if attempt == MAX_RETRIES:
                    raise
                wait = RETRY_BACKOFF ** attempt
                log(f"  Request error ({e}), retry {attempt}/{MAX_RETRIES} in {wait:.0f}s")
                time.sleep(wait)
                continue

            if resp.status_code == 200:
                return resp

            if resp.status_code == 404:
                return None  # No data — caller decides how to handle

            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == MAX_RETRIES:
                    raise NBBError(resp.status_code, resp.text[:200])
                wait = RETRY_BACKOFF ** attempt
                log(f"  HTTP {resp.status_code}, retry {attempt}/{MAX_RETRIES} in {wait:.0f}s")
                time.sleep(wait)
                continue

            # 400, 401, 403 — don't retry
            raise NBBError(resp.status_code, resp.text[:200])

        raise NBBError(0, "Max retries exceeded")

    # ------------------------------------------------------------------
    # Authentic Data Query endpoints
    # ------------------------------------------------------------------

    def get_references(self, cbe_number, fiscal_year=None):
        """Get all filing references for a company.

        Args:
            cbe_number:  10-digit CBE number without dots (e.g. "0403101811").
            fiscal_year: Optional int/str to filter by fiscal year.

        Returns:
            List of reference dicts, or [] if no data found.
            Each dict has at minimum: depositKey, fiscalYear, depositDate.
        """
        cbe = str(cbe_number).replace(".", "")
        path = f"/authentic/legalEntity/{cbe}/references"
        params = {}
        if fiscal_year:
            params["fiscalYear"] = str(fiscal_year)

        resp = self._request("GET", path, "application/json", params=params or None)
        if resp is None:
            return []
        return resp.json()

    def get_filing_json(self, deposit_key):
        """Get JSON (XBRL-derived) data for a single filing.

        Args:
            deposit_key: Filing reference in format "YYYY-NNNNNNNN".

        Returns:
            Parsed JSON dict, or None if not found.
        """
        path = f"/authentic/deposit/{deposit_key}/accountingData"
        resp = self._request("GET", path, "application/x.jsonxbrl")
        if resp is None:
            return None
        return resp.json()

    def get_filing_pdf(self, deposit_key):
        """Get PDF bytes for a filing.

        Returns:
            bytes, or None if not found.
        """
        path = f"/authentic/deposit/{deposit_key}/accountingData"
        resp = self._request("GET", path, "application/pdf")
        if resp is None:
            return None
        return resp.content

    # ------------------------------------------------------------------
    # Daily extract endpoints
    # ------------------------------------------------------------------

    def get_extract_references(self, date):
        """Get all filing references published on a given date (ZIP of JSON).

        Args:
            date: "YYYY-MM-DD" string or datetime.date.

        Returns:
            Response object with .content (ZIP bytes), or None if no data.
        """
        date_str = str(date)
        path = f"/extracts/batch/{date_str}/references"
        return self._request("GET", path, "application/x.zip+json")

    def get_extract_json(self, date):
        """Get all JSON filings published on a given date (ZIP of JSON).

        Args:
            date: "YYYY-MM-DD" string or datetime.date.

        Returns:
            Response object with .content (ZIP bytes), or None if no data.
        """
        date_str = str(date)
        path = f"/extracts/batch/{date_str}/accountingData"
        return self._request("GET", path, "application/x.zip+jsonxbrl")

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def get_latest_filing_json(self, cbe_number):
        """Return JSON data for the most recent filing of a company, or None."""
        refs = self.get_references(cbe_number)
        if not refs:
            return None
        # Sort by depositDate descending, take first
        refs_sorted = sorted(
            refs,
            key=lambda r: r.get("depositDate") or r.get("DepositDate") or "",
            reverse=True,
        )
        ref = refs_sorted[0]
        deposit_key = ref.get("depositKey") or ref.get("ReferenceNumber")
        if not deposit_key:
            return None
        return self.get_filing_json(deposit_key)

    def iter_company_filings(self, cbe_number, since_year=None):
        """Yield (deposit_key, fiscal_year, deposit_date, json_data) for each filing.

        Filings are yielded oldest-first. Skips filings where JSON is unavailable.

        Args:
            cbe_number: 10-digit CBE number.
            since_year: Only include filings with fiscal_year >= since_year.
        """
        refs = self.get_references(cbe_number)
        if not refs:
            return

        if since_year:
            refs = [r for r in refs if int(r.get("fiscalYear", 0)) >= int(since_year)]

        refs_sorted = sorted(refs, key=lambda r: r.get("depositDate", ""))

        for ref in refs_sorted:
            deposit_key = ref.get("depositKey")
            if not deposit_key:
                continue
            data = self.get_filing_json(deposit_key)
            if data is None:
                continue
            yield deposit_key, ref.get("fiscalYear"), ref.get("depositDate"), data


# ------------------------------------------------------------------
# CLI — test / inspect individual companies
# ------------------------------------------------------------------

def main():
    import argparse, json

    parser = argparse.ArgumentParser(description="Query NBB CBSO API")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_refs = sub.add_parser("refs", help="List filing references for a company")
    p_refs.add_argument("cbe", help="CBE number (10 digits)")
    p_refs.add_argument("--year", help="Filter by fiscal year")

    p_filing = sub.add_parser("filing", help="Fetch JSON for a specific filing")
    p_filing.add_argument("deposit_key", help="Deposit key e.g. 2021-00000132")

    p_latest = sub.add_parser("latest", help="Fetch latest JSON filing for a company")
    p_latest.add_argument("cbe", help="CBE number (10 digits)")

    p_extract = sub.add_parser("extract-refs", help="List filing refs published on a date")
    p_extract.add_argument("date", help="Date in YYYY-MM-DD format")

    parser.add_argument("--env", default=UAT2_URL,
                        help="Base URL (default: UAT2 test environment)")
    args = parser.parse_args()

    client = NBBClient(base_url=os.getenv("NBB_BASE_URL", UAT2_URL))

    if args.cmd == "refs":
        result = client.get_references(args.cbe, fiscal_year=args.year)
        print(json.dumps(result, indent=2))
        log(f"{len(result)} reference(s) found")

    elif args.cmd == "filing":
        result = client.get_filing_json(args.deposit_key)
        if result is None:
            log("No data found (404)")
        else:
            print(json.dumps(result, indent=2))

    elif args.cmd == "latest":
        result = client.get_latest_filing_json(args.cbe)
        if result is None:
            log("No data found")
        else:
            print(json.dumps(result, indent=2))

    elif args.cmd == "extract-refs":
        resp = client.get_extract_references(args.date)
        if resp is None:
            log("No data found (404)")
        else:
            log(f"Got ZIP: {len(resp.content):,} bytes")
            # Show first few entries from the ZIP
            import zipfile, io
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                names = zf.namelist()
                log(f"Files in ZIP: {len(names)}")
                for name in names[:5]:
                    with zf.open(name) as f:
                        data = json.load(f)
                        print(json.dumps(data, indent=2))
                    break  # just show first one


if __name__ == "__main__":
    main()
