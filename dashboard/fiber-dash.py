#!/usr/bin/env python3
"""
Fiber Network Node Dashboard — Full Edition
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Zero-dependency local dashboard. Monitor AND control your Fiber node.
"""
DASHBOARD_VERSION = "1.3.0"
DASHBOARD_RAW_URL = "https://raw.githubusercontent.com/toastmanAu/fiber-installer/master/dashboard/fiber-dash.py"
DASHBOARD_RELEASES_URL = "https://api.github.com/repos/toastmanAu/fiber-installer/releases/latest"

_USAGE = """
Usage:
    python3 fiber-dash.py [options]

Options:
    --fiber-rpc  URL    Fiber RPC endpoint (default: http://127.0.0.1:8227)
    --ckb-rpc    URL    CKB RPC endpoint   (default: http://127.0.0.1:8114)
    --port       INT    Dashboard port     (default: 8229)
    --host       STR    Listen host        (default: 0.0.0.0)
    --biscuit    STR    Biscuit auth token
    --network    STR    mainnet|testnet    (default: mainnet)
    --fnn-bin    PATH   Path to fnn binary (enables node control)
    --data-dir   PATH   Fiber data dir     (enables log/maintenance ops)
    --service    STR    systemd service name (default: fiber)
    --log-file   PATH   Log file path      (alternative to journald)
    --ssh-host   STR    SSH host to run control commands on (e.g. orangepi@192.168.68.87)
                        If set, Start/Stop/Restart/logs run via SSH instead of locally
    --ssh-user   STR    SSH user override (alternative to user@host in --ssh-host)
    --control         Enable node control + maintenance ops (required for those features)
"""

import argparse, json, sys, os, socket, subprocess, shutil, threading, time
import urllib.request, urllib.error, hashlib
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# ── Args ───────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--fiber-rpc", default="http://127.0.0.1:8227")
parser.add_argument("--ckb-rpc",   default="http://127.0.0.1:8114")
parser.add_argument("--port",      default=8229, type=int)
parser.add_argument("--host",      default="0.0.0.0")
parser.add_argument("--biscuit",   default="")
parser.add_argument("--network",   default="mainnet", choices=["mainnet","testnet","devnet"])
parser.add_argument("--fnn-bin",   default="")
parser.add_argument("--data-dir",  default="")
parser.add_argument("--service",   default="fiber")
parser.add_argument("--log-file",  default="")
parser.add_argument("--ssh-host",  default="", help="SSH host for remote control (user@host or host)")
parser.add_argument("--control",   action="store_true")
args = parser.parse_args()

FIBER_RPC    = args.fiber_rpc
CKB_RPC      = args.ckb_rpc
BISCUIT      = args.biscuit
NETWORK      = args.network
FNN_BIN      = args.fnn_bin or shutil.which("fnn") or ""
DATA_DIR     = args.data_dir
SERVICE      = args.service
LOG_FILE     = args.log_file
SSH_HOST     = args.ssh_host   # e.g. "orangepi@192.168.68.87"
CONTROL      = args.control

# Auto-detect data dir if not specified
if not DATA_DIR and os.path.isdir(os.path.expanduser("~/.fiber/data")):
    DATA_DIR = os.path.expanduser("~/.fiber/data")

# ── CKB Address derivation ─────────────────────────────────────────────────────
BECH32M_CONST = 0x2bc830a3
CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"

def _polymod(values):
    GEN = [0x3b6a57b2,0x26508e6d,0x1ea119fa,0x3d4233dd,0x2a1462b3]
    chk = 1
    for v in values:
        b = chk >> 25; chk = (chk & 0x1ffffff) << 5 ^ v
        for i in range(5): chk ^= GEN[i] if ((b >> i) & 1) else 0
    return chk

def _hrp_expand(hrp): return [ord(x)>>5 for x in hrp]+[0]+[ord(x)&31 for x in hrp]

def _create_checksum(hrp, data):
    poly = _polymod(_hrp_expand(hrp)+list(data)+[0,0,0,0,0,0]) ^ BECH32M_CONST
    return [(poly>>5*(5-i))&31 for i in range(6)]

def _convertbits(data, frombits, tobits, pad=True):
    acc=bits=0; ret=[]; maxv=(1<<tobits)-1
    for v in data:
        acc=(acc<<frombits)|v; bits+=frombits
        while bits>=tobits: bits-=tobits; ret.append((acc>>bits)&maxv)
    if pad and bits: ret.append((acc<<(tobits-bits))&maxv)
    return ret

def lock_to_address(code_hash_hex, hash_type, args_hex, network="mainnet"):
    try:
        hrp = {"mainnet":"ckb","testnet":"ckt","devnet":"ckt"}.get(network,"ckb")
        code_hash = bytes.fromhex(code_hash_hex.lstrip("0x"))
        ht_byte   = 0x01 if hash_type=="type" else (0x02 if hash_type=="data1" else 0x00)
        arg_bytes = bytes.fromhex(args_hex.lstrip("0x"))
        payload   = bytes([0x00])+code_hash+bytes([ht_byte])+arg_bytes
        data5     = _convertbits(payload,8,5)
        checksum  = _create_checksum(hrp, data5)
        return hrp+"1"+"".join(CHARSET[d] for d in data5+checksum)
    except: return None

# ── RPC ────────────────────────────────────────────────────────────────────────
_rpc_id = 0
def rpc_call(url, method, params=None, token=""):
    global _rpc_id; _rpc_id += 1
    body = json.dumps({"id":_rpc_id,"jsonrpc":"2.0","method":method,"params":params or [{}]}).encode()
    headers = {"Content-Type":"application/json"}
    if token: headers["Authorization"] = f"Bearer {token}"
    try:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=8) as r: return json.loads(r.read())
    except Exception as e: return {"error":{"message":str(e)}}

# ── System helpers ─────────────────────────────────────────────────────────────
def _run(cmd_list, timeout=10, remote=False):
    """Run a command locally or via SSH if SSH_HOST is configured."""
    if remote and SSH_HOST:
        full_cmd = ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
                    SSH_HOST, " ".join(cmd_list)]
    else:
        full_cmd = cmd_list
    return subprocess.run(full_cmd, capture_output=True, text=True, timeout=timeout)

def get_fnn_pid():
    try:
        import platform
        if platform.system() == "Windows":
            r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq fnn.exe", "/FO", "CSV", "/NH"],
                               capture_output=True, text=True, timeout=5)
            for line in r.stdout.splitlines():
                if "fnn.exe" in line:
                    parts = line.strip('"').split('","')
                    if len(parts) > 1:
                        try: return int(parts[1])
                        except: pass
            return None
        r = _run(["pgrep", "-f", "fnn"], remote=bool(SSH_HOST), timeout=5)
        pids = [int(p) for p in r.stdout.strip().split() if p.isdigit()]
        return pids[0] if pids else None
    except: return None

def get_process_stats():
    pid = get_fnn_pid()
    if not pid: return {"running": False}
    try:
        r = _run(["ps", "-p", str(pid), "-o", "pid=,pcpu=,rss=,etime="],
                 remote=bool(SSH_HOST), timeout=5)
        parts = r.stdout.strip().split()
        if len(parts) >= 4:
            return {"running": True, "pid": parts[0], "cpu_pct": parts[1],
                    "ram_mb": round(int(parts[2])/1024, 1), "uptime": parts[3]}
    except: pass
    return {"running": bool(pid), "pid": pid}

def get_connections():
    try:
        import platform
        if platform.system() == "Windows":
            r = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=5)
            pid = get_fnn_pid()
            if pid:
                return [l for l in r.stdout.splitlines() if str(pid) in l and "ESTABLISHED" in l][:20]
            return []
        r = _run(["ss", "-tnp"], remote=bool(SSH_HOST), timeout=5)
        return [l for l in r.stdout.splitlines() if "fnn" in l or "fiber" in l.lower()][:20]
    except: return []

def get_log_lines(n=50):
    lines = []
    if LOG_FILE and os.path.isfile(LOG_FILE) and not SSH_HOST:
        try:
            # Pure Python tail — works on all platforms including Windows
            with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()[-n:]
            lines = [l.rstrip() for l in lines]
        except: pass
    else:
        try:
            if SSH_HOST:
                cmd = ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", SSH_HOST,
                       f"journalctl --user -u {SERVICE} -n{n} --no-pager --output=short 2>/dev/null || "
                       f"tail -n{n} {LOG_FILE} 2>/dev/null || echo 'No logs available'"]
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            else:
                r = subprocess.run(
                    ["journalctl", "--user", "-u", SERVICE, f"-n{n}", "--no-pager", "--output=short"],
                    capture_output=True, text=True, timeout=5)
            lines = r.stdout.splitlines()
        except: pass
    return lines

def systemctl(action):
    """Run a systemctl --user action. Falls back to direct process management if no service exists."""
    try:
        # First try systemctl user service
        cmd = ["systemctl", "--user", action, SERVICE]
        r = _run(cmd, remote=bool(SSH_HOST), timeout=15)
        if r.returncode == 0:
            return {"ok": True, "output": r.stdout.strip() or f"{action} OK"}

        # If service not found, try system-level service
        if "not found" in r.stderr.lower() or "not found" in r.stdout.lower():
            cmd_sys = ["sudo", "systemctl", action, SERVICE]
            r2 = _run(cmd_sys, remote=bool(SSH_HOST), timeout=15)
            if r2.returncode == 0:
                return {"ok": True, "output": f"{action} OK (system service)"}

            # Fall back to direct process control
            if action == "stop":
                r3 = _run(["pkill", "-TERM", "-f", "fnn"], remote=bool(SSH_HOST), timeout=10)
                return {"ok": True, "output": "Sent SIGTERM to fnn process"}

            elif action == "start":
                if not FNN_BIN:
                    return {"ok": False, "output": "No systemd service found and --fnn-bin not set. Cannot start."}
                config = os.path.join(DATA_DIR, "config.yml") if DATA_DIR else ""
                if not config or not os.path.isfile(config if not SSH_HOST else "/dev/null"):
                    return {"ok": False, "output": f"No systemd service found. Set --data-dir or install service."}
                install_dir = os.path.dirname(os.path.dirname(FNN_BIN))
                env = os.environ.copy()
                import platform
                if platform.system() == "Windows":
                    # Use start-fiber.bat if it exists (has key password set)
                    bat = os.path.join(install_dir, "start-fiber.bat")
                    if os.path.isfile(bat):
                        subprocess.Popen(["cmd", "/c", bat], creationflags=0x00000008)
                    else:
                        key_pass = os.environ.get("COMPUTERNAME","PC") + "-fiber-" + str(__import__("datetime").date.today().year)
                        env["FIBER_SECRET_KEY_PASSWORD"] = key_pass
                        subprocess.Popen([FNN_BIN, "--config", config, "--dir", install_dir], env=env,
                                         creationflags=0x00000008)
                else:
                    start_cmd = f"nohup {FNN_BIN} --config {config} --dir {install_dir} > /tmp/fnn.log 2>&1 &"
                    if SSH_HOST:
                        subprocess.run(["ssh", "-o", "BatchMode=yes", SSH_HOST, start_cmd],
                            capture_output=True, text=True, timeout=10)
                    else:
                        subprocess.run(start_cmd, shell=True, capture_output=True, text=True)
                return {"ok": True, "output": "Started fnn"}

            elif action == "restart":
                import platform
                install_dir = os.path.dirname(os.path.dirname(FNN_BIN)) if FNN_BIN else ""
                if platform.system() == "Windows":
                    subprocess.run(["taskkill", "/IM", "fnn.exe", "/F"], capture_output=True)
                    time.sleep(2)
                    if FNN_BIN and DATA_DIR:
                        bat = os.path.join(install_dir, "start-fiber.bat")
                        if os.path.isfile(bat):
                            subprocess.Popen(["cmd", "/c", bat], creationflags=0x00000008)
                        else:
                            config = os.path.join(DATA_DIR, "config.yml")
                            subprocess.Popen([FNN_BIN, "--config", config, "--dir", install_dir],
                                             creationflags=0x00000008)
                    return {"ok": True, "output": "Restarted fnn"}
                else:
                    _run(["pkill", "-TERM", "-f", "fnn"], remote=bool(SSH_HOST), timeout=10)
                    time.sleep(3)
                    if FNN_BIN and DATA_DIR:
                        config = os.path.join(DATA_DIR, "config.yml")
                        start_cmd = f"nohup {FNN_BIN} --config {config} --dir {install_dir} > /tmp/fnn.log 2>&1 &"
                        if SSH_HOST:
                            subprocess.run(["ssh", "-o", "BatchMode=yes", SSH_HOST, start_cmd], timeout=10)
                        else:
                            subprocess.run(start_cmd, shell=True)
                    return {"ok": True, "output": "Restarted fnn"}

            elif action in ("enable", "disable"):
                return {"ok": False, "output": "Autostart requires a systemd service. Run the installer to set one up."}

        return {"ok": False, "output": (r.stdout + r.stderr).strip()}
    except Exception as e:
        return {"ok": False, "output": str(e)}

