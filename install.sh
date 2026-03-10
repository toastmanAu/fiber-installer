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
  ask_choice3 NETWORK "Which network?" "mainnet" "testnet" "both" "1"

  section "Dashboard"
  echo -e "     Install a local browser dashboard to monitor your node?"
  echo -e "     Accessible from any device on your local network."
  ask_choice INSTALL_DASH "Install dashboard?" "yes" "no" "1"
  if [ "$INSTALL_DASH" = "yes" ]; then
    ask DASH_PORT "Dashboard port" "8229"
  fi

  section "Installation Directory"
  if [ "$NETWORK" = "both" ]; then
    ask INSTALL_DIR "Base install directory (mainnet + testnet go in subdirs)" "$HOME/.fiber"
  else
    ask INSTALL_DIR "Where should Fiber be installed?" "$HOME/.fiber"
  fi

  section "Data Directory"
  if [ "$NETWORK" = "both" ]; then
    DATA_DIR="${INSTALL_DIR}/data"
    info "Mainnet data: ${INSTALL_DIR}-mainnet/data  |  Testnet data: ${INSTALL_DIR}-testnet/data"
  else
    ask DATA_DIR "Where should Fiber store its data?" "${INSTALL_DIR}/data"
  fi

  section "CKB Node"
  echo -e "     Fiber needs a CKB full node RPC to operate."
  echo -e "     Public mainnet RPC: ${CYAN}https://mainnet.ckb.dev/rpc${RESET}"
  echo -e "     Public testnet RPC: ${CYAN}https://testnet.ckb.dev/rpc${RESET}"
  if [ "$NETWORK" = "mainnet" ]; then
    ask CKB_RPC "CKB RPC URL" "http://127.0.0.1:8114/"
  elif [ "$NETWORK" = "testnet" ]; then
    ask CKB_RPC "CKB RPC URL" "https://testnet.ckb.dev/rpc"
  else
    ask MAINNET_CKB_RPC "Mainnet CKB RPC URL" "http://127.0.0.1:8114/"
    ask TESTNET_CKB_RPC "Testnet CKB RPC URL" "https://testnet.ckb.dev/rpc"
  fi

  section "P2P Port"
  echo -e "     This port must be open/forwarded if you want to be publicly reachable."
  if [ "$NETWORK" = "both" ]; then
    ask MAINNET_P2P_PORT "Mainnet P2P port" "8228"
    ask TESTNET_P2P_PORT "Testnet P2P port" "8229"
  else
    ask P2P_PORT "Fiber P2P port" "8228"
  fi

  section "Public IP (optional)"
  echo -e "     If you have a static public IP, enter it to announce your node."
  echo -e "     Leave blank to run as a private node (can still open channels)."
  printf "     > " >&2
  read -r PUBLIC_IP < /dev/tty || PUBLIC_IP=""

  section "RPC Port"
  echo -e "     Local-only by default. Do NOT expose this to the internet."
  if [ "$NETWORK" = "both" ]; then
    ask MAINNET_RPC_PORT "Mainnet RPC listen address" "127.0.0.1:8227"
    ask TESTNET_RPC_PORT "Testnet RPC listen address" "127.0.0.1:8226"
  else
    ask RPC_PORT "Fiber RPC listen address" "127.0.0.1:8227"
  fi

  section "Wallet"
  echo -e "     Fiber needs a CKB private key for its internal wallet."
  echo -e "     We'll generate a fresh key and show you the address to fund."
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

  # Pull base config from official repo
  if [ "$NETWORK" = "mainnet" ]; then
    BASE_CONFIG=$(curl -sSL "${MAINNET_CONFIG_URL}")
  else
    BASE_CONFIG=$(curl -sSL "${TESTNET_CONFIG_URL}")
  fi

  ANNOUNCED=""
  if [ -n "${PUBLIC_IP:-}" ]; then
    ANNOUNCED="    - \"/ip4/${PUBLIC_IP}/tcp/${P2P_PORT}\""
  fi

  cat > "${CONFIG_FILE}" << YAML
# Generated by Fiber Node Installer
# Edit this file to customise your node

fiber:
  listening_addr: "/ip4/0.0.0.0/tcp/${P2P_PORT}"
  bootnode_addrs:
$(echo "$BASE_CONFIG" | grep -A20 'bootnode_addrs:' | grep '^\s*-' | head -4)
  announce_listening_addr: $([ -n "${PUBLIC_IP:-}" ] && echo "true" || echo "false")
$([ -n "${ANNOUNCED:-}" ] && printf "  announced_addrs:\n%s\n" "${ANNOUNCED}" || echo "  announced_addrs: []")
  chain: ${NETWORK}
$(echo "$BASE_CONFIG" | grep -A60 '^  scripts:' | head -61)

rpc:
  listening_addr: "${RPC_PORT}"

ckb:
  rpc_url: "${CKB_RPC}"
$(echo "$BASE_CONFIG" | grep -A40 'udt_whitelist:' | head -41)

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
      SERVICE_FILE="$HOME/.config/systemd/user/fiber.service"
      mkdir -p "$(dirname "$SERVICE_FILE")"
      cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Fiber Network Node
After=network-online.target
Wants=network-online.target

[Service]
ExecStartPre=/bin/sh -c 'pkill -9 fnn || true'
ExecStart=${INSTALL_DIR}/bin/fnn --config ${DATA_DIR}/config.yml
Restart=on-failure
RestartSec=10
LimitNOFILE=65535

