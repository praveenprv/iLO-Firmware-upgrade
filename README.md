# HPE iLO Firmware Upgrade Automation Suite (Redfish RESTful API)

An enterprise-grade automation solution designed for **Windows System Administrators** to query, flash, reset, and verify firmware updates across **HPE iLO 4, iLO 5, iLO 6, and iLO 7** management processors using the DMTF Redfish RESTful API.

---

## Key Features

- **Automated Excel Inventory Ingestion**: Reads server names, iLO IP addresses, credentials, and iLO generations from standard `.xlsx` files with flexible column headers.
- **Step 1 - Live Firmware & Hardware Auditing**: Connects to each iLO, authenticating via Redfish SessionService or Basic Auth to retrieve the active firmware version, server model (e.g. DL380 Gen10), hostname, and health state.
- **Step 2 - Interactive Administrator Selection**: Allows administrators to pick specific servers (`1`), custom lists (`1,3,5`), ranges (`1-4`), or `ALL` servers.
- **Step 3 - Local Firmware Matching & Multipart Push**: Scans a designated local directory for `.fwpkg` or `.bin` files, auto-matches firmware to the server's iLO generation, and streams the payload directly to iLO's `HttpPushUri` with immediate flash instructions (`UpdateTarget: true`).
- **Step 4 - Real-Time Flash Monitoring**: Continuously polls the Redfish Task Service and HPE OEM extensions (`Oem.Hpe.FlashProgressPercent` and `Oem.Hpe.State`) with live terminal progress bars.
- **Step 5 - Graceful iLO Reset & Verification**: Issues a graceful reset to the iLO processor (`/redfish/v1/Managers/1/Actions/Manager.Reset/`), waits for iLO to reboot, re-authenticates, and verifies that the new firmware is active.
- **Audit Reporting**: Exports an Excel audit report (`iLO_Upgrade_Report_<timestamp>.xlsx`) documenting initial versions, upgraded versions, reset status, and timestamps.
- **Zero-Risk Mock Mode (`--mock`)**: Built-in mock Redfish server for testing and dry-runs on your Windows workstation before touching production hardware.

---

## Directory Structure

```
iLO-Firmware-upgrade/
├── ilo_updater/
│   ├── __init__.py
│   ├── redfish_client.py     # Pure Redfish API client (Sessions, Inventory, Push, Flash, Reset)
│   ├── excel_parser.py       # Excel parser, validator, and audit report generator
│   ├── firmware_manager.py   # Local directory scanner & intelligent iLO type matching
│   ├── ui_console.py         # Rich interactive console with tables, progress bars & spinners
│   └── mock_server.py        # Simulated HPE iLO 5/6 Redfish server for local testing
├── firmware/                 # Local directory for keeping downloaded firmware files (.fwpkg, .bin)
│   └── README.md             # Guide on downloading HPE iLO firmware packages
├── main.py                   # Main CLI entrypoint
├── generate_template.py      # Utility script to produce fresh Excel templates
├── test_suite.py             # Automated end-to-end test suite
├── run_ilo_updater.bat       # Windows 1-click Batch launcher
├── run_ilo_updater.ps1       # Windows PowerShell launcher
├── sample_inventory.xlsx     # Pre-configured sample Excel template
├── requirements.txt          # Python dependencies (requests, openpyxl, rich, urllib3)
└── README.md                 # Complete documentation
```

---

## Prerequisites (Windows Workstation)

