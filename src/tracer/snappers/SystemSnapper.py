"""
SystemSnapper - capture device hardware/software specs as JSON.

Dependency-free analogue of the Linux SystemSnapper. Reads /proc and Android
system properties (``getprop``) to produce the same set of ``system_spec/*.json``
files the Linux tracer emits, giving traces the context needed for analysis.
"""

import json
import os
import platform
import subprocess

from ...utility.utils import logger


def _getprop_all() -> dict:
    """Return all Android system properties as a dict (empty off-device)."""
    props = {}
    try:
        out = subprocess.check_output(["getprop"], text=True, stderr=subprocess.DEVNULL, timeout=10)
    except Exception:
        return props
    for line in out.splitlines():
        # Format: [key]: [value]
        if line.startswith("[") and "]: [" in line:
            k, v = line[1:].split("]: [", 1)
            props[k] = v.rstrip("]")
    return props


def _read(path: str) -> str:
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return ""


class SystemSnapper:
    def __init__(self, wm):
        self.wm = wm
        self.props = _getprop_all()

    def _cpu_info(self) -> dict:
        cpuinfo = _read("/proc/cpuinfo")
        model = ""
        for line in cpuinfo.splitlines():
            if line.startswith(("model name", "Hardware", "Processor")) and ":" in line:
                model = line.split(":", 1)[1].strip()
                break
        if not model:
            model = self.props.get("ro.board.platform", "") or platform.processor()
        return {
            "brand": model,
            "soc_manufacturer": self.props.get("ro.soc.manufacturer", ""),
            "soc_model": self.props.get("ro.soc.model", ""),
            "cores_logical": os.cpu_count(),
            "abi": self.props.get("ro.product.cpu.abi", platform.machine()),
        }

    def _memory_info(self) -> dict:
        info = {}
        for line in _read("/proc/meminfo").splitlines():
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            parts = v.split()
            if parts and parts[0].isdigit():
                info[k.strip()] = int(parts[0])  # kB
        total = info.get("MemTotal", 0)
        avail = info.get("MemAvailable", 0)
        return {
            "total_bytes": total * 1024,
            "available_bytes": avail * 1024,
            "total_gb": round(total / (1024 ** 2), 2),
            "available_gb": round(avail / (1024 ** 2), 2),
            "swap_total_bytes": info.get("SwapTotal", 0) * 1024,
            "swap_free_bytes": info.get("SwapFree", 0) * 1024,
        }

    def _disk_info(self) -> dict:
        partitions = []
        for line in _read("/proc/mounts").splitlines():
            parts = line.split()
            if len(parts) >= 3:
                device, mountpoint, fstype = parts[0], parts[1], parts[2]
                entry = {"device": device, "mountpoint": mountpoint, "fstype": fstype}
                try:
                    st = os.statvfs(mountpoint)
                    entry["total_bytes"] = st.f_blocks * st.f_frsize
                    entry["free_bytes"] = st.f_bavail * st.f_frsize
                except OSError:
                    pass
                partitions.append(entry)
        # Block devices and their rotational/size attributes from sysfs.
        devices = []
        sysblock = "/sys/block"
        if os.path.isdir(sysblock):
            for name in sorted(os.listdir(sysblock)):
                size = _read(f"{sysblock}/{name}/size").strip()
                rot = _read(f"{sysblock}/{name}/queue/rotational").strip()
                devices.append({
                    "name": name,
                    "size_bytes": int(size) * 512 if size.isdigit() else None,
                    "rotational": rot,
                })
        return {"partitions": partitions, "block_devices": devices}

    def _os_info(self) -> dict:
        return {
            "system": platform.system(),
            "kernel_release": platform.release(),
            "kernel_version": platform.version(),
            "machine": platform.machine(),
            "android_release": self.props.get("ro.build.version.release", ""),
            "android_sdk": self.props.get("ro.build.version.sdk", ""),
            "build_fingerprint": self.props.get("ro.build.fingerprint", ""),
            "manufacturer": self.props.get("ro.product.manufacturer", ""),
            "model": self.props.get("ro.product.model", ""),
            "device": self.props.get("ro.product.device", ""),
        }

    def capture_spec_snapshot(self):
        try:
            self.wm.direct_write("cpu_info.json", json.dumps(self._cpu_info(), indent=2))
            self.wm.direct_write("memory_info.json", json.dumps(self._memory_info(), indent=2))
            self.wm.direct_write("disk_info.json", json.dumps(self._disk_info(), indent=2))
            self.wm.direct_write("os_info.json", json.dumps(self._os_info(), indent=2))
            logger("info", "System spec snapshot captured")
        except Exception as e:
            logger("warning", f"System spec snapshot failed: {e}")
