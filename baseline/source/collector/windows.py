from __future__ import annotations

import sys

from .contract import DETECTOR_ID, DETECTOR_VERSION, MAX_EVIDENCE, digest

UNINSTALL = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
FIELDS = {
    "raw_identifier": "DisplayName",
    "version": "DisplayVersion",
    "publisher": "Publisher",
}


def installed_programs(observed_at: str):
    """Read three named values in uninstall inventory; never recurse user files."""
    if sys.platform != "win32":
        return [], "unsupported"
    import winreg

    records = []
    status = "complete"
    for label, hive in (
        ("HKLM", winreg.HKEY_LOCAL_MACHINE),
        ("HKCU", winreg.HKEY_CURRENT_USER),
    ):
        for view, flag in (
            ("64", winreg.KEY_WOW64_64KEY),
            ("32", winreg.KEY_WOW64_32KEY),
        ):
            try:
                with winreg.OpenKey(hive, UNINSTALL, 0, winreg.KEY_READ | flag) as root:
                    count = winreg.QueryInfoKey(root)[0]
                    for index in range(min(count, MAX_EVIDENCE)):
                        try:
                            child = winreg.EnumKey(root, index)
                            with winreg.OpenKey(root, child) as item:
                                values = {}
                                for field, registry_value in FIELDS.items():
                                    try:
                                        value = winreg.QueryValueEx(
                                            item, registry_value
                                        )[0]
                                    except FileNotFoundError:
                                        value = ""
                                    if not isinstance(value, str):
                                        value = ""
                                    values[field] = "".join(
                                        c for c in value if ord(c) >= 32
                                    )[:512]
                            if not values["raw_identifier"].strip():
                                continue
                            record = {
                                "detector_id": DETECTOR_ID,
                                "detector_version": DETECTOR_VERSION,
                                "observed_at": observed_at,
                                "evidence_type": "installed_program",
                                "evidence_locator": (
                                    f"{label}/{view}/{UNINSTALL}/{child}"[:512]
                                ),
                                **values,
                            }
                            record["evidence_hash"] = digest(record)
                            records.append(record)
                            if len(records) >= MAX_EVIDENCE:
                                return records, "partial"
                        except OSError:
                            status = "partial"
                    if count > MAX_EVIDENCE:
                        status = "partial"
            except FileNotFoundError:
                continue
            except OSError:
                status = "partial"
    return sorted(records, key=lambda item: item["evidence_locator"]), status
