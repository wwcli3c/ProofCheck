#!/usr/bin/env python3
"""
ProofCheck local agent (prototype).
Runs only on localhost. Does not upload device data anywhere.
Python 3.10+ recommended. Optional: pip install psutil
"""
import json
import os
import platform
import socket
import tempfile
import time
import math
import shutil
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HOST = "127.0.0.1"
PORT = 8765
MAX_DISK_TEST_MB = 64

try:
    import psutil
except ImportError:
    psutil = None

def run_cmd(args, timeout=4):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        return (p.stdout or p.stderr).strip()[:5000]
    except Exception:
        return None

def get_battery():
    if psutil:
        try:
            b = psutil.sensors_battery()
            if b:
                return {
                    "percent": b.percent,
                    "plugged_in": b.power_plugged,
                    "seconds_left": b.secsleft if b.secsleft >= 0 else None,
                    "source": "psutil"
                }
        except Exception:
            pass
    system = platform.system()
    if system == "Darwin":
        out = run_cmd(["pmset", "-g", "batt"])
        if out:
            return {"raw": out, "source": "pmset", "note": "Battery percentage may be available; detailed health depends on macOS permissions/model."}
    elif system == "Windows":
        out = run_cmd(["powershell", "-NoProfile", "-Command",
                       "Get-CimInstance Win32_Battery | Select-Object EstimatedChargeRemaining,BatteryStatus | ConvertTo-Json -Compress"])
        if out and out != "null":
            try:
                return {"windows_battery": json.loads(out), "source": "Win32_Battery"}
            except Exception:
                pass
    return {"available": False, "note": "Battery telemetry unavailable through this prototype on this device."}

def get_temperature():
    if psutil:
        try:
            temps = psutil.sensors_temperatures(fahrenheit=False)
            result = {}
            for group, entries in (temps or {}).items():
                result[group] = [
                    {"label": e.label or group, "current_c": e.current, "high_c": e.high, "critical_c": e.critical}
                    for e in entries if e.current is not None
                ]
            if result:
                return {"available": True, "sensors": result, "source": "psutil"}
        except Exception:
            pass
    return {
        "available": False,
        "note": "CPU temperature is not exposed consistently by Windows/macOS APIs. Use a trusted vendor/OEM tool or a dedicated sensor-reading helper for this metric."
    }

def get_device_identity():
    """Return hardware identity fields exposed by the local operating system."""
    system = platform.system()
    if system == "Windows":
        ps = r"$cs=Get-CimInstance Win32_ComputerSystem; $bios=Get-CimInstance Win32_BIOS; [PSCustomObject]@{manufacturer=$cs.Manufacturer; model=$cs.Model; serial_number=$bios.SerialNumber; bios_release_date=if($bios.ReleaseDate){$bios.ReleaseDate.ToString('yyyy-MM-dd')}else{$null}} | ConvertTo-Json -Compress"
        try:
            raw = subprocess.check_output(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps], text=True, stderr=subprocess.DEVNULL, timeout=8)
            result = json.loads(raw.strip()) if raw.strip() else {}
            return {
                "manufacturer": result.get("manufacturer"),
                "model": result.get("model"),
                "serial_number": result.get("serial_number"),
                "bios_release_date": result.get("bios_release_date"),
                "release_date_note": "This is the BIOS firmware release date, not the laptop model's original market release date."
            }
        except Exception:
            pass
    elif system == "Darwin":
        try:
            raw = subprocess.check_output(["system_profiler", "SPHardwareDataType", "-json"], text=True, stderr=subprocess.DEVNULL, timeout=10)
            rows = json.loads(raw).get("SPHardwareDataType", [])
            hw = rows[0] if rows else {}
            return {
                "manufacturer": "Apple",
                "model": hw.get("machine_name") or hw.get("machine_model"),
                "serial_number": hw.get("serial_number"),
                "bios_release_date": None,
                "release_date_note": "macOS does not reliably expose the original market release date locally."
            }
        except Exception:
            pass
    return {"manufacturer": None, "model": None, "serial_number": None, "bios_release_date": None,
            "release_date_note": "Hardware identity fields were not available from the operating system."}

def system_info():
    disk = shutil.disk_usage(os.path.expanduser("~"))
    identity = get_device_identity()
    data = {
        "device_identity": identity,
        "os": platform.system(),
        "os_version": platform.version(),
        "os_release": platform.release(),
        "machine": platform.machine(),
        "processor": platform.processor() or "Not reported by OS",
        "python_version": platform.python_version(),
        "hostname": socket.gethostname(),
        "logical_cpu_count": os.cpu_count(),
        "memory": None,
        "disk_home": {
            "total_bytes": disk.total,
            "used_bytes": disk.used,
            "free_bytes": disk.free
        },
        "battery": get_battery(),
        "temperature": get_temperature(),
        "notes": [
            "Hostname is shown locally only; avoid sharing reports containing identifying information.",
            "Storage capacity/free space is not the same as SSD health.",
            "Battery charge percentage is not the same as battery maximum capacity/health."
        ]
    }
    if psutil:
        try:
            vm = psutil.virtual_memory()
            data["memory"] = {
                "total_bytes": vm.total, "available_bytes": vm.available,
                "used_bytes": vm.used, "percent_used": vm.percent
            }
            data["cpu_usage_percent_sample"] = psutil.cpu_percent(interval=0.35)
        except Exception:
            pass
    return data

