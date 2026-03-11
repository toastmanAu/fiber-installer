# ============================================================
#  Fiber Network Node Installer - Windows (PowerShell)
#  Run in PowerShell as Administrator:
#  irm https://raw.githubusercontent.com/toastmanAu/fiber-installer/refs/heads/master/install.ps1 | iex
# ============================================================
#Requires -Version 5.1
$ErrorActionPreference = "Stop"

$VERSION    = "v0.7.1"
$REPO       = "nervosnetwork/fiber"
$RELEASES   = "https://github.com/$REPO/releases/download/$VERSION"
$TARBALL    = "fnn_${VERSION}-x86_64-windows.tar.gz"
$DASH_URL   = "https://raw.githubusercontent.com/toastmanAu/fiber-installer/refs/heads/master/dashboard/fiber-dash.py"
$MAINNET_CFG_URL = "https://raw.githubusercontent.com/nervosnetwork/fiber/main/config/mainnet/config.yml"
$TESTNET_CFG_URL = "https://raw.githubusercontent.com/nervosnetwork/fiber/main/config/testnet/config.yml"

# ── Colours ────────────────────────────────────────────────
function Write-Ok    ($m) { Write-Host "  [OK] $m" -ForegroundColor Green }
function Write-Warn  ($m) { Write-Host "  [!]  $m" -ForegroundColor Yellow }
function Write-Fail  ($m) { Write-Host "  [X]  $m" -ForegroundColor Red }
function Write-Step  ($m) { Write-Host "`n== $m ==" -ForegroundColor Cyan }
function Write-Info  ($m) { Write-Host "       $m" -ForegroundColor DarkGray }

function Ask {
    param($Prompt, $Default)
    Write-Host "  [?] $Prompt" -ForegroundColor Cyan
    Write-Host "      [$Default] (Enter to accept)" -ForegroundColor DarkYellow
    $v = Read-Host "      >"
    if ([string]::IsNullOrWhiteSpace($v)) { return $Default }
    return $v
}

function AskChoice {
    param($Prompt, $Opt1, $Opt2, $Default = "1")
    Write-Host "  [?] $Prompt" -ForegroundColor Cyan
    Write-Host "      1) $Opt1"
    Write-Host "      2) $Opt2"
    while ($true) {
        $v = Read-Host "      >"
        if ([string]::IsNullOrWhiteSpace($v)) { $v = $Default }
        if ($v -eq "1" -or $v -eq $Opt1) { return $Opt1 }
        if ($v -eq "2" -or $v -eq $Opt2) { return $Opt2 }
        Write-Host "      Please enter 1 or 2"
    }
}

function AskChoice3 {
    param($Prompt, $Opt1, $Opt2, $Opt3, $Default = "1")
    Write-Host "  [?] $Prompt" -ForegroundColor Cyan
    Write-Host "      1) $Opt1"
    Write-Host "      2) $Opt2"
    Write-Host "      3) $Opt3"
    while ($true) {
        $v = Read-Host "      >"
        if ([string]::IsNullOrWhiteSpace($v)) { $v = $Default }
        if ($v -eq "1" -or $v -eq $Opt1) { return $Opt1 }
        if ($v -eq "2" -or $v -eq $Opt2) { return $Opt2 }
        if ($v -eq "3" -or $v -eq $Opt3) { return $Opt3 }
        Write-Host "      Please enter 1, 2 or 3"
    }
}

# ── Banner ─────────────────────────────────────────────────
function Show-Banner {
    Write-Host ""
    Write-Host "  FIBER NETWORK NODE INSTALLER" -ForegroundColor Cyan
    Write-Host "  Version: $VERSION  (Windows / PowerShell)" -ForegroundColor Cyan
    Write-Host "  https://github.com/nervosnetwork/fiber" -ForegroundColor DarkCyan
    Write-Host ""
}