def do_maintenance(action, payload=None):
    """Execute a maintenance action. Returns {ok, message}."""
    if not CONTROL:
        return {"ok": False, "message": "Control mode not enabled (pass --control flag)"}

    if action == "clean-locks":
        if not DATA_DIR: return {"ok": False, "message": "--data-dir not set"}
        removed = []
        for f in Path(DATA_DIR).rglob("*.lock"):
            try: f.unlink(); removed.append(str(f))
            except: pass
        return {"ok": True, "message": f"Removed {len(removed)} lock file(s)"}

    elif action == "backup":
        if not DATA_DIR: return {"ok": False, "message": "--data-dir not set"}
        backup_path = os.path.expanduser(f"~/fiber-backup-{int(time.time())}.tar.gz")
        try:
            r = subprocess.run(
                ["tar","czf",backup_path,"--exclude=store","-C",os.path.dirname(DATA_DIR),os.path.basename(DATA_DIR)],
                capture_output=True, text=True, timeout=30
            )
            if r.returncode == 0:
                size = os.path.getsize(backup_path)
                return {"ok": True, "message": f"Backup saved: {backup_path} ({size//1024}KB)"}
            return {"ok": False, "message": r.stderr}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    elif action == "check-updates":
        results = {}
        # Check fnn binary version vs latest release
        try:
            rel = json.loads(urllib.request.urlopen(
                "https://api.github.com/repos/nervosnetwork/fiber/releases/latest", timeout=10
            ).read())
            latest_fnn = rel["tag_name"]
            current_fnn = "unknown"
            if FNN_BIN and os.path.isfile(FNN_BIN):
                r = subprocess.run([FNN_BIN, "--version"], capture_output=True, text=True, timeout=5)
                import re as _re
                m = _re.search(r'v[\d.]+', r.stdout + r.stderr)
                current_fnn = m.group(0) if m else "unknown"
            results["fnn"] = {"current": current_fnn, "latest": latest_fnn,
                              "up_to_date": current_fnn == latest_fnn}
        except Exception as e:
            results["fnn"] = {"error": str(e)}
        # Check dashboard version vs latest on GitHub
        try:
            raw = urllib.request.urlopen(DASHBOARD_RAW_URL, timeout=10).read().decode()
            import re as _re
            m = _re.search(r'DASHBOARD_VERSION\s*=\s*["\']([^"\']+)["\']', raw)
            latest_dash = m.group(1) if m else "unknown"
            results["dashboard"] = {"current": DASHBOARD_VERSION, "latest": latest_dash,
                                    "up_to_date": DASHBOARD_VERSION == latest_dash}
        except Exception as e:
            results["dashboard"] = {"current": DASHBOARD_VERSION, "error": str(e)}
        any_updates = any(not v.get("up_to_date", True) for v in results.values() if "error" not in v)
        msg = "Everything up to date ✓" if not any_updates else "Updates available"
        return {"ok": True, "message": msg, "results": results}

    elif action == "update-dashboard":
        # OTA update: fetch latest fiber-dash.py from GitHub, replace self, restart service
        try:
            raw = urllib.request.urlopen(DASHBOARD_RAW_URL, timeout=30).read()
            if len(raw) < 1000:
                return {"ok": False, "message": "Downloaded file too small — aborting"}
            this_file = os.path.abspath(__file__)
            # Backup current
            backup = this_file + ".bak"
            shutil.copy2(this_file, backup)
            with open(this_file, "wb") as f:
                f.write(raw)
            os.chmod(this_file, 0o755)
            # Restart the dashboard service
            _SC = "systemctl" if os.geteuid() == 0 else "systemctl --user"
            svc = "fiber-dash"
            subprocess.Popen(f"{_SC} restart {svc}", shell=True)
            return {"ok": True, "message": f"Dashboard updated and restarting — refresh in 5 seconds (backup at {backup})"}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    elif action == "update-binary":
        if not FNN_BIN: return {"ok": False, "message": "--fnn-bin not set"}
        import platform
        os_name = platform.system().lower()
        arch = platform.machine().lower()
        if os_name == "linux": plat = "x86_64-linux-portable" if "x86" in arch else "aarch64-linux-portable"
        elif os_name == "darwin": plat = "x86_64-darwin-portable"
        else: return {"ok": False, "message": f"Unsupported OS: {os_name}"}
        try:
            # Get latest version
            rel = json.loads(urllib.request.urlopen(
                "https://api.github.com/repos/nervosnetwork/fiber/releases/latest",timeout=10
            ).read())
            version = rel["tag_name"]
            url = f"https://github.com/nervosnetwork/fiber/releases/download/{version}/fnn_{version}-{plat}.tar.gz"
            tmp = f"/tmp/fnn-update-{int(time.time())}.tar.gz"
            urllib.request.urlretrieve(url, tmp)
            # Extract
            subprocess.run(["tar","xzf",tmp,"-C","/tmp"], check=True, timeout=30)
            # Find binary
            fnn_tmp = subprocess.run(["find","/tmp","-name","fnn","-newer",tmp,"-type","f"],
                capture_output=True,text=True).stdout.strip().split("\n")[0]
            if not fnn_tmp or not os.path.isfile(fnn_tmp):
                return {"ok": False, "message": "Could not find fnn in extracted archive"}
            shutil.copy2(fnn_tmp, FNN_BIN)
            os.chmod(FNN_BIN, 0o755)
            os.unlink(tmp)
            return {"ok": True, "message": f"Updated to {version} at {FNN_BIN}"}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    elif action == "open-firewall":
        port = "8228"
        try:
            r = subprocess.run(["sudo","ufw","allow",port+"/tcp"], capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                return {"ok": True, "message": f"ufw: port {port}/tcp allowed"}
            # Try firewall-cmd
            r2 = subprocess.run(["sudo","firewall-cmd","--add-port="+port+"/tcp","--permanent"],
                capture_output=True, text=True, timeout=10)
            return {"ok": r2.returncode==0, "message": r2.stdout+r2.stderr}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    elif action == "view-config":
        if not DATA_DIR: return {"ok": False, "message": "--data-dir not set"}
        cfg = os.path.join(DATA_DIR, "config.yml")
        if not os.path.isfile(cfg): return {"ok": False, "message": f"Not found: {cfg}"}
        try:
            return {"ok": True, "content": open(cfg).read()}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    elif action == "edit-config":
        # Patch specific keys in config.yml without requiring a full rewrite
        # Payload: {"action":"edit-config", "changes": {"ckb_rpc_url": "http://...", ...}}
        if not DATA_DIR: return {"ok": False, "message": "--data-dir not set"}
        cfg_path = os.path.join(DATA_DIR, "config.yml")
        if not os.path.isfile(cfg_path): return {"ok": False, "message": f"Config not found: {cfg_path}"}
        changes = payload.get("changes", {}) if isinstance(payload, dict) else {}
        if not changes: return {"ok": False, "message": "No changes provided"}
        try:
            content = open(cfg_path).read()
            import re as _re
            applied = []
            for key, val in changes.items():
                if key == "ckb_rpc_url":
                    content, n = _re.subn(r'(rpc_url:\s*)["\']?[^"\'\n]+["\']?', f'rpc_url: "{val}"', content)
                    if n: applied.append(f"ckb_rpc_url → {val}")
                elif key == "fiber_rpc_port":
                    content, n = _re.subn(r'(listening_addr:\s*)["\']?[^"\'\n]+["\']?', f'listening_addr: "{val}"', content, count=1)
                    if n: applied.append(f"fiber_rpc_port → {val}")
                elif key == "biscuit_public_key":
                    if val:
                        # Set or update biscuit_public_key under rpc: section
                        if _re.search(r'biscuit_public_key:', content):
                            content, n = _re.subn(r'(biscuit_public_key:\s*)["\']?[^"\'\n]*["\']?', f'biscuit_public_key: "{val}"', content)
                        else:
                            # Insert after listening_addr in rpc: block
                            content, n = _re.subn(r'(rpc:\s*\n\s*listening_addr:[^\n]+)', rf'\1\n  biscuit_public_key: "{val}"', content)
                        if n: applied.append(f"biscuit_public_key set")
                    else:
                        # Remove biscuit_public_key line entirely
                        content, n = _re.subn(r'\s*biscuit_public_key:[^\n]*\n', '\n', content)
                        if n: applied.append("biscuit_public_key removed (auth disabled)")
            if not applied: return {"ok": False, "message": "No matching keys found to update"}
            with open(cfg_path, "w") as f: f.write(content)
            return {"ok": True, "message": "Config updated: " + ", ".join(applied) + ". Restart Fiber to apply."}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    elif action == "verify-key":
        if not DATA_DIR: return {"ok": False, "message": "--data-dir not set"}
        key_file = os.path.join(DATA_DIR, "key")
        issues = []
        if not os.path.isfile(key_file): return {"ok": False, "message": f"Key file not found: {key_file}"}
        mode = oct(os.stat(key_file).st_mode)
        if not mode.endswith("600"): issues.append(f"Permissions {mode} (should be 600)")
        content = open(key_file).read().strip()
        if not content.startswith("0x"): issues.append("Key doesn't start with 0x")
        if len(content) != 66: issues.append(f"Key length {len(content)} (expected 66 chars)")
        if issues:
            return {"ok": False, "message": "Key issues: " + "; ".join(issues)}
        return {"ok": True, "message": f"Key OK ✓ — {key_file} (600, 32 bytes)"}

    elif action == "download-config":
        if not DATA_DIR: return {"ok": False, "message": "--data-dir not set"}
        net = NETWORK
        url = f"https://raw.githubusercontent.com/nervosnetwork/fiber/main/config/{net}/config.yml"
        out = os.path.join(DATA_DIR, "config-latest.yml")
        try:
            urllib.request.urlretrieve(url, out)
            return {"ok": True, "message": f"Downloaded to {out}"}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    elif action == "install-ckb-cli":
        install_dir = os.path.dirname(FNN_BIN) if FNN_BIN else os.path.expanduser("~/.fiber/bin")
        try:
            rel = json.loads(urllib.request.urlopen(
                "https://api.github.com/repos/nervosnetwork/ckb/releases/latest",timeout=10
            ).read())
            version = rel["tag_name"]
            import platform; os_name = platform.system().lower()
            plat = "x86_64-unknown-linux-gnu" if os_name=="linux" else "x86_64-apple-darwin"
            url = f"https://github.com/nervosnetwork/ckb/releases/download/{version}/ckb_{version}_{plat}.tar.gz"
            tmp = f"/tmp/ckb-cli-{int(time.time())}.tar.gz"
            urllib.request.urlretrieve(url, tmp)
            subprocess.run(["tar","xzf",tmp,"-C","/tmp"],check=True,timeout=60)
            cli = subprocess.run(["find","/tmp","-name","ckb-cli","-newer",tmp,"-type","f"],
                capture_output=True,text=True).stdout.strip().split("\n")[0]
            if cli and os.path.isfile(cli):
                dest = os.path.join(install_dir, "ckb-cli")
                shutil.copy2(cli, dest); os.chmod(dest, 0o755)
                return {"ok": True, "message": f"ckb-cli {version} → {dest}"}
            return {"ok": False, "message": "Binary not found in archive"}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    return {"ok": False, "message": f"Unknown action: {action}"}

# ── HTML ───────────────────────────────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Fiber Node Dashboard</title>
<style>
:root{
  --bg:#07090f;--surface:#0f1117;--surface2:#161b26;--surface3:#1c2333;
  --border:#1e2a3a;--text:#e2e8f0;--muted:#64748b;
  --accent:#00c8ff;--green:#22c55e;--red:#ef4444;--yellow:#f59e0b;--purple:#a78bfa;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:14px}

header{background:var(--surface);border-bottom:1px solid var(--border);padding:0 1.5rem;
  display:flex;align-items:center;justify-content:space-between;height:56px;position:sticky;top:0;z-index:100}
.logo{font-size:1.1rem;font-weight:700;color:var(--accent);display:flex;align-items:center;gap:.5rem}
.logo svg{width:22px;height:22px}
.hdr-right{display:flex;align-items:center;gap:.6rem;flex-wrap:wrap}
.status-badge{display:flex;align-items:center;gap:.4rem;font-size:.8rem;color:var(--muted)}
.dot{width:8px;height:8px;border-radius:50%;background:var(--muted)}
.dot.green{background:var(--green);box-shadow:0 0 6px var(--green);animation:pulse 2s infinite}
.dot.red{background:var(--red)} .dot.yellow{background:var(--yellow)}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}

.btn{display:inline-flex;align-items:center;gap:.3rem;padding:.4rem .9rem;border-radius:7px;
  font-size:.82rem;font-weight:500;cursor:pointer;border:none;transition:all .15s;white-space:nowrap}
.btn-ghost{background:none;border:1px solid var(--border);color:var(--muted)}
.btn-ghost:hover{border-color:var(--accent);color:var(--accent)}
.btn-primary{background:var(--accent);color:#000}
.btn-primary:hover{background:#33d4ff}
.btn-danger{background:rgba(239,68,68,.15);color:var(--red);border:1px solid rgba(239,68,68,.3)}
.btn-danger:hover{background:rgba(239,68,68,.25)}
.btn-success{background:rgba(34,197,94,.15);color:var(--green);border:1px solid rgba(34,197,94,.3)}
.btn-success:hover{background:rgba(34,197,94,.25)}
.btn-warn{background:rgba(245,158,11,.15);color:var(--yellow);border:1px solid rgba(245,158,11,.3)}
.btn-warn:hover{background:rgba(245,158,11,.25)}
.btn-sm{padding:.25rem .6rem;font-size:.75rem}
.btn:disabled{opacity:.4;cursor:not-allowed}

main{max-width:1360px;margin:0 auto;padding:1.5rem;display:grid;gap:1rem}
.grid-2{display:grid;grid-template-columns:1fr 1fr;gap:1rem}
.grid-3{display:grid;grid-template-columns:repeat(3,1fr);gap:1rem}
.grid-4{display:grid;grid-template-columns:repeat(4,1fr);gap:1rem}
@media(max-width:1000px){.grid-2,.grid-3,.grid-4{grid-template-columns:1fr 1fr}}
@media(max-width:600px){.grid-2,.grid-3,.grid-4{grid-template-columns:1fr}}

.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;overflow:hidden}
.card-header{padding:.8rem 1.2rem;border-bottom:1px solid var(--border);
  display:flex;align-items:center;justify-content:space-between;gap:.5rem}
.card-title{font-weight:600;font-size:.82rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
.card-body{padding:1.2rem}

.stat-value{font-size:1.8rem;font-weight:700;line-height:1}
.stat-value.accent{color:var(--accent)}.stat-value.green{color:var(--green)}.stat-value.purple{color:var(--purple)}
.stat-label{font-size:.72rem;color:var(--muted);margin-top:.3rem}

.info-row{display:flex;justify-content:space-between;align-items:center;
  padding:.4rem 0;border-bottom:1px solid var(--border);font-size:.82rem}
.info-row:last-child{border-bottom:none}
.info-key{color:var(--muted);flex-shrink:0;margin-right:.5rem}
.info-val{font-family:monospace;font-size:.76rem;max-width:65%;text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

.tbl-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:.82rem}
th{text-align:left;padding:.5rem .75rem;color:var(--muted);font-weight:500;border-bottom:1px solid var(--border);white-space:nowrap}
td{padding:.6rem .75rem;border-bottom:1px solid var(--border);vertical-align:middle}
tr:last-child td{border-bottom:none}
tr:hover td{background:var(--surface2)}
.mono{font-family:monospace;font-size:.73rem}

.pill{display:inline-block;padding:.15rem .5rem;border-radius:99px;font-size:.7rem;font-weight:600}
.pill-green{background:rgba(34,197,94,.15);color:var(--green)}
.pill-yellow{background:rgba(245,158,11,.15);color:var(--yellow)}
.pill-red{background:rgba(239,68,68,.15);color:var(--red)}
.pill-blue{background:rgba(0,200,255,.12);color:var(--accent)}
.pill-purple{background:rgba(167,139,250,.12);color:var(--purple)}

.liq-wrap{display:flex;align-items:center;gap:.5rem;min-width:100px}
.liq-bar{flex:1;height:6px;border-radius:3px;background:var(--surface2);overflow:hidden}
.liq-fill{height:100%;border-radius:3px;background:linear-gradient(90deg,var(--accent),var(--purple))}

.addr-box{font-family:monospace;font-size:.72rem;color:var(--accent);background:var(--surface2);
  padding:.5rem .75rem;border-radius:6px;word-break:break-all;cursor:pointer;
  border:1px solid var(--border);transition:border-color .15s;margin-top:.3rem}
.addr-box:hover{border-color:var(--accent)}

.empty{text-align:center;color:var(--muted);padding:2.5rem 1rem}
.empty .icon{font-size:2rem;margin-bottom:.5rem}
.spin{display:inline-block;width:16px;height:16px;border:2px solid var(--border);
  border-top-color:var(--accent);border-radius:50%;animation:spin .7s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}

/* Node control button group */
.ctrl-grid{display:grid;grid-template-columns:1fr 1fr;gap:.5rem}
.ctrl-btn{display:flex;align-items:center;justify-content:center;gap:.4rem;
  padding:.6rem;border-radius:8px;font-size:.8rem;font-weight:500;cursor:pointer;border:none;transition:all .15s}
.ctrl-btn.start{background:rgba(34,197,94,.12);color:var(--green);border:1px solid rgba(34,197,94,.25)}
.ctrl-btn.start:hover{background:rgba(34,197,94,.22)}
.ctrl-btn.stop{background:rgba(239,68,68,.12);color:var(--red);border:1px solid rgba(239,68,68,.25)}
.ctrl-btn.stop:hover{background:rgba(239,68,68,.22)}
.ctrl-btn.restart{background:rgba(245,158,11,.12);color:var(--yellow);border:1px solid rgba(245,158,11,.25)}
.ctrl-btn.restart:hover{background:rgba(245,158,11,.22)}
.ctrl-btn.neutral{background:var(--surface2);color:var(--muted);border:1px solid var(--border)}
.ctrl-btn.neutral:hover{border-color:var(--accent);color:var(--accent)}
.ctrl-btn:disabled{opacity:.4;cursor:not-allowed}
.ctrl-divider{grid-column:1/-1;border-top:1px solid var(--border);margin:.25rem 0}

/* Log panel */
.log-box{background:var(--bg);border:1px solid var(--border);border-radius:8px;
  font-family:monospace;font-size:.72rem;line-height:1.6;padding:.75rem;overflow-y:auto;max-height:320px}
.log-box .log-line{white-space:pre-wrap;word-break:break-all;padding:.05rem 0;border-bottom:1px solid rgba(255,255,255,.03)}
.log-box .log-line.error{color:var(--red)}
.log-box .log-line.warn{color:var(--yellow)}
.log-box .log-line:last-child{border-bottom:none}
.log-controls{display:flex;align-items:center;gap:.5rem;margin-bottom:.6rem}

/* Resource bar */
.res-bar{height:4px;border-radius:2px;background:var(--surface2);overflow:hidden;margin-top:.25rem}
.res-fill{height:100%;border-radius:2px;background:var(--accent);transition:width .5s}

/* Maintenance grid */
.maint-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:.4rem}
@media(max-width:700px){.maint-grid{grid-template-columns:1fr 1fr}}
@media(max-width:420px){.maint-grid{grid-template-columns:1fr}}
.maint-btn{display:flex;align-items:center;justify-content:center;text-align:center;gap:.4rem;padding:.6rem .5rem;border-radius:8px;font-size:.8rem;word-break:break-word;min-height:2.8rem;
  font-size:.78rem;font-weight:500;cursor:pointer;border:1px solid var(--border);
  background:var(--surface2);color:var(--text);transition:all .15s;white-space:nowrap}
.maint-btn:hover{border-color:var(--accent);color:var(--accent)}
.maint-btn.danger:hover{border-color:var(--red);color:var(--red)}
.maint-btn:disabled{opacity:.35;cursor:not-allowed}

/* Modals */
.modal-backdrop{position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:200;
  display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:opacity .2s}
.modal-backdrop.open{opacity:1;pointer-events:all}
.modal{background:var(--surface);border:1px solid var(--border);border-radius:14px;
  width:100%;max-width:520px;margin:1rem;overflow:hidden;max-height:90vh;display:flex;flex-direction:column}
.modal-header{padding:1rem 1.2rem;border-bottom:1px solid var(--border);
  display:flex;align-items:center;justify-content:space-between;flex-shrink:0}
.modal-title{font-weight:600}
.modal-close{background:none;border:none;color:var(--muted);font-size:1.2rem;cursor:pointer}
.modal-close:hover{color:var(--text)}
.modal-body{padding:1.2rem;display:flex;flex-direction:column;gap:.9rem;overflow-y:auto}
.modal-footer{padding:1rem 1.2rem;border-top:1px solid var(--border);display:flex;gap:.6rem;justify-content:flex-end;flex-shrink:0}

label{font-size:.78rem;color:var(--muted);display:block;margin-bottom:.3rem}
input,textarea,select{width:100%;background:var(--surface2);border:1px solid var(--border);
  color:var(--text);padding:.5rem .75rem;border-radius:7px;font-size:.84rem;font-family:inherit;outline:none;transition:border-color .15s}
input:focus,textarea:focus{border-color:var(--accent)}
textarea{resize:vertical}
.field{display:flex;flex-direction:column}
.field-hint{font-size:.7rem;color:var(--muted);margin-top:.25rem}
.toggle-row{display:flex;align-items:center;justify-content:space-between;gap:.5rem}
.toggle{position:relative;width:36px;height:20px;flex-shrink:0}
.toggle input{opacity:0;width:0;height:0}
.toggle-slider{position:absolute;inset:0;background:var(--border);border-radius:20px;cursor:pointer;transition:.3s}
.toggle-slider:before{content:'';position:absolute;height:14px;width:14px;left:3px;bottom:3px;
  background:#fff;border-radius:50%;transition:.3s}
.toggle input:checked+.toggle-slider{background:var(--accent)}
.toggle input:checked+.toggle-slider:before{transform:translateX(16px)}

#toast{position:fixed;bottom:1.5rem;right:1.5rem;z-index:999;display:flex;flex-direction:column;gap:.5rem}
.toast-msg{background:var(--surface3);border:1px solid var(--border);border-radius:8px;padding:.65rem 1rem;
  font-size:.82rem;max-width:320px;animation:slide-in .2s ease;box-shadow:0 4px 20px rgba(0,0,0,.4)}
.toast-msg.success{border-color:var(--green);color:var(--green)}
.toast-msg.error{border-color:var(--red);color:var(--red)}
.toast-msg.info{border-color:var(--accent);color:var(--accent)}
.toast-msg.warn{border-color:var(--yellow);color:var(--yellow)}
@keyframes slide-in{from{transform:translateX(100%);opacity:0}to{transform:none;opacity:1}}

/* Config viewer */
.config-view{background:var(--bg);border-radius:8px;padding:.75rem;font-family:monospace;
  font-size:.72rem;line-height:1.6;white-space:pre-wrap;overflow:auto;max-height:400px;color:#94a3b8}

footer{text-align:center;color:var(--muted);font-size:.72rem;padding:2rem;margin-top:1rem}
footer a{color:var(--muted)}
</style>
</head>
<body>

<!-- Boot console: static HTML, visible immediately before any JS runs -->
<div id="boot-console" style="position:fixed;bottom:70px;right:16px;width:340px;max-width:92vw;background:#0f1117;border:1px solid #1e2a3a;border-radius:10px;padding:12px 14px;z-index:9999;box-shadow:0 4px 24px rgba(0,0,0,.6);font-family:sans-serif">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
    <span id="bc-title" style="font-weight:600;font-size:.8rem;color:#00c8ff">⚡ Starting up…</span>
    <button onclick="var e=document.getElementById('boot-console');if(e)e.style.display='none';" style="background:none;border:none;color:#64748b;cursor:pointer;font-size:1.1rem;line-height:1;padding:0 2px">✕</button>
  </div>
  <div id="bc-log" style="font-family:monospace;font-size:.72rem;line-height:1.8;color:#94a3b8;max-height:200px;overflow-y:auto">
    <div style="color:#64748b">⏳ Loading JavaScript…</div>
  </div>
</div>

<header>
  <div class="logo">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
    </svg>
    Fiber Node
  </div>
  <div class="hdr-right">
    <div class="status-badge"><div class="dot" id="status-dot"></div><span id="status-text">Connecting…</span></div>
    <button class="btn btn-ghost btn-sm" onclick="showModal('modal-peer')">+ Peer</button>
    <button class="btn btn-primary btn-sm" onclick="showModal('modal-open')">⚡ Open Channel</button>
    <button class="btn btn-ghost btn-sm" onclick="loadAll()">↺ Refresh</button>
  </div>
</header>

<main>
  <!-- Stat row -->
  <div class="grid-4">
    <div class="card"><div class="card-header"><span class="card-title">Channels</span></div>
      <div class="card-body"><div class="stat-value accent" id="s-channels">—</div><div class="stat-label">Open channels</div></div></div>
    <div class="card"><div class="card-header"><span class="card-title">Local Balance</span></div>
      <div class="card-body"><div class="stat-value green" id="s-local">—</div><div class="stat-label">CKB to send</div></div></div>
    <div class="card"><div class="card-header"><span class="card-title">Remote Balance</span></div>
      <div class="card-body"><div class="stat-value purple" id="s-remote">—</div><div class="stat-label">CKB to receive</div></div></div>
    <div class="card"><div class="card-header"><span class="card-title">Peers</span></div>
      <div class="card-body"><div class="stat-value" id="s-peers">—</div><div class="stat-label">Connected peers</div></div></div>
  </div>

  <!-- Node Control + System -->
  <div class="grid-2">
    <div class="card" id="ctrl-card">
      <div class="card-header"><span class="card-title">Node Control</span><span id="ctrl-status" class="pill" style="font-size:.7rem"></span></div>
      <div class="card-body" id="ctrl-body"><div class="spin"></div></div>
    </div>
    <div class="card">
      <div class="card-header"><span class="card-title">Resource Usage</span></div>
      <div class="card-body" id="sys-body"><div class="spin"></div></div>
    </div>
  </div>

  <!-- Node info + Wallet -->
  <div class="grid-2">
    <div class="card">
      <div class="card-header"><span class="card-title">Node Info</span></div>
      <div class="card-body" id="node-info-body"><div class="spin"></div></div>
    </div>
    <div class="card">
      <div class="card-header">
        <span class="card-title">Wallet</span>
        <div style="display:flex;gap:.4rem">
          <button class="btn btn-success btn-sm" onclick="showModal('modal-invoice')">+ Invoice</button>
          <button class="btn btn-ghost btn-sm" onclick="showModal('modal-pay')">↑ Pay</button>
        </div>
      </div>
      <div class="card-body" id="wallet-body"><div class="spin"></div></div>
    </div>
  </div>

  <!-- Channels table -->
  <div class="card">
    <div class="card-header"><span class="card-title">Channels</span><span id="ch-count" style="font-size:.75rem;color:var(--muted)"></span></div>
    <div class="tbl-wrap"><table>
      <thead><tr><th>Peer</th><th>State</th><th>Liquidity</th><th>Local</th><th>Remote</th><th>Type</th><th>ID</th><th></th></tr></thead>
      <tbody id="ch-body"><tr><td colspan="8" style="text-align:center;padding:2rem"><div class="spin"></div></td></tr></tbody>
    </table></div>
  </div>

  <!-- Logs -->
  <div class="card">
    <div class="card-header">
      <span class="card-title">Logs</span>
      <div style="display:flex;gap:.5rem;align-items:center">
        <button class="btn btn-ghost btn-sm" id="log-refresh-btn" onclick="loadLogs()">↺ Refresh</button>
        <button class="btn btn-ghost btn-sm" id="log-live-btn" onclick="toggleLiveLogs()">▶ Live</button>
      </div>
    </div>
    <div class="card-body" style="padding:.75rem">
      <div class="log-box" id="log-box"><span style="color:var(--muted)">Click ↺ Refresh to load logs</span></div>
    </div>
  </div>

  <!-- Peers + Payments -->
  <div class="grid-2">
    <div class="card">
      <div class="card-header"><span class="card-title">Connected Peers</span></div>
      <div class="card-body" id="peers-body"><div class="spin"></div></div>
    </div>
    <div class="card">
      <div class="card-header"><span class="card-title">Recent Payments</span></div>
      <div class="card-body" id="pay-body"><div class="spin"></div></div>
    </div>
  </div>

  <!-- Maintenance -->
  <div class="card">
    <div class="card-header"><span class="card-title">Maintenance</span><span id="maint-note" style="font-size:.72rem;color:var(--muted)"></span></div>
    <div class="card-body" id="maint-body"><div class="spin"></div></div>
  </div>
</main>

<footer>Fiber Node Dashboard · <a href="https://github.com/nervosnetwork/fiber" target="_blank">nervosnetwork/fiber</a> · <a href="https://wyltekindustries.com" target="_blank">Wyltek Industries</a></footer>

<!-- ── Modals ──────────────────────────────────────────────────────────────── -->
<div class="modal-backdrop" id="modal-peer">
  <div class="modal">
    <div class="modal-header"><span class="modal-title">Connect to Peer</span><button class="modal-close" onclick="closeModal('modal-peer')">✕</button></div>
    <div class="modal-body">
      <div class="field"><label>Peer Multiaddr</label>
        <input id="peer-addr" placeholder="/ip4/1.2.3.4/tcp/8228/p2p/QmXxx..."/>
        <span class="field-hint">Full multiaddr including /p2p/PeerID</span></div>
    </div>
    <div class="modal-footer">
      <button class="btn btn-ghost" onclick="closeModal('modal-peer')">Cancel</button>
      <button class="btn btn-primary" id="btn-connect-peer" onclick="doConnectPeer()">Connect</button>
    </div>
  </div>
</div>

<div class="modal-backdrop" id="modal-open">
  <div class="modal">
    <div class="modal-header"><span class="modal-title">Open Channel</span><button class="modal-close" onclick="closeModal('modal-open')">✕</button></div>
    <div class="modal-body">
      <div class="field"><label>Peer Multiaddr</label>
        <input id="oc-addr" placeholder="/ip4/1.2.3.4/tcp/8228/p2p/QmXxx..."/>
        <span class="field-hint">Will auto-connect then open channel</span></div>
      <div class="field"><label>Funding Amount (CKB)</label>
        <input id="oc-amount" type="number" placeholder="e.g. 1000" min="162" step="1"/>
        <span class="field-hint">Minimum ~162 CKB — locked for channel lifetime</span></div>
      <div class="toggle-row">
        <div><div style="font-size:.82rem">Announce to network</div>
          <div style="font-size:.72rem;color:var(--muted)">Public channels are visible to routing nodes</div></div>
        <label class="toggle"><input type="checkbox" id="oc-public" checked><span class="toggle-slider"></span></label>
      </div>
    </div>
    <div class="modal-footer">
      <button class="btn btn-ghost" onclick="closeModal('modal-open')">Cancel</button>
      <button class="btn btn-primary" id="btn-open-ch" onclick="doOpenChannel()">⚡ Open Channel</button>
    </div>
  </div>
</div>

<div class="modal-backdrop" id="modal-close">
  <div class="modal">
    <div class="modal-header"><span class="modal-title">Close Channel</span><button class="modal-close" onclick="closeModal('modal-close')">✕</button></div>
    <div class="modal-body">
      <p style="font-size:.85rem;line-height:1.6">Cooperatively close this channel? Funds return to your on-chain wallet — takes a few minutes to settle.</p>
      <div style="background:var(--surface2);border-radius:8px;padding:.75rem">
        <div style="font-size:.72rem;color:var(--muted);margin-bottom:.25rem">Channel ID</div>
        <div class="mono" id="close-ch-id" style="font-size:.73rem;color:var(--accent);word-break:break-all"></div>
      </div>
    </div>
    <div class="modal-footer">
      <button class="btn btn-ghost" onclick="closeModal('modal-close')">Cancel</button>
      <button class="btn btn-danger" id="btn-close-ch" onclick="doCloseChannel()">Close Channel</button>
    </div>
  </div>
</div>

<div class="modal-backdrop" id="modal-invoice">
  <div class="modal">
    <div class="modal-header"><span class="modal-title">Create Invoice</span><button class="modal-close" onclick="closeModal('modal-invoice')">✕</button></div>
    <div class="modal-body">
      <div class="field"><label>Amount (CKB)</label><input id="inv-amount" type="number" placeholder="e.g. 10" step="0.00000001" min="0"/></div>
      <div class="field"><label>Description (optional)</label><input id="inv-desc" placeholder="Payment for…"/></div>
      <div class="field"><label>Expiry (minutes)</label><input id="inv-expiry" type="number" value="60" min="1"/></div>
      <div id="inv-result" style="display:none">
        <div style="font-size:.78rem;color:var(--muted);margin-bottom:.4rem">Invoice (click to copy)</div>
        <div class="addr-box" id="inv-str" onclick="copyText(this.textContent)" style="font-size:.68rem"></div>
      </div>
    </div>
    <div class="modal-footer">
      <button class="btn btn-ghost" onclick="closeModal('modal-invoice')">Close</button>
      <button class="btn btn-primary" id="btn-create-inv" onclick="doCreateInvoice()">Generate</button>
    </div>
  </div>
</div>

<div class="modal-backdrop" id="modal-pay">
  <div class="modal">
    <div class="modal-header"><span class="modal-title">Send Payment</span><button class="modal-close" onclick="closeModal('modal-pay')">✕</button></div>
    <div class="modal-body">
      <div class="field"><label>Invoice</label><textarea id="pay-invoice" placeholder="Paste invoice string here…" rows="3"></textarea></div>
    </div>
    <div class="modal-footer">
      <button class="btn btn-ghost" onclick="closeModal('modal-pay')">Cancel</button>
      <button class="btn btn-primary" id="btn-send-pay" onclick="doSendPayment()">↑ Send</button>
    </div>
  </div>
</div>

<div class="modal-backdrop" id="modal-config">
  <div class="modal" style="max-width:700px">
    <div class="modal-header"><span class="modal-title">config.yml</span><button class="modal-close" onclick="closeModal('modal-config')">✕</button></div>
    <div class="modal-body"><pre class="config-view" id="config-content">Loading…</pre></div>
    <div class="modal-footer"><button class="btn btn-ghost" onclick="closeModal('modal-config')">Close</button></div>
  </div>
</div>

<div class="modal-backdrop" id="modal-settings">
  <div class="modal" style="max-width:500px">
    <div class="modal-header"><span class="modal-title">⚙️ Node Settings</span><button class="modal-close" onclick="closeModal('modal-settings')">✕</button></div>
    <div class="modal-body">
      <p style="color:var(--text-muted);font-size:0.85rem;margin-bottom:1rem">
        Edit connection settings. Changes are written to config.yml — restart the node to apply.
      </p>
      <div style="margin-bottom:1rem">
        <label style="display:block;margin-bottom:4px;font-size:0.85rem;color:var(--text-muted)">CKB Full Node URL <span style="color:var(--text-muted)">(Fiber connects TO this)</span></label>
        <input id="settings-ckb-rpc" type="text" placeholder="http://192.168.x.x:8114"
          style="width:100%;padding:8px 10px;background:var(--bg-secondary);border:1px solid var(--border);border-radius:6px;color:var(--text-primary);font-family:monospace;font-size:0.9rem;box-sizing:border-box">
      </div>
      <div style="margin-bottom:1rem">
        <label style="display:block;margin-bottom:4px;font-size:0.85rem;color:var(--text-muted)">Biscuit Public Key <span style="color:var(--text-muted)">(leave blank to disable RPC auth)</span></label>
        <input id="settings-biscuit-key" type="text" placeholder="ed25519 public key hex (optional)"
          style="width:100%;padding:8px 10px;background:var(--bg-secondary);border:1px solid var(--border);border-radius:6px;color:var(--text-primary);font-family:monospace;font-size:0.9rem;box-sizing:border-box">
        <div style="margin-top:4px;font-size:0.75rem;color:var(--text-muted)">Set this if your Fiber RPC returns "Unauthorized". The matching token goes in <code>--biscuit</code> on the dashboard.</div>
      </div>
      <div id="settings-result" style="display:none;padding:10px;border-radius:6px;font-size:0.85rem;margin-top:0.5rem"></div>
    </div>
    <div class="modal-footer">
      <button class="btn btn-ghost" onclick="closeModal('modal-settings')">Cancel</button>
      <button class="btn btn-primary" onclick="saveSettings()">Save &amp; Restart Node</button>
    </div>
  </div>
</div>

<div id="toast"></div>

<script>
const API = '/api';
let nodeInfo = null, pendingCloseId = null, liveLogSource = null;

function fetchWithTimeout(url, opts, ms) {
  ms = ms || 8000;
  var controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
  var timer = controller ? setTimeout(function() { controller.abort(); }, ms) : null;
  var fetchOpts = controller ? Object.assign({}, opts, {signal: controller.signal}) : opts;
  return fetch(url, fetchOpts).then(function(r) {
    if (timer) clearTimeout(timer);
    return r;
  }).catch(function(e) {
    if (timer) clearTimeout(timer);
    throw e;
  });
}

async function fiberRpc(method, params) {
  if (params === undefined) params = {};
  var r = await fetchWithTimeout(API + '/fiber', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({method:method,params:params})}, 8000);
  return r.json();
}
async function ckbRpc(method, params) {
  if (params === undefined) params = [];
  var r = await fetchWithTimeout(API + '/ckb', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({method:method,params:params})}, 8000);
  return r.json();
}
async function ctrl(action, extra) {
  if (extra === undefined) extra = {};
  var body = Object.assign({action:action}, extra);
  var r = await fetchWithTimeout(API + '/control', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}, 8000);
  return r.json();
}
async function maint(action, extra) {
  if (extra === undefined) extra = {};
  var body = Object.assign({action:action}, extra);
  var r = await fetchWithTimeout(API + '/maintenance', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}, 8000);
  return r.json();
}

