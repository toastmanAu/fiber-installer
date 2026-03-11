#!/usr/bin/env bash
# ============================================================
#  Fiber Network Node Installer
#  One-line install: curl -sSL https://fiber.wyltek.xyz/install.sh | bash
#  Supports: Linux x86_64 / aarch64 · macOS x86_64 / arm64
# ============================================================
set -euo pipefail

VERSION="v0.7.1"
REPO="nervosnetwork/fiber"
RELEASES="https://github.com/${REPO}/releases/download/${VERSION}"
MAINNET_CONFIG_URL="https://raw.githubusercontent.com/nervosnetwork/fiber/main/config/mainnet/config.yml"
TESTNET_CONFIG_URL="https://raw.githubusercontent.com/nervosnetwork/fiber/main/config/testnet/config.yml"

# ── Colours ────────────────────────────────────────────────
RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

banner() {
  echo -e "${CYAN}"
  echo "  ███████╗██╗██████╗ ███████╗██████╗ "
  echo "  ██╔════╝██║██╔══██╗██╔════╝██╔══██╗"
  echo "  █████╗  ██║██████╔╝█████╗  ██████╔╝"
  echo "  ██╔══╝  ██║██╔══██╗██╔══╝  ██╔══██╗"
  echo "  ██║     ██║██████╔╝███████╗██║  ██║"
  echo "  ╚═╝     ╚═╝╚═════╝ ╚══════╝╚═╝  ╚═╝"
  echo -e "${RESET}"
  echo -e "  ${BOLD}Fiber Network Node Installer${RESET} · ${VERSION}"
  echo -e "  ${CYAN}https://github.com/nervosnetwork/fiber${RESET}"
  echo ""
}

info()    { echo -e "  ${GREEN}✓${RESET}  $*"; }
warn()    { echo -e "  ${YELLOW}⚠${RESET}  $*"; }
error()   { echo -e "  ${RED}✗${RESET}  $*" >&2; exit 1; }
prompt()  { echo -e "  ${CYAN}?${RESET}  $*"; }
section() { echo -e "\n${BOLD}── $* ──────────────────────────────────────────${RESET}"; }

# ── Detect OS / Arch ───────────────────────────────────────
# Evaluate root status once at startup — avoids subshell timing issues
# when script is piped (curl | bash) or run in unusual contexts
IS_ROOT=0
[ "$(id -u)" = "0" ] && IS_ROOT=1

detect_platform() {
  OS=$(uname -s | tr '[:upper:]' '[:lower:]')
  ARCH=$(uname -m)
  BUILD_FROM_SOURCE=0

  case "$OS" in
    linux)
      case "$ARCH" in
        x86_64)  PLATFORM="x86_64-linux-portable" ;;
        aarch64|arm64)
          # No official aarch64 prebuilt — build from source
          PLATFORM="aarch64-linux"
          BUILD_FROM_SOURCE=1
          ;;
        *) error "Unsupported Linux architecture: $ARCH" ;;
      esac
      ;;
    darwin)
      case "$ARCH" in
        x86_64) PLATFORM="x86_64-darwin-portable" ;;
        arm64)  PLATFORM="x86_64-darwin-portable" ;;  # Rosetta fallback
        *) error "Unsupported macOS architecture: $ARCH" ;;
      esac
      ;;
    *) error "Unsupported OS: $OS (Windows users: see install.ps1)" ;;
  esac

  TARBALL="fnn_${VERSION}-${PLATFORM}.tar.gz"
  DOWNLOAD_URL="${RELEASES}/${TARBALL}"
}

# ── Check dependencies ─────────────────────────────────────
check_deps() {
  for cmd in curl tar; do
    command -v "$cmd" &>/dev/null || error "Required command not found: $cmd"
  done
  command -v jq &>/dev/null && HAS_JQ=1 || HAS_JQ=0
}

# ── Interactive config ─────────────────────────────────────
ask() {
  local var="$1" msg="$2" default="$3"
  prompt "${msg}"
  echo -e "     ${YELLOW}[${default}]${RESET} (press Enter to accept)"
  printf "     > " >&2
  read -r input < /dev/tty || true
  printf -v "$var" '%s' "${input:-$default}"
}

ask_choice() {
  local var="$1" msg="$2" opt1="$3" opt2="$4" default="$5"
  prompt "${msg}"
  echo "     1) $opt1"
  echo "     2) $opt2"
  while true; do
    printf "     > " >&2
    read -r choice < /dev/tty || true
    choice="${choice:-$default}"
    case "$choice" in
      1|"$opt1") printf -v "$var" '%s' "$opt1"; break ;;
      2|"$opt2") printf -v "$var" '%s' "$opt2"; break ;;
      *) echo "     Please enter 1 or 2" ;;
    esac
  done
}

ask_choice3() {
  local var="$1" msg="$2" opt1="$3" opt2="$4" opt3="$5" default="$6"
  prompt "${msg}"
  echo "     1) $opt1"
  echo "     2) $opt2"
  echo "     3) $opt3"
  while true; do
    printf "     > " >&2
    read -r choice < /dev/tty || true
    choice="${choice:-$default}"
    case "$choice" in
      1|"$opt1") printf -v "$var" '%s' "$opt1"; break ;;
      2|"$opt2") printf -v "$var" '%s' "$opt2"; break ;;
      3|"$opt3") printf -v "$var" '%s' "$opt3"; break ;;
      *) echo "     Please enter 1, 2 or 3" ;;
    esac
  done
}

