"""
HPE iLO Firmware Upgrade Automation Tool via Redfish API.
Main CLI orchestrator implementing the 5-step firmware lifecycle:
1. Check existing firmware versions across servers in Excel
2. Allow administrator to select target server(s)
3. Match local firmware packages (.fwpkg / .bin) and initiate push upgrade
4. Monitor and display flash completion
5. Reset iLO, wait for reboot, and verify the new firmware version
"""

import os
import sys
import time
import argparse
from typing import List, Dict, Any, Optional

from ilo_updater.redfish_client import IloRedfishClient
from ilo_updater.excel_parser import read_ilo_inventory, generate_sample_excel, export_upgrade_report
from ilo_updater.firmware_manager import (
    scan_firmware_directory, 
    find_best_firmware_match, 
    validate_firmware_file,
    FirmwareFile
)
from ilo_updater.ui_console import (
    print_banner, 
    print_step, 
    print_info, 
    print_success, 
    print_warning, 
    print_error,
    display_server_table, 
    display_firmware_files_table, 
    display_results_summary_table,
    prompt_user_selection, 
    confirm_action,
    console,
    RICH_AVAILABLE
)
from ilo_updater.mock_server import MockRedfishServer


def step1_check_inventory(servers: List[Dict[str, Any]], timeout: int = 15, is_mock: bool = False, mock_port: int = 8443):
    """Step 1: Check existing firmware version of each iLO in the Excel inventory."""
    print_step(1, "Checking Existing iLO Firmware Versions")
    print_info(f"Connecting to {len(servers)} iLO management controllers via Redfish API...")

    for idx, s in enumerate(servers, 1):
        ip = s.get("ilo_ip")
        user = s.get("username", "Administrator")
        pwd = s.get("password", "")
        port = mock_port if is_mock else 443
        protocol = "http" if is_mock else "https"

        print_info(f"[{idx}/{len(servers)}] Querying {s.get('server_name')} ({ip})...")
        client = IloRedfishClient(
            ip_or_host=ip,
            username=user,
            password=pwd,
            timeout=timeout,
            port=port,
            use_https=(protocol == "https")
        )

        try:
            info = client.get_firmware_version_and_info()
            s["current_fw"] = info.get("firmware_version", "Unknown")
            s["detected_model"] = info.get("detected_model", s.get("ilo_type", "iLO5"))
            s["server_model"] = info.get("server_model", "")
            s["status"] = "Online (Checked)"
            s["error"] = None
        except Exception as e:
            s["current_fw"] = "Unreachable"
            s["status"] = "Connection Error"
            s["error"] = str(e)
            print_warning(f"Could not reach {ip}: {str(e)}")
        finally:
            client.logout()

    display_server_table(servers, title="Discovered iLO Inventory & Active Firmware")


def step2_select_servers(servers: List[Dict[str, Any]], select_query: Optional[str] = None) -> List[Dict[str, Any]]:
    """Step 2: Let the end user select which server's iLO firmware needs to be updated."""
    print_step(2, "Select Target Servers for Firmware Upgrade")
    
    online_servers = [s for s in servers if s.get("current_fw") not in [None, "Unreachable", ""]]
    if not online_servers:
        print_error("No servers are currently reachable. Please check network connectivity and credentials.")
        return []

    if select_query:
        print_info(f"Using pre-configured server selection: '{select_query}'")
        if select_query.strip().upper() == "ALL":
            selected_indices = list(range(len(servers)))
        else:
            selected_indices = [int(x) - 1 for x in select_query.split(",") if x.strip().isdigit()]
    else:
        selected_indices = prompt_user_selection(len(servers))

    selected_targets = [servers[i] for i in selected_indices if 0 <= i < len(servers)]

    print_info(f"Selected {len(selected_targets)} server(s):")
    for s in selected_targets:
        print(f"  • {s.get('server_name')} ({s.get('ilo_ip')}) - Current FW: {s.get('current_fw')}")

    return selected_targets


