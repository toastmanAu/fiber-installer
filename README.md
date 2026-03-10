# Fiber Network Node Installer

One-command installers for [Fiber Network](https://github.com/nervosnetwork/fiber) nodes — the CKB payment channel network.

## Quick Install

### Linux / macOS
```bash
curl -sSL https://raw.githubusercontent.com/toastmanAu/fiber-installer/main/install.sh | bash
```

### Windows (PowerShell — run as Administrator)
```powershell
iwr -useb https://raw.githubusercontent.com/toastmanAu/fiber-installer/main/install.ps1 | iex
```

## What it does

The installer walks you through:

1. **Network** — mainnet or testnet
2. **Install directory** — where the binary lives (`~/.fiber` by default)
3. **Data directory** — where chain data, keys, and config are stored
4. **CKB RPC** — point at your local node or a public endpoint
5. **P2P port** — 8228 by default, needs to be open if you want to be publicly reachable
6. **Public IP** — optional, announces your node to the network
7. **RPC port** — local-only by default (never expose to internet)

Then it:
- Downloads the correct binary for your platform
- Generates a private key (or uses existing)
- Writes a `config.yml` with your settings
- Installs a system service (systemd / launchd / NSSM)
- Adds `fnn` to your PATH
- Shows your wallet address to fund

## Platform Support

| Platform | Status | Notes |
|----------|--------|-------|
| Linux x86_64 | ✅ | systemd user service |
| Linux aarch64 | ✅ | Raspberry Pi, ARM servers |
| macOS x86_64 | ✅ | launchd agent |
| macOS arm64 | ✅ | Runs via Rosetta (native ARM release pending upstream) |
| Windows x86_64 | ✅ | NSSM service or startup script |

## After Installing

### Fund your wallet
Get your CKB address:
```bash
fnn --config-file ~/.fiber/data/config.yml local-node-info
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

**Windows:**
```powershell
nssm start FiberNode
nssm stop FiberNode
```

### Open a channel
```bash
# Get a peer's address from the Fiber network
fnn-cli --url http://127.0.0.1:8227 open-channel \
  --peer-id <PEER_ID> \
  --funding-amount 10000000000   # in shannons (100 CKB)
```

## Configuration

Config lives at `~/.fiber/data/config.yml` (or your chosen data dir).

Key settings:
- `fiber.listening_addr` — P2P listen address
- `fiber.announced_addrs` — public addresses to announce (add your IP here)
- `ckb.rpc_url` — CKB full node RPC
- `rpc.listening_addr` — Fiber RPC (keep localhost-only)

## Updating

Re-run the installer. It will download the new binary and restart the service.

Or manually:
```bash
# Check latest version
curl -s https://api.github.com/repos/nervosnetwork/fiber/releases/latest | grep tag_name

# Download and replace binary
curl -L https://github.com/nervosnetwork/fiber/releases/download/vX.Y.Z/fnn_vX.Y.Z-x86_64-linux-portable.tar.gz | tar -xz
cp fnn ~/.fiber/bin/fnn
systemctl --user restart fiber
```

## Security Notes

- **Back up `~/.fiber/data/key`** — this is your private key. Losing it = losing your funds.
- Never expose the RPC port (8227) to the internet.
- The P2P port (8228) is designed to be public — it's safe to open.

## Built by

[Wyltek Industries](https://wyltekindustries.com) — building on [Nervos CKB](https://nervos.org).

Community: [Wyltek Telegram Mini App](https://t.me/WyltekIndustriesBot)
