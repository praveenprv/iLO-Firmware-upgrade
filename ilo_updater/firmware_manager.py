"""
Firmware Manager: scans, detects, matches, and validates local HPE iLO firmware packages.
Supports .fwpkg (standard Gen10/Gen11), .bin (raw flash), and .compsig signature pairing.
"""

import os
import re
from typing import List, Dict, Any, Optional


SUPPORTED_EXTENSIONS = [".fwpkg", ".bin", ".exe", ".rpm"]


class FirmwareFile:
    def __init__(self, file_path: str):
        self.file_path = os.path.abspath(file_path)
        self.filename = os.path.basename(file_path)
        self.size_bytes = os.path.getsize(self.file_path) if os.path.exists(self.file_path) else 0
        self.size_mb = round(self.size_bytes / (1024 * 1024), 2)
        self.extension = os.path.splitext(self.filename)[1].lower()
        self.detected_ilo_type = self._detect_ilo_type()
        self.version_hint = self._detect_version()
        self.compsig_path = self._find_compsig()

    def _detect_ilo_type(self) -> Optional[str]:
        """Detect target iLO generation from filename."""
        fn = self.filename.lower()
        if "ilo7" in fn or "ilo_7" in fn:
            return "iLO7"
        if "ilo6" in fn or "ilo_6" in fn:
            return "iLO6"
        if "ilo5" in fn or "ilo_5" in fn:
            return "iLO5"
        if "ilo4" in fn or "ilo_4" in fn:
            return "iLO4"
        return "Unknown"

    def _detect_version(self) -> Optional[str]:
        """Attempt to extract version string from filename (e.g., ilo5_304 -> 3.04)."""
        fn = self.filename.lower()
        # Match patterns like ilo5_304 or ilo6_167 or 3.04 or v2.81
        match = re.search(r"ilo\d[_-](\d)(\d{2})", fn)
        if match:
            return f"v{match.group(1)}.{match.group(2)}"
        match = re.search(r"[vV]?(\d+\.\d+(\.\d+)?)", fn)
        if match:
            return f"v{match.group(1)}"
        return None

    def _find_compsig(self) -> Optional[str]:
        """Check if an associated .compsig file exists alongside this component."""
        base, _ = os.path.splitext(self.file_path)
        compsig_candidate = base + ".compsig"
        if os.path.isfile(compsig_candidate):
            return compsig_candidate
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "filename": self.filename,
            "path": self.file_path,
            "size_mb": self.size_mb,
            "extension": self.extension,
            "detected_type": self.detected_ilo_type,
            "version_hint": self.version_hint,
            "has_compsig": self.compsig_path is not None,
            "compsig_path": self.compsig_path
        }


def scan_firmware_directory(dir_path: str) -> List[FirmwareFile]:
    """Scan a local directory for valid iLO firmware files."""
    if not os.path.isdir(dir_path):
        return []

    firmware_files: List[FirmwareFile] = []
    for entry in os.listdir(dir_path):
        full_path = os.path.join(dir_path, entry)
        if os.path.isfile(full_path):
            _, ext = os.path.splitext(entry)
            if ext.lower() in SUPPORTED_EXTENSIONS:
                firmware_files.append(FirmwareFile(full_path))

    # Sort files by filename
    firmware_files.sort(key=lambda x: x.filename.lower())
    return firmware_files


def find_best_firmware_match(
    ilo_type: str, 
    available_files: List[FirmwareFile]
) -> Optional[FirmwareFile]:
    """Find the best matching firmware file for a given iLO generation (e.g. iLO5)."""
    norm_type = ilo_type.upper().replace(" ", "")
    matches = [fw for fw in available_files if fw.detected_ilo_type.upper() == norm_type]
    
    if matches:
        # Return the newest or first match
        return matches[-1]
    
    # Fallback: if only one firmware file in directory, match it
    if len(available_files) == 1:
        return available_files[0]
        
    return None


def validate_firmware_file(file_path: str) -> bool:
    """Validate that a firmware file exists, is non-empty, and has a supported extension."""
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"Firmware file not found: {file_path}")
    
    size = os.path.getsize(file_path)
    if size == 0:
        raise ValueError(f"Firmware file is empty (0 bytes): {file_path}")

    _, ext = os.path.splitext(file_path)
    if ext.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file format '{ext}'. Supported formats: {', '.join(SUPPORTED_EXTENSIONS)}"
        )

    return True