collect_config() {
  section "Network"
  echo -e "     Mainnet uses real CKB. Testnet is a sandbox with no real value — good for testing."
  echo -e "     If you're just getting started, mainnet is fine. Testnet CKB is free from a faucet."
  ask_choice3 NETWORK "Which network?" "mainnet" "testnet" "both" "1"

  section "Dashboard"
  echo -e "     A simple web page you can open in any browser to see your node's status —"
  echo -e "     channels, balances, payments, connected peers. Runs on your local network only."
  ask_choice INSTALL_DASH "Install dashboard?" "yes" "no" "1"
  if [ "$INSTALL_DASH" = "yes" ]; then
    ask DASH_PORT "Dashboard port (leave as default unless something else uses 8229)" "8229"
  fi

  section "Installation Directory"
  echo -e "     Where the Fiber program files will be stored. The default is fine for most people."
  if [ "$NETWORK" = "both" ]; then
    ask INSTALL_DIR "Base install directory (mainnet + testnet go in subdirs)" "$HOME/.fiber"
  else
    ask INSTALL_DIR "Where should Fiber be installed?" "$HOME/.fiber-${NETWORK}"
  fi

  section "Data Directory"
  echo -e "     Where Fiber stores its working data — channel state, keys, sync data."
  echo -e "     Needs to be on a drive with at least a few GB free. Default is fine."
  if [ "$NETWORK" = "both" ]; then
    DATA_DIR="${INSTALL_DIR}/data"
    info "Mainnet data: ${INSTALL_DIR}-mainnet/data  |  Testnet data: ${INSTALL_DIR}-testnet/data"
  else
    ask DATA_DIR "Where should Fiber store its data?" "${INSTALL_DIR}/data"
  fi

  section "CKB Node (upstream)"
  echo -e "     Fiber connects TO a CKB full node to read chain state and submit transactions."
  echo -e "     This is NOT Fiber's own RPC — it's the CKB blockchain node Fiber depends on."
  echo -e "     Public mainnet endpoint: ${CYAN}https://mainnet.ckb.dev/rpc${RESET}"
  echo -e "     Public testnet endpoint: ${CYAN}https://testnet.ckb.dev/rpc${RESET}"
  echo -e "     If you run your own CKB node on LAN, use its IP (e.g. http://192.168.x.x:8114)"
  if [ "$NETWORK" = "mainnet" ]; then
    ask CKB_RPC "CKB full node URL (Fiber connects TO this)" "https://mainnet.ckb.dev/rpc"
  elif [ "$NETWORK" = "testnet" ]; then
    ask CKB_RPC "CKB full node URL (Fiber connects TO this)" "https://testnet.ckb.dev/rpc"
  else
    ask MAINNET_CKB_RPC "Mainnet CKB full node URL (Fiber connects TO this)" "https://mainnet.ckb.dev/rpc"
    ask TESTNET_CKB_RPC "Testnet CKB full node URL (Fiber connects TO this)" "https://testnet.ckb.dev/rpc"
  fi

  section "P2P Port"
  echo -e "     The port other Fiber nodes use to find and connect to yours — like a door number."
  echo -e "     Default (8228) is fine. If you're behind a home router, you may need to forward"
  echo -e "     this port in your router settings to be reachable from the wider network."
  echo -e "     ${YELLOW}Don't worry if you skip that — your node still works, it just can't accept"
  echo -e "     inbound connections. You can still open channels and send/receive payments.${RESET}"
  if [ "$NETWORK" = "both" ]; then
    ask MAINNET_P2P_PORT "Mainnet P2P port" "8228"
    ask TESTNET_P2P_PORT "Testnet P2P port" "8238"
  else
    ask P2P_PORT "Fiber P2P port" "8228"
  fi

  section "Public IP (optional)"
  echo -e "     If your machine has a fixed public IP address, enter it here so other nodes"
  echo -e "     can find you directly. Most home users: leave blank (your IP changes anyway)."
  echo -e "     VPS / server users with a static IP: enter it."
  printf "     > " >&2
  read -r PUBLIC_IP < /dev/tty || PUBLIC_IP=""

  section "Fiber RPC Port (your control port)"
  echo -e "     Once Fiber is running, this is how YOU talk to it — to open channels,"
  echo -e "     check balances, send payments, and so on. The dashboard uses this too."
  echo -e "     It listens on 127.0.0.1 (this machine only) by default — that's correct."
  echo -e "     ${YELLOW}Do not change 127.0.0.1 to 0.0.0.0 — that would expose your node controls"
  echo -e "     to your whole network (or the internet if port forwarded).${RESET}"
  if [ "$NETWORK" = "both" ]; then
    ask MAINNET_RPC_PORT "Mainnet Fiber control port" "127.0.0.1:8227"
    ask TESTNET_RPC_PORT "Testnet Fiber control port" "127.0.0.1:8226"
  else
    ask RPC_PORT "Fiber control port" "127.0.0.1:8227"
  fi

  section "Wallet"
  echo -e "     Fiber needs its own CKB wallet to open and close payment channels on-chain."
  echo -e "     We'll generate a fresh private key now and save it securely on this machine."
  echo -e "     After install, you'll need to send some CKB to this wallet's address to fund it."
  echo ""
}

