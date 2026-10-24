"""
Automated End-to-End Test Suite for HPE iLO Firmware Upgrade Suite.
Validates Excel parsing, Firmware file detection, Redfish API communications,
flash tracking, simulated reset, and verification report generation.
"""

import os
import sys
import time
import openpyxl
from ilo_updater.excel_parser import read_ilo_inventory, generate_sample_excel, export_upgrade_report
from ilo_updater.firmware_manager import scan_firmware_directory, find_best_firmware_match
from ilo_updater.redfish_client import IloRedfishClient
from ilo_updater.mock_server import MockRedfishServer


def test_excel_pipeline():
    print("[TEST 1/4] Testing Excel Template Generation and Parsing...")
    test_excel = "test_inventory.xlsx"
    generate_sample_excel(test_excel)
    assert os.path.exists(test_excel), "Excel template was not created"

    inventory = read_ilo_inventory(test_excel)
    assert len(inventory) >= 3, f"Expected at least 3 rows, got {len(inventory)}"
    assert inventory[0]["ilo_ip"] == "192.168.10.51"
    assert inventory[0]["ilo_type"] == "iLO5"
    print(f"  ✓ Excel loaded {len(inventory)} rows with normalized headers.")

    # Test report export
    mock_results = [
        {
            "server_name": "Test-Node-1",
            "ilo_ip": "192.168.10.51",
            "ilo_type": "iLO5",
            "initial_fw": "iLO 5 v2.81",
            "new_fw": "iLO 5 v3.04",
            "status": "SUCCESS",
            "reset_verified": "Yes",
            "details": "Upgrade verified post-reboot"
        }
    ]
    report_file = export_upgrade_report(mock_results, test_excel)
    assert os.path.exists(report_file), "Upgrade report not exported"
    print(f"  ✓ Exported audit report: {report_file}")
    
    # Cleanup
    if os.path.exists(test_excel):
        os.remove(test_excel)
    if os.path.exists(report_file):
        os.remove(report_file)


def test_firmware_manager():
    print("[TEST 2/4] Testing Firmware Manager Scanning and Matching...")
    test_dir = "test_fw_dir"
    os.makedirs(test_dir, exist_ok=True)
    fw5_path = os.path.join(test_dir, "ilo5_304.fwpkg")
    fw6_path = os.path.join(test_dir, "ilo6_167.fwpkg")
    with open(fw5_path, "wb") as f:
        f.write(b"MOCK_ILO5_FW" * 100)
    with open(fw6_path, "wb") as f:
        f.write(b"MOCK_ILO6_FW" * 100)

    files = scan_firmware_directory(test_dir)
    assert len(files) == 2, f"Expected 2 firmware files, got {len(files)}"

    match5 = find_best_firmware_match("iLO5", files)
    assert match5 is not None and "ilo5" in match5.filename.lower()
    print(f"  ✓ Matched iLO5 -> {match5.filename}")

    match6 = find_best_firmware_match("iLO6", files)
    assert match6 is not None and "ilo6" in match6.filename.lower()
    print(f"  ✓ Matched iLO6 -> {match6.filename}")

    # Cleanup
    os.remove(fw5_path)
    os.remove(fw6_path)
    os.rmdir(test_dir)


def test_redfish_client_and_mock_server():
    print("[TEST 3/4] Testing Redfish Client Communication with Mock Server...")
    server = MockRedfishServer(port=9443, ilo_type="iLO5")
    server.start()
    time.sleep(1)

    client = IloRedfishClient(
        ip_or_host="127.0.0.1",
        username="Administrator",
        password="Password123!",
        port=9443,
        use_https=False
    )

    try:
        # 1. Login
        logged_in = client.login()
        assert logged_in is True, "Login failed"
        print("  ✓ Authenticated via Redfish SessionService")

        # 2. Get existing firmware info (Step 1)
        info = client.get_firmware_version_and_info()
        initial_version = info.get("firmware_version")
        assert "iLO 5 v2.81" in initial_version, f"Unexpected version: {initial_version}"
        print(f"  ✓ Step 1 Verified: Current Firmware = {initial_version}")

        # 3. Create dummy firmware file
        dummy_fw = "dummy_ilo5.fwpkg"
        with open(dummy_fw, "wb") as f:
            f.write(b"DUMMY_PAYLOAD" * 500)

        # 4. Upload and flash (Step 3)
        upload_ok, upload_msg, task_uri = client.upload_and_flash_firmware(
            firmware_path=dummy_fw,
            update_repository=False,
            update_target=True
        )
        assert upload_ok is True, f"Upload failed: {upload_msg}"
        print(f"  ✓ Step 3a Verified: Firmware upload succeeded -> {upload_msg}")

        # 5. Poll flash progress (Step 3b / 4)
        progress_records = []
        def cb(pct, msg):
            progress_records.append((pct, msg))

        flash_ok, flash_msg = client.poll_flash_progress(
            task_uri=task_uri,
            progress_cb=cb,
            max_duration_seconds=30,
            poll_interval=1
        )
        assert flash_ok is True, f"Flash polling failed: {flash_msg}"
        print(f"  ✓ Step 4 Verified: Flash reached 100% completion")

        # 6. Reset iLO and verify post-reboot upgrade (Step 5)
        reset_ok, reset_msg = client.reset_ilo(reset_type="GracefulRestart")
        assert reset_ok is True, f"Reset command failed: {reset_msg}"
        print(f"  ✓ Step 5a Verified: Manager.Reset triggered")

        verify_ok, new_version, verify_msg = client.wait_for_reboot_and_verify(
            initial_version=initial_version,
            max_wait_seconds=20
        )
        assert verify_ok is True, f"Reboot verification failed: {verify_msg}"
        assert "3.04" in new_version, f"Expected v3.04, got {new_version}"
        print(f"  ✓ Step 5b Verified: Post-reboot active firmware = {new_version}")

        if os.path.exists(dummy_fw):
            os.remove(dummy_fw)

    finally:
        client.logout()
        server.stop()


def main():
    print("=" * 65)
    print("  RUNNING AUTOMATED TEST SUITE FOR HPE iLO FIRMWARE UPGRADER")
    print("=" * 65)
    test_excel_pipeline()
    test_firmware_manager()
    test_redfish_client_and_mock_server()
    print("=" * 65)
    print("  ALL 3 TEST SUITES PASSED FLAWLESSLY! [4/4 Complete]")
    print("=" * 65)


if __name__ == "__main__":
    main()