def cpu_benchmark():
    # Small, bounded arithmetic benchmark; not a standardized industry benchmark.
    start = time.perf_counter()
    n = 220_000
    acc = 0.0
    for i in range(1, n + 1):
        acc += math.sqrt(i) * math.sin(i / 17.0)
    elapsed = time.perf_counter() - start
    return {
        "test": "CPU arithmetic microbenchmark",
        "elapsed_seconds": round(elapsed, 4),
        "operations": n,
        "operations_per_second": round(n / elapsed, 1) if elapsed else None,
        "checksum": round(acc, 4),
        "interpretation": "Compare repeated runs on the same device under similar power/temperature conditions. Not a universal pass/fail score."
    }

def memory_benchmark():
    # Allocate and touch a modest block; avoids stressing system memory.
    size = 8 * 1024 * 1024
    start = time.perf_counter()
    block = bytearray(size)
    step = 4096
    for i in range(0, size, step):
        block[i] = (i // step) % 256
    checksum = sum(block[::step])
    elapsed = time.perf_counter() - start
    del block
    return {
        "test": "Memory allocation/touch microbenchmark",
        "bytes_tested": size,
        "elapsed_seconds": round(elapsed, 4),
        "checksum": checksum,
        "interpretation": "Checks that a small memory allocation and write/read operation completes; it is not a full RAM error test."
    }

def disk_benchmark():
    # Non-destructive test: creates a temporary file in the user's home directory, then deletes it.
    # Limited to 64 MiB and reports buffered OS-level speed, not a certified drive health test.
    size = MAX_DISK_TEST_MB * 1024 * 1024
    chunk = os.urandom(1024 * 1024)
    path = None
    try:
        with tempfile.NamedTemporaryFile(prefix="proofcheck_", suffix=".tmp", dir=os.path.expanduser("~"), delete=False) as f:
            path = f.name
            start = time.perf_counter()
            written = 0
            while written < size:
                f.write(chunk[:min(len(chunk), size - written)])
                written += min(len(chunk), size - written)
            f.flush()
            os.fsync(f.fileno())
            write_elapsed = time.perf_counter() - start
        start = time.perf_counter()
        read = 0
        with open(path, "rb") as f:
            while True:
                part = f.read(1024 * 1024)
                if not part:
                    break
                read += len(part)
        read_elapsed = time.perf_counter() - start
        return {
            "test": "Temporary-file storage throughput test",
            "size_bytes": size,
            "write_mib_per_second": round((size / (1024*1024)) / write_elapsed, 2) if write_elapsed else None,
            "read_mib_per_second": round((read / (1024*1024)) / read_elapsed, 2) if read_elapsed else None,
            "write_seconds": round(write_elapsed, 3),
            "read_seconds": round(read_elapsed, 3),
            "interpretation": "Short buffered throughput sample only. Results vary with cache, free space, encryption, and background activity; not a SMART/SSD health test."
        }
    except Exception as e:
        return {"test": "Temporary-file storage throughput test", "error": str(e), "note": "Check free space and write permissions."}
    finally:
        if path:
            try:
                os.remove(path)
            except OSError:
                pass

def storage_health():
    system = platform.system()
    if system == "Windows":
        out = run_cmd(["powershell", "-NoProfile", "-Command",
                       "Get-PhysicalDisk | Select-Object FriendlyName,MediaType,HealthStatus,OperationalStatus,Size | ConvertTo-Json -Compress"], timeout=8)
        if out:
            try:
                return {"available": True, "source": "Get-PhysicalDisk", "data": json.loads(out)}
            except Exception:
                pass
    elif system == "Darwin":
        out = run_cmd(["diskutil", "info", "/"], timeout=5)
        if out:
            return {"available": True, "source": "diskutil info / (volume details, not full SMART health)", "data": out}
    return {
        "available": False,
        "note": "Detailed SMART health requires OS/vendor support and sometimes administrator permission. Consider smartmontools (smartctl) after reviewing its official documentation."
    }

class Handler(BaseHTTPRequestHandler):
    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(200, {"ok": True})

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            self._send(200, {"ok": True, "service": "ProofCheck Local Agent", "version": "0.1"})
        elif path == "/api/system":
            self._send(200, system_info())
        elif path == "/api/storage-health":
            self._send(200, storage_health())
        else:
            self._send(404, {"error": "Not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        if path != "/api/test":
            self._send(404, {"error": "Not found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1000:
            self._send(413, {"error": "Request too large"})
            return
        body = self.rfile.read(length) if length else b"{}"
        try:
            request = json.loads(body.decode("utf-8"))
        except Exception:
            request = {}
        tests = request.get("tests", ["cpu", "memory", "disk"])
        allowed = {"cpu", "memory", "disk"}
        if not isinstance(tests, list) or any(t not in allowed for t in tests):
            self._send(400, {"error": "Choose cpu, memory, and/or disk tests only."})
            return
        results = {}
        for test in tests:
            if test == "cpu": results["cpu"] = cpu_benchmark()
            elif test == "memory": results["memory"] = memory_benchmark()
            elif test == "disk": results["disk"] = disk_benchmark()
        self._send(200, {"results": results, "created_at": time.strftime("%Y-%m-%d %H:%M:%S")})

    def log_message(self, fmt, *args):
        print("[ProofCheck] " + fmt % args)

if __name__ == "__main__":
    print("ProofCheck local agent starting...")
    print("Only listening on this computer: http://127.0.0.1:%d" % PORT)
    print("Press Ctrl+C to stop.")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