# ── Download binary ────────────────────────────────────────
download_binary() {
  if [ "$BUILD_FROM_SOURCE" = "1" ]; then
    build_from_source
    return
  fi

  section "Downloading Fiber ${VERSION}"
  info "Platform: ${PLATFORM}"
  info "URL: ${DOWNLOAD_URL}"

  TMPDIR=$(mktemp -d)
  trap 'rm -rf "$TMPDIR"' EXIT

  curl -L --progress-bar "${DOWNLOAD_URL}" -o "${TMPDIR}/${TARBALL}"
  tar -xzf "${TMPDIR}/${TARBALL}" -C "${TMPDIR}"

  mkdir -p "${INSTALL_DIR}/bin"
  BIN=$(find "$TMPDIR" -name "fnn" -type f | head -1)
  [ -z "$BIN" ] && error "Could not find fnn binary in archive"
  cp "$BIN" "${INSTALL_DIR}/bin/fnn"
  chmod +x "${INSTALL_DIR}/bin/fnn"
  info "Binary installed: ${INSTALL_DIR}/bin/fnn"
}

build_from_source() {
  section "Building Fiber from source (aarch64 — no prebuilt available)"
  warn "This will take 15-30 minutes on ARM hardware. Please be patient."

  # Check for Rust
  if ! command -v cargo &>/dev/null; then
    info "Rust not found — installing via rustup..."
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable
    # shellcheck disable=SC1091
    . "$HOME/.cargo/env"
  fi

  # Check for build deps (libclang required by ckb-librocksdb-sys bindgen)
  if command -v apt-get &>/dev/null; then
    info "Installing build dependencies..."
    sudo apt-get install -y build-essential pkg-config git clang libclang-dev 2>/dev/null || true
  elif command -v yum &>/dev/null; then
    sudo yum install -y gcc gcc-c++ make pkgconfig git clang clang-devel 2>/dev/null || true
  elif command -v pacman &>/dev/null; then
    sudo pacman -Sy --noconfirm base-devel git clang 2>/dev/null || true
  fi

  # Use a persistent build dir so re-runs can resume from where cargo left off
  BUILDDIR="$HOME/.fiber-build-cache"
  mkdir -p "$BUILDDIR"

  # If binary already exists and is the right version, skip compile entirely
  CACHED_BIN="$BUILDDIR/fiber/target/release/fnn"
  if [ -f "$CACHED_BIN" ]; then
    CACHED_VER=$("$CACHED_BIN" --version 2>/dev/null | grep -o 'v[0-9]\+\.[0-9]\+\.[0-9]\+' | head -1 || echo "unknown")
    if [ "$CACHED_VER" = "$VERSION" ]; then
      info "Using cached binary ($VERSION) — skipping compile"
      mkdir -p "${INSTALL_DIR}/bin"
      cp "$CACHED_BIN" "${INSTALL_DIR}/bin/fnn"
      chmod +x "${INSTALL_DIR}/bin/fnn"
      info "Binary installed from cache: ${INSTALL_DIR}/bin/fnn"
      return 0
    else
      warn "Cached binary is $CACHED_VER, need $VERSION — rebuilding"
    fi
  fi

  # Clone if not already present, otherwise fetch + checkout
  if [ -d "$BUILDDIR/fiber/.git" ]; then
    info "Resuming previous build in $BUILDDIR/fiber ..."
    cd "$BUILDDIR/fiber"
    git fetch --depth 1 origin "refs/tags/${VERSION}" 2>&1 | tail -1 || true
    git checkout "${VERSION}" 2>&1 | tail -1 || true
  else
    info "Cloning fiber ${VERSION}..."
    git clone --depth 1 --branch "${VERSION}" https://github.com/nervosnetwork/fiber.git "$BUILDDIR/fiber" 2>&1 | tail -3
    cd "$BUILDDIR/fiber"
  fi

  info "Building (this takes a while — build cache at $BUILDDIR)..."
  # cargo incremental build: picks up where it left off if interrupted
  cargo build --release 2>&1 &
  CARGO_PID=$!
  SPIN='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
  i=0
  while kill -0 $CARGO_PID 2>/dev/null; do
    printf "\r  %s  Compiling fiber... (this takes 15-30 min on ARM)" "${SPIN:$((i % ${#SPIN})):1}"
    sleep 0.2
    i=$((i+1))
  done
  wait $CARGO_PID
  BUILD_EXIT=$?
  printf "\r  ✓  Compile finished%30s\n" ""
  [ $BUILD_EXIT -ne 0 ] && error "Build failed — check Rust/gcc/clang versions and retry. Cache preserved at $BUILDDIR"
  cd - >/dev/null

  BIN="$BUILDDIR/fiber/target/release/fnn"
  [ -f "$BIN" ] || error "Build failed — fnn binary not found at $BIN"

  mkdir -p "${INSTALL_DIR}/bin"
  cp "$BIN" "${INSTALL_DIR}/bin/fnn"
  chmod +x "${INSTALL_DIR}/bin/fnn"
  info "Binary built and installed: ${INSTALL_DIR}/bin/fnn"
}

# ── Generate key ───────────────────────────────────────────
generate_key() {
  section "Wallet Setup"
  KEY_FILE="${DATA_DIR}/key"
  mkdir -p "${DATA_DIR}"

  if [ -f "${KEY_FILE}" ]; then
    warn "Key file already exists at ${KEY_FILE} — skipping generation"
  else
    # Generate 32 random bytes as hex private key
    KEY_HEX=$(od -A n -t x1 -N 32 /dev/urandom | tr -d ' \n')
    echo "0x${KEY_HEX}" > "${KEY_FILE}"
    chmod 600 "${KEY_FILE}"
    info "Private key generated: ${KEY_FILE}"
  fi
}