const shan = hex => hex ? Number(BigInt(hex)) / 1e8 : 0;
const toHex = ckb => '0x' + BigInt(Math.round(ckb * 1e8)).toString(16);
function fmt(v) { return v>=1e6?(v/1e6).toFixed(2)+'M':v>=1e3?(v/1e3).toFixed(2)+'k':v.toFixed(2); }
function shortId(id) { return id ? id.slice(0,10)+'…'+id.slice(-6) : '—'; }
function copyText(t) { navigator.clipboard?.writeText(t.trim()).then(()=>toast('Copied!','info')); }
function stateClass(s) { const l=(s||'').toLowerCase(); return l.includes('ready')?'pill-green':l.includes('clos')?'pill-red':'pill-yellow'; }

function toast(msg, type='info', ms=3500) {
  const el=document.createElement('div'); el.className=`toast-msg ${type}`; el.textContent=msg;
  document.getElementById('toast').appendChild(el); setTimeout(()=>el.remove(),ms);
}
function showModal(id){document.getElementById(id).classList.add('open')}
function closeModal(id){document.getElementById(id).classList.remove('open')}
document.addEventListener('keydown',e=>{if(e.key==='Escape')document.querySelectorAll('.modal-backdrop.open').forEach(m=>m.classList.remove('open'))});
document.querySelectorAll('.modal-backdrop').forEach(m=>m.addEventListener('click',e=>{if(e.target===m)m.classList.remove('open')}));

