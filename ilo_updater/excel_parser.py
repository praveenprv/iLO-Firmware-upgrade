"""
Excel parser and report generator for HPE iLO inventory.
Handles flexible column names, validation, and status report export.
"""

import os
from datetime import datetime
from typing import List, Dict, Any, Optional
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter


COLUMN_MAPPINGS = {
    "server_name": [
        "server name", "server", "hostname", "host", "name", 
        "server_name", "server-name", "device", "node"
    ],
    "ilo_ip": [
        "ilo ip", "ilo_ip", "ip address", "ip", "ilo address", 
        "management ip", "ilo", "ilo_address", "ip_address", "host ip"
    ],
    "username": [
        "username", "user name", "user", "login", "admin", 
        "account", "user_name", "ilo username", "ilo user"
    ],
    "password": [
        "password", "pass", "pwd", "secret", "ilo password", 
        "ilo pass", "passwd"
    ],
    "ilo_type": [
        "ilo type", "type", "generation", "ilo generation", 
        "gen", "ilo gen", "model", "ilo_type", "ilo version"
    ]
}


def normalize_header(header: Optional[str]) -> str:
    """Normalize a header string for case-insensitive and punctuation-free matching."""
    if not header:
        return ""
    return str(header).strip().lower().replace("_", " ").replace("-", " ")


def identify_columns(headers: List[Optional[str]]) -> Dict[str, int]:
    """Map required logical fields to column indices based on header names."""
    field_to_col: Dict[str, int] = {}
    normalized_headers = [normalize_header(h) for h in headers]

    for field, aliases in COLUMN_MAPPINGS.items():
        matched = False
        for alias in aliases:
            for idx, header in enumerate(normalized_headers):
                if alias == header:
                    field_to_col[field] = idx
                    matched = True
                    break
            if matched:
                break

        # Secondary fallback: partial match if exact match not found
        if not matched:
            for alias in aliases:
                for idx, header in enumerate(normalized_headers):
                    if alias in header:
                        field_to_col[field] = idx
                        matched = True
                        break
                if matched:
                    break

    return field_to_col


