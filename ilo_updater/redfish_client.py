"""
HPE iLO Redfish API Client.
Specialized for firmware discovery, multipart upload, flash tracking,
graceful reset, and post-reboot verification across iLO 4, iLO 5, iLO 6, and iLO 7.
"""

import os
import time
import json
import socket
from typing import Dict, Any, Optional, Tuple, Callable
import urllib3
import requests
from requests.auth import HTTPBasicAuth

# Suppress insecure HTTPS warnings for datacenter self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class ProgressFileReader:
    """A file-like wrapper to track upload progress during multipart POST."""
    def __init__(self, file_path: str, progress_callback: Optional[Callable[[int, int, float], None]] = None):
        self.file_path = file_path
        self.file_obj = open(file_path, "rb")
        self.total_size = os.path.getsize(file_path)
        self.uploaded_bytes = 0
        self.progress_callback = progress_callback

    def read(self, size: int = -1) -> bytes:
        chunk = self.file_obj.read(size)
        if chunk:
            self.uploaded_bytes += len(chunk)
            if self.progress_callback and self.total_size > 0:
                percent = round((self.uploaded_bytes / self.total_size) * 100, 1)
                self.progress_callback(self.uploaded_bytes, self.total_size, percent)
        return chunk

    def close(self):
        self.file_obj.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class IloRedfishClient:
    def __init__(
        self,
        ip_or_host: str,
        username: str,
        password: str,
        timeout: int = 30,
        port: int = 443,
        use_https: bool = True
    ):
        self.host = ip_or_host.strip()
        self.username = username.strip()
        self.password = password
        self.timeout = timeout
        self.port = port
        self.protocol = "https" if use_https else "http"
        self.base_url = f"{self.protocol}://{self.host}:{self.port}"
        
        self.session = requests.Session()
        self.session.verify = False
        self.session_token: Optional[str] = None
        self.session_uri: Optional[str] = None
        self.is_logged_in = False
        self.auth_mode = "Session"  # "Session" or "Basic"

    def _full_url(self, uri: str) -> str:
        if uri.startswith("http://") or uri.startswith("https://"):
            return uri
        if not uri.startswith("/"):
            uri = "/" + uri
        return f"{self.base_url}{uri}"

    def _get_headers(self, custom_headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "HPE-iLO-Firmware-Updater/1.0"
        }
        if self.session_token:
            headers["X-Auth-Token"] = self.session_token
            headers["Cookie"] = f"sessionKey={self.session_token}"
        if custom_headers:
            headers.update(custom_headers)
        return headers

    def login(self) -> bool:
        """
        Authenticate with HPE iLO.
        First tries Redfish SessionService; falls back to HTTP Basic Auth if needed.
        """
        # Step 1: Try Redfish Session Login
        session_url = self._full_url("/redfish/v1/SessionService/Sessions/")
        payload = {
            "UserName": self.username,
            "Password": self.password
        }
        headers = {"Content-Type": "application/json", "Accept": "application/json"}

        try:
            resp = self.session.post(session_url, json=payload, headers=headers, timeout=self.timeout)
            if resp.status_code in [200, 201]:
                self.session_token = resp.headers.get("X-Auth-Token")
                self.session_uri = resp.headers.get("Location")
                if not self.session_uri and resp.status_code == 201:
                    try:
                        self.session_uri = resp.json().get("@odata.id")
                    except Exception:
                        pass
                self.is_logged_in = True
                self.auth_mode = "Session"
                return True
        except Exception:
            pass

        # Step 2: Fallback to Basic Auth
        try:
            test_url = self._full_url("/redfish/v1/Managers/1")
            resp = self.session.get(
                test_url,
                auth=HTTPBasicAuth(self.username, self.password),
                headers={"Accept": "application/json"},
                timeout=self.timeout
            )
            if resp.status_code == 200:
                self.session.auth = HTTPBasicAuth(self.username, self.password)
                self.is_logged_in = True
                self.auth_mode = "Basic"
                return True
        except Exception as e:
            raise ConnectionError(f"Failed to connect to iLO at {self.host}: {str(e)}")

        raise PermissionError(f"Authentication failed for user '{self.username}' on iLO {self.host}")

    def logout(self):
        """Cleanly terminate the active Redfish session."""
        if self.is_logged_in and self.session_uri and self.session_token:
            try:
                logout_url = self._full_url(self.session_uri)
                self.session.delete(logout_url, headers=self._get_headers(), timeout=10)
            except Exception:
                pass
        self.is_logged_in = False
        self.session_token = None
        self.session_uri = None

    def get_firmware_version_and_info(self) -> Dict[str, Any]:
        """
        Retrieve current iLO firmware version, model, and server metadata.
        Queries /redfish/v1/Managers/1 and /redfish/v1/Systems/1.
        """
        if not self.is_logged_in:
            self.login()

        mgr_url = self._full_url("/redfish/v1/Managers/1")
        resp = self.session.get(mgr_url, headers=self._get_headers(), timeout=self.timeout)
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to query iLO Manager info: HTTP {resp.status_code}")

        mgr_data = resp.json()
        fw_version = mgr_data.get("FirmwareVersion", "Unknown")
        detected_model = mgr_data.get("Model", "Unknown iLO")
        health = mgr_data.get("Status", {}).get("Health", "Unknown")

        # Query System metadata for context (Host Name, Server Model, Serial)
        server_model = "ProLiant Server"
        server_hostname = ""
        power_state = "Unknown"
        bios_version = "Unknown"

        try:
            sys_url = self._full_url("/redfish/v1/Systems/1")
            sys_resp = self.session.get(sys_url, headers=self._get_headers(), timeout=10)
            if sys_resp.status_code == 200:
                sys_data = sys_resp.json()
                server_model = sys_data.get("Model", server_model)
                server_hostname = sys_data.get("HostName", "")
                power_state = sys_data.get("PowerState", "Unknown")
                bios_version = sys_data.get("BiosVersion", "Unknown")
        except Exception:
            pass

        return {
            "firmware_version": fw_version,
            "detected_model": detected_model,
            "health": health,
            "server_model": server_model,
            "server_hostname": server_hostname,
            "power_state": power_state,
            "bios_version": bios_version,
            "raw_manager": mgr_data
        }

    def get_update_service_info(self) -> Dict[str, Any]:
        """Discover UpdateService capabilities, push URIs, and flash status."""
        if not self.is_logged_in:
            self.login()

        url = self._full_url("/redfish/v1/UpdateService/")
        resp = self.session.get(url, headers=self._get_headers(), timeout=self.timeout)
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to query UpdateService: HTTP {resp.status_code}")
        return resp.json()

    def upload_and_flash_firmware(
        self,
        firmware_path: str,
        compsig_path: Optional[str] = None,
        update_repository: bool = False,
        update_target: bool = True,
        upload_progress_cb: Optional[Callable[[int, int, float], None]] = None
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Upload local firmware package (.fwpkg or .bin) via multipart/form-data to HttpPushUri.
        Returns: (success: bool, message: str, task_uri: Optional[str])
        """
        if not os.path.isfile(firmware_path):
            raise FileNotFoundError(f"Firmware file not found: {firmware_path}")

        if not self.is_logged_in:
            self.login()

        # Discover push endpoint
        service_info = self.get_update_service_info()
        push_uri = service_info.get("HttpPushUri") or service_info.get("MultipartHttpPushUri")
        if not push_uri:
            # Standard HPE fallback
            push_uri = "/redfish/v1/UpdateService/update-multipart"

        target_url = self._full_url(push_uri)
        filename = os.path.basename(firmware_path)

        # JSON parameters block to instruct iLO to flash immediately
        update_params = {
            "UpdateRepository": update_repository,
            "UpdateTarget": update_target,
            "ETag": "atag",
            "Section": 0
        }

        # Build multipart/form-data payload
        headers = self._get_headers({
            "Expect": ""  # Bypass 100-continue expectation
        })

        file_size = os.path.getsize(firmware_path)
        with open(firmware_path, "rb") as f_bin:
            files: Dict[str, Any] = {
                "parameters": (None, json.dumps(update_params), "application/json"),
                "file": (filename, f_bin, "application/octet-stream")
            }

            if self.session_token:
                files["sessionKey"] = (None, self.session_token)

            # Optional component signature file
            compsig_file_obj = None
            if compsig_path and os.path.isfile(compsig_path):
                compsig_file_obj = open(compsig_path, "rb")
                files["comp_file"] = (os.path.basename(compsig_path), compsig_file_obj, "application/octet-stream")

            try:
                # Trigger upload callback at 0%
                if upload_progress_cb:
                    upload_progress_cb(0, file_size, 0.0)

                resp = self.session.post(
                    target_url,
                    headers=headers,
                    files=files,
                    timeout=300
                )

                if upload_progress_cb:
                    upload_progress_cb(file_size, file_size, 100.0)

            finally:
                if compsig_file_obj:
                    compsig_file_obj.close()

        if resp.status_code in [200, 201, 202]:
            task_uri = resp.headers.get("Location") or resp.headers.get("TaskMonitor")
            if not task_uri and resp.status_code == 202:
                try:
                    task_uri = resp.json().get("@odata.id")
                except Exception:
                    pass
            return True, f"Upload successful (HTTP {resp.status_code})", task_uri
        else:
            return False, f"Upload failed: HTTP {resp.status_code} - {resp.text[:300]}", None

    def poll_flash_progress(
        self,
        task_uri: Optional[str] = None,
        progress_cb: Optional[Callable[[int, str], None]] = None,
        max_duration_seconds: int = 600,
        poll_interval: int = 4
    ) -> Tuple[bool, str]:
        """
        Poll iLO flash progress via UpdateService and OEM extension Oem.Hpe.FlashProgressPercent.
        """
        start_time = time.time()
        last_percent = -1

        while time.time() - start_time < max_duration_seconds:
            try:
                # 1. Query UpdateService or Task
                service_info = self.get_update_service_info()
                oem_hpe = service_info.get("Oem", {}).get("Hpe", {})
                
                flash_percent = oem_hpe.get("FlashProgressPercent")
                flash_state = oem_hpe.get("State") or oem_hpe.get("States") or "Processing"

                # Check task object if task_uri is available
                task_state = None
                if task_uri:
                    try:
                        task_resp = self.session.get(self._full_url(task_uri), headers=self._get_headers(), timeout=10)
                        if task_resp.status_code == 200:
                            task_data = task_resp.json()
                            task_state = task_data.get("TaskState")
                            task_percent = task_data.get("PercentComplete")
                            if flash_percent is None and task_percent is not None:
                                flash_percent = int(task_percent)
                    except Exception:
                        pass

                # If flash progress percent is reported
                if flash_percent is not None:
                    try:
                        percent_int = int(flash_percent)
                    except ValueError:
                        percent_int = 0

                    if percent_int != last_percent:
                        last_percent = percent_int
                        if progress_cb:
                            progress_cb(percent_int, f"Flashing iLO ({flash_state})")

                    if percent_int >= 100:
                        return True, "Flash operation completed (100%)"

                # If state indicates completion
                if str(flash_state).lower() in ["complete", "completed", "idle", "success"]:
                    if last_percent >= 0:
                        if progress_cb:
                            progress_cb(100, "Flashing complete")
                        return True, f"Flash completed with state: {flash_state}"

                if str(task_state).lower() in ["completed", "complete"]:
                    if progress_cb:
                        progress_cb(100, "Task completed")
                    return True, "Task completed successfully"

                if str(flash_state).lower() in ["exception", "failed", "error", "killed"]:
                    return False, f"Flash failed with state: {flash_state}"

            except (requests.ConnectionError, requests.Timeout):
                # When iLO starts rewriting flash / preparing reboot, it may briefly hesitate or disconnect
                pass
            except Exception as e:
                # Intermittent network jitter
                pass

            time.sleep(poll_interval)

        return False, f"Flash operation timed out after {max_duration_seconds} seconds"

    def reset_ilo(self, reset_type: str = "GracefulRestart") -> Tuple[bool, str]:
        """
        Trigger iLO management controller reset via /redfish/v1/Managers/1/Actions/Manager.Reset.
        Does not affect the host OS running on the server.
        """
        if not self.is_logged_in:
            self.login()

        reset_url = self._full_url("/redfish/v1/Managers/1/Actions/Manager.Reset/")
        payload = {"ResetType": reset_type}
        headers = self._get_headers({"Content-Type": "application/json"})

        try:
            resp = self.session.post(reset_url, json=payload, headers=headers, timeout=15)
            if resp.status_code in [200, 202, 204]:
                return True, f"iLO reset command issued successfully (HTTP {resp.status_code})"
            else:
                return False, f"Reset command failed: HTTP {resp.status_code} - {resp.text}"
        except (requests.ConnectionError, requests.Timeout):
            # iLO often drops TCP immediately on reset; this confirms reset is underway
            return True, "iLO reset initiated (connection disconnected as expected)"
        except Exception as e:
            return False, f"Reset exception: {str(e)}"

    def wait_for_reboot_and_verify(
        self,
        initial_version: str,
        max_wait_seconds: int = 300,
        status_cb: Optional[Callable[[int, str], None]] = None
    ) -> Tuple[bool, str, str]:
        """
        Wait for iLO to restart, come back online, and verify the active firmware version.
        Returns: (success: bool, new_version: str, message: str)
        """
        self.logout()  # Invalidate old session
        start_time = time.time()

        # Phase 1: Wait for iLO to go offline
        if status_cb:
            status_cb(5, "Waiting for iLO services to shut down...")
        time.sleep(15)

        # Phase 2: Wait for iLO to come back online
        is_online = False
        while time.time() - start_time < max_wait_seconds:
            elapsed = int(time.time() - start_time)
            if status_cb:
                status_cb(min(int((elapsed / max_wait_seconds) * 100), 90), f"Waiting for iLO to boot ({elapsed}s)...")

            try:
                # Test connectivity
                test_url = self._full_url("/redfish/v1/")
                resp = requests.get(test_url, verify=False, timeout=5)
                if resp.status_code == 200:
                    is_online = True
                    break
            except Exception:
                pass

            time.sleep(5)

        if not is_online:
            return False, "Unreachable", f"iLO did not respond within {max_wait_seconds} seconds after reset"

        # Phase 3: Give iLO subsystem 10 seconds to fully stabilize manager services
        if status_cb:
            status_cb(92, "iLO is back online. Stabilizing Redfish services...")
        time.sleep(10)

        # Phase 4: Re-authenticate and verify firmware version
        if status_cb:
            status_cb(96, "Re-authenticating and querying new firmware version...")

        try:
            self.login()
            info = self.get_firmware_version_and_info()
            new_version = info.get("firmware_version", "Unknown")

            if status_cb:
                status_cb(100, f"Verified active firmware: {new_version}")

            is_updated = (new_version != initial_version)
            summary = (
                f"Upgrade Verified: '{initial_version}' -> '{new_version}'"
                if is_updated else
                f"Firmware version is '{new_version}' (No version change detected)"
            )
            return True, new_version, summary

        except Exception as e:
            return False, "Unknown", f"Re-authentication failed after reboot: {str(e)}"