function setBusy(id, busy, label='') {
  const el=document.getElementById(id); if(!el)return;
  el.disabled=busy; el.innerHTML=busy?'<div class="spin"></div>':label;
}

// ── Node Control ───────────────────────────────────────────────────────────────
async function loadCtrl() {
  const res = await fetch(`${API}/control_status`).then(r=>r.json()).catch(()=>({enabled:false}));
  const body = document.getElementById('ctrl-body');
  const badge = document.getElementById('ctrl-status');

  if (!res.enabled) {
    badge.className = 'pill pill-yellow'; badge.textContent = 'Read-only';
    body.innerHTML = `<div class="empty" style="padding:1rem"><div class="icon">🔒</div>
      <p>Start with <code style="color:var(--accent)">--control</code> flag to enable node management</p></div>`;
    return;
  }

  const running = res.running;
  const svcMode = res.service_mode || 'unknown';
  badge.className = `pill ${running?'pill-green':'pill-red'}`;
  badge.textContent = running ? `Running (PID ${res.pid||'?'})` : 'Stopped';

  const svcNote = svcMode === 'systemd'
    ? `<div style="font-size:.7rem;color:var(--muted);margin-bottom:.6rem">via systemd · <code>${res.service||'fiber'}</code></div>`
    : svcMode === 'direct'
    ? `<div style="font-size:.7rem;color:var(--yellow);margin-bottom:.6rem">⚠ Running as direct process — install as service for full control</div>`
    : '';

  body.innerHTML = `
    ${svcNote}
    <div class="ctrl-grid">
      <button class="ctrl-btn start" id="btn-start-mainnet" onclick="doCtrl('start','mainnet')">▶ Start Mainnet</button>
      <button class="ctrl-btn start" id="btn-start-testnet" onclick="doCtrl('start','testnet')">▶ Start Testnet</button>
      <button class="ctrl-btn stop"  id="btn-stop"          onclick="doCtrl('stop')">■ Stop Node</button>
      <button class="ctrl-btn restart"                       onclick="doCtrl('restart')">↺ Restart Node</button>
      <div class="ctrl-divider"></div>
      <button class="ctrl-btn neutral" onclick="doCtrl('enable')">✓ Enable Autostart</button>
      <button class="ctrl-btn neutral" onclick="doCtrl('disable')">✗ Disable Autostart</button>
    </div>`;
  // Set button states based on running — always done after render
  applyCtrlState(running);
}