# ── Write config ───────────────────────────────────────────
write_config() {
  section "Writing Configuration"
  CONFIG_FILE="${DATA_DIR}/config.yml"

  # Pull base config from official repo (|| true so set -e doesn't kill us if fetch fails)
  BASE_CONFIG=""
  if [ "$NETWORK" = "mainnet" ]; then
    BASE_CONFIG=$(curl -sSL "${MAINNET_CONFIG_URL}" 2>/dev/null) || true
  else
    BASE_CONFIG=$(curl -sSL "${TESTNET_CONFIG_URL}" 2>/dev/null) || true
  fi
  if [ -z "$BASE_CONFIG" ]; then
    warn "Could not fetch upstream config — using minimal defaults (bootnodes may be missing)"
  fi

  # Pre-compute heredoc fragments (grep non-match = exit 1 under set -e inside heredoc)
  BOOTNODE_LINES=$(echo "$BASE_CONFIG" | grep -A20 'bootnode_addrs:' | grep '^\s*-' | head -4 || true)
  SCRIPTS_BLOCK=$(echo "$BASE_CONFIG" | grep -A60 '^  scripts:' | head -61 || true)
  UDT_BLOCK=$(echo "$BASE_CONFIG" | grep -A40 'udt_whitelist:' | head -41 || true)
  ANNOUNCE_ADDR=$([ -n "${PUBLIC_IP:-}" ] && echo "true" || echo "false")
  ANNOUNCED_BLOCK=$([ -n "${ANNOUNCED:-}" ] && printf "  announced_addrs:\n%s\n" "${ANNOUNCED}" || echo "  announced_addrs: []")

  cat > "${CONFIG_FILE}" << YAML
# Generated by Fiber Node Installer
# Edit this file to customise your node

fiber:
  listening_addr: "/ip4/0.0.0.0/tcp/${P2P_PORT}"
  bootnode_addrs:
${BOOTNODE_LINES}
  announce_listening_addr: ${ANNOUNCE_ADDR}
${ANNOUNCED_BLOCK}
  chain: ${NETWORK}
${SCRIPTS_BLOCK}

rpc:
  listening_addr: "${RPC_PORT}"

ckb:
  rpc_url: "${CKB_RPC}"
${UDT_BLOCK}

store:
  path: "${DATA_DIR}/store"

fiber:
  private_key_path: "${KEY_FILE}"

services:
  - fiber
  - rpc
  - ckb
YAML

  info "Config written: ${CONFIG_FILE}"
}

# ── Install service ────────────────────────────────────────
install_service() {
  section "System Service"

  if [ "$OS" = "linux" ]; then
    if command -v systemctl &>/dev/null; then
      # If running as root, install as a system service; otherwise user service
      if [ "$IS_ROOT" = "1" ]; then
        SERVICE_FILE="/etc/systemd/system/fiber.service"
        SYSTEMCTL="systemctl"
        SERVICE_USER="root"
        # Remove any conflicting user-level service from a previous non-root install
        USER_SVC="$HOME/.config/systemd/user/fiber.service"
        if [ -f "$USER_SVC" ]; then
          warn "Removing conflicting user-level fiber.service (was installed as non-root earlier)"
          systemctl --user stop fiber 2>/dev/null || true
          systemctl --user disable fiber 2>/dev/null || true
          rm -f "$USER_SVC" "$HOME/.config/systemd/user/default.target.wants/fiber.service"
          systemctl --user daemon-reload 2>/dev/null || true
        fi
      else
        SERVICE_FILE="$HOME/.config/systemd/user/fiber.service"
        SYSTEMCTL="systemctl --user"
        SERVICE_USER=""
      fi
      # Derive key password — use existing env var or generate a stable one
      FNN_KEY_PASSWORD="${FIBER_SECRET_KEY_PASSWORD:-$(hostname)-fiber-$(date +%Y)}"
      mkdir -p "$(dirname "$SERVICE_FILE")"
      cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Fiber Network Node
After=network-online.target
Wants=network-online.target

[Service]
Environment=FIBER_SECRET_KEY_PASSWORD=${FNN_KEY_PASSWORD}
ExecStart=${INSTALL_DIR}/bin/fnn --config ${DATA_DIR}/config.yml --dir ${INSTALL_DIR}
Restart=on-failure
RestartSec=10
KillSignal=SIGTERM
TimeoutStopSec=30
LimitNOFILE=65535
${SERVICE_USER:+User=$SERVICE_USER}

[Install]
WantedBy=$([ "$IS_ROOT" = "1" ] && echo "multi-user.target" || echo "default.target")
EOF
      # Also write the key to the expected ckb subdir
      mkdir -p "${INSTALL_DIR}/ckb"
      if [ -f "${DATA_DIR}/key" ] && [ ! -f "${INSTALL_DIR}/ckb/key" ]; then
        # Strip 0x prefix if present (fnn hex::decode needs raw hex)
        sed 's/^0x//' "${DATA_DIR}/key" > "${INSTALL_DIR}/ckb/key"
        chmod 600 "${INSTALL_DIR}/ckb/key"
      fi
      $SYSTEMCTL daemon-reload 2>/dev/null || true
      $SYSTEMCTL enable fiber 2>/dev/null || true
      info "Systemd service installed: ${SERVICE_FILE}"
      info "Start: ${SYSTEMCTL} start fiber"
      info "Logs:  journalctl -u fiber -f"
    else
      warn "systemd not available — manual start required:"
      warn "  ${INSTALL_DIR}/bin/fnn --config ${DATA_DIR}/config.yml"
    fi

  elif [ "$OS" = "darwin" ]; then
    PLIST="$HOME/Library/LaunchAgents/xyz.wyltek.fiber.plist"
    FNN_KEY_PASSWORD="${FIBER_SECRET_KEY_PASSWORD:-$(hostname)-fiber-$(date +%Y)}"
    cat > "$PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>xyz.wyltek.fiber</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>FIBER_SECRET_KEY_PASSWORD</key>
    <string>${FNN_KEY_PASSWORD}</string>
  </dict>
  <key>ProgramArguments</key>
  <array>
    <string>${INSTALL_DIR}/bin/fnn</string>
    <string>--config</string>
    <string>${DATA_DIR}/config.yml</string>
    <string>--dir</string>
    <string>${INSTALL_DIR}</string>
  </array>
  <key>RunAtLoad</key>
  <false/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardErrorPath</key>
  <string>${DATA_DIR}/fiber.log</string>
  <key>StandardOutPath</key>
  <string>${DATA_DIR}/fiber.log</string>
</dict>
</plist>
EOF
    # Copy key to ckb subdir like Linux installer does
    mkdir -p "${INSTALL_DIR}/ckb"
    if [ -f "${DATA_DIR}/key" ] && [ ! -f "${INSTALL_DIR}/ckb/key" ]; then
      sed 's/^0x//' "${DATA_DIR}/key" > "${INSTALL_DIR}/ckb/key"
      chmod 600 "${INSTALL_DIR}/ckb/key"
    fi
    launchctl load "$PLIST" 2>/dev/null || true
    info "launchd service installed: ${PLIST}"
    info "Start: launchctl start xyz.wyltek.fiber"
    info "Logs:  tail -f ${DATA_DIR}/fiber.log"
  fi
}

