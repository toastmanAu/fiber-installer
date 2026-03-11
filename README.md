# Fiber Network Node Installer

One-command installers for [Fiber Network](https://github.com/nervosnetwork/fiber) nodes — the CKB payment channel network.

## Quick Install

### Linux / macOS
```bash
curl -sSL https://raw.githubusercontent.com/toastmanAu/fiber-installer/master/install.sh | bash
```

### Windows (PowerShell — run as Administrator)
```powershell
irm https://raw.githubusercontent.com/toastmanAu/fiber-installer/refs/heads/master/install.ps1 | iex
```

## What it does

The installer walks you through:

1. **Network** — mainnet, testnet, or both
2. **Dashboard** — optional web UI to monitor your node (channels, peers, payments)
3. **Install directory** — where the binary lives (`~/.fiber` by default)
4. **Data directory** — where chain data, keys, and config are stored
5. **CKB RPC** — point at your local node or a public endpoint
6. **P2P port** — 8228 by default, needs to be open if you want to be publicly reachable
7. **Public IP** — optional, announces your node to the network
8. **RPC port** — local-only by default (never expose to internet)

Then it:
- Downloads the correct binary for your platform (or builds from source on aarch64)
- Generates a private key (or uses existing)
- Writes a `config.yml` with your settings
- Installs a system service (systemd / launchd / NSSM)
- Installs the dashboard (Python 3 required — auto-installed on Windows)
- Runs a smoke test to verify the node starts and RPC responds
- Adds `fnn` to your PATH
- Shows your wallet address to fund

## Platform Support

| Platform | Status | Notes |
|----------|--------|-------|
| Linux x86_64 | ✅ | systemd user/system service |
| Linux aarch64 | ✅ | Builds from source (Raspberry Pi, ARM servers) |
| macOS x86_64 | ✅ | launchd agent |
| macOS arm64 | ✅ | Runs via Rosetta (native ARM release pending upstream) |
| Windows x86_64 | ✅ | NSSM service or startup script; VC++ runtime + Python auto-installed |

## After Installing

### Fund your wallet
Get your CKB address:
```bash
fnn --config ~/.fiber/data/config.yml local-node-info
```
Send at least **162 CKB** to your node's address. More CKB = more channel capacity you can offer.

### Start / Stop

**Linux:**
```bash
systemctl --user start fiber
systemctl --user stop fiber
journalctl --user -u fiber -f
```

**macOS:**
```bash
launchctl start xyz.wyltek.fiber
launchctl stop xyz.wyltek.fiber
tail -f ~/.fiber/data/fiber.log
```

**Windows (with NSSM):**
```powershell
nssm start FiberNode
nssm stop FiberNode
Get-Content -Wait "$env:USERPROFILE\.fiber\data\fiber.log"
```

**Windows (without NSSM):**
```
%USERPROFILE%\.fiber\start-fiber.bat
```

### Dashboard

Open in any browser on your local network:
```
http://<your-ip>:8229
```

### Open a channel
Use the dashboard, or via the Fiber CLI.

## Configuration

Config lives at `~/.fiber/data/config.yml` (or your chosen data dir).

Key settings:
- `fiber.listening_addr` — P2P listen address
- `fiber.announced_addrs` — public addresses to announce (add your IP here)
- `ckb.rpc_url` — CKB full node RPC
- `rpc.listening_addr` — Fiber RPC (keep localhost-only)

## Updating

Re-run the installer. It will download the new binary and restart the service.

## Security Notes

- **Back up `~/.fiber/data/key`** — this is your private key. Losing it = losing your funds.
- Never expose the RPC port (8227) to the internet.
- The P2P port (8228) is designed to be public — it's safe to open.

## Built by

[Wyltek Industries](https://wyltekindustries.com) — building on [Nervos CKB](https://nervos.org).

Community: [Wyltek Telegram Mini App](https://t.me/WyltekIndustriesBot)