# ── Collect config ─────────────────────────────────────────
function Collect-Config {
    Write-Step "Network"
    Write-Info "Mainnet uses real CKB. Testnet is a sandbox with no real value - good for testing."
    Write-Info "If you're just getting started, mainnet is fine. Testnet CKB is free from a faucet."
    $script:NETWORK = AskChoice3 "Which network?" "mainnet" "testnet" "both"

    Write-Step "Dashboard"
    Write-Info "A simple web page you can open in any browser to see your node's status -"
    Write-Info "channels, balances, payments, peers. Runs on your local network only."
    Write-Info "Requires Python 3 to be installed."
    $script:INSTALL_DASH = AskChoice "Install dashboard?" "yes" "no"
    if ($script:INSTALL_DASH -eq "yes") {
        $script:DASH_PORT = Ask "Dashboard port" "8229"
    }

    Write-Step "Installation Directory"
    Write-Info "Where the Fiber program files will be stored."
    $defaultDir = "$env:USERPROFILE\.fiber"
    if ($script:NETWORK -eq "both") {
        $script:BASE_INSTALL_DIR = Ask "Base install directory (mainnet + testnet go in subdirs)" $defaultDir
        $script:INSTALL_DIR = $script:BASE_INSTALL_DIR
    } else {
        $script:INSTALL_DIR = Ask "Where should Fiber be installed?" $defaultDir
    }

    Write-Step "CKB Node (upstream)"
    Write-Info "Fiber connects TO a CKB full node to read chain state and submit transactions."
    Write-Info "Public mainnet RPC: https://mainnet.ckb.dev/rpc"
    Write-Info "Public testnet RPC: https://testnet.ckb.dev/rpc"
    Write-Info "If you run your own CKB node on LAN, use its IP (e.g. http://192.168.x.x:8114)"
    if ($script:NETWORK -eq "mainnet") {
        $script:CKB_RPC = Ask "CKB full node URL (Fiber connects TO this)" "http://127.0.0.1:8114/"
    } elseif ($script:NETWORK -eq "testnet") {
        $script:CKB_RPC = Ask "CKB full node URL (Fiber connects TO this)" "https://testnet.ckb.dev/rpc"
    } else {
        $script:MAINNET_CKB_RPC = Ask "Mainnet CKB full node URL" "http://127.0.0.1:8114/"
        $script:TESTNET_CKB_RPC = Ask "Testnet CKB full node URL" "https://testnet.ckb.dev/rpc"
    }

    Write-Step "P2P Port"
    Write-Info "The port other Fiber nodes use to find and connect to yours."
    Write-Info "Default (8228) is fine. You may need to forward this port in your router"
    Write-Info "settings to be reachable from the wider network."
    if ($script:NETWORK -eq "both") {
        $script:MAINNET_P2P_PORT = Ask "Mainnet P2P port" "8228"
        $script:TESTNET_P2P_PORT = Ask "Testnet P2P port" "8229"
    } else {
        $script:P2P_PORT = Ask "Fiber P2P port" "8228"
    }

    Write-Step "Public IP (optional)"
    Write-Info "If your machine has a fixed public IP, enter it here so other nodes can find you."
    Write-Info "Most home users: leave blank."
    $script:PUBLIC_IP = Read-Host "      >"

    Write-Step "Fiber RPC Port (your control port)"
    Write-Info "How YOU talk to Fiber - to open channels, check balances, send payments."
    Write-Info "127.0.0.1 means this machine only - do NOT change to 0.0.0.0."
    if ($script:NETWORK -eq "both") {
        $script:MAINNET_RPC_PORT = Ask "Mainnet Fiber control port" "127.0.0.1:8227"
        $script:TESTNET_RPC_PORT = Ask "Testnet Fiber control port" "127.0.0.1:8226"
    } else {
        $script:RPC_PORT = Ask "Fiber control port" "127.0.0.1:8227"
    }

    Write-Step "Wallet"
    Write-Info "Fiber needs its own CKB wallet to open and close payment channels on-chain."
    Write-Info "We'll generate a fresh private key now and save it securely on this machine."
    Write-Info "After install, send some CKB to this wallet's address to fund it."
    Write-Host ""
}