# ── Add to PATH ────────────────────────────────────────────
install_dashboard() {
  [ "${INSTALL_DASH:-no}" = "no" ] && return
  section "Installing Dashboard"

  DASH_DIR="${INSTALL_DIR}/dashboard"
  mkdir -p "$DASH_DIR"
  curl -sSL "https://raw.githubusercontent.com/toastmanAu/fiber-installer/master/dashboard/fiber-dash.py" \
    -o "${DASH_DIR}/fiber-dash.py"
  chmod +x "${DASH_DIR}/fiber-dash.py"
  info "Dashboard installed: ${DASH_DIR}/fiber-dash.py"

  if [ "$OS" = "linux" ] && command -v systemctl &>/dev/null; then
    if [ "$IS_ROOT" = "1" ]; then
      DASH_SERVICE="/etc/systemd/system/fiber-dash.service"
      SYSTEMCTL_DASH="systemctl"
    else
      DASH_SERVICE="$HOME/.config/systemd/user/fiber-dash.service"
      SYSTEMCTL_DASH="systemctl --user"
    fi
    mkdir -p "$(dirname "$DASH_SERVICE")"
    BISCUIT_TOKEN=""
    if [ -f "${DATA_DIR}/secret_key" ]; then
      BISCUIT_TOKEN=$(cat "${DATA_DIR}/secret_key" 2>/dev/null || true)
    fi
    BISCUIT_FLAG=""
    if [ -n "$BISCUIT_TOKEN" ]; then
      BISCUIT_FLAG="  --biscuit ${BISCUIT_TOKEN} \\"$'\n'
    fi
    cat > "$DASH_SERVICE" << EOF
[Unit]
Description=Fiber Node Dashboard (${NETWORK})
After=network.target fiber.service
Wants=fiber.service

[Service]
ExecStartPre=/bin/sh -c 'for i in \$(seq 1 15); do python3 -c "import socket; s=socket.socket(); s.connect((\"127.0.0.1\", ${RPC_PORT:-8227})); s.close()" 2>/dev/null && break || sleep 2; done'
ExecStart=$(command -v python3) ${DASH_DIR}/fiber-dash.py \
  --fiber-rpc ${FIBER_RPC:-http://127.0.0.1:8227} \
  --ckb-rpc ${CKB_RPC:-https://mainnet.ckb.dev/rpc} \
  --port ${DASH_PORT:-8229} \
  --control \
  --data-dir ${DATA_DIR} \
  --fnn-bin ${INSTALL_DIR}/bin/fnn \
  --network ${NETWORK:-mainnet} \
${BISCUIT_FLAG}Restart=on-failure
RestartSec=5
StartLimitBurst=10
StartLimitIntervalSec=60

[Install]
WantedBy=$([ "$IS_ROOT" = "1" ] && echo "multi-user.target" || echo "default.target")
EOF
    $SYSTEMCTL_DASH daemon-reload 2>/dev/null || true
    $SYSTEMCTL_DASH enable fiber-dash 2>/dev/null || true
    info "Dashboard service installed: ${DASH_SERVICE}"
    info "Start: ${SYSTEMCTL_DASH} start fiber-dash"

  elif [ "$OS" = "darwin" ]; then
    DASH_PLIST="$HOME/Library/LaunchAgents/xyz.wyltek.fiber-dash.plist"
    FIBER_RPC_ADDR="${RPC_PORT:-127.0.0.1:8227}"
    cat > "$DASH_PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>xyz.wyltek.fiber-dash</string>
  <key>ProgramArguments</key>
  <array>
    <string>$(command -v python3)</string>
    <string>${DASH_DIR}/fiber-dash.py</string>
    <string>--fiber-rpc</string><string>http://${FIBER_RPC_ADDR}</string>
    <string>--ckb-rpc</string><string>${CKB_RPC:-https://mainnet.ckb.dev/rpc}</string>
    <string>--port</string><string>${DASH_PORT:-8229}</string>
    <string>--control</string>
    <string>--data-dir</string><string>${DATA_DIR}</string>
    <string>--fnn-bin</string><string>${INSTALL_DIR}/bin/fnn</string>
    <string>--network</string><string>${NETWORK:-mainnet}</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardErrorPath</key><string>${DATA_DIR}/fiber-dash.log</string>
  <key>StandardOutPath</key><string>${DATA_DIR}/fiber-dash.log</string>
</dict>
</plist>
EOF
    # Don't auto-load yet — offer happens after smoke test
    info "Dashboard launchd agent written: ${DASH_PLIST}"
    info "Logs: tail -f ${DATA_DIR}/fiber-dash.log"
  fi
}

add_to_path() {
  local shell_rc=""
  case "$SHELL" in
    */zsh)  shell_rc="$HOME/.zshrc" ;;
    */bash) shell_rc="$HOME/.bashrc" ;;
    *)      shell_rc="$HOME/.profile" ;;
  esac

  if ! grep -q "fiber/bin" "$shell_rc" 2>/dev/null; then
    echo "" >> "$shell_rc"
    echo "# Fiber Network Node" >> "$shell_rc"
    echo "export PATH=\"\$PATH:${INSTALL_DIR}/bin\"" >> "$shell_rc"
    info "Added ${INSTALL_DIR}/bin to PATH in ${shell_rc}"
  fi
}

