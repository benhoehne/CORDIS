"""
CORDIS REST API Client
======================
Handles async extraction flow:
  1. Submit query → taskID
  2. Poll getExtractionStatus until complete
  3. Download result from destinationFileUri
"""

import time
import os
import io
import requests
from urllib.parse import urlencode, quote
from typing import Optional, Literal
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn

console = Console()

BASE_URL = "https://cordis.europa.eu"
ENDPOINTS = {
    "getExtraction":       f"{BASE_URL}/api/dataextractions/getExtraction",
    "getExtractionStatus": f"{BASE_URL}/api/dataextractions/getExtractionStatus",
    "cancelExtraction":    f"{BASE_URL}/api/dataextractions/cancelExtraction",
    "deleteExtraction":    f"{BASE_URL}/api/dataextractions/deleteExtraction",
    "listExtractions":     f"{BASE_URL}/api/dataextractions/listExtractions",
}

OutputFormat = Literal["xml", "csv", "json", "xlsx", "summary"]

POLL_INTERVAL_SECONDS = 5   # How often to poll for status
MAX_WAIT_SECONDS = 600       # 10 min max wait


class CordisAPIError(Exception):
    """Raised when the CORDIS API returns an error."""


class CordisClient:
    """
    Client for the CORDIS Data Extraction REST API.

    Parameters
    ----------
    api_key : str
        Your personal CORDIS API key.
    timeout : int
        HTTP request timeout in seconds (default 30).
    """

    def __init__(self, api_key: str, timeout: int = 30):
        if not api_key:
            raise ValueError("CORDIS API key must not be empty.")
        self.api_key = api_key
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

    # ------------------------------------------------------------------
    # Public high-level method
    # ------------------------------------------------------------------

    def extract(
        self,
        query: str,
        output_format: OutputFormat = "json",
        archived: bool = False,
        poll_interval: int = POLL_INTERVAL_SECONDS,
        max_wait: int = MAX_WAIT_SECONDS,
    ) -> bytes:
        """
        Submit a query, wait for completion, and return the raw file bytes.

        Parameters
        ----------
        query : str
            CORDIS search query string.
        output_format : str
            One of xml | csv | json | xlsx | summary.
        archived : bool
            If True, also search archived content.
        poll_interval : int
            Seconds between status polls.
        max_wait : int
            Max seconds to wait before giving up.

        Returns
        -------
        bytes
            Raw content of the downloaded file.
        """
        task_id = self._submit_extraction(query, output_format, archived)
        console.print(f"[bold cyan]⏳ Task submitted.[/] Task ID: [bold]{task_id}[/]")

        destination_uri = self._wait_for_completion(task_id, poll_interval, max_wait)
        console.print(f"[bold green]✓ Extraction complete.[/] Downloading from:\n  {destination_uri}")

        return self._download_file(destination_uri)

    # ------------------------------------------------------------------
    # Internal URL / HTTP helpers
    # ------------------------------------------------------------------

    def _build_url(self, endpoint: str, params: dict) -> str:
        """
        Build a URL with %20-encoded spaces (not + signs).

        The CORDIS API rejects query strings that use '+' for spaces;
        it expects proper percent-encoding (%20).
        """
        qs = urlencode(params, quote_via=quote)
        return f"{endpoint}?{qs}"

    def _get_json(self, url: str) -> dict:
        """
        GET a URL and return parsed JSON.
        Reads the response body before raising HTTP errors so we can
        surface the CORDIS error message from the payload.
        """
        resp = self.session.get(url, timeout=self.timeout)
        try:
            data = resp.json()
        except Exception:
            resp.raise_for_status()   # no JSON → just raise the HTTP error
            raise

        # CORDIS returns status:false with HTTP 4xx for application errors;
        # extract the message before raising so users see the real reason.
        if not resp.ok:
            msg = (
                data.get("payload", {}).get("message")
                or data.get("message")
                or resp.reason
            )
            raise CordisAPIError(
                f"CORDIS API error (HTTP {resp.status_code}): {msg}\n"
                f"Full response: {data}"
            )
        return data

    def _submit_extraction(
        self,
        query: str,
        output_format: OutputFormat,
        archived: bool,
    ) -> int:
        """Submit the extraction job and return taskID."""
        url = self._build_url(ENDPOINTS["getExtraction"], {
            "query": query,
            "key": self.api_key,
            "outputFormat": output_format,
            "archived": str(archived).lower(),
        })
        data = self._get_json(url)

        if not data.get("status"):
            raise CordisAPIError(f"API returned status=False: {data}")

        payload = data.get("payload", {})
        task_id = payload.get("taskID")
        if task_id is None:
            raise CordisAPIError(f"No taskID in response: {data}")
        return task_id

    def _get_status(self, task_id: int) -> dict:
        """Return the status payload dict for a given taskID.

        The getExtractionStatus endpoint returns the status object directly
        in payload (not wrapped in a result list like listExtractions does):
          {"status": true, "payload": {"taskID": ..., "progress": "Ongoing", ...}}
        """
        url = self._build_url(ENDPOINTS["getExtractionStatus"], {
            "key": self.api_key,
            "taskId": task_id,
        })
        data = self._get_json(url)

        if not data.get("status"):
            raise CordisAPIError(f"Status call returned status=False: {data}")

        # payload IS the status object — return it directly
        return data.get("payload", {})

    def _wait_for_completion(
        self, task_id: int, poll_interval: int, max_wait: int
    ) -> str:
        """Poll until extraction is complete; return destinationFileUri."""
        elapsed = 0
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.fields[records]} records"),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("Extracting…", total=100, records="?")

            while elapsed < max_wait:
                status = self._get_status(task_id)
                prog_str = status.get("progress", "")

                # Progress may be a number ("75"), a percentage ("75 %"),
                # or a word ("Ongoing", "Done"). Parse what we can.
                try:
                    pct = float(prog_str.replace("%", "").strip())
                    desc = f"Extracting… {pct:.0f}%"
                except (ValueError, AttributeError):
                    pct = 0.0
                    desc = f"Extracting… ({prog_str})" if prog_str else "Extracting…"

                records_total   = status.get("numberOfRecords", "") or status.get("numberOfRecordsEstimated", "?")
                records_proc    = status.get("numberOfProcessedRecords", "?")
                progress.update(
                    task,
                    completed=pct,
                    description=desc,
                    records=f"{records_proc}/{records_total}",
                )

                dest_uri = status.get("destinationFileUri", "")
                if dest_uri:
                    return dest_uri

                # If numeric progress hits 100 but no URI yet, keep polling briefly
                if pct >= 100:
                    time.sleep(poll_interval)
                    elapsed += poll_interval
                    # One extra check
                    status = self._get_status(task_id)
                    dest_uri = status.get("destinationFileUri", "")
                    if dest_uri:
                        return dest_uri
                    raise CordisAPIError(
                        "Extraction reached 100% but no destinationFileUri returned."
                    )

                time.sleep(poll_interval)
                elapsed += poll_interval

        raise TimeoutError(
            f"Extraction task {task_id} did not complete within {max_wait}s."
        )

    def _download_file(self, uri: str) -> bytes:
        """Download the result file and return its bytes."""
        # destinationFileUri may be a full URL or a relative path
        if not uri.startswith("http"):
            uri = BASE_URL + uri
        resp = self.session.get(uri, timeout=120)
        resp.raise_for_status()
        return resp.content

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def list_extractions(self) -> list[dict]:
        """Return a list of all extraction tasks for this API key."""
        url = self._build_url(ENDPOINTS["listExtractions"], {"key": self.api_key})
        data = self._get_json(url)
        return data.get("payload", {}).get("result", [])

    def cancel_extraction(self, task_id: int) -> dict:
        """Cancel an in-progress extraction task."""
        url = self._build_url(ENDPOINTS["cancelExtraction"], {
            "key": self.api_key, "taskId": task_id,
        })
        return self._get_json(url)

    def delete_extraction(self, task_id: int) -> dict:
        """Delete a completed extraction task."""
        url = self._build_url(ENDPOINTS["deleteExtraction"], {
            "key": self.api_key, "taskId": task_id,
        })
        resp = self.session.delete(url, timeout=self.timeout)
        try:
            data = resp.json()
        except Exception:
            resp.raise_for_status()
            raise
        if not resp.ok:
            msg = data.get("payload", {}).get("message") or resp.reason
            raise CordisAPIError(f"Delete failed (HTTP {resp.status_code}): {msg}")
        return data