def read_ilo_inventory(file_path: str) -> List[Dict[str, Any]]:
    """
    Read iLO inventory from an Excel sheet.
    Returns a list of dictionaries with normalized keys:
    [
        {
            "row_index": 2,
            "server_name": "DL380-Gen10-Node01",
            "ilo_ip": "192.168.1.50",
            "username": "Administrator",
            "password": "Password123!",
            "ilo_type": "iLO5",
            "raw_data": {...}
        },
        ...
    ]
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Inventory Excel file not found: {file_path}")

    wb = openpyxl.load_workbook(file_path, data_only=True)
    sheet = wb.active
    if not sheet:
        raise ValueError(f"No active worksheet found in {file_path}")

    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        raise ValueError(f"Excel file is empty: {file_path}")

    header_row_idx = None
    headers: List[Optional[str]] = []

    # Find the header row (the first row containing identifiable iLO fields)
    for r_idx, row in enumerate(rows):
        test_headers = [str(cell) if cell is not None else "" for cell in row]
        cols = identify_columns(test_headers)
        if "ilo_ip" in cols or "server_name" in cols:
            header_row_idx = r_idx
            headers = test_headers
            break

    if header_row_idx is None:
        raise ValueError(
            "Could not identify required columns in Excel sheet. "
            "Please ensure headers include at least 'iLO IP' and 'Username'."
        )

    col_map = identify_columns(headers)
    if "ilo_ip" not in col_map:
        raise ValueError("Missing required column: 'iLO IP' (or IP / Host).")

    inventory = []
    for r_idx in range(header_row_idx + 1, len(rows)):
        row = rows[r_idx]
        if not row or all(cell is None or str(cell).strip() == "" for cell in row):
            continue  # Skip blank row

        def get_val(field: str, default: str = "") -> str:
            if field in col_map and col_map[field] < len(row):
                val = row[col_map[field]]
                return str(val).strip() if val is not None else default
            return default

        ilo_ip = get_val("ilo_ip")
        if not ilo_ip:
            continue  # Skip rows without IP

        server_name = get_val("server_name", default=f"Server-{ilo_ip}")
        username = get_val("username", default="Administrator")
        password = get_val("password", default="")
        ilo_type = get_val("ilo_type", default="Auto-detect")

        # Normalize ilo_type (e.g., 'ilo 5', '5', 'Gen10' -> 'iLO5')
        clean_type = ilo_type.upper().replace(" ", "").replace("-", "")
        if "ILO5" in clean_type or clean_type == "5":
            normalized_type = "iLO5"
        elif "ILO6" in clean_type or clean_type == "6":
            normalized_type = "iLO6"
        elif "ILO7" in clean_type or clean_type == "7":
            normalized_type = "iLO7"
        elif "ILO4" in clean_type or clean_type == "4":
            normalized_type = "iLO4"
        else:
            normalized_type = ilo_type or "iLO5"

        inventory.append({
            "row_index": r_idx + 1,  # 1-based Excel row number
            "server_name": server_name,
            "ilo_ip": ilo_ip,
            "username": username,
            "password": password,
            "ilo_type": normalized_type,
            "current_fw": None,
            "detected_model": None,
            "server_model": None,
            "status": "Pending Check",
            "error": None
        })

    wb.close()
    return inventory


def generate_sample_excel(output_path: str = "ilo_inventory_template.xlsx") -> str:
    """Generate a clean, pre-styled template Excel sheet for the user."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "iLO Inventory"

    # Styling definitions
    header_fill = PatternFill(start_color="003366", end_color="003366", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    data_font = Font(name="Calibri", size=11)
    thin_border = Border(
        left=Side(style="thin", color="D3D3D3"),
        right=Side(style="thin", color="D3D3D3"),
        top=Side(style="thin", color="D3D3D3"),
        bottom=Side(style="thin", color="D3D3D3")
    )

    headers = [
        "Server Name",
        "iLO IP",
        "Username",
        "Password",
        "iLO Type",
        "Notes / Location"
    ]

    ws.append(headers)

    sample_rows = [
        ["Prod-DB-Server-01", "192.168.10.51", "Administrator", "HPEpassword123!", "iLO5", "Rack 1 - U12 (DL380 Gen10)"],
        ["Prod-DB-Server-02", "192.168.10.52", "Administrator", "HPEpassword123!", "iLO5", "Rack 1 - U14 (DL380 Gen10)"],
        ["Prod-Web-Node-01",  "192.168.10.61", "Administrator", "Admin@Secure2026", "iLO6", "Rack 2 - U20 (DL360 Gen11)"],
        ["Prod-Web-Node-02",  "192.168.10.62", "Administrator", "Admin@Secure2026", "iLO6", "Rack 2 - U22 (DL360 Gen11)"],
        ["Compute-Cluster-01","192.168.10.71", "Administrator", "ClusterPass#1",   "iLO5", "Rack 3 - U05 (Synergy / DL380)"]
    ]

    for row_data in sample_rows:
        ws.append(row_data)

    # Style header
    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    # Style data rows
    for row_idx in range(2, len(sample_rows) + 2):
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.font = data_font
            cell.border = thin_border
            if col_idx in [2, 5]:  # IP and Type center-aligned
                cell.alignment = Alignment(horizontal="center")

    # Adjust column widths
    for col in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = max(max_len + 4, 15)

    wb.save(output_path)
    wb.close()
    return output_path


def export_upgrade_report(results: List[Dict[str, Any]], original_file: str) -> str:
    """
    Export a detailed post-upgrade verification report to Excel.
    Saves as iLO_Upgrade_Report_<timestamp>.xlsx in the same folder.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_dir = os.path.dirname(original_file) or "."
    report_filename = f"iLO_Upgrade_Report_{timestamp}.xlsx"
    report_path = os.path.join(base_dir, report_filename)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Upgrade Results"

    headers = [
        "Server Name",
        "iLO IP",
        "iLO Type",
        "Initial Firmware",
        "New Firmware",
        "Upgrade Status",
        "iLO Reset & Verified",
        "Completion Time",
        "Details / Error"
    ]
    ws.append(headers)

    header_fill = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    success_fill = PatternFill(start_color="D9EAD3", end_color="D9EAD3", fill_type="solid")
    failed_fill = PatternFill(start_color="F4CCCC", end_color="F4CCCC", fill_type="solid")
    skipped_fill = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
    data_font = Font(name="Calibri", size=11)
    thin_border = Border(
        left=Side(style="thin", color="CCCCCC"),
        right=Side(style="thin", color="CCCCCC"),
        top=Side(style="thin", color="CCCCCC"),
        bottom=Side(style="thin", color="CCCCCC")
    )

    for item in results:
        status = item.get("status", "Unknown")
        row = [
            item.get("server_name", ""),
            item.get("ilo_ip", ""),
            item.get("ilo_type", ""),
            item.get("initial_fw", "N/A"),
            item.get("new_fw", "N/A"),
            status,
            item.get("reset_verified", "No"),
            item.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            item.get("details", "")
        ]
        ws.append(row)

        current_row_idx = ws.max_row
        row_fill = None
        if "SUCCESS" in status.upper():
            row_fill = success_fill
        elif "FAIL" in status.upper() or "ERROR" in status.upper():
            row_fill = failed_fill
        elif "SKIP" in status.upper():
            row_fill = skipped_fill

        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=current_row_idx, column=col_idx)
            cell.font = data_font
            cell.border = thin_border
            if row_fill and col_idx == 6:  # Highlight status column
                cell.fill = row_fill

    # Header styling
    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    # Column widths
    for col in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = max(max_len + 3, 14)

    wb.save(report_path)
    wb.close()
    return report_path