function clearNodeData() {
  // Wipe all node-dependent panels when stopped — avoids showing stale data
  const clear = (id, msg='—') => { const el=document.getElementById(id); if(el) el.innerHTML=`<div class="empty"><div class="icon">💤</div><p>${msg}</p></div>`; };
  clear('node-info-body', 'Node stopped');
  clear('channels-body', 'Node stopped');
  clear('peers-body', 'Node stopped');
  clear('payments-body', 'Node stopped');
  clear('sys-body', 'Node stopped');
  const badge = document.getElementById('node-status-badge');
  if (badge) { badge.className='pill pill-red'; badge.textContent='Offline'; }
}

function applyCtrlState(running) {
  const startBtns = document.querySelectorAll('.ctrl-btn.start');
  const stopBtn   = document.getElementById('btn-stop');
  startBtns.forEach(b => { b.disabled = !!running; });
  if (stopBtn) stopBtn.disabled = !running;
}

async function doCtrl(action, network='') {
  const label = action.charAt(0).toUpperCase()+action.slice(1);
  toast(`${label}ing node…`, 'info');
  const res = await ctrl(action, network ? {network} : {});
  if (res.ok) {
    toast(`${label} OK`, 'success');
    const expectRunning = (action === 'start' || action === 'restart');

    // Immediately update button states and badge — don't wait for server
    if (action === 'stop') {
      applyCtrlState(false);
      clearNodeData();
      const badge = document.getElementById('ctrl-status');
      if (badge) { badge.textContent = 'Stopped'; badge.className = 'pill pill-red'; }
    } else if (action === 'start') {
      applyCtrlState(true);
      const badge = document.getElementById('ctrl-status');
      if (badge) { badge.textContent = 'Starting…'; badge.className = 'pill pill-yellow'; }
    } else if (action === 'restart') {
      clearNodeData();
      const badge = document.getElementById('ctrl-status');
      if (badge) { badge.textContent = 'Restarting…'; badge.className = 'pill pill-yellow'; }
    }

    const delay = (action === 'stop') ? 6000 : (action === 'restart') ? 5000 : 2000;
    const pollState = async (attempts=0) => {
      await loadCtrl();
      const status = await fetch(`${API}/control_status`).then(r=>r.json()).catch(()=>({}));
      if (status.running) {
        // Node is (back) up — reload all node-dependent data
        loadNodeInfo(); loadChannels(); loadPeers(); loadPayments(); loadSys();
      } else if (action === 'start' && attempts < 3) {
        // Waiting for start to take effect
        setTimeout(()=>pollState(attempts+1), 3000);
      }
    };
    setTimeout(()=>pollState(0), delay);
  } else {
    toast(`Failed: ${res.output||res.error}`, 'error', 6000);
  }
}

// ── System stats ───────────────────────────────────────────────────────────────
async function loadSys() {
  const res = await fetch(`${API}/system`).then(r=>r.json()).catch(()=>({}));
  const el = document.getElementById('sys-body');
  if (!res.running) {
    el.innerHTML = `<div class="empty" style="padding:1rem"><div class="icon">💤</div><p>Node not running</p></div>`;
    return;
  }
  const cpuPct = Math.min(parseFloat(res.cpu_pct||0), 100);
  const ramPct = res.ram_mb && res.total_ram_mb ? Math.round((res.ram_mb/res.total_ram_mb)*100) : 0;

  el.innerHTML = `
    <div class="info-row"><span class="info-key">PID</span><span class="info-val">${res.pid||'—'}</span></div>
    <div class="info-row"><span class="info-key">Uptime</span><span class="info-val">${res.uptime||'—'}</span></div>
    <div class="info-row" style="flex-direction:column;align-items:flex-start;gap:.3rem">
      <div style="display:flex;justify-content:space-between;width:100%"><span style="color:var(--muted);font-size:.82rem">CPU</span><span style="font-size:.82rem">${res.cpu_pct||0}%</span></div>
      <div class="res-bar" style="width:100%"><div class="res-fill" style="width:${cpuPct}%;background:${cpuPct>80?'var(--red)':cpuPct>50?'var(--yellow)':'var(--accent)'}"></div></div>
    </div>
    <div class="info-row" style="flex-direction:column;align-items:flex-start;gap:.3rem">
      <div style="display:flex;justify-content:space-between;width:100%"><span style="color:var(--muted);font-size:.82rem">RAM</span><span style="font-size:.82rem">${res.ram_mb||0} MB${res.total_ram_mb?' / '+res.total_ram_mb+' MB':''}</span></div>
      <div class="res-bar" style="width:100%"><div class="res-fill" style="width:${ramPct}%;background:${ramPct>80?'var(--red)':ramPct>50?'var(--yellow)':'var(--purple)'}"></div></div>
    </div>
    ${res.connections?.length ? `<div class="info-row"><span class="info-key">Connections</span><span class="info-val">${res.connections.length} active</span></div>` : ''}
  `;
}

// ── Logs ───────────────────────────────────────────────────────────────────────
async function loadLogs() {
  const box = document.getElementById('log-box');
  box.innerHTML = '<div class="spin"></div>';
  const res = await fetch(`${API}/logs?lines=50`).then(r=>r.json()).catch(()=>({lines:[]}));
  renderLogs(res.lines || []);
}