1. **Python 3.8 or higher**:
   - Download from [python.org](https://www.python.org/downloads/windows/).
   - **Crucial**: During installation, check the box: **"Add Python to PATH"**.
2. **Network Access**:
   - HTTPS port `443` open from the Windows machine to the target iLO IP addresses.
3. **iLO Account Privileges**:
   - An iLO user account with **Configure iLO Settings** and **Firmware Update** privileges (default `Administrator` has full privileges).

---

## Quick Start on Windows

### Option 1: 1-Click Windows Batch Launcher (`.bat`)
Simply double-click:
```cmd
run_ilo_updater.bat
```
*The batch file will automatically detect Python, create a virtual environment (`venv`), install dependencies, and launch the tool.*

### Option 2: PowerShell (`.ps1`)
Open PowerShell as Administrator or standard user:
```powershell
# Standard execution
.\run_ilo_updater.ps1

# Point to custom Excel file and custom firmware folder
.\run_ilo_updater.ps1 -Excel ".\datacenter_ilo.xlsx" -FirmwareDir "C:\iLO_Firmware"

# Run in safe Mock Simulation mode
.\run_ilo_updater.ps1 -Mock
```

### Option 3: Python Command Line
```cmd
# Create and activate virtual environment
python -m venv venv
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run interactive workflow
python main.py --excel sample_inventory.xlsx --firmware-dir firmware
```

---

## Excel Sheet Format

The script includes smart header matching. Any standard column header names will work:

| Server Name | iLO IP | Username | Password | iLO Type | Notes / Location |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `Prod-DB-01` | `192.168.10.51` | `Administrator` | `YourPassword!` | `iLO5` | Rack 1 - U12 (DL380 Gen10) |
| `Prod-DB-02` | `192.168.10.52` | `Administrator` | `YourPassword!` | `iLO5` | Rack 1 - U14 (DL380 Gen10) |
| `Web-Node-01` | `192.168.10.61` | `Administrator` | `AdminPass2026` | `iLO6` | Rack 2 - U20 (DL360 Gen11) |
| `Web-Node-02` | `192.168.10.62` | `Administrator` | `AdminPass2026` | `iLO6` | Rack 2 - U22 (DL360 Gen11) |

> **Tip:** You can generate a fresh template at any time by running:
> ```cmd
> python main.py --template
> ```

---

## Step-by-Step Workflow Walkthrough

### Step 1: Check Existing Firmware Versions
The tool connects to each iLO via the Redfish API (`/redfish/v1/Managers/1` and `/redfish/v1/Systems/1`), logging in and reading:
- **Active Firmware Version** (e.g. `iLO 5 v2.81 (May 04 2023)`)
- **iLO Model & Generation** (e.g. `iLO 5`, `iLO 6`)
- **Server Model** (e.g. `ProLiant DL380 Gen10`)
- **Host Name & Health State**
All results are displayed in a clean colored table.

### Step 2: Administrator Server Selection
The administrator is prompted to select which servers to flash:
- **Single Server**: `1`
- **Multiple Servers**: `1, 3, 5`
- **Range**: `1-3`
- **All Servers**: `ALL`

### Step 3: Match Local Firmware & Push Upgrade
- The script checks the local `firmware/` directory for `.fwpkg` or `.bin` files.
- It auto-matches the appropriate firmware package to the server's iLO generation:
  - `ilo5_*.fwpkg` -> iLO 5
  - `ilo6_*.fwpkg` -> iLO 6
- The package is uploaded using multipart/form-data to iLO's `HttpPushUri`.
- Flashing parameters are applied:
  ```json
  {
    "UpdateRepository": false,
    "UpdateTarget": true,
    "ETag": "atag",
    "Section": 0
  }
  ```
- Flash progress is monitored live via `Oem.Hpe.FlashProgressPercent`.

### Step 4: Show Upgrade Completion
Once the flash reaches 100% and state transitions to `Complete`, the console informs the administrator of the successful write.

### Step 5: Reset iLO and Verify Post-Reboot
- The script issues a Redfish reset command to the management processor:
  ```http
  POST /redfish/v1/Managers/1/Actions/Manager.Reset/
  {"ResetType": "GracefulRestart"}
  ```
  *(Note: Resetting iLO only reboots the out-of-band management controller; it **does NOT** disrupt the host OS or running workloads).*
- The script tracks iLO restarting and reconnects once Redfish comes back online (typically 60–90 seconds).
- It queries `/redfish/v1/Managers/1` to verify the **New Firmware Version**.
- It renders a side-by-side **Previous vs Upgraded** comparison table and writes an Excel audit file.

---

## Testing & Demonstration (Mock Simulation Mode)

To test the entire 5-step flow without physical HPE servers:
```cmd
python main.py --mock
```
This starts an internal Redfish simulator on `127.0.0.1:8443` simulating an iLO 5 controller running `v2.81`, pushes a mock package, flashes to 100%, simulates a reboot, and verifies the upgrade to `v3.04`!

---

## Redfish API Endpoints Reference

| Operation | HTTP Method | Redfish Endpoint | Description |
| :--- | :--- | :--- | :--- |
| **Authentication** | `POST` | `/redfish/v1/SessionService/Sessions/` | Obtains `X-Auth-Token` and session URI |
| **Manager Info** | `GET` | `/redfish/v1/Managers/1` | Reads `FirmwareVersion`, `Model`, `Status` |
| **Server Info** | `GET` | `/redfish/v1/Systems/1` | Reads `Model` (DL380/360), `HostName` |
| **Update Service** | `GET` | `/redfish/v1/UpdateService/` | Discovers `HttpPushUri`, `FlashProgressPercent` |
| **Firmware Push** | `POST` | `/redfish/v1/UpdateService/update-multipart` | Multipart payload with `.fwpkg` or `.bin` |
| **iLO Reset** | `POST` | `/redfish/v1/Managers/1/Actions/Manager.Reset/` | Graceful restart of the iLO processor |