# ── Download binary ────────────────────────────────────────
function Download-Binary {
    param($InstallDir)
    Write-Step "Downloading Fiber $VERSION"
    $url = "$RELEASES/$TARBALL"
    Write-Ok "URL: $url"

    $tmpDir = Join-Path ([System.IO.Path]::GetTempPath()) ([System.Guid]::NewGuid().ToString())
    New-Item -ItemType Directory -Path $tmpDir | Out-Null

    try {
        $tarPath = Join-Path $tmpDir "fiber.tar.gz"
        Write-Host "  Downloading..." -NoNewline
        Invoke-WebRequest -Uri $url -OutFile $tarPath -UseBasicParsing
        Write-Host " done"

        & tar -xzf $tarPath -C $tmpDir
        if ($LASTEXITCODE -ne 0) { throw "tar extraction failed" }

        $binDir = Join-Path $InstallDir "bin"
        New-Item -ItemType Directory -Force -Path $binDir | Out-Null

        $fnn = Get-ChildItem -Path $tmpDir -Recurse -Filter "fnn.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $fnn) {
            $fnn = Get-ChildItem -Path $tmpDir -Recurse -Filter "fnn" -ErrorAction SilentlyContinue | Select-Object -First 1
        }
        if (-not $fnn) { throw "Could not find fnn binary in archive" }

        Copy-Item $fnn.FullName (Join-Path $binDir "fnn.exe") -Force
        Write-Ok "Binary installed: $(Join-Path $binDir 'fnn.exe')"
    } finally {
        Remove-Item -Recurse -Force $tmpDir -ErrorAction SilentlyContinue
    }
}

