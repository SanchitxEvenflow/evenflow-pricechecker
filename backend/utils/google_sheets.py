import base64
import json
import logging
import os
from typing import Any

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

class GoogleSheetsClient:
    def __init__(self):
        self.credentials = self._load_credentials()
        self.service = None
        if self.credentials:
            self.service = build("sheets", "v4", credentials=self.credentials)
        else:
            logger.warning("Google Sheets credentials not found. Sheets integration will fail.")

    @staticmethod
    def _tab(name: str) -> str:
        """Escape a tab name for use in Sheets API range strings (doubles internal single quotes)."""
        return f"'{name.replace(chr(39), chr(39) + chr(39))}'"

    def _load_credentials(self) -> Credentials | None:
        # 1. Try file path from standard GOOGLE_APPLICATION_CREDENTIALS
        creds_file = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        logger.info("[Sheets] GOOGLE_APPLICATION_CREDENTIALS = %r", creds_file)
        if creds_file:
            exists = os.path.exists(creds_file)
            logger.info("[Sheets] Credentials file exists on disk: %s", exists)
            if exists:
                try:
                    creds = Credentials.from_service_account_file(creds_file, scopes=SCOPES)
                    logger.info("[Sheets] Loaded credentials from file successfully.")
                    return creds
                except Exception as e:
                    logger.error("Failed to load Google credentials from file: %s", e)
        
        # 2. Fallback to base64 env var
        b64_creds = os.getenv("GOOGLE_CREDENTIALS_BASE64")
        logger.info("[Sheets] GOOGLE_CREDENTIALS_BASE64 set: %s", bool(b64_creds))
        if b64_creds:
            try:
                decoded = base64.b64decode(b64_creds).decode("utf-8")
                info = json.loads(decoded)
                return Credentials.from_service_account_info(info, scopes=SCOPES)
            except Exception as e:
                logger.error("Failed to load Google credentials from base64: %s", e)
                
        return None

    def get_asins_with_rows(self, spreadsheet_id: str, tab_name: str) -> list[dict[str, Any]]:
        """
        Reads Columns A:D and returns a list of dictionaries with row number and ASIN.
        Skips the header row (row 1). Only returns rows where column D is "Active".
        """
        if not self.service:
            raise ValueError("Google Sheets service not initialized (missing credentials).")

        range_name = f"{self._tab(tab_name)}!A:D"

        result = self.service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_name
        ).execute()

        values = result.get("values", [])

        asins = []
        for i in range(1, len(values)):
            row_data = values[i]
            if not row_data or not row_data[0].strip():
                continue
            status = row_data[3].strip().lower() if len(row_data) > 3 else "active"
            if status != "active":
                continue
            asins.append({
                "row": i + 1,
                "asin": row_data[0].strip()
            })

        return asins

    def get_products_from_sheet(self, spreadsheet_id: str, tab_name: str) -> list[dict[str, Any]]:
        """Read columns A:D and return active product catalog for the picker UI.

        Skips header row (row 1). Returns [{id, title, brand}] where:
          A = ASIN/FSN/PID, B = Product title, C = Brand, D = Status
        Only rows with Status == "Active" (case-insensitive) are returned.
        """
        if not self.service:
            raise ValueError("Google Sheets service not initialized (missing credentials).")

        range_name = f"{self._tab(tab_name)}!A:D"
        result = self.service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_name
        ).execute()

        values = result.get("values", [])
        products = []
        for i in range(1, len(values)):
            row = values[i]
            if not row or not row[0].strip():
                continue
            status = row[3].strip().lower() if len(row) > 3 else "active"
            if status != "active":
                continue
            products.append({
                "id": row[0].strip(),
                "title": row[1].strip() if len(row) > 1 else "",
                "brand": row[2].strip() if len(row) > 2 else "",
            })
        return products

    def list_tabs(self, spreadsheet_id: str) -> list[str]:
        """Returns all sheet/tab names in the spreadsheet."""
        if not self.service:
            raise ValueError("Google Sheets service not initialized (missing credentials).")
        meta = self.service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        return [s["properties"]["title"] for s in meta.get("sheets", [])]

    def create_tab(self, spreadsheet_id: str, tab_name: str) -> None:
        """Create a new sheet tab in the spreadsheet."""
        if not self.service:
            raise ValueError("Google Sheets service not initialized (missing credentials).")
        body = {"requests": [{"addSheet": {"properties": {"title": tab_name}}}]}
        self.service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body=body).execute()

    def write_header_and_asins(self, spreadsheet_id: str, tab_name: str, asins: list[str]) -> None:
        """Write header row + ASIN list to column A of a newly created tab."""
        if not self.service:
            raise ValueError("Google Sheets service not initialized (missing credentials).")
        rows: list[list[str]] = [
            ["ASIN", "Price", "Rating", "Rating Count", "Rating Breakdown", "Parent Node", "Parent Node Rank", "Child Node", "Child Node Rank", "Status", "Checked At"]
        ]
        rows.extend([[a] for a in asins])
        self.service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{self._tab(tab_name)}!A1",
            valueInputOption="USER_ENTERED",
            body={"values": rows},
        ).execute()

    def write_blinkit_header_and_pids(self, spreadsheet_id: str, tab_name: str, pids: list[str]) -> None:
        """Write wide-format header + PID list to a newly created Blinkit result tab.

        Header: PID | {City} Price | {City} MRP | {City} Status  ×  10 cities  (31 columns total)
        PIDs are written to column A rows 2+.
        """
        if not self.service:
            raise ValueError("Google Sheets service not initialized (missing credentials).")
        from utils.scrape_helpers import BLINKIT_CITIES
        city_cols = []
        for city in BLINKIT_CITIES:
            city_cols.extend([f"{city} Price", f"{city} MRP", f"{city} Status"])
        header = ["PID"] + city_cols
        rows: list[list[str]] = [header] + [[pid] for pid in pids]
        self.service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{self._tab(tab_name)}!A1",
            valueInputOption="USER_ENTERED",
            body={"values": rows},
        ).execute()

    def batch_update_blinkit_rows(self, spreadsheet_id: str, tab_name: str, updates: list[dict[str, Any]]):
        """Batch-update Blinkit result rows.

        Each update: {"row": int, "values": [price, mrp, status] × 10 cities}
        Updates columns B through AE (30 values per row).
        """
        if not self.service:
            raise ValueError("Google Sheets service not initialized (missing credentials).")
        data = []
        for update in updates:
            row = update["row"]
            vals = update["values"]
            data.append({
                "range": f"{self._tab(tab_name)}!B{row}:AE{row}",
                "values": [vals],
            })
        body = {"valueInputOption": "USER_ENTERED", "data": data}
        return self.service.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id, body=body
        ).execute()

    def write_zepto_header_and_pids(self, spreadsheet_id: str, tab_name: str, pids: list[str]) -> None:
        """Write wide-format header + PID list to a newly created Zepto result tab.

        Header: PID | {City} Price | {City} MRP | {City} Status  ×  10 cities  (31 columns total)
        PIDs are written to column A rows 2+.
        """
        if not self.service:
            raise ValueError("Google Sheets service not initialized (missing credentials).")
        from utils.scrape_helpers import ZEPTO_CITIES
        city_cols = []
        for city in ZEPTO_CITIES:
            city_cols.extend([f"{city} Price", f"{city} MRP", f"{city} Status"])
        header = ["PID"] + city_cols
        rows: list[list[str]] = [header] + [[pid] for pid in pids]
        self.service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{self._tab(tab_name)}!A1",
            valueInputOption="USER_ENTERED",
            body={"values": rows},
        ).execute()

    def batch_update_zepto_rows(self, spreadsheet_id: str, tab_name: str, updates: list[dict[str, Any]]):
        """Batch-update Zepto result rows.

        Each update: {"row": int, "values": [price, mrp, status] × 9 cities}
        Updates columns B through AB (27 values per row).
        """
        if not self.service:
            raise ValueError("Google Sheets service not initialized (missing credentials).")
        data = []
        for update in updates:
            row = update["row"]
            vals = update["values"]
            data.append({
                "range": f"{self._tab(tab_name)}!B{row}:AB{row}",
                "values": [vals],
            })
        body = {"valueInputOption": "USER_ENTERED", "data": data}
        return self.service.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id, body=body
        ).execute()

    def batch_update_rows(self, spreadsheet_id: str, tab_name: str, updates: list[dict[str, Any]]):
        """
        Updates multiple rows in the spreadsheet.
        `updates` should be a list of dicts:
        {
            "row": 2,
            "values": ["Price", "Rating", "Rating Count", "Parent Node", "Child Node", "Status", "Checked At"]
        }
        """
        if not self.service:
            raise ValueError("Google Sheets service not initialized (missing credentials).")

        data = []
        for update in updates:
            row = update["row"]
            vals = update["values"]
            
            # We update columns B through K
            range_name = f"{self._tab(tab_name)}!B{row}:K{row}"
            data.append({
                "range": range_name,
                "values": [vals]
            })

        body = {
            "valueInputOption": "USER_ENTERED",
            "data": data
        }

        result = self.service.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body=body
        ).execute()

        return result

    def write_header_and_fsns(self, spreadsheet_id: str, tab_name: str, fsns: list[str]) -> None:
        """Write header row + FSN list to column A of a newly created Flipkart result tab."""
        if not self.service:
            raise ValueError("Google Sheets service not initialized (missing credentials).")
        rows: list[list[str]] = [
            ["FSN", "Price", "MRP", "Discount", "Rating", "Rating Count", "Fulfilled By", "Status", "Checked At"]
        ]
        rows.extend([[f] for f in fsns])
        self.service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{self._tab(tab_name)}!A1",
            valueInputOption="USER_ENTERED",
            body={"values": rows},
        ).execute()

    def batch_update_flipkart_rows(self, spreadsheet_id: str, tab_name: str, updates: list[dict[str, Any]]):
        """Batch-update Flipkart result rows.

        Each update: {"row": int, "values": [price, mrp, discount, rating, rating_count, fulfilled_by, status, checked_at]}
        Updates columns B through I (8 values per row).
        """
        if not self.service:
            raise ValueError("Google Sheets service not initialized (missing credentials).")
        data = []
        for update in updates:
            row = update["row"]
            vals = update["values"]
            data.append({
                "range": f"{self._tab(tab_name)}!B{row}:I{row}",
                "values": [vals],
            })
        body = {"valueInputOption": "USER_ENTERED", "data": data}
        return self.service.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id, body=body
        ).execute()

    # ── Async wrappers (run sync calls in executor to avoid blocking event loop) ──

    async def async_batch_update_rows(self, spreadsheet_id: str, tab_name: str, updates: list[dict]):
        """Async wrapper for batch_update_rows — runs in thread executor."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.batch_update_rows, spreadsheet_id, tab_name, updates)


    async def async_batch_update_blinkit_rows(self, spreadsheet_id: str, tab_name: str, updates: list[dict]):
        """Async wrapper for batch_update_blinkit_rows — runs in thread executor."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.batch_update_blinkit_rows, spreadsheet_id, tab_name, updates)

    async def async_batch_update_zepto_rows(self, spreadsheet_id: str, tab_name: str, updates: list[dict]):
        """Async wrapper for batch_update_zepto_rows — runs in thread executor."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.batch_update_zepto_rows, spreadsheet_id, tab_name, updates)

    def write_instamart_header_and_pids(self, spreadsheet_id: str, tab_name: str, pids: list[str]) -> None:
        """Write wide-format header + PID list to a newly created Instamart result tab.

        Format matches Blinkit/Zepto:
          PID | {City} Price | {City} MRP | {City} Status × 10 cities
        Updates start at A1; PIDs are written to column A rows 2+.
        """
        if not self.service:
            raise ValueError("Google Sheets service not initialized (missing credentials).")
        from utils.scrape_helpers import INSTAMART_CITIES
        city_cols = []
        for city in INSTAMART_CITIES:
            city_cols.extend([f"{city} Price", f"{city} MRP", f"{city} Status"])
        header = ["PID"] + city_cols
        rows: list[list[str]] = [header] + [[pid] for pid in pids]
        self.service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{self._tab(tab_name)}!A1",
            valueInputOption="USER_ENTERED",
            body={"values": rows},
        ).execute()

    def batch_update_instamart_rows(self, spreadsheet_id: str, tab_name: str, updates: list[dict[str, Any]]):
        """Batch-update Instamart result rows.

        Each update: {"row": int, "values": [price, mrp, status] × 10 cities}
        Updates columns B through AE (30 values per row).
        """
        if not self.service:
            raise ValueError("Google Sheets service not initialized (missing credentials).")
        data = []
        for update in updates:
            row = update["row"]
            vals = update["values"]
            data.append({
                "range": f"{self._tab(tab_name)}!B{row}:AE{row}",
                "values": [vals],
            })
        body = {"valueInputOption": "USER_ENTERED", "data": data}
        return self.service.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id, body=body
        ).execute()

    # ── Async wrappers (run sync calls in executor to avoid blocking event loop) ──

    async def async_batch_update_rows(self, spreadsheet_id: str, tab_name: str, updates: list[dict]):
        """Async wrapper for batch_update_rows — runs in thread executor."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.batch_update_rows, spreadsheet_id, tab_name, updates)

    async def async_batch_update_blinkit_rows(self, spreadsheet_id: str, tab_name: str, updates: list[dict]):
        """Async wrapper for batch_update_blinkit_rows — runs in thread executor."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.batch_update_blinkit_rows, spreadsheet_id, tab_name, updates)

    async def async_batch_update_zepto_rows(self, spreadsheet_id: str, tab_name: str, updates: list[dict]):
        """Async wrapper for batch_update_zepto_rows — runs in thread executor."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.batch_update_zepto_rows, spreadsheet_id, tab_name, updates)

    async def async_batch_update_instamart_rows(self, spreadsheet_id: str, tab_name: str, updates: list[dict]):
        """Async wrapper for batch_update_instamart_rows — runs in thread executor."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.batch_update_instamart_rows, spreadsheet_id, tab_name, updates)

    async def async_batch_update_flipkart_rows(self, spreadsheet_id: str, tab_name: str, updates: list[dict]):
        """Async wrapper for batch_update_flipkart_rows — runs in thread executor."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.batch_update_flipkart_rows, spreadsheet_id, tab_name, updates)

