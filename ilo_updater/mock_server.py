"""
Mock HPE iLO Redfish API Server for safe local testing and demonstration.
Simulates iLO 5 and iLO 6 behavior:
- Redfish Session authentication
- Manager info and firmware inventory
- Multipart firmware upload to HttpPushUri
- Incremental flash progress tracking (0% -> 100%)
- iLO reset simulation and firmware version increment post-reboot!
"""

import time
import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, Any, Optional


class MockIloState:
    def __init__(self, ilo_type: str = "iLO5", initial_fw: str = "iLO 5 v2.81 (May 04 2023)"):
        self.ilo_type = ilo_type
        self.initial_fw = initial_fw
        self.current_fw = initial_fw
        self.pending_fw = "iLO 5 v3.04 (Jan 15 2024)" if "5" in ilo_type else "iLO 6 v1.67 (Feb 2024)"
        self.flash_progress = 0
        self.flash_state = "Idle"
        self.is_flashing = False
        self.is_rebooting = False
        self.reboot_until = 0.0

    def start_flash(self, target_version: Optional[str] = None):
        self.is_flashing = True
        self.flash_progress = 0
        self.flash_state = "Writing"
        if target_version:
            self.pending_fw = target_version

        def _simulate_progress():
            for p in range(0, 101, 20):
                time.sleep(0.8)
                self.flash_progress = p
                if p < 50:
                    self.flash_state = "Writing"
                elif p < 100:
                    self.flash_state = "Flashing"
                else:
                    self.flash_state = "Complete"
            self.is_flashing = False

        t = threading.Thread(target=_simulate_progress, daemon=True)
        t.start()

    def trigger_reset(self, downtime_seconds: float = 6.0):
        self.is_rebooting = True
        self.reboot_until = time.time() + downtime_seconds

        def _reboot_done():
            time.sleep(downtime_seconds)
            self.current_fw = self.pending_fw
            self.flash_state = "Idle"
            self.flash_progress = 0
            self.is_rebooting = False

        t = threading.Thread(target=_reboot_done, daemon=True)
        t.start()


class MockIloRequestHandler(BaseHTTPRequestHandler):
    state = MockIloState()

    def log_message(self, format, *args):
        # Silence routine HTTP request logging during CLI interaction
        pass

    def _check_offline(self) -> bool:
        if self.state.is_rebooting and time.time() < self.state.reboot_until:
            self.send_error(503, "Service Unavailable - iLO is rebooting")
            return True
        return False

    def _send_json(self, status: int, data: Dict[str, Any], extra_headers: Optional[Dict[str, str]] = None):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self._check_offline():
            return

        path = self.path.split("?")[0].rstrip("/")

        if path == "/redfish/v1" or path == "/redfish/v1/":
            self._send_json(200, {
                "@odata.id": "/redfish/v1/",
                "Name": "Redfish Root Service",
                "RedfishVersion": "1.6.0",
                "Managers": {"@odata.id": "/redfish/v1/Managers/"},
                "Systems": {"@odata.id": "/redfish/v1/Systems/"},
                "UpdateService": {"@odata.id": "/redfish/v1/UpdateService/"}
            })

        elif path == "/redfish/v1/Managers/1":
            self._send_json(200, {
                "@odata.id": "/redfish/v1/Managers/1",
                "Id": "1",
                "Name": "Manager",
                "ManagerType": "BMC",
                "Model": self.state.ilo_type,
                "FirmwareVersion": self.state.current_fw,
                "Status": {"Health": "OK", "State": "Enabled"},
                "Actions": {
                    "#Manager.Reset": {
                        "target": "/redfish/v1/Managers/1/Actions/Manager.Reset/"
                    }
                }
            })

        elif path == "/redfish/v1/Systems/1":
            self._send_json(200, {
                "@odata.id": "/redfish/v1/Systems/1",
                "Id": "1",
                "Name": "ProLiant Server",
                "Model": "ProLiant DL380 Gen10" if "5" in self.state.ilo_type else "ProLiant DL360 Gen11",
                "HostName": "hpe-prod-node",
                "PowerState": "On",
                "BiosVersion": "U30 v2.70"
            })

        elif path == "/redfish/v1/UpdateService":
            self._send_json(200, {
                "@odata.id": "/redfish/v1/UpdateService/",
                "Id": "UpdateService",
                "Name": "Update Service",
                "HttpPushUri": "/redfish/v1/UpdateService/update-multipart",
                "MultipartHttpPushUri": "/redfish/v1/UpdateService/update-multipart",
                "Oem": {
                    "Hpe": {
                        "FlashProgressPercent": self.state.flash_progress,
                        "State": self.state.flash_state
                    }
                }
            })

        elif "/redfish/v1/TaskService/Tasks/" in path:
            self._send_json(200, {
                "@odata.id": path,
                "TaskState": "Completed" if self.state.flash_progress >= 100 else "Running",
                "PercentComplete": self.state.flash_progress
            })

        else:
            self._send_json(404, {"error": "Not Found", "path": path})

    def do_POST(self):
        if self._check_offline():
            return

        path = self.path.split("?")[0].rstrip("/")

        if path == "/redfish/v1/SessionService/Sessions":
            # Session Login
            self._send_json(201, {
                "@odata.id": "/redfish/v1/SessionService/Sessions/1",
                "Id": "1",
                "UserName": "Administrator"
            }, extra_headers={
                "X-Auth-Token": "mock-ilo-token-session-9999",
                "Location": "/redfish/v1/SessionService/Sessions/1"
            })

        elif path == "/redfish/v1/UpdateService/update-multipart":
            # Multipart firmware upload
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 0:
                _ = self.rfile.read(content_length)

            self.state.start_flash()
            self._send_json(202, {
                "message": "Firmware upload received. Flashing initiated."
            }, extra_headers={
                "Location": "/redfish/v1/TaskService/Tasks/1"
            })

        elif path == "/redfish/v1/Managers/1/Actions/Manager.Reset":
            # Reset iLO
            self.state.trigger_reset(downtime_seconds=6.0)
            self._send_json(200, {
                "message": "iLO reset initiated. System will reboot."
            })

        else:
            self._send_json(404, {"error": "Endpoint not found"})

    def do_DELETE(self):
        # Logout
        self._send_json(200, {"message": "Session terminated"})


class MockRedfishServer:
    def __init__(self, port: int = 8443, ilo_type: str = "iLO5"):
        self.port = port
        self.ilo_type = ilo_type
        MockIloRequestHandler.state = MockIloState(ilo_type=ilo_type)
        self.httpd = HTTPServer(("127.0.0.1", self.port), MockIloRequestHandler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