def step3_match_and_upgrade(
    targets: List[Dict[str, Any]], 
    firmware_dir: str,
    timeout: int = 30,
    is_mock: bool = False,
    mock_port: int = 8443,
    auto_confirm: bool = False
) -> List[Dict[str, Any]]:
    """
    Step 3, 4, and 5:
    - Match firmware files in local directory
    - Push firmware via Redfish HttpPushUri
    - Poll flash completion
    - Reset iLO and verify upgraded firmware version
    """
    print_step(3, "Scanning Local Firmware Directory & Initiating Upgrade")

    if not os.path.isdir(firmware_dir):
        os.makedirs(firmware_dir, exist_ok=True)

    # In mock simulation mode, generate demo firmware packages if folder is empty
    if is_mock:
        demo_fwpkg_5 = os.path.join(firmware_dir, "ilo5_304.fwpkg")
        demo_fwpkg_6 = os.path.join(firmware_dir, "ilo6_167.fwpkg")
        if not os.path.exists(demo_fwpkg_5):
            print_info("Generating demo firmware packages for Mock testing...")
            with open(demo_fwpkg_5, "wb") as f:
                f.write(b"HPE_ILO5_FIRMWARE_MOCK_PAYLOAD_V304" * 1024)
        if not os.path.exists(demo_fwpkg_6):
            with open(demo_fwpkg_6, "wb") as f:
                f.write(b"HPE_ILO6_FIRMWARE_MOCK_PAYLOAD_V167" * 1024)

    available_files = scan_firmware_directory(firmware_dir)
    if not available_files:
        print_warning(f"No firmware files (.fwpkg, .bin) found in '{firmware_dir}'.")
        print_info("Please place relevant HPE iLO firmware packages in this directory.")
        custom_dir = input(f"Enter path to firmware directory (or press Enter to retry '{firmware_dir}'): ").strip()
        if custom_dir and os.path.isdir(custom_dir):
            firmware_dir = custom_dir
            available_files = scan_firmware_directory(firmware_dir)

    display_firmware_files_table(available_files, title=f"Firmware Packages Found in '{firmware_dir}'")

    # Match firmware for each selected target
    target_assignments: List[Tuple[Dict[str, Any], FirmwareFile]] = []
    for s in targets:
        ilo_gen = s.get("ilo_type", "iLO5")
        match = find_best_firmware_match(ilo_gen, available_files)
        if match:
            print_info(f"Target '{s.get('server_name')}' ({ilo_gen}) -> Auto-matched: [bold green]{match.filename}[/bold green]")
            target_assignments.append((s, match))
        else:
            print_warning(f"No auto-match found for '{s.get('server_name')}' ({ilo_gen}).")
            if available_files:
                print("Available files:")
                for idx, f in enumerate(available_files, 1):
                    print(f"  [{idx}] {f.filename}")
                choice = input(f"Select firmware file number for '{s.get('server_name')}' [1]: ").strip() or "1"
                try:
                    c_idx = int(choice) - 1
                    target_assignments.append((s, available_files[c_idx]))
                except Exception:
                    print_error(f"Skipping server '{s.get('server_name')}': No valid firmware selected.")
            else:
                print_error(f"Cannot upgrade '{s.get('server_name')}': No firmware files available.")

    if not target_assignments:
        print_error("No firmware assignments made. Aborting upgrade.")
        return []

    # Confirmation
    print_info(f"\nReady to upgrade {len(target_assignments)} server(s).")
    if not auto_confirm:
        if not confirm_action("Do you want to proceed with uploading and flashing the firmware?", default=True):
            print_warning("Upgrade cancelled by user.")
            return []
    else:
        print_info("Auto-confirm active: proceeding with upload and flashing.")

    # Execute upgrade for each server
    results: List[Dict[str, Any]] = []
    total_targets = len(target_assignments)

    for idx, (s, fw_file) in enumerate(target_assignments, 1):
        server_name = s.get("server_name")
        ip = s.get("ilo_ip")
        user = s.get("username", "Administrator")
        pwd = s.get("password", "")
        initial_fw = s.get("current_fw", "Unknown")
        port = mock_port if is_mock else 443
        protocol = "http" if is_mock else "https"

        print(f"\n{'=' * 75}")
        print_info(f"[{idx}/{total_targets}] Processing '{server_name}' ({ip}) with '{fw_file.filename}'...")
        print(f"{'=' * 75}")

        client = IloRedfishClient(
            ip_or_host=ip,
            username=user,
            password=pwd,
            timeout=timeout,
            port=port,
            use_https=(protocol == "https")
        )

        record = {
            "server_name": server_name,
            "ilo_ip": ip,
            "ilo_type": s.get("ilo_type"),
            "initial_fw": initial_fw,
            "new_fw": "Pending",
            "status": "In Progress",
            "reset_verified": "No",
            "details": ""
        }

        try:
            # Step 3a: Upload firmware via multipart push
            print_info(f"Step 3a: Uploading firmware payload ({fw_file.size_mb} MB) to iLO HttpPushUri...")
            
            def upload_cb(uploaded, total, percent):
                if percent in [0.0, 25.0, 50.0, 75.0, 100.0] or percent % 20 == 0:
                    print(f"  ➜ Upload Progress: {percent}% ({round(uploaded/(1024*1024), 1)} MB / {round(total/(1024*1024), 1)} MB)")

            upload_ok, upload_msg, task_uri = client.upload_and_flash_firmware(
                firmware_path=fw_file.file_path,
                compsig_path=fw_file.compsig_path,
                update_repository=False,
                update_target=True,
                upload_progress_cb=upload_cb
            )

            if not upload_ok:
                print_error(f"Firmware upload failed: {upload_msg}")
                record["status"] = "Upload Failed"
                record["details"] = upload_msg
                results.append(record)
                continue

            print_success("Firmware uploaded successfully! iLO has accepted the package.")

            # Step 3b: Poll flash progress
            print_info("Step 3b: Flashing firmware in iLO management processor...")
            
            def flash_cb(percent, msg):
                print(f"  ➜ Flashing Progress: {percent}% [{msg}]")

            flash_ok, flash_msg = client.poll_flash_progress(
                task_uri=task_uri,
                progress_cb=flash_cb,
                max_duration_seconds=600,
                poll_interval=3
            )

            if not flash_ok:
                print_error(f"Flashing failed or timed out: {flash_msg}")
                record["status"] = "Flash Failed"
                record["details"] = flash_msg
                results.append(record)
                continue

            # Step 4: Show intermediate completion
            print_step(4, f"iLO Upgrade Completed for {server_name}")
            print_success(f"Firmware flash completed successfully: {flash_msg}")

            # Step 5: Reset iLO and verify new firmware version
            print_step(5, f"Resetting iLO and Verifying Active Firmware ({server_name})")
            print_info("Issuing 'GracefulRestart' command to iLO management processor...")

            reset_ok, reset_msg = client.reset_ilo(reset_type="GracefulRestart")
            print_info(f"Reset status: {reset_msg}")

            print_info("Waiting for iLO to reboot and stabilize (this typically takes 60-120 seconds)...")

            def reboot_cb(pct, status_text):
                print(f"  ➜ Reboot Monitor: {status_text}")

            verify_ok, new_version, verify_msg = client.wait_for_reboot_and_verify(
                initial_version=initial_fw,
                max_wait_seconds=300,
                status_cb=reboot_cb
            )

            if verify_ok:
                print_success(f"iLO is back online! Verified Active Firmware: [bold green]{new_version}[/bold green]")
                record["new_fw"] = new_version
                record["status"] = "SUCCESS"
                record["reset_verified"] = "Yes"
                record["details"] = verify_msg
            else:
                print_error(f"Post-upgrade verification failed: {verify_msg}")
                record["new_fw"] = new_version
                record["status"] = "Verify Failed"
                record["reset_verified"] = "No"
                record["details"] = verify_msg

        except Exception as e:
            print_error(f"Unexpected exception during upgrade of {server_name}: {str(e)}")
            record["status"] = "Error"
            record["details"] = str(e)
        finally:
            client.logout()

        results.append(record)

    return results


