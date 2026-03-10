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

  case "$OS" in
    linux)
      case "$ARCH" in
        x86_64)  PLATFORM="x86_64-linux-portable" ;;
        aarch64|arm64) PLATFORM="aarch64-linux-portable" ;;
        *) error "Unsupported Linux architecture: $ARCH" ;;
      esac
      ;;
    darwin)
      case "$ARCH" in
        x86_64) PLATFORM="x86_64-darwin-portable" ;;
        arm64)  PLATFORM="x86_64-darwin-portable" ;;  # Rosetta fallback; native arm64 not yet in releases
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
  read -r -p "     > " input
  printf -v "$var" '%s' "${input:-$default}"
}

ask_choice() {
  local var="$1" msg="$2" opt1="$3" opt2="$4" default="$5"
  prompt "${msg}"
  echo "     1) $opt1"
  echo "     2) $opt2"
  while true; do
    read -r -p "     > " choice
    choice="${choice:-$default}"
    case "$choice" in
      1|"$opt1") printf -v "$var" '%s' "$opt1"; break ;;
      2|"$opt2") printf -v "$var" '%s' "$opt2"; break ;;
      *) echo "     Please enter 1 or 2" ;;
    esac
  done
}

collect_config() {
  section "Network"
  ask_choice NETWORK "Which network?" "mainnet" "testnet" "1"

  section "Installation Directory"
  ask INSTALL_DIR "Where should Fiber be installed?" "$HOME/.fiber"

  section "Data Directory"
  ask DATA_DIR "Where should Fiber store its data?" "${INSTALL_DIR}/data"

  section "CKB Node"
  echo -e "     Fiber needs a CKB full node RPC to operate."
  echo -e "     Public mainnet RPC: ${CYAN}https://mainnet.ckb.dev/rpc${RESET}"
  echo -e "     Public testnet RPC: ${CYAN}https://testnet.ckb.dev/rpc${RESET}"
  if [ "$NETWORK" = "mainnet" ]; then
    ask CKB_RPC "CKB RPC URL" "http://127.0.0.1:8114/"
  else
    ask CKB_RPC "CKB RPC URL" "https://testnet.ckb.dev/rpc"
  fi

  section "P2P Port"
  echo -e "     This port must be open/forwarded if you want to be publicly reachable."
  ask P2P_PORT "Fiber P2P port" "8228"

  section "Public IP (optional)"
  echo -e "     If you have a static public IP, enter it to announce your node."
  echo -e "     Leave blank to run as a private node (can still open channels)."
  read -r -p "     > " PUBLIC_IP

  section "RPC Port"
  echo -e "     Local-only by default. Do NOT expose this to the internet."
  ask RPC_PORT "Fiber RPC listen address" "127.0.0.1:8227"

  section "Wallet"
  echo -e "     Fiber needs a CKB private key for its internal wallet."
  echo -e "     We'll generate a fresh key and show you the address to fund."
  echo ""
}

# ── Download binary ────────────────────────────────────────
download_binary() {
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
ExecStart=${INSTALL_DIR}/bin/fnn --config-file ${DATA_DIR}/config.yml
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
      warn "  ${INSTALL_DIR}/bin/fnn --config-file ${DATA_DIR}/config.yml"
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
    <string>--config-file</string>
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
  echo -e "  ${CYAN}  ${INSTALL_DIR}/bin/fnn --config-file ${DATA_DIR}/config.yml local-node-info${RESET}"
  echo ""
  echo -e "  ${BOLD}Fund your node wallet with at least 162 CKB${RESET} to auto-accept channels."
  echo -e "  More CKB = more channel capacity you can offer."
  echo ""
}

# ── Summary ────────────────────────────────────────────────
summary() {
  section "Installation Complete"
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
  echo -e "  ${BOLD}Fiber docs:${RESET}  https://github.com/nervosnetwork/fiber"
  echo -e "  ${BOLD}Community:${RESET}   https://t.me/WyltekIndustriesBot"
  echo ""
}

# ── Main ───────────────────────────────────────────────────
main() {
  banner
  check_deps
  detect_platform
  collect_config
  download_binary
  generate_key
  write_config
  install_service
  add_to_path
  show_wallet
  summary
}

main "$@"