# ── Show wallet address ────────────────────────────────────
show_wallet() {
  section "Your Fiber Wallet"
  echo ""
  echo -e "  ${BOLD}Private key:${RESET} ${KEY_FILE}"
  echo ""
  echo -e "  ${YELLOW}⚠  BACK UP YOUR KEY FILE. If you lose it, you lose access to your channels.${RESET}"
  echo -e "     Copy it somewhere safe — an encrypted USB drive, password manager, etc."
  echo ""
  echo -e "  To get your CKB address, run:"
  echo -e "  ${CYAN}  ${INSTALL_DIR}/bin/fnn --config ${DATA_DIR}/config.yml local-node-info${RESET}"
  echo ""
  echo -e "  ${BOLD}Send at least 162 CKB to that address${RESET} before starting your node."
  echo -e "  This covers the on-chain cost of opening your first payment channel."
  echo -e "  More CKB in the wallet = larger channels you can open with other nodes."
  echo ""
}

# ── Summary ────────────────────────────────────────────────
verify_install() {
  section "Verifying Installation"
  local ok=1

  # 1. Binary exists and runs
  if [ -f "${INSTALL_DIR}/bin/fnn" ]; then
    BIN_VER=$("${INSTALL_DIR}/bin/fnn" --version 2>/dev/null | head -1 || echo "unknown")
    info "Binary: ${BIN_VER}"
  else
    warn "Binary not found at ${INSTALL_DIR}/bin/fnn"; ok=0
  fi

  # 2. Config file exists and has required keys
  if [ -f "${DATA_DIR}/config.yml" ]; then
    if grep -q "listening_addr" "${DATA_DIR}/config.yml" && grep -q "rpc_url" "${DATA_DIR}/config.yml"; then
      info "Config: OK"
    else
      warn "Config exists but may be incomplete"; ok=0
    fi
  else
    warn "Config not found at ${DATA_DIR}/config.yml"; ok=0
  fi

  # 3. Key file exists with correct permissions
  if [ -f "${DATA_DIR}/key" ]; then
    PERMS=$(stat -c "%a" "${DATA_DIR}/key" 2>/dev/null || stat -f "%A" "${DATA_DIR}/key" 2>/dev/null)
    if [ "$PERMS" = "600" ]; then
      info "Key file: OK (600)"
    else
      warn "Key file permissions are $PERMS — should be 600"
      chmod 600 "${DATA_DIR}/key"
      info "Key file: permissions fixed → 600"
    fi
  else
    warn "Key file not found at ${DATA_DIR}/key"; ok=0
  fi

  # 4. Service registered (Linux systemd only)
  if [ "$OS" = "linux" ] && command -v systemctl &>/dev/null; then
    _SC=$([ "$IS_ROOT" = "1" ] && echo "systemctl" || echo "systemctl --user")
    if $_SC cat fiber.service &>/dev/null 2>&1; then
      info "Systemd service: registered"
    else
      warn "Systemd service not found — you may need to run: ${_SC} daemon-reload"
    fi
  fi

  if [ "$ok" = "1" ]; then
    echo -e "\n  ${GREEN}${BOLD}✓ Verification passed${RESET}"
  else
    echo -e "\n  ${YELLOW}${BOLD}⚠ Verification completed with warnings — review above${RESET}"
  fi

  # ── Smoke test: start node, check RPC responds, shut it back down ──
  section "Smoke Test"
  echo -e "     Starting Fiber briefly to verify it can connect to CKB RPC..."
  echo -e "     ${YELLOW}(node will be stopped automatically after the test)${RESET}"
  echo ""

  SMOKE_PASS=0
  SMOKE_PID=""

  # Start the node directly (not via systemd) so we control it
  "${INSTALL_DIR}/bin/fnn" --config "${DATA_DIR}/config.yml" > /tmp/fiber-smoke.log 2>&1 &
  SMOKE_PID=$!

  # Wait up to 15s for the RPC to respond
  RPC_ADDR="${RPC_PORT:-127.0.0.1:8227}"
  RPC_HOST=$(echo "$RPC_ADDR" | cut -d: -f1)
  RPC_PORT_NUM=$(echo "$RPC_ADDR" | cut -d: -f2)
  WAITED=0
  printf "     Waiting for RPC on %s" "$RPC_ADDR"
  while [ $WAITED -lt 15 ]; do
    if curl -sf -X POST "http://${RPC_ADDR}" \
        -H "Content-Type: application/json" \
        -d '{"jsonrpc":"2.0","method":"get_node_info","params":[],"id":1}' \
        -o /tmp/fiber-smoke-rpc.json 2>/dev/null; then
      echo ""
      NODE_ID=$(python3 -c "import json,sys; d=json.load(open('/tmp/fiber-smoke-rpc.json')); print(d['result']['node_id'][:20]+'...')" 2>/dev/null || echo "unknown")
      info "RPC responded — node_id: ${NODE_ID}"
      SMOKE_PASS=1
      break
    fi
    printf "."
    sleep 1
    WAITED=$((WAITED + 1))
  done

  if [ $SMOKE_PASS -eq 0 ]; then
    echo ""
    # Check if process died
    if ! kill -0 "$SMOKE_PID" 2>/dev/null; then
      warn "Node process exited during smoke test — check logs:"
      tail -10 /tmp/fiber-smoke.log | sed 's/^/     /'
    else
      warn "RPC did not respond within 15s — node may still be initialising"
      if [ "$OS" = "linux" ] && command -v systemctl &>/dev/null; then
        _SC=$([ "$IS_ROOT" = "1" ] && echo "systemctl" || echo "systemctl --user")
        warn "This is normal on first boot. Check logs: journalctl -u fiber -f"
      elif [ "$OS" = "darwin" ]; then
        warn "This is normal on first boot. Check logs: tail -f ${DATA_DIR}/fiber.log"
      fi
    fi
  fi

  # Always shut down the smoke test process
  if kill -0 "$SMOKE_PID" 2>/dev/null; then
    kill "$SMOKE_PID" 2>/dev/null
    sleep 1
    kill -9 "$SMOKE_PID" 2>/dev/null || true
    info "Smoke test node stopped"
  fi
  rm -f /tmp/fiber-smoke-rpc.json

  if [ $SMOKE_PASS -eq 1 ]; then
    echo -e "\n  ${GREEN}${BOLD}✓ Smoke test passed — node starts and RPC is reachable${RESET}"
  else
    echo -e "\n  ${YELLOW}${BOLD}⚠ Smoke test inconclusive — see warnings above${RESET}"
    echo -e "     This does not mean the install failed. Start manually and check logs."
  fi

  # ── Offer to start Fiber node now ──────────────────────────────────
  if [ "$OS" = "linux" ] && command -v systemctl &>/dev/null; then
    _SC=$([ "$IS_ROOT" = "1" ] && echo "systemctl" || echo "systemctl --user")
    echo ""
    printf "  Start the Fiber node now? [Y/n] " >&2
    read -r start_fiber < /dev/tty || start_fiber="y"
    start_fiber="${start_fiber:-y}"
    case "$start_fiber" in
      [Yy]*|"")
        $_SC start fiber 2>/dev/null && info "Fiber node started" || warn "Could not start — check: $_SC status fiber"
        ;;
      *)
        info "Skipped — start manually with: ${_SC} start fiber"
        ;;
    esac

    if [ "${INSTALL_DASH:-no}" = "yes" ]; then
      echo ""
      printf "  Start the dashboard now? [Y/n] " >&2
      read -r start_dash < /dev/tty || start_dash="y"
      start_dash="${start_dash:-y}"
      case "$start_dash" in
        [Yy]*|"")
          $_SC start fiber-dash 2>/dev/null && info "Dashboard started" || warn "Could not start — check: $_SC status fiber-dash"
          local_ip=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "YOUR-IP")
          echo -e "  ${GREEN}${BOLD}→ Dashboard: http://${local_ip}:${DASH_PORT:-8229}${RESET}"
          ;;
        *)
          info "Skipped — start manually with: ${_SC} start fiber-dash"
          ;;
      esac
    fi
  elif [ "$OS" = "darwin" ]; then
    echo ""
    printf "  Start the Fiber node now? [Y/n] " >&2
    read -r start_fiber < /dev/tty || start_fiber="y"
    start_fiber="${start_fiber:-y}"
    case "$start_fiber" in
      [Yy]*|"")
        launchctl load "$HOME/Library/LaunchAgents/xyz.wyltek.fiber.plist" 2>/dev/null || true
        launchctl start xyz.wyltek.fiber 2>/dev/null || true
        info "Fiber node started — logs: tail -f ${DATA_DIR}/fiber.log"
        ;;
      *)
        info "Skipped — start manually with: launchctl start xyz.wyltek.fiber"
        ;;
    esac

    if [ "${INSTALL_DASH:-no}" = "yes" ]; then
      echo ""
      printf "  Start the dashboard now? [Y/n] " >&2
      read -r start_dash < /dev/tty || start_dash="y"
      start_dash="${start_dash:-y}"
      case "$start_dash" in
        [Yy]*|"")
          launchctl load "$HOME/Library/LaunchAgents/xyz.wyltek.fiber-dash.plist" 2>/dev/null || true
          launchctl start xyz.wyltek.fiber-dash 2>/dev/null || true
          local_ip=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "YOUR-IP")
          echo -e "  ${GREEN}${BOLD}→ Dashboard: http://${local_ip}:${DASH_PORT:-8229}${RESET}"
          ;;
        *)
          info "Skipped — start manually with: launchctl start xyz.wyltek.fiber-dash"
          ;;
      esac
    fi
  fi

  # 5. Clean up build cache — AFTER smoke test so we know binary works
  if [ "$BUILD_FROM_SOURCE" = "1" ] && [ "$ok" = "1" ]; then
    BUILD_CACHE="$HOME/.fiber-build-cache"
    if [ -d "$BUILD_CACHE" ]; then
      CACHE_SIZE=$(du -sh "$BUILD_CACHE" 2>/dev/null | cut -f1)
      echo ""
      printf "  Clean up build cache (~%s at %s)? [Y/n] " "$CACHE_SIZE" "$BUILD_CACHE" >&2
      read -r clean_cache < /dev/tty || clean_cache="y"
      clean_cache="${clean_cache:-y}"
      case "$clean_cache" in
        [Yy]*|"")
          rm -rf "$BUILD_CACHE"
          info "Build cache removed (${CACHE_SIZE} freed)"
          ;;
        *)
          info "Build cache kept at ${BUILD_CACHE} (re-runs will be faster)"
          ;;
      esac
    fi
  fi
}

