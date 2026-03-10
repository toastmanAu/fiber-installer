# ============================================================
#  Fiber Network Node Installer — Windows (PowerShell)
#  Run in PowerShell as Administrator:
#  iwr -useb https://fiber.wyltek.xyz/install.ps1 | iex
# ============================================================
#Requires -Version 5.1

$VERSION = "v0.7.1"
$REPO = "nervosnetwork/fiber"
$RELEASES = "https://github.com/$REPO/releases/download/$VERSION"
$TARBALL = "fnn_${VERSION}-x86_64-windows.tar.gz"
$DOWNLOAD_URL = "$RELEASES/$TARBALL"

# ── Colours ────────────────────────────────────────────────
function Write-Banner {
    Write-Host ""
    Write-Host "  FIBER NETWORK NODE INSTALLER" -ForegroundColor Cyan
    Write-Host "  Version: $VERSION" -ForegroundColor Cyan
    Write-Host "  https://github.com/nervosnetwork/fiber" -ForegroundColor DarkCyan
    Write-Host ""
}

function Write-Info  ($msg) { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn  ($msg) { Write-Host "  [!]  $msg" -ForegroundColor Yellow }
function Write-Step  ($msg) { Write-Host "`n== $msg ==" -ForegroundColor White }
function Prompt-User ($msg, $default) {
    Write-Host "  [?] $msg" -ForegroundColor Cyan
    Write-Host "      [$default] (press Enter to accept)" -ForegroundColor DarkYellow
    $input = Read-Host "      >"
    if ([string]::IsNullOrWhiteSpace($input)) { return $default }
    return $input
}

# ── Collect config ─────────────────────────────────────────
function Collect-Config {
    Write-Step "Network"
    Write-Host "  1) mainnet"
    Write-Host "  2) testnet"
    $netChoice = Read-Host "  > [1]"
    $script:NETWORK = if ($netChoice -eq "2") { "testnet" } else { "mainnet" }

    Write-Step "Installation Directory"
    $default = "$env:USERPROFILE\.fiber"
    $script:INSTALL_DIR = Prompt-User "Where should Fiber be installed?" $default

    Write-Step "Data Directory"
    $script:DATA_DIR = Prompt-User "Where should Fiber store data?" "$script:INSTALL_DIR\data"

    Write-Step "CKB Node RPC"
    Write-Host "  Public mainnet RPC: https://mainnet.ckb.dev/rpc"
    Write-Host "  Public testnet RPC: https://testnet.ckb.dev/rpc"
    if ($script:NETWORK -eq "mainnet") {
        $script:CKB_RPC = Prompt-User "CKB RPC URL" "http://127.0.0.1:8114/"
    } else {
        $script:CKB_RPC = Prompt-User "CKB RPC URL" "https://testnet.ckb.dev/rpc"
    }

    Write-Step "P2P Port"
    Write-Host "  This port must be open in Windows Firewall if you want to be publicly reachable."
    $script:P2P_PORT = Prompt-User "Fiber P2P port" "8228"

    Write-Step "Public IP (optional)"
    Write-Host "  Enter your static public IP to announce your node, or leave blank."
    $script:PUBLIC_IP = Read-Host "  >"

    Write-Step "RPC Port"
    $script:RPC_PORT = Prompt-User "Fiber RPC listen address" "127.0.0.1:8227"
}

# ── Download binary ────────────────────────────────────────
function Download-Binary {
    Write-Step "Downloading Fiber $VERSION"
    Write-Info "URL: $DOWNLOAD_URL"

    $tmpDir = [System.IO.Path]::GetTempPath() + [System.Guid]::NewGuid().ToString()
    New-Item -ItemType Directory -Path $tmpDir | Out-Null

    $tarPath = "$tmpDir\fiber.tar.gz"
    Invoke-WebRequest -Uri $DOWNLOAD_URL -OutFile $tarPath -UseBasicParsing

    # Extract (requires tar on Windows 10 1803+)
    & tar -xzf $tarPath -C $tmpDir

    $binDir = "$script:INSTALL_DIR\bin"
    New-Item -ItemType Directory -Force -Path $binDir | Out-Null

    $fnn = Get-ChildItem -Path $tmpDir -Recurse -Filter "fnn.exe" | Select-Object -First 1
    if (-not $fnn) {
        # try without .exe
        $fnn = Get-ChildItem -Path $tmpDir -Recurse -Filter "fnn" | Select-Object -First 1
    }
    if (-not $fnn) { Write-Error "Could not find fnn binary in archive"; exit 1 }

    Copy-Item $fnn.FullName "$binDir\fnn.exe" -Force
    Write-Info "Binary installed: $binDir\fnn.exe"

    Remove-Item -Recurse -Force $tmpDir
}

# ── Generate key ───────────────────────────────────────────
function Generate-Key {
    Write-Step "Wallet Setup"
    New-Item -ItemType Directory -Force -Path $script:DATA_DIR | Out-Null
    $keyFile = "$script:DATA_DIR\key"
    $script:KEY_FILE = $keyFile

    if (Test-Path $keyFile) {
        Write-Warn "Key file already exists at $keyFile — skipping generation"
    } else {
        $bytes = New-Object byte[] 32
        [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
        $hex = "0x" + ($bytes | ForEach-Object { $_.ToString("x2") }) -join ""
        Set-Content -Path $keyFile -Value $hex -Encoding ASCII
        Write-Info "Private key generated: $keyFile"
    }
}

# ── Write config ───────────────────────────────────────────
function Write-Config {
    Write-Step "Writing Configuration"

    $announcedAddr = ""
    if ($script:PUBLIC_IP) {
        $announcedAddr = "  announced_addrs:`n    - `"/ip4/$($script:PUBLIC_IP)/tcp/$($script:P2P_PORT)`""
    } else {
        $announcedAddr = "  announced_addrs: []"
    }

    if ($script:NETWORK -eq "mainnet") {
        $bootnodes = @(
            "  - `"/ip4/43.199.24.44/tcp/8228/p2p/QmZ2gCTfEF6vKsiYFF2STPeA2rRLRim9nMtzfwiE7uMQ4v`"",
            "  - `"/ip4/54.255.71.126/tcp/8228/p2p/QmcMLnWraRyxd7PFRgvn1QeYRQS2DGsP6fPFCQjtfMs5b2`""
        ) -join "`n"
        $scripts = Get-MainnetScripts
    } else {
        $bootnodes = ""
        $scripts = ""
    }

    $config = @"
# Generated by Fiber Node Installer (Windows)
fiber:
  listening_addr: "/ip4/0.0.0.0/tcp/$($script:P2P_PORT)"
  bootnode_addrs:
$bootnodes
  announce_listening_addr: $(if ($script:PUBLIC_IP) { "true" } else { "false" })
$announcedAddr
  chain: $($script:NETWORK)
  private_key_path: "$($script:KEY_FILE -replace '\\', '/')"
$scripts

rpc:
  listening_addr: "$($script:RPC_PORT)"

ckb:
  rpc_url: "$($script:CKB_RPC)"

store:
  path: "$($script:DATA_DIR -replace '\\', '/')/store"

services:
  - fiber
  - rpc
  - ckb
"@

    $configFile = "$script:DATA_DIR\config.yml"
    Set-Content -Path $configFile -Value $config -Encoding UTF8
    Write-Info "Config written: $configFile"
    $script:CONFIG_FILE = $configFile
}

function Get-MainnetScripts {
    return @"
  scripts:
    - name: FundingLock
      script:
        code_hash: 0xe45b1f8f21bff23137035a3ab751d75b36a981deec3e7820194b9c042967f4f1
        hash_type: type
        args: 0x
      cell_deps:
        - type_id:
            code_hash: 0x00000000000000000000000000000000000000000000000000545950455f4944
            hash_type: type
            args: 0x64818d82a372312fb007c480391e1b9759d21b2c7f7959b9c177d72cdc243394
        - cell_dep:
            out_point:
              tx_hash: 0x95006eee7b4c0c8ad66e0514c88ed0ae43fc8db27793427de86a348ec720b9d6
              index: 0x0
            dep_type: code
    - name: CommitmentLock
      script:
        code_hash: 0x2d45c4d3ed3e942f1945386ee82a5d1b7e4bb16d7fe1ab015421174ab747406c
        hash_type: type
        args: 0x
      cell_deps:
        - type_id:
            code_hash: 0x00000000000000000000000000000000000000000000000000545950455f4944
            hash_type: type
            args: 0xdb16e6dcb17f670e5fb7c556d81e522ec5edb069ad2fa3e898e7ccea6c26a39f
        - cell_dep:
            out_point:
              tx_hash: 0x95006eee7b4c0c8ad66e0514c88ed0ae43fc8db27793427de86a348ec720b9d6
              index: 0x0
            dep_type: code
"@
}

# ── Install Windows Service (NSSM) ─────────────────────────
function Install-Service {
    Write-Step "Windows Service"

    # Try NSSM if available
    if (Get-Command nssm -ErrorAction SilentlyContinue) {
        & nssm install FiberNode "$script:INSTALL_DIR\bin\fnn.exe"
        & nssm set FiberNode AppParameters "--config-file `"$script:CONFIG_FILE`""
        & nssm set FiberNode AppDirectory "$script:DATA_DIR"
        & nssm set FiberNode DisplayName "Fiber Network Node"
        & nssm set FiberNode Description "Fiber CKB payment channel node"
        & nssm set FiberNode Start SERVICE_AUTO_START
        Write-Info "NSSM service installed: FiberNode"
        Write-Info "Start: nssm start FiberNode"
    } else {
        Write-Warn "NSSM not found — creating a startup script instead"
        $startScript = "$script:INSTALL_DIR\start-fiber.bat"
        Set-Content -Path $startScript -Value "@echo off`n`"$script:INSTALL_DIR\bin\fnn.exe`" --config-file `"$script:CONFIG_FILE`""
        Write-Info "Start script: $startScript"
        Write-Warn "To auto-start on boot, add a shortcut to: shell:startup"
        Write-Warn "Or install NSSM (https://nssm.cc) and re-run this script"
    }
}

# ── Add to PATH ────────────────────────────────────────────
function Add-ToPath {
    $binDir = "$script:INSTALL_DIR\bin"
    $currentPath = [Environment]::GetEnvironmentVariable("PATH", "User")
    if ($currentPath -notlike "*$binDir*") {
        [Environment]::SetEnvironmentVariable("PATH", "$currentPath;$binDir", "User")
        Write-Info "Added $binDir to user PATH"
    }
}

# ── Firewall rule ──────────────────────────────────────────
function Add-FirewallRule {
    if ($script:PUBLIC_IP) {
        Write-Step "Firewall"
        try {
            New-NetFirewallRule -DisplayName "Fiber Network P2P" -Direction Inbound `
                -Protocol TCP -LocalPort $script:P2P_PORT -Action Allow -ErrorAction Stop | Out-Null
            Write-Info "Firewall rule added for port $script:P2P_PORT"
        } catch {
            Write-Warn "Could not add firewall rule automatically."
            Write-Warn "Manually allow inbound TCP on port $($script:P2P_PORT) in Windows Defender Firewall."
        }
    }
}

# ── Summary ────────────────────────────────────────────────
function Show-Summary {
    Write-Step "Installation Complete"
    Write-Host ""
    Write-Host "  Fiber $VERSION is installed!" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Install dir:  $script:INSTALL_DIR" -ForegroundColor Cyan
    Write-Host "  Data dir:     $script:DATA_DIR" -ForegroundColor Cyan
    Write-Host "  Config:       $script:CONFIG_FILE" -ForegroundColor Cyan
    Write-Host "  Network:      $script:NETWORK" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  IMPORTANT: Back up your private key!" -ForegroundColor Yellow
    Write-Host "  Key file: $script:KEY_FILE" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Fund your wallet with 162+ CKB to start accepting channels."
    Write-Host ""
    Write-Host "  Fiber docs: https://github.com/nervosnetwork/fiber"
    Write-Host "  Community:  https://t.me/WyltekIndustriesBot"
    Write-Host ""
}

# ── Main ───────────────────────────────────────────────────
Write-Banner
Collect-Config
Download-Binary
Generate-Key
Write-Config
Install-Service
Add-ToPath
Add-FirewallRule
Show-Summary