# ── Generate key ───────────────────────────────────────────
function Generate-Key {
    param($DataDir)
    Write-Step "Wallet Setup"
    New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
    $keyFile = Join-Path $DataDir "key"

    if (Test-Path $keyFile) {
        Write-Warn "Key file already exists at $keyFile - skipping generation"
    } else {
        $bytes = New-Object byte[] 32
        [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
        $hex = "0x" + (($bytes | ForEach-Object { $_.ToString("x2") }) -join "")
        Set-Content -Path $keyFile -Value $hex -Encoding ASCII -NoNewline
        Write-Ok "Private key generated: $keyFile"
    }
    return $keyFile
}

# ── Write config ───────────────────────────────────────────
function Write-FiberConfig {
    param($DataDir, $KeyFile, $Network, $CkbRpc, $P2pPort, $RpcPort, $PublicIp)

    Write-Step "Writing Configuration"
    $configFile = Join-Path $DataDir "config.yml"

    # Fetch base config from official repo
    $baseConfig = ""
    try {
        $cfgUrl = if ($Network -eq "mainnet") { $MAINNET_CFG_URL } else { $TESTNET_CFG_URL }
        $baseConfig = (Invoke-WebRequest -Uri $cfgUrl -UseBasicParsing).Content
    } catch {
        Write-Warn "Could not fetch upstream config - using minimal defaults (bootnodes may be missing)"
    }

    # Extract bootnode lines
    $bootnodeLines = ""
    if ($baseConfig) {
        $lines = $baseConfig -split "`n"
        $inBootnodes = $false
        $collected = @()
        foreach ($line in $lines) {
            if ($line -match "^\s*bootnode_addrs:") { $inBootnodes = $true; continue }
            if ($inBootnodes) {
                if ($line -match "^\s*-") { $collected += $line }
                elseif ($line -match "^\S" -or ($line -notmatch "^\s*-" -and $line -match "^\s+\w")) { break }
            }
        }
        $bootnodeLines = $collected -join "`n"
    }

    # Extract scripts block
    $scriptsBlock = ""
    if ($baseConfig) {
        $lines = $baseConfig -split "`n"
        $inScripts = $false
        $collected = @()
        $depth = 0
        foreach ($line in $lines) {
            if ($line -match "^\s{2}scripts:") { $inScripts = $true }
            if ($inScripts) {
                $collected += $line
                if ($collected.Count -gt 80) { break }
                if ($collected.Count -gt 1 -and $line -match "^\S") { break }
            }
        }
        $scriptsBlock = $collected -join "`n"
    }

    $announceAddr  = if ($PublicIp) { "true" } else { "false" }
    $announcedBlock = if ($PublicIp) {
        "  announced_addrs:`n    - `"/ip4/$PublicIp/tcp/$P2pPort`""
    } else {
        "  announced_addrs: []"
    }

    $keyForward = $KeyFile -replace "\\", "/"

    $config = @"
# Generated by Fiber Node Installer (Windows)
fiber:
  listening_addr: "/ip4/0.0.0.0/tcp/$P2pPort"
  bootnode_addrs:
$bootnodeLines
  announce_listening_addr: $announceAddr
$announcedBlock
  chain: $Network
  private_key_path: "$keyForward"
$scriptsBlock

rpc:
  listening_addr: "$RpcPort"

ckb:
  rpc_url: "$CkbRpc"

store:
  path: "$($DataDir -replace '\\','/')/store"

services:
  - fiber
  - rpc
  - ckb
"@

    Set-Content -Path $configFile -Value $config -Encoding UTF8
    Write-Ok "Config written: $configFile"
    return $configFile
}

# ── Install Windows service (NSSM or batch fallback) ───────
function Install-FiberService {
    param($InstallDir, $DataDir, $ConfigFile, $Network)
    Write-Step "Windows Service"

    $fnnExe = Join-Path $InstallDir "bin\fnn.exe"
    $svcName = if ($Network -eq "testnet") { "FiberNodeTestnet" } else { "FiberNode" }
    $svcDesc = "Fiber Network Node ($Network)"

    # Generate a stable key password
    $keyPass = "$env:COMPUTERNAME-fiber-$(Get-Date -Format 'yyyy')"

    if (Get-Command nssm -ErrorAction SilentlyContinue) {
        & nssm install $svcName $fnnExe "--config `"$ConfigFile`""
        & nssm set $svcName AppDirectory $DataDir
        & nssm set $svcName DisplayName $svcDesc
        & nssm set $svcName Description "Fiber CKB payment channel node ($Network)"
        & nssm set $svcName AppEnvironmentExtra "FIBER_SECRET_KEY_PASSWORD=$keyPass"
        & nssm set $svcName Start SERVICE_AUTO_START
        & nssm set $svcName AppStdout (Join-Path $DataDir "fiber.log")
        & nssm set $svcName AppStderr (Join-Path $DataDir "fiber.log")
        Write-Ok "NSSM service installed: $svcName"
        Write-Info "Start:  nssm start $svcName"
        Write-Info "Logs:   Get-Content -Wait $(Join-Path $DataDir 'fiber.log')"
    } else {
        Write-Warn "NSSM not found - creating start/stop scripts instead"
        Write-Info "Install NSSM for auto-start on boot: https://nssm.cc"

        $startBat = Join-Path $InstallDir "start-fiber.bat"
        $stopBat  = Join-Path $InstallDir "stop-fiber.bat"

        "@echo off`r`nset FIBER_SECRET_KEY_PASSWORD=$keyPass`r`n`"$fnnExe`" --config `"$ConfigFile`" >> `"$(Join-Path $DataDir 'fiber.log')`" 2>&1" |
            Set-Content -Path $startBat -Encoding ASCII

        "@echo off`r`ntaskkill /IM fnn.exe /F`r`necho Fiber stopped." |
            Set-Content -Path $stopBat -Encoding ASCII

        Write-Ok "Start script: $startBat"
        Write-Ok "Stop  script: $stopBat"
        Write-Warn "To auto-start on boot, add a shortcut to $startBat in:"
        Write-Info "shell:startup  (Win+R, type shell:startup)"
    }
}

# ── Install dashboard ──────────────────────────────────────
function Install-Dashboard {
    param($InstallDir, $DataDir, $Network, $FiberRpc, $CkbRpc, $DashPort)

    if ($script:INSTALL_DASH -ne "yes") { return }

    # Check Python
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) { $py = Get-Command python3 -ErrorAction SilentlyContinue }
    if (-not $py) {
        Write-Warn "Python not found - skipping dashboard install"
        Write-Info "Install Python from https://python.org then re-run this installer"
        return
    }

    Write-Step "Installing Dashboard"
    $dashDir = Join-Path $InstallDir "dashboard"
    New-Item -ItemType Directory -Force -Path $dashDir | Out-Null

    Invoke-WebRequest -Uri $DASH_URL -OutFile (Join-Path $dashDir "fiber-dash.py") -UseBasicParsing
    Write-Ok "Dashboard installed: $(Join-Path $dashDir 'fiber-dash.py')"

    # Write start script
    $dashBat = Join-Path $InstallDir "start-dashboard.bat"
    $pyExe   = $py.Source
    "@echo off`r`n`"$pyExe`" `"$(Join-Path $dashDir 'fiber-dash.py')`" --fiber-rpc $FiberRpc --ckb-rpc $CkbRpc --port $DashPort --control --data-dir `"$DataDir`" --fnn-bin `"$(Join-Path $InstallDir 'bin\fnn.exe')`" --network $Network`r`n" |
        Set-Content -Path $dashBat -Encoding ASCII

    Write-Ok "Dashboard start script: $dashBat"
    Write-Info "Run: $dashBat"
    Write-Info "Then open: http://localhost:$DashPort"
}

# ── Add to PATH ────────────────────────────────────────────
function Add-ToPath {
    param($InstallDir)
    $binDir = Join-Path $InstallDir "bin"
    $currentPath = [Environment]::GetEnvironmentVariable("PATH", "User")
    if ($currentPath -notlike "*$binDir*") {
        [Environment]::SetEnvironmentVariable("PATH", "$currentPath;$binDir", "User")
        Write-Ok "Added $binDir to user PATH"
    }
}

# ── Firewall rule ──────────────────────────────────────────
function Add-FirewallRule {
    param($Port, $Network)
    if (-not $script:PUBLIC_IP) { return }
    Write-Step "Firewall"
    $ruleName = "Fiber Network P2P ($Network)"
    try {
        $existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
        if ($existing) {
            Write-Ok "Firewall rule already exists for port $Port"
        } else {
            New-NetFirewallRule -DisplayName $ruleName -Direction Inbound `
                -Protocol TCP -LocalPort $Port -Action Allow | Out-Null
            Write-Ok "Firewall rule added for port $Port"
        }
    } catch {
        Write-Warn "Could not add firewall rule automatically."
        Write-Info "Manually allow inbound TCP on port $Port in Windows Defender Firewall."
    }
}