function renderLogs(lines) {
  const box = document.getElementById('log-box');
  if (!lines.length) { box.innerHTML = '<span style="color:var(--muted)">No log output available</span>'; return; }
  box.innerHTML = lines.map(l => {
    const cls = /error|ERR|panic/i.test(l)?'error':/warn|WARN/i.test(l)?'warn':'';
    return `<div class="log-line ${cls}">${escHtml(l)}</div>`;
  }).join('');
  box.scrollTop = box.scrollHeight;
}

function escHtml(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

function toggleLiveLogs() {
  const btn = document.getElementById('log-live-btn');
  if (liveLogSource) {
    liveLogSource.close(); liveLogSource = null;
    btn.textContent = '▶ Live'; btn.className = 'btn btn-ghost btn-sm';
    return;
  }
  btn.textContent = '⬛ Stop'; btn.className = 'btn btn-danger btn-sm';
  const box = document.getElementById('log-box');
  box.innerHTML = '<span style="color:var(--accent)">Streaming live logs…</span><br>';
  liveLogSource = new EventSource(`${API}/logs/stream`);
  liveLogSource.onmessage = e => {
    const data = JSON.parse(e.data);
    const div = document.createElement('div');
    div.className = 'log-line' + (/error|ERR/i.test(data.line)?' error':(/warn|WARN/i.test(data.line)?' warn':''));
    div.textContent = data.line;
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
    // Keep max 200 lines
    while (box.children.length > 200) box.removeChild(box.firstChild);
  };
  liveLogSource.onerror = () => { toast('Log stream disconnected','warn'); toggleLiveLogs(); };
}

// ── Node Info ──────────────────────────────────────────────────────────────────
async function loadNodeInfo() {
  const res = await fiberRpc('node_info');
  const dot=document.getElementById('status-dot'), stxt=document.getElementById('status-text');
  if (res.error || !res.result) {
    dot.className='dot red'; stxt.textContent=res.error?.message||'Offline';
    document.getElementById('node-info-body').innerHTML=`<div class="empty"><div class="icon">⚠️</div><p>${res.error?.message||'Cannot reach Fiber RPC'}</p></div>`;
    document.getElementById('wallet-body').innerHTML=`<div class="empty"><div class="icon">⚠️</div><p>Node offline</p></div>`;
    return false;
  }
  const info=res.result; nodeInfo=info;
  dot.className='dot green'; stxt.textContent=`Online · v${info.version||'?'}`;
  document.getElementById('s-peers').textContent=parseInt(info.peers_count||'0',16)||'0';
  document.getElementById('node-info-body').innerHTML=`
    <div class="info-row"><span class="info-key">Version</span><span class="info-val">${info.version||'—'}</span></div>
    <div class="info-row"><span class="info-key">Network</span><span class="info-val">${info.chain_hash?.startsWith('0x92b1')?'Mainnet':'Testnet'}</span></div>
    <div class="info-row"><span class="info-key">Peers</span><span class="info-val">${parseInt(info.peers_count||'0',16)}</span></div>
    <div class="info-row"><span class="info-key">Channels</span><span class="info-val">${parseInt(info.channel_count||'0',16)} (${parseInt(info.pending_channel_count||'0',16)} pending)</span></div>
    <div class="info-row"><span class="info-key">Min Accept</span><span class="info-val">${fmt(shan(info.open_channel_auto_accept_min_ckb_funding_amount))} CKB</span></div>
    <div style="margin-top:.75rem">
      <div style="font-size:.7rem;color:var(--muted);margin-bottom:.3rem">Node ID (click to copy)</div>
      <div class="addr-box" onclick="copyText(this.textContent)">${info.node_id||'—'}</div>
    </div>
    ${(info.addresses||[]).map(a=>`<div class="addr-box" style="margin-top:.25rem;font-size:.68rem" onclick="copyText(this.textContent)">${a}</div>`).join('')}
  `;
  await loadWallet(info);
  return true;
}

async function loadWallet(info) {
  const ls = info?.default_funding_lock_script;
  if (!ls) { document.getElementById('wallet-body').innerHTML=`<div class="empty"><div class="icon">💳</div><p>Lock script unavailable</p></div>`; return; }
  const addrRes = await fetch(`${API}/derive_address`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({lock:ls})}).then(r=>r.json()).catch(()=>({}));
  const address = addrRes.address;
  let balCKB = null;
  if (address) {
    const balRes = await ckbRpc('get_cells_capacity',[{script:ls,script_type:'lock'}]);
    if (balRes.result?.capacity) balCKB = shan(balRes.result.capacity);
  }
  document.getElementById('wallet-body').innerHTML=`
    <div class="info-row"><span class="info-key">On-chain Balance</span><span class="info-val" style="color:var(--green);font-size:.85rem">${balCKB!==null?fmt(balCKB)+' CKB':'—'}</span></div>
    <div style="margin-top:.75rem"><div style="font-size:.7rem;color:var(--muted);margin-bottom:.3rem">Deposit Address (click to copy)</div>
    <div class="addr-box" onclick="copyText(this.textContent)">${address||'Derivation failed'}</div></div>
    <div style="margin-top:.6rem;font-size:.72rem;color:var(--muted)">Send CKB here to fund channels.</div>
  `;
}

// ── Channels ───────────────────────────────────────────────────────────────────
async function loadChannels() {
  const res = await fiberRpc('list_channels',{include_closed:false});
  const channels = res.result?.channels||[];
  let totalLocal=0,totalRemote=0,openCount=0;
  channels.forEach(c=>{totalLocal+=shan(c.local_balance);totalRemote+=shan(c.remote_balance);if(c.state?.state_name==='CHANNEL_READY')openCount++;});
  document.getElementById('s-channels').textContent=openCount;
  document.getElementById('s-local').textContent=fmt(totalLocal)+' CKB';
  document.getElementById('s-remote').textContent=fmt(totalRemote)+' CKB';
  document.getElementById('ch-count').textContent=`${channels.length} total`;
  if (!channels.length) {
    document.getElementById('ch-body').innerHTML=`<tr><td colspan="8"><div class="empty"><div class="icon">⚡</div><p>No channels yet</p><button class="btn btn-primary" style="margin-top:.75rem" onclick="showModal('modal-open')">Open first channel</button></div></td></tr>`;
    return;
  }
  document.getElementById('ch-body').innerHTML=channels.map(c=>{
    const local=shan(c.local_balance),remote=shan(c.remote_balance),total=local+remote;
    const pct=total>0?Math.round((local/total)*100):0;
    const state=c.state?.state_name?.replace(/_/g,' ')||'Unknown';
    const canClose=c.state?.state_name==='CHANNEL_READY';
    return `<tr>
      <td class="mono" title="${c.peer_id}">${shortId(c.peer_id)}</td>
      <td><span class="pill ${stateClass(state)}">${state}</span></td>
      <td><div class="liq-wrap"><div class="liq-bar"><div class="liq-fill" style="width:${pct}%"></div></div><span style="font-size:.68rem;color:var(--muted)">${pct}%</span></div></td>
      <td>${fmt(local)} <small style="color:var(--muted)">CKB</small></td>
      <td>${fmt(remote)} <small style="color:var(--muted)">CKB</small></td>
      <td>${c.is_public?'<span class="pill pill-blue">Public</span>':'<span class="pill pill-purple">Private</span>'}</td>
      <td class="mono" title="${c.channel_id}" onclick="copyText('${c.channel_id}')" style="cursor:pointer">${shortId(c.channel_id)}</td>
      <td>${canClose?`<button class="btn btn-danger btn-sm" onclick="confirmClose('${c.channel_id}')">Close</button>`:`<span style="font-size:.72rem;color:var(--muted)">—</span>`}</td>
    </tr>`;
  }).join('');
}

// ── Peers ──────────────────────────────────────────────────────────────────────
async function loadPeers() {
  const res = await fiberRpc('list_peers');
  const peers = res.result?.peers||res.result||[];
  const el = document.getElementById('peers-body');
  if (!peers.length) { el.innerHTML=`<div class="empty"><div class="icon">🌐</div><p>No connected peers</p><button class="btn btn-ghost" style="margin-top:.6rem" onclick="showModal('modal-peer')">+ Connect Peer</button></div>`; return; }
  el.innerHTML=peers.slice(0,8).map(p=>{
    const id=p.peer_id||p.id||'',addr=p.address||p.multiaddr||'';
    return `<div style="padding:.5rem 0;border-bottom:1px solid var(--border)">
      <div style="display:flex;align-items:center;justify-content:space-between">
        <div class="mono" style="color:var(--accent);font-size:.72rem" title="${id}">${shortId(id)}</div>
        <button class="btn btn-primary btn-sm" onclick="prefillOpen('${addr}')">+ Channel</button>
      </div>
      ${addr?`<div style="color:var(--muted);font-size:.68rem;margin-top:.15rem">${addr}</div>`:''}
    </div>`;
  }).join('');
}

// ── Payments ───────────────────────────────────────────────────────────────────
async function loadPayments() {
  const res = await fiberRpc('list_payments');
  const payments = res.result?.payments||(Array.isArray(res.result)?res.result:[]);
  const el = document.getElementById('pay-body');
  if (res.error||!payments.length) { el.innerHTML=`<div class="empty"><div class="icon">💸</div><p>${res.error?'Payments require auth':'No payments yet'}</p><button class="btn btn-ghost" style="margin-top:.6rem" onclick="showModal('modal-pay')">↑ Send Payment</button></div>`; return; }
  el.innerHTML=payments.slice(0,10).map(p=>{
    const amount=shan(p.amount||p.paid_amount||0),status=p.status||'unknown',isSent=p.direction!=='received';
    const col=status==='success'?'var(--green)':status==='failed'?'var(--red)':'var(--yellow)';
    return `<div style="display:flex;align-items:center;gap:.6rem;padding:.5rem 0;border-bottom:1px solid var(--border)">
      <div style="font-size:1.1rem">${isSent?'↑':'↓'}</div>
      <div style="flex:1"><div class="mono" style="font-size:.7rem;color:var(--muted)">${shortId(p.payment_hash||p.id)}</div>
      <div style="font-size:.72rem;color:${col}">${status}</div></div>
      <div style="font-weight:600;font-size:.83rem;color:${isSent?'var(--text)':'var(--green)'}">${isSent?'-':'+'}${fmt(amount)} CKB</div>
    </div>`;
  }).join('');
}

// ── Maintenance ────────────────────────────────────────────────────────────────
function loadMaintenance(enabled) {
  const note = document.getElementById('maint-note');
  const body = document.getElementById('maint-body');
  if (!enabled) {
    note.textContent = 'Start with --control to enable';
    body.innerHTML = `<div class="empty" style="padding:1rem"><div class="icon">🔒</div><p>Requires <code style="color:var(--accent)">--control</code> flag</p></div>`;
    return;
  }
  note.textContent = '';
  body.innerHTML = `<div class="maint-grid">
    <button class="maint-btn" onclick="doMaint('view-config')">📄 View Config</button>
    <button class="maint-btn" onclick="openSettings()">⚙️ Edit Settings</button>
    <button class="maint-btn" onclick="doMaint('verify-key')">🔑 Verify Key</button>
    <button class="maint-btn" onclick="doMaint('download-config')">⬇ Download Latest Config</button>
    <button class="maint-btn" onclick="doMaint('clean-locks')">🧹 Clean Lock Files</button>
    <button class="maint-btn" onclick="doMaint('backup')">💾 Backup Data</button>
    <button class="maint-btn" onclick="doMaint('update-binary')">⬆ Update FNN Binary</button>
    <button class="maint-btn" onclick="checkAndUpdate()">🔄 Check for Updates</button>
    <button class="maint-btn" onclick="doMaint('install-ckb-cli')">🛠 Install ckb-cli</button>
    <button class="maint-btn" onclick="doMaint('open-firewall')">🔓 Open Firewall Port</button>
  </div>`;
}

async function doMaint(action) {
  if (action === 'view-config') {
    showModal('modal-config');
    document.getElementById('config-content').textContent = 'Loading…';
    const res = await maint('view-config');
    document.getElementById('config-content').textContent = res.content || res.message || 'Error';
    return;
  }
  toast(`Running: ${action}…`, 'info');
  const res = await maint(action);
  if (res.ok) toast(res.message||'Done', 'success', 5000);
  else toast('Failed: '+(res.message||res.error), 'error', 6000);
}