summary() {
  echo ""
  echo -e "  ${GREEN}${BOLD}✓ Fiber ${VERSION} is installed!${RESET}"
  echo ""
  echo -e "  ${BOLD}What was installed:${RESET}"
  echo -e "    Program:  ${CYAN}${INSTALL_DIR}/bin/fnn${RESET}"
  echo -e "    Config:   ${CYAN}${DATA_DIR}/config.yml${RESET}  ← edit this to change settings"
  echo -e "    Network:  ${CYAN}${NETWORK}${RESET}"
  echo -e "    P2P port: ${CYAN}${P2P_PORT}${RESET}  ← other Fiber nodes connect here"
  echo -e "    CKB node: ${CYAN}${CKB_RPC}${RESET}  ← the CKB chain Fiber reads from"
  echo ""
  echo -e "  ${BOLD}Next steps:${RESET}"
  echo -e "    1. Get your wallet address (see above) and send it at least 162 CKB"
  echo -e "    2. Start your node:"
  if [ "$OS" = "linux" ] && command -v systemctl &>/dev/null; then
    _SC=$([ "$IS_ROOT" = "1" ] && echo "systemctl" || echo "systemctl --user")
    _JC=$([ "$IS_ROOT" = "1" ] && echo "journalctl" || echo "journalctl --user")
    echo -e "       ${CYAN}${_SC} start fiber${RESET}"
    echo -e "    3. Watch it start up:"
    echo -e "       ${CYAN}${_JC} -u fiber -f${RESET}  (Ctrl+C to stop watching)"
  elif [ "$OS" = "darwin" ]; then
    echo -e "       ${CYAN}launchctl start xyz.wyltek.fiber${RESET}"
    echo -e "    3. Watch it start up:"
    echo -e "       ${CYAN}tail -f ${DATA_DIR}/fiber.log${RESET}  (Ctrl+C to stop watching)"
  fi
  echo -e "    4. Open a channel with another Fiber node to start sending payments"
  echo ""
  if [ "${INSTALL_DASH:-no}" = "yes" ]; then
    if [ "$OS" = "darwin" ]; then
      local_ip=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "YOUR-IP")
    else
      local_ip=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "YOUR-IP")
    fi
    echo -e "  ${BOLD}Dashboard:${RESET}   http://${local_ip}:${DASH_PORT:-8229}"
    echo -e "             Open this in any browser on your local network"
    echo ""
  fi
  echo -e "  ${BOLD}Fiber docs:${RESET}  https://github.com/nervosnetwork/fiber"
  echo -e "  ${BOLD}Community:${RESET}   https://t.me/WyltekIndustriesBot"
  echo ""
}

