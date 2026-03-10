#!/usr/bin/env python3
"""
Fiber Network Node Dashboard — Interactive Edition
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Zero-dependency dashboard. Monitor + control your Fiber node from any browser
on your local network.

Features:
  • Live channel monitoring (balances, state, liquidity)
  • Wallet address + CKB balance (derived from node info)
  • Open channel — connect to peer and fund a channel
  • Close channel — cooperative shutdown with confirmation
  • Create invoice — generate a payment request
  • Send payment — pay an invoice
  • Connect peer — add a peer without opening a channel

Usage:
    python3 fiber-dash.py [--fiber-rpc URL] [--ckb-rpc URL] [--port 8229] [--biscuit TOKEN]
"""

import argparse, json, sys, socket, urllib.request, urllib.error, hashlib
from http.server import HTTPServer, BaseHTTPRequestHandler

# ── Args ───────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="Fiber Network Dashboard")
parser.add_argument("--fiber-rpc", default="http://127.0.0.1:8227")
parser.add_argument("--ckb-rpc",   default="http://127.0.0.1:8114")
parser.add_argument("--port",      default=8229, type=int)
parser.add_argument("--host",      default="0.0.0.0")
parser.add_argument("--biscuit",   default="")
parser.add_argument("--network",   default="mainnet", choices=["mainnet","testnet","devnet"])
args = parser.parse_args()

FIBER_RPC = args.fiber_rpc
CKB_RPC   = args.ckb_rpc
BISCUIT   = args.biscuit
NETWORK   = args.network

# ── CKB Address derivation ─────────────────────────────────────────────────────
BECH32M_CONST = 0x2bc830a3
CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"

def _polymod(values):
    GEN = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3]
    chk = 1
    for v in values:
        b = chk >> 25
        chk = (chk & 0x1ffffff) << 5 ^ v
        for i in range(5):
            chk ^= GEN[i] if ((b >> i) & 1) else 0
    return chk

def _hrp_expand(hrp):
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]

def _create_checksum(hrp, data):
    values = _hrp_expand(hrp) + list(data)
    poly = _polymod(values + [0,0,0,0,0,0]) ^ BECH32M_CONST
    return [(poly >> 5*(5-i)) & 31 for i in range(6)]

def _convertbits(data, frombits, tobits, pad=True):
    acc = bits = 0; ret = []; maxv = (1 << tobits) - 1
    for v in data:
        acc = (acc << frombits) | v; bits += frombits
        while bits >= tobits:
            bits -= tobits; ret.append((acc >> bits) & maxv)
    if pad and bits:
        ret.append((acc << (tobits - bits)) & maxv)
    return ret

def lock_to_address(code_hash_hex, hash_type, args_hex, network="mainnet"):
    """Convert a CKB lock script to a bech32m full address."""
    try:
        hrp = {"mainnet":"ckb","testnet":"ckt","devnet":"ckt"}.get(network,"ckb")
        code_hash = bytes.fromhex(code_hash_hex.lstrip("0x"))
        ht_byte   = 0x01 if hash_type == "type" else (0x02 if hash_type == "data1" else 0x00)
        arg_bytes = bytes.fromhex(args_hex.lstrip("0x"))
        payload   = bytes([0x00]) + code_hash + bytes([ht_byte]) + arg_bytes
        data5     = _convertbits(payload, 8, 5)
        checksum  = _create_checksum(hrp, data5)
        return hrp + "1" + "".join(CHARSET[d] for d in data5 + checksum)
    except Exception as e:
        return None

# ── RPC helpers ────────────────────────────────────────────────────────────────
_rpc_id = 0
def rpc_call(url, method, params=None, token=""):
    global _rpc_id
    _rpc_id += 1
    body = json.dumps({"id":_rpc_id,"jsonrpc":"2.0","method":method,"params":params or [{}]}).encode()
    headers = {"Content-Type":"application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error":{"message":str(e)}}

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

/* Header */
header{background:var(--surface);border-bottom:1px solid var(--border);padding:0 1.5rem;
  display:flex;align-items:center;justify-content:space-between;height:56px;position:sticky;top:0;z-index:100}
.logo{font-size:1.1rem;font-weight:700;color:var(--accent);display:flex;align-items:center;gap:.5rem}
.logo svg{width:22px;height:22px}
.hdr-right{display:flex;align-items:center;gap:.75rem}
.status-badge{display:flex;align-items:center;gap:.4rem;font-size:.8rem;color:var(--muted)}
.dot{width:8px;height:8px;border-radius:50%;background:var(--muted)}
.dot.green{background:var(--green);box-shadow:0 0 6px var(--green);animation:pulse 2s infinite}
.dot.red{background:var(--red)}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}

/* Buttons */
.btn{display:inline-flex;align-items:center;gap:.3rem;padding:.4rem .9rem;border-radius:7px;
  font-size:.82rem;font-weight:500;cursor:pointer;border:none;transition:all .15s}