def main():
    parser = argparse.ArgumentParser(
        description="HPE iLO Firmware Upgrade Automation Suite (Redfish REST API)",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--excel", "-e",
        default="sample_inventory.xlsx",
        help="Path to Excel sheet containing iLO IPs and credentials (default: sample_inventory.xlsx)"
    )
    parser.add_argument(
        "--firmware-dir", "-f",
        default="firmware",
        help="Local directory where downloaded firmware packages (.fwpkg, .bin) are stored (default: firmware)"
    )
    parser.add_argument(
        "--template", "-t",
        action="store_true",
        help="Generate a blank Excel inventory template with sample rows and exit"
    )
    parser.add_argument(
        "--mock", "-m",
        action="store_true",
        help="Run in Mock Simulation mode (spins up local Mock iLO Redfish server for zero-risk testing)"
    )
    parser.add_argument(
        "--mock-port",
        type=int,
        default=8443,
        help="Port for the mock Redfish server (default: 8443)"
    )
    parser.add_argument(
        "--select", "-s",
        default=None,
        help="Pre-select server index(es) for upgrade (e.g. '1', '1,3', 'ALL')"
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Automatically confirm firmware flash without prompting"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=25,
        help="HTTP request timeout in seconds (default: 25)"
    )

    args = parser.parse_args()

    print_banner()

    # Handle template generation
    if args.template:
        template_file = "ilo_inventory_template.xlsx"
        generate_sample_excel(template_file)
        print_success(f"Created sample Excel inventory template: '{template_file}'")
        print_info("Open this file in Excel, fill in your server iLO details, and run the script again!")
        sys.exit(0)

    # Handle Mock mode setup
    mock_server = None
    if args.mock:
        print_warning("MOCK SIMULATION MODE ACTIVATED")
        print_info(f"Starting local Mock HPE iLO Redfish Server on http://127.0.0.1:{args.mock_port}...")
        mock_server = MockRedfishServer(port=args.mock_port, ilo_type="iLO5")
        mock_server.start()
        time.sleep(1)

        # Generate mock inventory if not already present
        if not os.path.exists(args.excel) or args.excel == "sample_inventory.xlsx":
            args.excel = "mock_inventory.xlsx"
            import openpyxl
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Mock iLOs"
            ws.append(["Server Name", "iLO IP", "Username", "Password", "iLO Type", "Notes"])
            ws.append(["Mock-DL380-Gen10-Node1", "127.0.0.1", "Administrator", "HpePassword123!", "iLO5", "Mock Test Node"])
            wb.save(args.excel)
            wb.close()
            print_info(f"Generated mock test inventory: '{args.excel}'")

    # Verify Excel file exists
    if not os.path.exists(args.excel):
        print_warning(f"Inventory file '{args.excel}' not found.")
        print_info("Generating a sample inventory template for you...")
        generate_sample_excel(args.excel)
        print_success(f"Generated '{args.excel}'.")

    try:
        # Load Excel inventory
        print_info(f"Loading iLO inventory from: '{args.excel}'")
        inventory = read_ilo_inventory(args.excel)
        print_info(f"Found {len(inventory)} server record(s) in Excel sheet.")

        # Step 1: Check existing firmware versions
        step1_check_inventory(
            inventory, 
            timeout=args.timeout, 
            is_mock=args.mock, 
            mock_port=args.mock_port
        )

        # Step 2: Select servers to update
        selected_targets = step2_select_servers(inventory, select_query=args.select)
        if not selected_targets:
            print_info("No servers selected. Exiting.")
            sys.exit(0)

        # Steps 3, 4, 5: Match firmware, push, flash, reset, and verify
        results = step3_match_and_upgrade(
            targets=selected_targets,
            firmware_dir=args.firmware_dir,
            timeout=args.timeout,
            is_mock=args.mock,
            mock_port=args.mock_port,
            auto_confirm=args.yes
        )

        if results:
            # Display final summary table
            display_results_summary_table(results)

            # Export Excel report
            report_file = export_upgrade_report(results, args.excel)
            print_success(f"Post-upgrade audit report saved to: [bold green]{report_file}[/bold green]")

    except KeyboardInterrupt:
        print_warning("\nOperation interrupted by user.")
    except Exception as e:
        print_error(f"Fatal error: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        if mock_server:
            print_info("Stopping Mock Redfish Server...")
            mock_server.stop()


if __name__ == "__main__":
    main()