# ── Main ───────────────────────────────────────────────────
install_single() {
  local net="$1"
  NETWORK="$net"

  if [ "$net" = "mainnet" ] && [ "${ORIG_NETWORK:-}" = "both" ]; then
    INSTALL_DIR="${BASE_INSTALL_DIR}-mainnet"
    DATA_DIR="${INSTALL_DIR}/data"
    CKB_RPC="$MAINNET_CKB_RPC"
    P2P_PORT="$MAINNET_P2P_PORT"
    RPC_PORT="$MAINNET_RPC_PORT"
  elif [ "$net" = "testnet" ] && [ "${ORIG_NETWORK:-}" = "both" ]; then
    INSTALL_DIR="${BASE_INSTALL_DIR}-testnet"
    DATA_DIR="${INSTALL_DIR}/data"
    CKB_RPC="$TESTNET_CKB_RPC"
    P2P_PORT="$TESTNET_P2P_PORT"
    RPC_PORT="$TESTNET_RPC_PORT"
  fi

  download_binary
  generate_key
  write_config
  install_service
  install_dashboard
  add_to_path
  verify_install
  show_wallet
  summary
}

main() {
  banner
  check_deps
  detect_platform
  collect_config

  if [ "$NETWORK" = "both" ]; then
    ORIG_NETWORK="both"
    BASE_INSTALL_DIR="$INSTALL_DIR"
    section "Installing Mainnet Node"
    install_single "mainnet"
    section "Installing Testnet Node"
    install_single "testnet"
  else
    install_single "$NETWORK"
  fi
}

main "$@"