# ── Smoke test ─────────────────────────────────────────────
function Run-SmokeTest {
    param($InstallDir, $DataDir, $ConfigFile, $RpcPort)
    Write-Step "Smoke Test"
    Write-Info "Starting Fiber briefly to verify it can connect to CKB RPC..."
    Write-Info "(node will be stopped automatically after the test)"
    Write-Host ""

    $fnnExe  = Join-Path $InstallDir "bin\fnn.exe"
    $rpcAddr = $RpcPort  # e.g. 127.0.0.1:8227
    $rpcUrl  = "http://$rpcAddr"

    $proc = Start-Process -FilePath $fnnExe `
        -ArgumentList "--config `"$ConfigFile`"" `
        -WindowStyle Hidden -PassThru

    $smokePass = $false
    Write-Host "  Waiting for RPC on $rpcAddr" -NoNewline
    for ($i = 0; $i -lt 15; $i++) {
        Start-Sleep 1
        Write-Host "." -NoNewline
        try {
            $body = '{"jsonrpc":"2.0","method":"node_info","params":[],"id":1}'
            $resp = Invoke-RestMethod -Uri $rpcUrl -Method Post `
                -ContentType "application/json" -Body $body -TimeoutSec 2 -ErrorAction Stop
            Write-Host ""
            $nodeId = if ($resp.result.node_id) { $resp.result.node_id.Substring(0,[Math]::Min(20,$resp.result.node_id.Length)) + "..." } else { "unknown" }
            Write-Ok "RPC responded - node_id: $nodeId"
            $smokePass = $true
            break
        } catch { }
    }

    if (-not $smokePass) {
        Write-Host ""
        Write-Warn "RPC did not respond within 15s"
        Write-Info "This is normal on first boot while the node initialises."
        Write-Info "Check logs: Get-Content -Wait `"$(Join-Path $DataDir 'fiber.log')`""
    }

    # Stop smoke test process
    if (-not $proc.HasExited) {
        $proc.Kill()
        Start-Sleep 1
    }
    Write-Ok "Smoke test node stopped"

    if ($smokePass) {
        Write-Host "`n  Smoke test PASSED - node starts and RPC is reachable" -ForegroundColor Green
    } else {
        Write-Host "`n  Smoke test inconclusive - see warnings above" -ForegroundColor Yellow
        Write-Info "This does not mean the install failed. Start manually and check logs."
    }

    # Offer to start node
    Write-Host ""
    $startNow = Read-Host "  Start the Fiber node now? [Y/n]"
    if ([string]::IsNullOrWhiteSpace($startNow) -or $startNow -match "^[Yy]") {
        if (Get-Command nssm -ErrorAction SilentlyContinue) {
            $svcName = if ($script:NETWORK -eq "testnet") { "FiberNodeTestnet" } else { "FiberNode" }
            & nssm start $svcName
            Write-Ok "Fiber node started (NSSM service: $svcName)"
        } else {
            $startBat = Join-Path $InstallDir "start-fiber.bat"
            Start-Process -FilePath $startBat -WindowStyle Minimized
            Write-Ok "Fiber node started (minimised window)"
        }
    } else {
        Write-Info "Skipped - start manually when ready"
    }

    if ($script:INSTALL_DASH -eq "yes") {
        Write-Host ""
        $startDash = Read-Host "  Start the dashboard now? [Y/n]"
        if ([string]::IsNullOrWhiteSpace($startDash) -or $startDash -match "^[Yy]") {
            $dashBat = Join-Path $InstallDir "start-dashboard.bat"
            if (Test-Path $dashBat) {
                Start-Process -FilePath $dashBat -WindowStyle Minimized
                Write-Ok "Dashboard started - open http://localhost:$($script:DASH_PORT)"
            }
        }
    }
}

# ── Show wallet info ───────────────────────────────────────
function Show-Wallet {
    param($InstallDir, $DataDir, $KeyFile)
    Write-Step "Your Fiber Wallet"
    Write-Host ""
    Write-Host "  Private key: $KeyFile" -ForegroundColor White
    Write-Host ""
    Write-Host "  WARNING: BACK UP YOUR KEY FILE." -ForegroundColor Yellow
    Write-Host "  If you lose it, you lose access to your channels." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  To get your CKB address, run:" -ForegroundColor White
    Write-Host "    $(Join-Path $InstallDir 'bin\fnn.exe') --config $(Join-Path $DataDir 'config.yml') local-node-info" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Send at least 162 CKB to that address before starting your node." -ForegroundColor White
    Write-Host ""
}

# ── Summary ────────────────────────────────────────────────
function Show-Summary {
    param($InstallDir, $DataDir, $ConfigFile, $Network, $P2pPort, $CkbRpc)
    Write-Host ""
    Write-Host "  Fiber $VERSION is installed!" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Program:  $(Join-Path $InstallDir 'bin\fnn.exe')" -ForegroundColor Cyan
    Write-Host "  Config:   $ConfigFile" -ForegroundColor Cyan
    Write-Host "  Network:  $Network" -ForegroundColor Cyan
    Write-Host "  P2P port: $P2pPort" -ForegroundColor Cyan
    Write-Host "  CKB node: $CkbRpc" -ForegroundColor Cyan
    Write-Host ""
    if ($script:INSTALL_DASH -eq "yes") {
        Write-Host "  Dashboard: http://localhost:$($script:DASH_PORT)" -ForegroundColor Cyan
        Write-Host "             Run: $(Join-Path $InstallDir 'start-dashboard.bat')" -ForegroundColor DarkGray
        Write-Host ""
    }
    Write-Host "  Fiber docs: https://github.com/nervosnetwork/fiber" -ForegroundColor White
    Write-Host "  Community:  https://t.me/WyltekIndustriesBot" -ForegroundColor White
    Write-Host ""
}

# ── Install single network ─────────────────────────────────
function Install-Single {
    param($Network, $InstallDir, $DataDir, $CkbRpc, $P2pPort, $RpcPort)

    Download-Binary  -InstallDir $InstallDir
    $keyFile   = Generate-Key  -DataDir $DataDir
    $cfgFile   = Write-FiberConfig `
                    -DataDir   $DataDir `
                    -KeyFile   $keyFile `
                    -Network   $Network `
                    -CkbRpc    $CkbRpc `
                    -P2pPort   $P2pPort `
                    -RpcPort   $RpcPort `
                    -PublicIp  $script:PUBLIC_IP
    Install-FiberService -InstallDir $InstallDir -DataDir $DataDir -ConfigFile $cfgFile -Network $Network
    $dashPort = if ($script:DASH_PORT) { $script:DASH_PORT } else { "8229" }
    Install-Dashboard    -InstallDir $InstallDir -DataDir $DataDir -Network $Network `
                         -FiberRpc "http://$RpcPort" -CkbRpc $CkbRpc -DashPort $dashPort
    Add-ToPath           -InstallDir $InstallDir
    Add-FirewallRule     -Port $P2pPort -Network $Network
    Run-SmokeTest        -InstallDir $InstallDir -DataDir $DataDir -ConfigFile $cfgFile -RpcPort $RpcPort
    Show-Wallet          -InstallDir $InstallDir -DataDir $DataDir -KeyFile $keyFile
    Show-Summary         -InstallDir $InstallDir -DataDir $DataDir -ConfigFile $cfgFile `
                         -Network $Network -P2pPort $P2pPort -CkbRpc $CkbRpc
}

# ── Main ───────────────────────────────────────────────────
Show-Banner
Collect-Config

if ($script:NETWORK -eq "both") {
    Write-Step "Installing Mainnet Node"
    $mnDir  = "$($script:BASE_INSTALL_DIR)-mainnet"
    Install-Single -Network "mainnet" -InstallDir $mnDir `
                   -DataDir "$mnDir\data" -CkbRpc $script:MAINNET_CKB_RPC `
                   -P2pPort $script:MAINNET_P2P_PORT -RpcPort $script:MAINNET_RPC_PORT

    Write-Step "Installing Testnet Node"
    $tnDir  = "$($script:BASE_INSTALL_DIR)-testnet"
    Install-Single -Network "testnet" -InstallDir $tnDir `
                   -DataDir "$tnDir\data" -CkbRpc $script:TESTNET_CKB_RPC `
                   -P2pPort $script:TESTNET_P2P_PORT -RpcPort $script:TESTNET_RPC_PORT
} else {
    Install-Single -Network $script:NETWORK -InstallDir $script:INSTALL_DIR `
                   -DataDir "$($script:INSTALL_DIR)\data" -CkbRpc $script:CKB_RPC `
                   -P2pPort $script:P2P_PORT -RpcPort $script:RPC_PORT
}