async function checkAndUpdate() {
  toast('Checking for updates…', 'info');
  const r = await maint('check-updates');
  if (!r.ok) { toast('Check failed: ' + (r.message||r.error), 'error', 6000); return; }
  const res = r.results || {};
  const fnn = res.fnn || {};
  const dash = res.dashboard || {};
  let lines = [];
  if (fnn.current) lines.push(`FNN binary: ${fnn.current} → ${fnn.latest} ${fnn.up_to_date ? '✓' : '⬆ update available'}`);
  if (dash.current) lines.push(`Dashboard: ${dash.current} → ${dash.latest} ${dash.up_to_date ? '✓' : '⬆ update available'}`);
  const msg = lines.join('\n') || r.message;
  const hasDashUpdate = dash.latest && !dash.up_to_date;
  const hasFnnUpdate = fnn.latest && !fnn.up_to_date;
  if (!hasDashUpdate && !hasFnnUpdate) {
    toast(msg, 'success', 5000); return;
  }
  // Offer to update what's outdated
  if (hasDashUpdate && confirm(`Dashboard update available (${dash.current} → ${dash.latest}).\n\nUpdate now? The page will refresh automatically.`)) {
    const u = await maint('update-dashboard');
    if (u.ok) { toast(u.message, 'success', 8000); setTimeout(()=>location.reload(), 5000); }
    else toast('Update failed: ' + u.message, 'error', 6000);
  }
  if (hasFnnUpdate && confirm(`FNN binary update available (${fnn.current} → ${fnn.latest}).\n\nUpdate now? The node will restart.`)) {
    const u = await maint('update-binary');
    if (u.ok) toast(u.message, 'success', 6000);
    else toast('Update failed: ' + u.message, 'error', 6000);
  }
}

async function openSettings() {
  // Pre-fill current CKB RPC from status API
  const el = document.getElementById('settings-ckb-rpc');
  const elBiscuit = document.getElementById('settings-biscuit-key');
  const res = document.getElementById('settings-result');
  res.style.display = 'none';
  try {
    const s = await fetchWithTimeout(API + '/control_status', {}, 8000).then(r=>r.json());
    el.value = s.ckb_rpc || '';
    elBiscuit.value = s.biscuit_public_key || '';
  } catch(e) { el.value = ''; }
  showModal('modal-settings');
}

async function saveSettings() {
  const ckbRpc = document.getElementById('settings-ckb-rpc').value.trim();
  const biscuitKey = document.getElementById('settings-biscuit-key').value.trim();
  const res = document.getElementById('settings-result');
  if (!ckbRpc) { res.style.display='block'; res.style.background='var(--danger-bg,rgba(255,80,80,.1))'; res.style.color='var(--danger,#ff5050)'; res.textContent='CKB RPC URL is required'; return; }
  res.style.display='block'; res.style.background='var(--bg-secondary)'; res.style.color='var(--text-muted)'; res.textContent='Saving…';
  const changes = {ckb_rpc_url: ckbRpc};
  if (biscuitKey) changes.biscuit_public_key = biscuitKey;
  else changes.biscuit_public_key = '';  // explicit blank = remove from config
  const r = await maint('edit-config', {changes});
  if (r.ok) {
    res.style.background='rgba(57,255,20,.1)'; res.style.color='#39ff14';
    res.textContent = r.message;
    // Restart node automatically
    setTimeout(async () => {
      await fetch(`${API}/control`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'restart'})});
      toast('Node restarted with new settings','success',5000);
      closeModal('modal-settings');
    }, 1000);
  } else {
    res.style.background='rgba(255,80,80,.1)'; res.style.color='#ff5050';
    res.textContent = 'Error: ' + (r.message||r.error);
  }
}

// ── Actions ────────────────────────────────────────────────────────────────────
async function doConnectPeer() {
  const addr=document.getElementById('peer-addr').value.trim();
  if (!addr){toast('Enter a peer multiaddr','error');return;}
  setBusy('btn-connect-peer',true);
  const res=await fiberRpc('connect_peer',{address:addr});
  setBusy('btn-connect-peer',false,'Connect');
  if(res.error){toast('Failed: '+res.error.message,'error');return;}
  toast('Peer connected!','success'); closeModal('modal-peer');
  document.getElementById('peer-addr').value=''; loadPeers();
}

async function doOpenChannel() {
  const addr=document.getElementById('oc-addr').value.trim();
  const ckbAmt=parseFloat(document.getElementById('oc-amount').value);
  const isPublic=document.getElementById('oc-public').checked;
  if(!addr){toast('Enter a peer multiaddr','error');return;}
  if(!ckbAmt||ckbAmt<162){toast('Minimum 162 CKB required','error');return;}
  setBusy('btn-open-ch',true);
  toast('Connecting to peer…','info');
  const connRes=await fiberRpc('connect_peer',{address:addr});
  if(connRes.error&&!connRes.error.message?.includes('already')){
    setBusy('btn-open-ch',false,'⚡ Open Channel');
    toast('Connect failed: '+connRes.error.message,'error'); return;
  }
  const match=addr.match(/\/p2p\/([A-Za-z0-9]+)/);
  if(!match){setBusy('btn-open-ch',false,'⚡ Open Channel');toast('Cannot extract peer ID from address','error');return;}
  toast('Opening channel…','info');
  const openRes=await fiberRpc('open_channel',{peer_id:match[1],funding_amount:toHex(ckbAmt),public:isPublic});
  setBusy('btn-open-ch',false,'⚡ Open Channel');
  if(openRes.error){toast('Open failed: '+openRes.error.message,'error');return;}
  toast('Channel opening! ID: '+shortId(openRes.result?.temporary_channel_id||''),'success',5000);
  closeModal('modal-open'); document.getElementById('oc-addr').value=''; document.getElementById('oc-amount').value='';
  setTimeout(loadChannels,2000);
}

function confirmClose(id){pendingCloseId=id;document.getElementById('close-ch-id').textContent=id;showModal('modal-close');}
async function doCloseChannel(){
  if(!pendingCloseId)return; setBusy('btn-close-ch',true);
  const params={channel_id:pendingCloseId,fee_rate:'0x3e8'};
  if(nodeInfo?.default_funding_lock_script) params.close_script=nodeInfo.default_funding_lock_script;
  const res=await fiberRpc('shutdown_channel',params);
  setBusy('btn-close-ch',false,'Close Channel');
  if(res.error){toast('Close failed: '+res.error.message,'error');return;}
  toast('Channel closing…','success'); closeModal('modal-close'); pendingCloseId=null;
  setTimeout(loadChannels,2000);
}

async function doCreateInvoice(){
  const ckbAmt=parseFloat(document.getElementById('inv-amount').value);
  if(!ckbAmt||ckbAmt<=0){toast('Enter an amount','error');return;}
  const desc=document.getElementById('inv-desc').value.trim();
  const expMin=parseInt(document.getElementById('inv-expiry').value)||60;
  let currency='Fibb';
  if(nodeInfo?.chain_hash&&!nodeInfo.chain_hash.startsWith('0x92b1'))currency='Fibt';
  setBusy('btn-create-inv',true);
  const res=await fiberRpc('new_invoice',{amount:toHex(ckbAmt),currency,expiry:'0x'+((expMin*60).toString(16)),...(desc?{description:desc}:{})});
  setBusy('btn-create-inv',false,'Generate');
  if(res.error){toast('Failed: '+res.error.message,'error');return;}
  const invStr=res.result?.invoice_address||res.result?.invoice;
  if(invStr){document.getElementById('inv-str').textContent=invStr;document.getElementById('inv-result').style.display='block';navigator.clipboard?.writeText(invStr).then(()=>toast('Invoice copied!','success'));}
}

async function doSendPayment(){
  const invoice=document.getElementById('pay-invoice').value.trim();
  if(!invoice){toast('Paste an invoice','error');return;}
  setBusy('btn-send-pay',true);
  const res=await fiberRpc('send_payment',{invoice});
  setBusy('btn-send-pay',false,'↑ Send');
  if(res.error){toast('Failed: '+res.error.message,'error');return;}
  toast('Payment sent! Hash: '+shortId(res.result?.payment_hash||''),'success',5000);
  closeModal('modal-pay'); document.getElementById('pay-invoice').value=''; setTimeout(loadPayments,1500);
}

function prefillOpen(addr){if(addr)document.getElementById('oc-addr').value=addr;showModal('modal-open');}

// ── Main ───────────────────────────────────────────────────────────────────────
// ── Boot Console helpers ───────────────────────────────────────────────────────

function bcLog(msg, ok) {
  var log = document.getElementById('bc-log');
  if (!log) return;
  var icon = ok === true ? '✅' : ok === false ? '❌' : '⏳';
  var color = ok === true ? 'var(--green)' : ok === false ? 'var(--red)' : 'var(--text)';
  var line = document.createElement('div');
  line.style.color = color;
  line.textContent = icon + ' ' + msg;
  log.appendChild(line);
  log.scrollTop = log.scrollHeight;
}

function bcDone(success) {
  var el = document.getElementById('boot-console');
  if (!el) return;
  var hdr = document.getElementById('bc-title');
  if (success) {
    if (hdr) { hdr.textContent = '✅ Connected'; hdr.style.color = 'var(--green)'; }
    setTimeout(function() { var e = document.getElementById('boot-console'); if (e) e.remove(); }, 3000);
  } else {
    if (hdr) { hdr.textContent = '⚠️ Could not connect — see errors above'; hdr.style.color = 'var(--yellow)'; }
  }
}

async function loadAll(){
  // Load control status first — determines what else to fetch
  bcLog('Fetching control status…');
  let ctrlStatus;
  try {
    const r = await fetchWithTimeout(API + '/control_status', {}, 8000);
    ctrlStatus = await r.json();
    bcLog('Service: ' + ctrlStatus.service_mode + ' · running=' + ctrlStatus.running, true);
  } catch(e) {
    bcLog('control_status failed: ' + (e && e.message ? e.message : String(e)), false);
    bcDone(false);
    return;
  }
  loadMaintenance(ctrlStatus.enabled);
  await loadCtrl();

  if (ctrlStatus.running) {
    bcLog('Node running — loading data…');
    var allOk = true;

    try { var niOk = await loadNodeInfo(); bcLog('node_info', niOk !== false); if(niOk===false) allOk=false; }
    catch(e) { bcLog('node_info error: ' + (e && e.message ? e.message : String(e)), false); allOk=false; }

    try { await loadChannels(); bcLog('list_channels', true); }
    catch(e) { bcLog('channels error: ' + (e && e.message ? e.message : String(e)), false); allOk=false; }

    try { await loadPeers(); bcLog('list_peers', true); }
    catch(e) { bcLog('peers error: ' + (e && e.message ? e.message : String(e)), false); allOk=false; }

    try { await loadPayments(); bcLog('list_payments', true); }
    catch(e) { bcLog('payments error: ' + (e && e.message ? e.message : String(e)), false); allOk=false; }

    try { await loadSys(); bcLog('system stats', true); }
    catch(e) { bcLog('system error: ' + (e && e.message ? e.message : String(e)), false); allOk=false; }

    bcDone(allOk);
  } else {
    bcLog('Node is not running — start it from the Controls panel', false);
    bcDone(false);
    clearNodeData();
  }
}

loadAll();
setInterval(()=>{ loadCtrl(); loadSys(); loadChannels(); }, 15000);
</script>

<!-- Bug Report Button + Modal -->
<style>
#bug-fab{position:fixed;bottom:22px;right:22px;width:46px;height:46px;border-radius:50%;
  background:#111318;border:1px solid #1e2430;color:#fff;font-size:1.3rem;cursor:pointer;
  display:flex;align-items:center;justify-content:center;z-index:900;
  box-shadow:0 2px 12px rgba(0,0,0,.4);transition:transform .15s,border-color .15s;}
#bug-fab:hover{transform:scale(1.1);border-color:var(--accent);}
#bug-modal-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:901;align-items:center;justify-content:center;}
#bug-modal-overlay.open{display:flex;}
#bug-modal{background:var(--surface);border:1px solid var(--border);border-radius:14px;
  padding:1.5rem;width:min(420px,92vw);display:flex;flex-direction:column;gap:.8rem;}