.btn-ghost{background:none;border:1px solid var(--border);color:var(--muted)}
.btn-ghost:hover{border-color:var(--accent);color:var(--accent)}
.btn-primary{background:var(--accent);color:#000}
.btn-primary:hover{background:#33d4ff}
.btn-danger{background:rgba(239,68,68,.15);color:var(--red);border:1px solid rgba(239,68,68,.3)}
.btn-danger:hover{background:rgba(239,68,68,.25)}
.btn-success{background:rgba(34,197,94,.15);color:var(--green);border:1px solid rgba(34,197,94,.3)}
.btn-success:hover{background:rgba(34,197,94,.25)}
.btn-sm{padding:.25rem .6rem;font-size:.75rem}
.btn:disabled{opacity:.4;cursor:not-allowed}

/* Layout */
main{max-width:1280px;margin:0 auto;padding:1.5rem;display:grid;gap:1rem}
.grid-2{display:grid;grid-template-columns:1fr 1fr;gap:1rem}
.grid-3{display:grid;grid-template-columns:repeat(3,1fr);gap:1rem}
.grid-4{display:grid;grid-template-columns:repeat(4,1fr);gap:1rem}
@media(max-width:900px){.grid-2,.grid-3,.grid-4{grid-template-columns:1fr}}

/* Cards */
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;overflow:hidden}
.card-header{padding:.8rem 1.2rem;border-bottom:1px solid var(--border);
  display:flex;align-items:center;justify-content:space-between}
.card-title{font-weight:600;font-size:.82rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
.card-body{padding:1.2rem}

/* Stats */
.stat-value{font-size:1.9rem;font-weight:700;line-height:1}
.stat-value.accent{color:var(--accent)}
.stat-value.green{color:var(--green)}
.stat-value.purple{color:var(--purple)}
.stat-label{font-size:.72rem;color:var(--muted);margin-top:.3rem}

/* Info rows */
.info-row{display:flex;justify-content:space-between;align-items:center;
  padding:.4rem 0;border-bottom:1px solid var(--border);font-size:.82rem}
.info-row:last-child{border-bottom:none}
.info-key{color:var(--muted)}
.info-val{font-family:monospace;font-size:.76rem;max-width:62%;text-align:right;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

/* Table */
.tbl-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:.82rem}
th{text-align:left;padding:.5rem .75rem;color:var(--muted);font-weight:500;
  border-bottom:1px solid var(--border);white-space:nowrap}
td{padding:.6rem .75rem;border-bottom:1px solid var(--border);vertical-align:middle}
tr:last-child td{border-bottom:none}
tr:hover td{background:var(--surface2)}
.mono{font-family:monospace;font-size:.73rem}

/* Pills */
.pill{display:inline-block;padding:.15rem .5rem;border-radius:99px;font-size:.7rem;font-weight:600}
.pill-green{background:rgba(34,197,94,.15);color:var(--green)}
.pill-yellow{background:rgba(245,158,11,.15);color:var(--yellow)}
.pill-red{background:rgba(239,68,68,.15);color:var(--red)}
.pill-blue{background:rgba(0,200,255,.12);color:var(--accent)}
.pill-purple{background:rgba(167,139,250,.12);color:var(--purple)}

/* Liquidity bar */
.liq-wrap{display:flex;align-items:center;gap:.5rem;min-width:120px}
.liq-bar{flex:1;height:6px;border-radius:3px;background:var(--surface2);overflow:hidden}
.liq-local{height:100%;border-radius:3px 0 0 3px;background:var(--accent)}
.liq-remote{height:100%;border-radius:0 3px 3px 0;background:var(--purple)}
.liq-pct{font-size:.68rem;color:var(--muted);white-space:nowrap}

/* Address box */
.addr-box{font-family:monospace;font-size:.72rem;color:var(--accent);background:var(--surface2);
  padding:.5rem .75rem;border-radius:6px;word-break:break-all;cursor:pointer;
  border:1px solid var(--border);transition:border-color .15s}
.addr-box:hover{border-color:var(--accent)}

/* Empty */
.empty{text-align:center;color:var(--muted);padding:2.5rem 1rem}
.empty .icon{font-size:2rem;margin-bottom:.5rem}

/* Loading */
.spin{display:inline-block;width:16px;height:16px;border:2px solid var(--border);
  border-top-color:var(--accent);border-radius:50%;animation:spin .7s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}

/* Modal */
.modal-backdrop{position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:200;
  display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:opacity .2s}
.modal-backdrop.open{opacity:1;pointer-events:all}
.modal{background:var(--surface);border:1px solid var(--border);border-radius:14px;
  width:100%;max-width:480px;margin:1rem;overflow:hidden}
.modal-header{padding:1rem 1.2rem;border-bottom:1px solid var(--border);
  display:flex;align-items:center;justify-content:space-between}
.modal-title{font-weight:600}
.modal-close{background:none;border:none;color:var(--muted);font-size:1.2rem;cursor:pointer;padding:.2rem .4rem}
.modal-close:hover{color:var(--text)}
.modal-body{padding:1.2rem;display:flex;flex-direction:column;gap:.9rem}
.modal-footer{padding:1rem 1.2rem;border-top:1px solid var(--border);display:flex;gap:.6rem;justify-content:flex-end}

/* Form */
label{font-size:.78rem;color:var(--muted);display:block;margin-bottom:.3rem}
input,textarea,select{width:100%;background:var(--surface2);border:1px solid var(--border);
  color:var(--text);padding:.5rem .75rem;border-radius:7px;font-size:.84rem;font-family:inherit;outline:none;
  transition:border-color .15s}
input:focus,textarea:focus,select:focus{border-color:var(--accent)}
textarea{resize:vertical;min-height:64px}
.field{display:flex;flex-direction:column}
.field-hint{font-size:.7rem;color:var(--muted);margin-top:.25rem}
.toggle-row{display:flex;align-items:center;justify-content:space-between}
.toggle{position:relative;width:36px;height:20px}
.toggle input{opacity:0;width:0;height:0}
.toggle-slider{position:absolute;inset:0;background:var(--border);border-radius:20px;cursor:pointer;transition:.3s}
.toggle-slider:before{content:'';position:absolute;height:14px;width:14px;left:3px;bottom:3px;
  background:#fff;border-radius:50%;transition:.3s}
.toggle input:checked+.toggle-slider{background:var(--accent)}
.toggle input:checked+.toggle-slider:before{transform:translateX(16px)}

/* Toast */
#toast{position:fixed;bottom:1.5rem;right:1.5rem;z-index:999;display:flex;flex-direction:column;gap:.5rem}
.toast-msg{background:var(--surface3);border:1px solid var(--border);border-radius:8px;padding:.65rem 1rem;
  font-size:.82rem;max-width:320px;animation:slide-in .2s ease;box-shadow:0 4px 20px rgba(0,0,0,.4)}
.toast-msg.success{border-color:var(--green);color:var(--green)}
.toast-msg.error{border-color:var(--red);color:var(--red)}
.toast-msg.info{border-color:var(--accent);color:var(--accent)}
@keyframes slide-in{from{transform:translateX(100%);opacity:0}to{transform:none;opacity:1}}

footer{text-align:center;color:var(--muted);font-size:.72rem;padding:2rem;margin-top:1rem}
footer a{color:var(--muted)}
</style>
</head>
<body>

<header>
  <div class="logo">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
    </svg>
    Fiber Node
  </div>
  <div class="hdr-right">
    <div class="status-badge">
      <div class="dot" id="status-dot"></div>
      <span id="status-text">Connecting…</span>
    </div>
    <button class="btn btn-ghost btn-sm" onclick="showModal('modal-peer')">+ Connect Peer</button>
    <button class="btn btn-primary btn-sm" onclick="showModal('modal-open')">⚡ Open Channel</button>
    <button class="btn btn-ghost btn-sm" onclick="loadAll()">↺</button>
  </div>
</header>

<main>
  <!-- Stats row -->
  <div class="grid-4">
    <div class="card"><div class="card-header"><span class="card-title">Channels</span></div>
      <div class="card-body"><div class="stat-value accent" id="s-channels">—</div><div class="stat-label">Open channels</div></div></div>
    <div class="card"><div class="card-header"><span class="card-title">Local Balance</span></div>
      <div class="card-body"><div class="stat-value green" id="s-local">—</div><div class="stat-label">CKB available to send</div></div></div>
    <div class="card"><div class="card-header"><span class="card-title">Remote Balance</span></div>
      <div class="card-body"><div class="stat-value purple" id="s-remote">—</div><div class="stat-label">CKB available to receive</div></div></div>
    <div class="card"><div class="card-header"><span class="card-title">Peers</span></div>
      <div class="card-body"><div class="stat-value" id="s-peers">—</div><div class="stat-label">Connected peers</div></div></div>
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
        <div style="display:flex;gap:.5rem">
          <button class="btn btn-success btn-sm" onclick="showModal('modal-invoice')">+ Invoice</button>
          <button class="btn btn-ghost btn-sm" onclick="showModal('modal-pay')">↑ Pay</button>
        </div>
      </div>
      <div class="card-body" id="wallet-body"><div class="spin"></div></div>
    </div>
  </div>

  <!-- Channels table -->
  <div class="card">
    <div class="card-header">
      <span class="card-title">Channels</span>
      <span id="ch-count" style="font-size:.75rem;color:var(--muted)"></span>
    </div>
    <div class="tbl-wrap">
      <table>
        <thead><tr>
          <th>Peer</th><th>State</th><th>Liquidity</th>
          <th>Local</th><th>Remote</th><th>Type</th><th>ID</th><th></th>
        </tr></thead>
        <tbody id="ch-body"><tr><td colspan="8" style="text-align:center;padding:2rem"><div class="spin"></div></td></tr></tbody>
      </table>
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
</main>

<footer>
  Fiber Node Dashboard · <a href="https://github.com/nervosnetwork/fiber" target="_blank">nervosnetwork/fiber</a>
  · <a href="https://wyltekindustries.com" target="_blank">Wyltek Industries</a>
</footer>

<!-- ── Modals ──────────────────────────────────────────────────────────── -->

<!-- Connect Peer -->
<div class="modal-backdrop" id="modal-peer">
  <div class="modal">
    <div class="modal-header">
      <span class="modal-title">Connect to Peer</span>
      <button class="modal-close" onclick="closeModal('modal-peer')">✕</button>
    </div>
    <div class="modal-body">
      <div class="field">
        <label>Peer Multiaddr</label>
        <input id="peer-addr" placeholder="/ip4/1.2.3.4/tcp/8228/p2p/QmXxx..." />
        <span class="field-hint">Full multiaddr including p2p/PeerID at the end</span>
      </div>
    </div>
    <div class="modal-footer">
      <button class="btn btn-ghost" onclick="closeModal('modal-peer')">Cancel</button>
      <button class="btn btn-primary" id="btn-connect-peer" onclick="doConnectPeer()">Connect</button>
    </div>
  </div>
</div>

<!-- Open Channel -->
<div class="modal-backdrop" id="modal-open">
  <div class="modal">
    <div class="modal-header">
      <span class="modal-title">Open Channel</span>
      <button class="modal-close" onclick="closeModal('modal-open')">✕</button>
    </div>
    <div class="modal-body">
      <div class="field">
        <label>Peer Multiaddr</label>
        <input id="oc-addr" placeholder="/ip4/1.2.3.4/tcp/8228/p2p/QmXxx..." />
        <span class="field-hint">Will auto-connect to peer before opening</span>
      </div>
      <div class="field">
        <label>Funding Amount (CKB)</label>
        <input id="oc-amount" type="number" placeholder="e.g. 1000" min="162" step="1" />
        <span class="field-hint">Minimum ~162 CKB. This CKB is locked for the channel's lifetime.</span>
      </div>
      <div class="toggle-row">
        <div>
          <div style="font-size:.82rem">Announce to network</div>
          <div style="font-size:.72rem;color:var(--muted)">Public channels are visible to routing nodes</div>
        </div>
        <label class="toggle">
          <input type="checkbox" id="oc-public" checked>
          <span class="toggle-slider"></span>
        </label>
      </div>
    </div>
    <div class="modal-footer">
      <button class="btn btn-ghost" onclick="closeModal('modal-open')">Cancel</button>
      <button class="btn btn-primary" id="btn-open-ch" onclick="doOpenChannel()">⚡ Open Channel</button>
    </div>
  </div>
</div>

<!-- Close Channel confirm -->
<div class="modal-backdrop" id="modal-close">
  <div class="modal">
    <div class="modal-header">
      <span class="modal-title">Close Channel</span>
      <button class="modal-close" onclick="closeModal('modal-close')">✕</button>
    </div>
    <div class="modal-body">
      <p style="font-size:.85rem;line-height:1.6;color:var(--text)">
        Cooperatively close this channel? Your funds will return to your on-chain wallet.
        This may take a few minutes to settle on-chain.
      </p>
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

<!-- Create Invoice -->
<div class="modal-backdrop" id="modal-invoice">
  <div class="modal">
    <div class="modal-header">
      <span class="modal-title">Create Invoice</span>
      <button class="modal-close" onclick="closeModal('modal-invoice')">✕</button>
    </div>
    <div class="modal-body">
      <div class="field">
        <label>Amount (CKB)</label>
        <input id="inv-amount" type="number" placeholder="e.g. 10" step="0.00000001" min="0" />
      </div>
      <div class="field">
        <label>Description (optional)</label>
        <input id="inv-desc" placeholder="Payment for…" />
      </div>
      <div class="field">
        <label>Expiry (minutes)</label>
        <input id="inv-expiry" type="number" value="60" min="1" />
      </div>
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

<!-- Send Payment -->
<div class="modal-backdrop" id="modal-pay">
  <div class="modal">
    <div class="modal-header">
      <span class="modal-title">Send Payment</span>
      <button class="modal-close" onclick="closeModal('modal-pay')">✕</button>
    </div>
    <div class="modal-body">
      <div class="field">
        <label>Invoice</label>
        <textarea id="pay-invoice" placeholder="Paste invoice string here…" rows="3"></textarea>
      </div>
    </div>
    <div class="modal-footer">
      <button class="btn btn-ghost" onclick="closeModal('modal-pay')">Cancel</button>
      <button class="btn btn-primary" id="btn-send-pay" onclick="doSendPayment()">↑ Send</button>
    </div>
  </div>
</div>

<!-- Toast container -->
<div id="toast"></div>

<script>
const API = '/api';
let nodeInfo = null;
let pendingCloseId = null;

// ── RPC ────────────────────────────────────────────────────────────────────────
async function fiberRpc(method, params = {}) {
  const r = await fetch(`${API}/fiber`, {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({method, params})
  });
  return r.json();
}
async function ckbRpc(method, params = []) {
  const r = await fetch(`${API}/ckb`, {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({method, params})
  });
  return r.json();
}

// ── Helpers ────────────────────────────────────────────────────────────────────
const shan = hex => hex ? Number(BigInt(hex)) / 1e8 : 0;
const toHex = ckb => '0x' + BigInt(Math.round(ckb * 1e8)).toString(16);
function fmt(ckb) {
  if (ckb >= 1e6) return (ckb/1e6).toFixed(2) + 'M';
  if (ckb >= 1e3) return (ckb/1e3).toFixed(2) + 'k';
  return ckb.toFixed(2);
}
function shortId(id) {
  if (!id) return '—';
  return id.slice(0,10) + '…' + id.slice(-6);
}
function copyText(text) {
  navigator.clipboard?.writeText(text.trim()).then(() => toast('Copied!','info'));
}
function stateClass(s) {
  if (!s) return 'pill-blue';
  const l = s.toLowerCase();
  if (l.includes('ready')) return 'pill-green';
  if (l.includes('clos')) return 'pill-red';
  return 'pill-yellow';
}

// ── Toasts ─────────────────────────────────────────────────────────────────────
function toast(msg, type='info', ms=3500) {
  const el = document.createElement('div');
  el.className = `toast-msg ${type}`;
  el.textContent = msg;
  document.getElementById('toast').appendChild(el);
  setTimeout(() => el.remove(), ms);
}

// ── Modal ──────────────────────────────────────────────────────────────────────
function showModal(id) {
  document.getElementById(id).classList.add('open');
}
function closeModal(id) {
  document.getElementById(id).classList.remove('open');
}
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') document.querySelectorAll('.modal-backdrop.open').forEach(m => m.classList.remove('open'));
});
document.querySelectorAll('.modal-backdrop').forEach(m => {
  m.addEventListener('click', e => { if (e.target === m) m.classList.remove('open'); });
});

function setBusy(btnId, busy, label) {
  const btn = document.getElementById(btnId);
  if (!btn) return;
  btn.disabled = busy;
  btn.innerHTML = busy ? '<div class="spin"></div>' : label;
}

// ── Load Node Info ─────────────────────────────────────────────────────────────
async function loadNodeInfo() {
  const res = await fiberRpc('node_info');
  const dot  = document.getElementById('status-dot');
  const stxt = document.getElementById('status-text');

  if (res.error || !res.result) {
    dot.className = 'dot red';
    stxt.textContent = res.error?.message || 'Offline';
    document.getElementById('node-info-body').innerHTML =
      `<div class="empty"><div class="icon">⚠️</div><p>${res.error?.message || 'Cannot reach Fiber RPC'}</p></div>`;
    document.getElementById('wallet-body').innerHTML =
      `<div class="empty"><div class="icon">⚠️</div><p>Node offline</p></div>`;
    return false;
  }

  const info = res.result;
  nodeInfo = info;
  dot.className = 'dot green';
  stxt.textContent = `Online · v${info.version || '?'}`;
  document.getElementById('s-peers').textContent = parseInt(info.peers_count||'0',16) || '0';

  document.getElementById('node-info-body').innerHTML = `
    <div class="info-row"><span class="info-key">Version</span><span class="info-val">${info.version || '—'}</span></div>
    <div class="info-row"><span class="info-key">Network</span><span class="info-val">${info.chain_hash ? (info.chain_hash.startsWith('0x92b1') ? 'Mainnet' : 'Testnet') : '—'}</span></div>
    <div class="info-row"><span class="info-key">Peers</span><span class="info-val">${parseInt(info.peers_count||'0',16)}</span></div>
    <div class="info-row"><span class="info-key">Channels</span><span class="info-val">${parseInt(info.channel_count||'0',16)} (${parseInt(info.pending_channel_count||'0',16)} pending)</span></div>
    <div class="info-row"><span class="info-key">Min Auto-Accept</span><span class="info-val">${fmt(shan(info.open_channel_auto_accept_min_ckb_funding_amount))} CKB</span></div>
    <div style="margin-top:.75rem">
      <div style="font-size:.7rem;color:var(--muted);margin-bottom:.3rem">Node ID (click to copy)</div>
      <div class="addr-box" onclick="copyText(this.textContent)">${info.node_id || '—'}</div>
    </div>
    ${(info.addresses||[]).length ? `
    <div style="margin-top:.6rem">
      <div style="font-size:.7rem;color:var(--muted);margin-bottom:.3rem">Addresses</div>
      ${info.addresses.map(a => `<div class="addr-box" style="margin-top:.25rem;font-size:.68rem" onclick="copyText(this.textContent)">${a}</div>`).join('')}
    </div>` : '<div style="margin-top:.6rem;font-size:.75rem;color:var(--muted)">⚠ No announced addresses — add your public IP to config</div>'}
  `;

  await loadWallet(info);
  return true;
}

// ── Wallet ─────────────────────────────────────────────────────────────────────
async function loadWallet(info) {
  const ls = info?.default_funding_lock_script;
  if (!ls) {
    document.getElementById('wallet-body').innerHTML =
      `<div class="empty"><div class="icon">💳</div><p>Lock script not available</p></div>`;
    return;
  }

  // Derive address + fetch balance from CKB RPC
  const addrRes = await fetch(`${API}/derive_address`, {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({lock: ls})
  });
  const { address } = await addrRes.json().catch(() => ({}));

  let balCKB = null;
  if (address) {
    // Fetch CKB balance via get_cells_capacity
    const balRes = await ckbRpc('get_cells_capacity', [{script: ls, script_type:'lock'}]);
    if (balRes.result?.capacity) {
      balCKB = shan(balRes.result.capacity);
    }
  }

  document.getElementById('wallet-body').innerHTML = `
    <div class="info-row">
      <span class="info-key">On-chain Balance</span>
      <span class="info-val" style="color:var(--green);font-size:.85rem">${balCKB !== null ? fmt(balCKB) + ' CKB' : '—'}</span>
    </div>
    <div style="margin-top:.75rem">
      <div style="font-size:.7rem;color:var(--muted);margin-bottom:.3rem">Deposit Address (click to copy)</div>
      <div class="addr-box" onclick="copyText(this.textContent)">${address || 'Derivation failed — check server logs'}</div>
    </div>
    ${address ? `<div style="margin-top:.6rem;font-size:.72rem;color:var(--muted)">Send CKB here to fund your node for opening channels.</div>` : ''}
  `;
}

// ── Channels ───────────────────────────────────────────────────────────────────
async function loadChannels() {
  const res = await fiberRpc('list_channels', {include_closed: false});
  const channels = res.result?.channels || [];

  let totalLocal = 0, totalRemote = 0, openCount = 0;
  channels.forEach(c => {
    totalLocal  += shan(c.local_balance);
    totalRemote += shan(c.remote_balance);
    if (c.state?.state_name === 'CHANNEL_READY') openCount++;
  });

  document.getElementById('s-channels').textContent = openCount;
  document.getElementById('s-local').textContent    = fmt(totalLocal) + ' CKB';
  document.getElementById('s-remote').textContent   = fmt(totalRemote) + ' CKB';
  document.getElementById('ch-count').textContent   = `${channels.length} total`;

  if (!channels.length) {
    document.getElementById('ch-body').innerHTML =
      `<tr><td colspan="8"><div class="empty"><div class="icon">⚡</div>
       <p>No channels yet</p>
       <button class="btn btn-primary" style="margin-top:.75rem" onclick="showModal('modal-open')">Open first channel</button>
       </div></td></tr>`;
    return;
  }

  document.getElementById('ch-body').innerHTML = channels.map(c => {
    const local  = shan(c.local_balance);
    const remote = shan(c.remote_balance);
    const total  = local + remote;
    const pct    = total > 0 ? Math.round((local/total)*100) : 0;
    const state  = c.state?.state_name?.replace(/_/g,' ') || 'Unknown';
    const canClose = c.state?.state_name === 'CHANNEL_READY';

    return `<tr>
      <td class="mono" title="${c.peer_id}">${shortId(c.peer_id)}</td>
      <td><span class="pill ${stateClass(state)}">${state}</span></td>
      <td>
        <div class="liq-wrap">
          <div class="liq-bar">
            <div class="liq-local" style="width:${pct}%;float:left"></div>
          </div>
          <span class="liq-pct">${pct}% / ${100-pct}%</span>
        </div>
      </td>
      <td>${fmt(local)} <small style="color:var(--muted)">CKB</small></td>
      <td>${fmt(remote)} <small style="color:var(--muted)">CKB</small></td>
      <td>${c.is_public ? '<span class="pill pill-blue">Public</span>' : '<span class="pill pill-purple">Private</span>'}</td>
      <td class="mono" title="${c.channel_id}" onclick="copyText('${c.channel_id}')" style="cursor:pointer">${shortId(c.channel_id)}</td>
      <td>
        ${canClose
          ? `<button class="btn btn-danger btn-sm" onclick="confirmClose('${c.channel_id}')">Close</button>`
          : `<span style="font-size:.72rem;color:var(--muted)">${state.includes('Clos') ? 'Closing…' : '—'}</span>`}
      </td>
    </tr>`;
  }).join('');
}

// ── Peers ──────────────────────────────────────────────────────────────────────
async function loadPeers() {
  const res = await fiberRpc('list_peers');
  const peers = res.result?.peers || res.result || [];
  const el = document.getElementById('peers-body');

  if (!peers.length) {
    el.innerHTML = `<div class="empty"><div class="icon">🌐</div>
      <p>No connected peers</p>
      <button class="btn btn-ghost" style="margin-top:.6rem" onclick="showModal('modal-peer')">+ Connect Peer</button>
    </div>`;
    return;
  }

  el.innerHTML = peers.slice(0,8).map(p => {
    const id   = p.peer_id || p.id || '';
    const addr = p.address || p.multiaddr || '';
    return `<div style="padding:.5rem 0;border-bottom:1px solid var(--border)">
      <div style="display:flex;align-items:center;justify-content:space-between">
        <div class="mono" style="color:var(--accent);font-size:.72rem" title="${id}">${shortId(id)}</div>
        <button class="btn btn-primary btn-sm" onclick="prefillOpenChannel('${addr}')">+ Channel</button>
      </div>
      ${addr ? `<div style="color:var(--muted);font-size:.68rem;margin-top:.15rem">${addr}</div>` : ''}
    </div>`;
  }).join('');
}

// ── Payments ───────────────────────────────────────────────────────────────────
async function loadPayments() {
  const res = await fiberRpc('list_payments');
  const payments = res.result?.payments || (Array.isArray(res.result) ? res.result : []);
  const el = document.getElementById('pay-body');

  if (res.error || !payments.length) {
    el.innerHTML = `<div class="empty"><div class="icon">💸</div>
      <p>${res.error ? 'Payments require auth' : 'No payments yet'}</p>
      <button class="btn btn-ghost" style="margin-top:.6rem" onclick="showModal('modal-pay')">↑ Send Payment</button>
    </div>`;
    return;
  }

  el.innerHTML = payments.slice(0,10).map(p => {
    const amount = shan(p.amount || p.paid_amount || 0);
    const status = p.status || 'unknown';
    const isSent = p.direction !== 'received';
    const col    = status === 'success' ? 'var(--green)' : status === 'failed' ? 'var(--red)' : 'var(--yellow)';
    return `<div style="display:flex;align-items:center;gap:.6rem;padding:.5rem 0;border-bottom:1px solid var(--border)">
      <div style="font-size:1.1rem">${isSent ? '↑' : '↓'}</div>
      <div style="flex:1">
        <div class="mono" style="font-size:.7rem;color:var(--muted)">${shortId(p.payment_hash||p.id)}</div>
        <div style="font-size:.72rem;color:${col}">${status}</div>
      </div>
      <div style="font-weight:600;font-size:.83rem;color:${isSent?'var(--text)':'var(--green)'}">${isSent?'-':'+'}${fmt(amount)} CKB</div>
    </div>`;
  }).join('');
}

// ── Actions ────────────────────────────────────────────────────────────────────
async function doConnectPeer() {
  const addr = document.getElementById('peer-addr').value.trim();
  if (!addr) { toast('Enter a peer multiaddr', 'error'); return; }
  setBusy('btn-connect-peer', true);
  const res = await fiberRpc('connect_peer', {address: addr});
  setBusy('btn-connect-peer', false, 'Connect');
  if (res.error) { toast('Failed: ' + res.error.message, 'error'); return; }
  toast('Peer connected!', 'success');
  closeModal('modal-peer');
  document.getElementById('peer-addr').value = '';
  loadPeers();
}

async function doOpenChannel() {
  const addr   = document.getElementById('oc-addr').value.trim();
  const ckbAmt = parseFloat(document.getElementById('oc-amount').value);
  const isPublic = document.getElementById('oc-public').checked;

  if (!addr) { toast('Enter a peer multiaddr', 'error'); return; }
  if (!ckbAmt || ckbAmt < 162) { toast('Minimum 162 CKB required', 'error'); return; }

  setBusy('btn-open-ch', true);

  // Step 1: connect peer
  toast('Connecting to peer…', 'info');
  const connRes = await fiberRpc('connect_peer', {address: addr});
  if (connRes.error && !connRes.error.message?.includes('already')) {
    setBusy('btn-open-ch', false, '⚡ Open Channel');
    toast('Connect failed: ' + connRes.error.message, 'error');
    return;
  }

  // Extract peer_id from multiaddr (/p2p/QmXxx)
  const peerIdMatch = addr.match(/\/p2p\/([A-Za-z0-9]+)/);
  const peerId = peerIdMatch?.[1];
  if (!peerId) {
    setBusy('btn-open-ch', false, '⚡ Open Channel');
    toast('Could not extract peer ID from address', 'error');
    return;
  }

  // Step 2: open channel
  toast('Opening channel…', 'info');
  const openRes = await fiberRpc('open_channel', {
    peer_id: peerId,
    funding_amount: toHex(ckbAmt),
    public: isPublic
  });

  setBusy('btn-open-ch', false, '⚡ Open Channel');

  if (openRes.error) {
    toast('Open failed: ' + openRes.error.message, 'error');
    return;
  }

  toast('Channel opening! Temp ID: ' + shortId(openRes.result?.temporary_channel_id||''), 'success', 5000);
  closeModal('modal-open');
  document.getElementById('oc-addr').value = '';
  document.getElementById('oc-amount').value = '';
  setTimeout(loadChannels, 2000);
}

function confirmClose(channelId) {
  pendingCloseId = channelId;
  document.getElementById('close-ch-id').textContent = channelId;
  showModal('modal-close');
}

async function doCloseChannel() {
  if (!pendingCloseId) return;
  setBusy('btn-close-ch', true);

  const params = {
    channel_id: pendingCloseId,
    fee_rate: '0x3e8'  // 1000 shannons/kB
  };

  // Include our funding lock script as close_script if available
  if (nodeInfo?.default_funding_lock_script) {
    params.close_script = nodeInfo.default_funding_lock_script;
  }

  const res = await fiberRpc('shutdown_channel', params);
  setBusy('btn-close-ch', false, 'Close Channel');

  if (res.error) {
    toast('Close failed: ' + res.error.message, 'error');
    return;
  }

  toast('Channel closing…', 'success');
  closeModal('modal-close');
  pendingCloseId = null;
  setTimeout(loadChannels, 2000);
}

async function doCreateInvoice() {
  const ckbAmt = parseFloat(document.getElementById('inv-amount').value);
  if (!ckbAmt || ckbAmt <= 0) { toast('Enter an amount', 'error'); return; }

  const desc   = document.getElementById('inv-desc').value.trim();
  const expMin = parseInt(document.getElementById('inv-expiry').value) || 60;

  // Determine currency from chain_hash
  let currency = 'Fibb'; // mainnet default
  if (nodeInfo?.chain_hash && !nodeInfo.chain_hash.startsWith('0x92b1')) currency = 'Fibt';

  setBusy('btn-create-inv', true);
  const res = await fiberRpc('new_invoice', {
    amount: toHex(ckbAmt),
    currency,
    expiry: '0x' + (expMin * 60).toString(16),
    ...(desc ? {description: desc} : {})
  });
  setBusy('btn-create-inv', false, 'Generate');

  if (res.error) { toast('Failed: ' + res.error.message, 'error'); return; }

  const invStr = res.result?.invoice_address || res.result?.invoice;
  if (invStr) {
    document.getElementById('inv-str').textContent = invStr;
    document.getElementById('inv-result').style.display = 'block';
    navigator.clipboard?.writeText(invStr).then(() => toast('Invoice copied to clipboard!', 'success'));
  }
}

async function doSendPayment() {
  const invoice = document.getElementById('pay-invoice').value.trim();
  if (!invoice) { toast('Paste an invoice', 'error'); return; }

  setBusy('btn-send-pay', true);
  const res = await fiberRpc('send_payment', {invoice});
  setBusy('btn-send-pay', false, '↑ Send');

  if (res.error) { toast('Failed: ' + res.error.message, 'error'); return; }

  toast('Payment sent! Hash: ' + shortId(res.result?.payment_hash||''), 'success', 5000);
  closeModal('modal-pay');
  document.getElementById('pay-invoice').value = '';
  setTimeout(loadPayments, 1500);
}

function prefillOpenChannel(addr) {
  if (addr) document.getElementById('oc-addr').value = addr;
  showModal('modal-open');
}

// ── Main ───────────────────────────────────────────────────────────────────────
async function loadAll() {
  const ok = await loadNodeInfo();
  if (ok) {
    await Promise.all([loadChannels(), loadPeers(), loadPayments()]);
  }
}

loadAll();
setInterval(loadAll, 15000);
</script>
</body>
</html>
"""

# ── Address derivation endpoint ────────────────────────────────────────────────
def derive_address(lock_script):
    try:
        addr = lock_to_address(
            lock_script.get("code_hash",""),
            lock_script.get("hash_type","type"),
            lock_script.get("args",""),
            NETWORK
        )
        return {"address": addr}
    except Exception as e:
        return {"address": None, "error": str(e)}

# ── HTTP Handler ───────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def _json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type","application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin","*")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html):
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type","text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Access-Control-Allow-Methods","POST,GET,OPTIONS")
        self.send_header("Access-Control-Allow-Headers","Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path in ("/","/index.html"): self._html(HTML)
        elif self.path == "/health": self._json({"ok":True,"fiber_rpc":FIBER_RPC,"ckb_rpc":CKB_RPC})
        else: self.send_response(404); self.end_headers()

    def do_POST(self):
        if not self.path.startswith("/api/"):
            self.send_response(404); self.end_headers(); return

        length  = int(self.headers.get("Content-Length",0))
        payload = json.loads(self.rfile.read(length)) if length else {}
        target  = self.path[5:]

        if target == "fiber":
            params = payload.get("params", {})
            # Fiber RPC wraps params in an array with single object
            result = rpc_call(FIBER_RPC, payload.get("method"), [params], BISCUIT)
            self._json(result)
        elif target == "ckb":
            result = rpc_call(CKB_RPC, payload.get("method"), payload.get("params",[]))
            self._json(result)
        elif target == "derive_address":
            self._json(derive_address(payload.get("lock",{})))
        else:
            self._json({"error":"unknown target"}, 400)

# ── Main ───────────────────────────────────────────────────────────────────────
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8",80)); return s.getsockname()[0]
    except: return "127.0.0.1"

if __name__ == "__main__":
    server = HTTPServer((args.host, args.port), Handler)
    ip = get_local_ip()
    print(f"""
╔══════════════════════════════════════════════════╗
║     Fiber Network Node Dashboard                 ║
╚══════════════════════════════════════════════════╝

  Dashboard:  http://{ip}:{args.port}
  Local:      http://127.0.0.1:{args.port}

  Fiber RPC:  {FIBER_RPC}
  CKB RPC:    {CKB_RPC}
  Network:    {NETWORK}

  Ctrl+C to stop
""")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")