[Install]
WantedBy=default.target
EOF
      systemctl --user daemon-reload
      systemctl --user enable fiber
      info "systemd user service installed (fiber.service)"
      info "Start: systemctl --user start fiber"
      info "Logs:  journalctl --user -u fiber -f"
    else
      warn "systemd not available — manual start required:"
      warn "  ${INSTALL_DIR}/bin/fnn --config ${DATA_DIR}/config.yml"
    fi

  elif [ "$OS" = "darwin" ]; then
    PLIST="$HOME/Library/LaunchAgents/xyz.wyltek.fiber.plist"
    cat > "$PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>xyz.wyltek.fiber</string>
  <key>ProgramArguments</key>
  <array>
    <string>${INSTALL_DIR}/bin/fnn</string>
    <string>--config</string>
    <string>${DATA_DIR}/config.yml</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardErrorPath</key>
  <string>${DATA_DIR}/fiber.log</string>
  <key>StandardOutPath</key>
  <string>${DATA_DIR}/fiber.log</string>
</dict>
</plist>
EOF
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
  curl -sSL "https://raw.githubusercontent.com/toastmanAu/fiber-installer/main/dashboard/fiber-dash.py" \
    -o "${DASH_DIR}/fiber-dash.py"
  chmod +x "${DASH_DIR}/fiber-dash.py"
  info "Dashboard installed: ${DASH_DIR}/fiber-dash.py"

  if [ "$OS" = "linux" ] && command -v systemctl &>/dev/null; then
    DASH_SERVICE="$HOME/.config/systemd/user/fiber-dash.service"
    cat > "$DASH_SERVICE" << EOF
[Unit]
Description=Fiber Node Dashboard
After=fiber.service

[Service]
ExecStart=$(command -v python3) ${DASH_DIR}/fiber-dash.py \
  --fiber-rpc ${FIBER_RPC:-http://127.0.0.1:8227} \
  --ckb-rpc ${CKB_RPC:-http://127.0.0.1:8114} \
  --port ${DASH_PORT:-8229}
Restart=on-failure

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable fiber-dash
    info "Dashboard service installed (fiber-dash.service)"
    info "Start: systemctl --user start fiber-dash"

  elif [ "$OS" = "darwin" ]; then
    DASH_PLIST="$HOME/Library/LaunchAgents/xyz.wyltek.fiber-dash.plist"
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
    <string>--port</string><string>${DASH_PORT:-8229}</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict>
</plist>
EOF
    launchctl load "$DASH_PLIST" 2>/dev/null || true
    info "Dashboard launchd agent installed"
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
  echo -e "  ${YELLOW}⚠  BACK UP YOUR KEY FILE. If you lose it, you lose your CKB.${RESET}"
  echo ""
  echo -e "  To get your CKB address, run:"
  echo -e "  ${CYAN}  ${INSTALL_DIR}/bin/fnn --config ${DATA_DIR}/config.yml local-node-info${RESET}"
  echo ""
  echo -e "  ${BOLD}Fund your node wallet with at least 162 CKB${RESET} to auto-accept channels."
  echo -e "  More CKB = more channel capacity you can offer."
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
    if systemctl --user cat fiber.service &>/dev/null 2>&1; then
      info "Systemd service: registered"
    else
      warn "Systemd service not found — you may need to run: systemctl --user daemon-reload"
    fi
  fi

  # 5. Clean up build cache if everything looks good (aarch64 only)
  if [ "$BUILD_FROM_SOURCE" = "1" ] && [ "$ok" = "1" ]; then
    BUILD_CACHE="$HOME/.fiber-build-cache"
    if [ -d "$BUILD_CACHE" ]; then
      CACHE_SIZE=$(du -sh "$BUILD_CACHE" 2>/dev/null | cut -f1)
      printf "     > " >&2
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

  if [ "$ok" = "1" ]; then
    echo -e "\n  ${GREEN}${BOLD}✓ Verification passed${RESET}"
  else
    echo -e "\n  ${YELLOW}${BOLD}⚠ Verification completed with warnings — review above${RESET}"
  fi
}

summary() {
  echo ""
  echo -e "  ${GREEN}${BOLD}Fiber ${VERSION} is installed!${RESET}"
  echo ""
  echo -e "  Install dir:  ${CYAN}${INSTALL_DIR}${RESET}"
  echo -e "  Data dir:     ${CYAN}${DATA_DIR}${RESET}"
  echo -e "  Config:       ${CYAN}${DATA_DIR}/config.yml${RESET}"
  echo -e "  Network:      ${CYAN}${NETWORK}${RESET}"
  echo -e "  P2P port:     ${CYAN}${P2P_PORT}${RESET}"
  echo -e "  CKB RPC:      ${CYAN}${CKB_RPC}${RESET}"
  echo ""

  if [ "$OS" = "linux" ] && command -v systemctl &>/dev/null; then
    echo -e "  ${BOLD}Start your node:${RESET}"
    echo -e "    ${CYAN}systemctl --user start fiber${RESET}"
    echo -e "  ${BOLD}View logs:${RESET}"
    echo -e "    ${CYAN}journalctl --user -u fiber -f${RESET}"
  elif [ "$OS" = "darwin" ]; then
    echo -e "  ${BOLD}Start your node:${RESET}"
    echo -e "    ${CYAN}launchctl start xyz.wyltek.fiber${RESET}"
    echo -e "  ${BOLD}View logs:${RESET}"
    echo -e "    ${CYAN}tail -f ${DATA_DIR}/fiber.log${RESET}"
  fi

  echo ""
  if [ "${INSTALL_DASH:-no}" = "yes" ]; then
    local_ip=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "YOUR-IP")
    echo -e "  ${BOLD}Dashboard:${RESET}   http://${local_ip}:${DASH_PORT:-8229}"
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