#bug-modal h3{margin:0;font-size:1rem;}
#bug-modal input,#bug-modal textarea{width:100%;box-sizing:border-box;background:var(--surface2);
  border:1px solid var(--border);border-radius:8px;color:var(--text);padding:.6rem .8rem;
  font-size:.9rem;font-family:inherit;resize:vertical;}
#bug-modal textarea{min-height:100px;}
#bug-modal .row{display:flex;gap:.6rem;justify-content:flex-end;}
#bug-issue-link{font-size:.8rem;color:var(--green);display:none;}
</style>

<button id="bug-fab" title="Report a bug" onclick="document.getElementById('bug-modal-overlay').classList.add('open')">🪲</button>

<div id="bug-modal-overlay" onclick="if(event.target===this)this.classList.remove('open')">
  <div id="bug-modal">
    <h3>🪲 Report a Bug</h3>
    <input id="bug-title" placeholder="Short title (e.g. Stop button doesn't work)" maxlength="120">
    <textarea id="bug-body" placeholder="What happened? What did you expect? Steps to reproduce…"></textarea>
    <div class="row">
      <span id="bug-issue-link"></span>
      <button class="btn" onclick="document.getElementById('bug-modal-overlay').classList.remove('open')">Cancel</button>
      <button class="btn btn-primary" id="bug-submit-btn" onclick="submitBugReport()">Submit Issue</button>
    </div>
  </div>
</div>

<script>
async function submitBugReport() {
  const title = document.getElementById('bug-title').value.trim();
  const body  = document.getElementById('bug-body').value.trim();
  if (!title) { toast('Please enter a title', 'error'); return; }
  const btn = document.getElementById('bug-submit-btn');
  btn.disabled = true; btn.textContent = 'Submitting…';
  try {
    const res = await fetch(`${API}/bug_report`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({title, body})
    }).then(r=>r.json());
    if (res.ok) {
      const link = document.getElementById('bug-issue-link');
      link.innerHTML = `✅ <a href="${res.issue_url}" target="_blank">#${res.number} opened</a>`;
      link.style.display = 'inline';
      toast(`Issue #${res.number} filed on GitHub ✅`, 'success');
      document.getElementById('bug-title').value = '';
      document.getElementById('bug-body').value = '';
      setTimeout(()=>document.getElementById('bug-modal-overlay').classList.remove('open'), 2000);
    } else {
      toast(`Failed: ${res.error}`, 'error', 6000);
    }
  } catch(e) { toast('Network error: ' + e.message, 'error', 6000); }
  btn.disabled = false; btn.textContent = 'Submit Issue';
}
</script>
</body>
</html>
"""

# ── HTTP Handler ───────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def _json(self, data, status=200):
        body=json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",len(body))
        self.send_header("Access-Control-Allow-Origin","*")
        self.end_headers(); self.wfile.write(body)

    def _html(self, html):
        body=html.encode()
        self.send_response(200)
        self.send_header("Content-Type","text/html; charset=utf-8")
        self.send_header("Content-Length",len(body))
        self.end_headers(); self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Access-Control-Allow-Methods","POST,GET,OPTIONS")
        self.send_header("Access-Control-Allow-Headers","Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path in ("/","/index.html"):
            self._html(HTML)
        elif self.path=="/health":
            self._json({"ok":True,"fiber_rpc":FIBER_RPC,"ckb_rpc":CKB_RPC,"control":CONTROL,"dashboard_version":DASHBOARD_VERSION})
        elif self.path=="/api/control_status":
            # Single SSH call: get ActiveState + MainPID in one shot
            svc_mode = "none"
            running = False
            pid = None
            try:
                r = _run(
                    ["systemctl", "--user", "show", SERVICE,
                     "--property=ActiveState,MainPID,SubState"],
                    remote=bool(SSH_HOST), timeout=8)
                props = dict(l.split("=",1) for l in r.stdout.splitlines() if "=" in l)
                active = props.get("ActiveState","")
                if active == "active":
                    svc_mode = "systemd"
                    running = True
                    p = props.get("MainPID","0").strip()
                    if p and p != "0": pid = p
                elif active:  # exists but inactive/failed
                    svc_mode = "systemd"
                else:
                    # Try system-level in one call
                    r2 = _run(
                        ["sudo", "systemctl", "show", SERVICE,
                         "--property=ActiveState,MainPID"],
                        remote=bool(SSH_HOST), timeout=5)
                    props2 = dict(l.split("=",1) for l in r2.stdout.splitlines() if "=" in l)
                    if props2.get("ActiveState") == "active":
                        svc_mode = "systemd-system"
                        running = True
                        p = props2.get("MainPID","0").strip()
                        if p and p != "0": pid = p
                    else:
                        # Fall back to pgrep
                        stats = get_process_stats()
                        running = stats.get("running", False)
                        pid = str(stats.get("pid","")) if running else None
                        svc_mode = "direct" if running else "none"
            except:
                stats = get_process_stats()
                running = stats.get("running", False)
                svc_mode = "direct" if running else "none"
            # Read biscuit_public_key from config.yml if available
            biscuit_pub = ""
            if DATA_DIR:
                cfg_path = os.path.join(DATA_DIR, "config.yml")
                try:
                    import re as _re
                    cfg_content = open(cfg_path).read()
                    m = _re.search(r'biscuit_public_key:\s*["\']?([^"\'\n]+)["\']?', cfg_content)
                    if m: biscuit_pub = m.group(1).strip()
                except: pass
            self._json({
                "enabled": CONTROL,
                "running": running,
                "pid": pid,
                "service_mode": svc_mode,
                "service": SERVICE,
                "ckb_rpc": CKB_RPC,
                "fiber_rpc": FIBER_RPC,
                "dashboard_version": DASHBOARD_VERSION,
                "biscuit_public_key": biscuit_pub
            })
        elif self.path=="/api/system":
            stats = get_process_stats()
            conns = get_connections()
            # Total RAM (local or remote)
            try:
                if SSH_HOST:
                    r = _run(["cat", "/proc/meminfo"], remote=True, timeout=5)
                    for line in r.stdout.splitlines():
                        if line.startswith("MemTotal:"):
                            stats["total_ram_mb"] = round(int(line.split()[1])/1024, 0); break
                else:
                    with open("/proc/meminfo") as f:
                        for line in f:
                            if line.startswith("MemTotal:"):
                                stats["total_ram_mb"] = round(int(line.split()[1])/1024, 0); break
            except: pass
            stats["connections"] = conns
            self._json(stats)
        elif self.path.startswith("/api/logs"):
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            n = int(qs.get("lines",["50"])[0])
            lines = get_log_lines(n)
            self._json({"lines": lines})
        elif self.path=="/api/logs/stream":
            self._stream_logs()
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        if not self.path.startswith("/api/"):
            self.send_response(404); self.end_headers(); return
        length = int(self.headers.get("Content-Length",0))
        payload = json.loads(self.rfile.read(length)) if length else {}
        target = self.path[5:]

        if target=="fiber":
            params=payload.get("params",{})
            result=rpc_call(FIBER_RPC,payload.get("method"),[params],BISCUIT)
            self._json(result)
        elif target=="ckb":
            result=rpc_call(CKB_RPC,payload.get("method"),payload.get("params",[]))
            self._json(result)
        elif target=="derive_address":
            self._json({"address": lock_to_address(
                payload.get("lock",{}).get("code_hash",""),
                payload.get("lock",{}).get("hash_type","type"),
                payload.get("lock",{}).get("args",""), NETWORK
            )})
        elif target=="control":
            self._json(self._handle_control(payload))
        elif target=="maintenance":
            self._json(do_maintenance(payload.get("action",""), payload))
        elif target=="bug_report":
            self._json(self._handle_bug_report(payload))
        else:
            self._json({"error":"unknown target"}, 400)

    def _handle_bug_report(self, payload):
        title = (payload.get("title") or "").strip()
        body  = (payload.get("body")  or "").strip()
        if not title:
            return {"ok": False, "error": "Title required"}
        # Get GH token from environment or gh CLI
        gh_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
        if not gh_token:
            try:
                r = subprocess.run(["gh","auth","token"], capture_output=True, text=True, timeout=5)
                gh_token = r.stdout.strip()
            except: pass
        if not gh_token:
            return {"ok": False, "error": "No GitHub token available — set GH_TOKEN env var"}
        # Get node info for context
        node_ctx = ""
        try:
            ni = rpc_call(FIBER_RPC, "node_info", [{}], BISCUIT)
            if "result" in ni:
                n = ni["result"]
                node_ctx = f"\n\n---\n**Node info:** v{n.get('version','?')} · {n.get('node_id','?')[:20]}… · {NETWORK}"
        except: pass
        issue_body = f"{body}{node_ctx}\n\n*Reported via Fiber Dashboard*"
        try:
            req = urllib.request.Request(
                "https://api.github.com/repos/toastmanAu/fiber-installer/issues",
                data=json.dumps({"title": title, "body": issue_body, "labels": ["bug","dashboard"]}).encode(),
                headers={
                    "Authorization": f"Bearer {gh_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                    "Content-Type": "application/json",
                    "User-Agent": "fiber-dashboard/1.0"
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                return {"ok": True, "issue_url": data.get("html_url",""), "number": data.get("number")}
        except urllib.error.HTTPError as e:
            return {"ok": False, "error": f"GitHub API error {e.code}: {e.read().decode()[:200]}"}

    def _handle_control(self, payload):
        if not CONTROL:
            return {"ok":False,"output":"Control not enabled (--control flag required)"}
        action = payload.get("action","")
        network = payload.get("network", NETWORK)
        if action in ("start","stop","restart","enable","disable"):
            if action == "start":
                # Stop first (clean locks), then start with correct config
                systemctl("stop")
                time.sleep(1)
                return systemctl("start")
            return systemctl(action)
        return {"ok":False,"output":f"Unknown action: {action}"}

    def _stream_logs(self):
        self.send_response(200)
        self.send_header("Content-Type","text/event-stream")
        self.send_header("Cache-Control","no-cache")
        self.send_header("Access-Control-Allow-Origin","*")
        self.end_headers()
        try:
            if SSH_HOST:
                journal_cmd = f"journalctl --user -u {SERVICE} -f --no-pager -n0 --output=short 2>/dev/null"
                log_cmd = f"tail -f {LOG_FILE}" if LOG_FILE else journal_cmd
                cmd = ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
                       SSH_HOST, log_cmd]
            elif LOG_FILE and os.path.isfile(LOG_FILE):
                cmd = ["tail", "-f", LOG_FILE]
            else:
                cmd = ["journalctl","--user","-u",SERVICE,"-f","--no-pager","-n0","--output=short"]
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            for line in proc.stdout:
                data = json.dumps({"line": line.rstrip()})
                self.wfile.write(f"data: {data}\n\n".encode())
                self.wfile.flush()
        except: pass

# ── Main ───────────────────────────────────────────────────────────────────────
def get_local_ip():
    try:
        s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.connect(("8.8.8.8",80)); return s.getsockname()[0]
    except: return "127.0.0.1"

if __name__=="__main__":
    server=HTTPServer((args.host,args.port),Handler)
    ip=get_local_ip()
    ctrl_note = " [CONTROL ENABLED]" if CONTROL else " [read-only — pass --control to manage node]"
    ssh_note  = f" via SSH → {SSH_HOST}" if SSH_HOST else " (local)"
    print(f"""
╔══════════════════════════════════════════════════════╗
║        Fiber Network Node Dashboard                  ║
╚══════════════════════════════════════════════════════╝

  Dashboard:  http://{ip}:{args.port}
  Local:      http://127.0.0.1:{args.port}

  Fiber RPC:  {FIBER_RPC}
  CKB RPC:    {CKB_RPC}
  Network:    {NETWORK}
  Mode:      {ctrl_note}
  Control:   {ssh_note}
  Data dir:   {DATA_DIR or "(not set)"}
  FNN binary: {FNN_BIN or "(not set)"}

  Ctrl+C to stop
""")
    try: server.serve_forever()
    except KeyboardInterrupt: print("\n  Stopped.")
