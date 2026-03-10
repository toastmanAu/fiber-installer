#!/usr/bin/env python3
"""
Fiber Network Node Dashboard
━━━━━━━━━━━━━━━━━━━━━━━━━━━
Zero-dependency local dashboard for Fiber Network nodes.
Serves a browser UI and proxies Fiber + CKB RPC calls.

Usage:
    python3 fiber-dash.py [--fiber-rpc http://127.0.0.1:8227] [--ckb-rpc http://127.0.0.1:8114] [--port 8229]
"""

import argparse
import json
import sys
import socket
import threading
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler

# ── Args ───────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="Fiber Network Dashboard")
parser.add_argument("--fiber-rpc", default="http://127.0.0.1:8227", help="Fiber RPC endpoint")
parser.add_argument("--ckb-rpc",   default="http://127.0.0.1:8114",  help="CKB RPC endpoint")
parser.add_argument("--port",      default=8229, type=int,            help="Dashboard port")
parser.add_argument("--host",      default="0.0.0.0",                 help="Listen host (0.0.0.0 = all interfaces)")
parser.add_argument("--biscuit",   default="",                        help="Biscuit token for Fiber RPC auth")
args = parser.parse_args()

FIBER_RPC  = args.fiber_rpc
CKB_RPC    = args.ckb_rpc
DASHBOARD_PORT = args.port
BISCUIT    = args.biscuit

# ── RPC helpers ────────────────────────────────────────────────────────────────
_rpc_id = 0
def rpc_call(url, method, params=None, token=""):
    global _rpc_id
    _rpc_id += 1
    body = json.dumps({"id": _rpc_id, "jsonrpc": "2.0", "method": method, "params": params or []}).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": {"message": str(e)}}

# ── HTML Dashboard ─────────────────────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Fiber Node Dashboard</title>
<style>
  :root {
    --bg: #07090f; --surface: #0f1117; --surface2: #161b26;
    --border: #1e2a3a; --text: #e2e8f0; --muted: #64748b;
    --accent: #00c8ff; --green: #22c55e; --red: #ef4444;
    --yellow: #f59e0b; --purple: #a78bfa; --orange: #fb923c;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; font-size: 14px; min-height: 100vh; }

  /* ── Header ── */
  header { background: var(--surface); border-bottom: 1px solid var(--border); padding: 0 1.5rem; display: flex; align-items: center; justify-content: space-between; height: 56px; position: sticky; top: 0; z-index: 100; }
  .logo { font-size: 1.1rem; font-weight: 700; color: var(--accent); display: flex; align-items: center; gap: 0.5rem; }
  .logo svg { width: 22px; height: 22px; }
  .status-badge { display: flex; align-items: center; gap: 0.4rem; font-size: 0.8rem; color: var(--muted); }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--muted); }
  .dot.green { background: var(--green); box-shadow: 0 0 6px var(--green); animation: pulse 2s infinite; }
  .dot.red { background: var(--red); }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.5; } }
  .refresh-btn { background: none; border: 1px solid var(--border); color: var(--muted); padding: 0.3rem 0.75rem; border-radius: 6px; cursor: pointer; font-size: 0.8rem; transition: all 0.15s; }
  .refresh-btn:hover { border-color: var(--accent); color: var(--accent); }

  /* ── Layout ── */
  main { max-width: 1200px; margin: 0 auto; padding: 1.5rem; display: grid; gap: 1rem; }
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
  .grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; }
  @media (max-width: 768px) { .grid-2, .grid-3 { grid-template-columns: 1fr; } }

  /* ── Cards ── */
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }
  .card-header { padding: 0.9rem 1.2rem; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; }
  .card-title { font-weight: 600; font-size: 0.85rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
  .card-body { padding: 1.2rem; }

  /* ── Stat tiles ── */
  .stat { }
  .stat-value { font-size: 1.8rem; font-weight: 700; color: var(--text); line-height: 1; }
  .stat-value.accent { color: var(--accent); }
  .stat-value.green { color: var(--green); }
  .stat-label { font-size: 0.75rem; color: var(--muted); margin-top: 0.3rem; }

  /* ── Node info ── */
  .node-id { font-family: monospace; font-size: 0.75rem; color: var(--accent); word-break: break-all; background: var(--surface2); padding: 0.5rem 0.75rem; border-radius: 6px; margin-top: 0.5rem; cursor: pointer; }
  .info-row { display: flex; justify-content: space-between; align-items: center; padding: 0.4rem 0; border-bottom: 1px solid var(--border); font-size: 0.82rem; }
  .info-row:last-child { border-bottom: none; }
  .info-key { color: var(--muted); }
  .info-val { color: var(--text); font-family: monospace; font-size: 0.78rem; max-width: 60%; text-align: right; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  /* ── Channels table ── */
  .table-wrap { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
  th { text-align: left; padding: 0.5rem 0.75rem; color: var(--muted); font-weight: 500; border-bottom: 1px solid var(--border); white-space: nowrap; }
  td { padding: 0.65rem 0.75rem; border-bottom: 1px solid var(--border); }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: var(--surface2); }
  .mono { font-family: monospace; font-size: 0.75rem; }
  .pill { display: inline-block; padding: 0.15rem 0.5rem; border-radius: 99px; font-size: 0.7rem; font-weight: 600; }
  .pill-green { background: rgba(34,197,94,0.15); color: var(--green); }
  .pill-yellow { background: rgba(245,158,11,0.15); color: var(--yellow); }
  .pill-red { background: rgba(239,68,68,0.15); color: var(--red); }
  .pill-blue { background: rgba(0,200,255,0.12); color: var(--accent); }

  /* ── Liquidity bar ── */
  .liq-bar { height: 6px; border-radius: 3px; background: var(--surface2); overflow: hidden; min-width: 80px; }
  .liq-fill { height: 100%; border-radius: 3px; background: linear-gradient(90deg, var(--accent), var(--purple)); }

  /* ── Addresses ── */
  .addr-list { display: flex; flex-direction: column; gap: 0.4rem; }
  .addr-item { font-family: monospace; font-size: 0.72rem; color: var(--muted); background: var(--surface2); padding: 0.35rem 0.6rem; border-radius: 5px; word-break: break-all; }

  /* ── Empty state ── */
  .empty { text-align: center; color: var(--muted); padding: 2rem 1rem; font-size: 0.85rem; }
  .empty .icon { font-size: 2rem; margin-bottom: 0.5rem; }

  /* ── Loading ── */
  .loading { display: inline-block; width: 16px; height: 16px; border: 2px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.7s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* ── Payments ── */
  .payment-row { display: flex; align-items: center; gap: 0.75rem; padding: 0.6rem 0; border-bottom: 1px solid var(--border); }
  .payment-row:last-child { border-bottom: none; }
  .payment-dir { font-size: 1rem; }
  .payment-info { flex: 1; }
  .payment-hash { font-family: monospace; font-size: 0.72rem; color: var(--muted); }
  .payment-status { font-size: 0.75rem; }
  .payment-amount { font-weight: 600; color: var(--text); font-size: 0.85rem; white-space: nowrap; }

  /* ── Footer ── */
  footer { text-align: center; color: var(--muted); font-size: 0.75rem; padding: 2rem 1rem; }
  footer a { color: var(--muted); }
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
  <div style="display:flex;align-items:center;gap:1rem">
    <div class="status-badge">
      <div class="dot" id="status-dot"></div>
      <span id="status-text">Connecting…</span>
    </div>
    <button class="refresh-btn" onclick="loadAll()">↺ Refresh</button>
  </div>
</header>

<main>
  <!-- Stat row -->
  <div class="grid-3">
    <div class="card">
      <div class="card-header"><span class="card-title">Channels</span></div>
      <div class="card-body"><div class="stat">
        <div class="stat-value accent" id="stat-channels">—</div>
        <div class="stat-label">Open channels</div>
      </div></div>
    </div>
    <div class="card">
      <div class="card-header"><span class="card-title">Local Balance</span></div>
      <div class="card-body"><div class="stat">
        <div class="stat-value green" id="stat-local">—</div>
        <div class="stat-label">CKB available to send</div>
      </div></div>
    </div>
    <div class="card">
      <div class="card-header"><span class="card-title">Remote Balance</span></div>
      <div class="card-body"><div class="stat">
        <div class="stat-value" id="stat-remote" style="color:var(--purple)">—</div>
        <div class="stat-label">CKB available to receive</div>
      </div></div>
    </div>
  </div>

  <!-- Node info + Addresses -->
  <div class="grid-2">
    <div class="card">
      <div class="card-header"><span class="card-title">Node Info</span></div>
      <div class="card-body" id="node-info-body"><div class="loading"></div></div>
    </div>
    <div class="card">
      <div class="card-header"><span class="card-title">Listen Addresses</span></div>
      <div class="card-body" id="addresses-body"><div class="loading"></div></div>
    </div>
  </div>

  <!-- Channels table -->
  <div class="card">
    <div class="card-header">
      <span class="card-title">Channels</span>
      <span id="channel-count" style="font-size:0.75rem;color:var(--muted)"></span>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>Peer</th>
          <th>State</th>
          <th>Liquidity (Local / Remote)</th>
          <th>Local</th>
          <th>Remote</th>
          <th>Public</th>
          <th>Channel ID</th>
        </tr></thead>
        <tbody id="channels-body"><tr><td colspan="7" style="text-align:center;padding:2rem"><div class="loading"></div></td></tr></tbody>
      </table>
    </div>
  </div>

  <!-- Payments + Peers -->
  <div class="grid-2">
    <div class="card">
      <div class="card-header"><span class="card-title">Recent Payments</span></div>
      <div class="card-body" id="payments-body"><div class="loading"></div></div>
    </div>
    <div class="card">
      <div class="card-header"><span class="card-title">Connected Peers</span></div>
      <div class="card-body" id="peers-body"><div class="loading"></div></div>
    </div>
  </div>
</main>

<footer>
  Fiber Node Dashboard · <a href="https://github.com/nervosnetwork/fiber" target="_blank">nervosnetwork/fiber</a>
  · Built by <a href="https://wyltekindustries.com" target="_blank">Wyltek Industries</a>
</footer>

<script>
const API = '/api';
let lastData = {};

async function rpc(method, params = []) {
  const r = await fetch(`${API}/fiber`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ method, params })
  });
  return r.json();
}

function shan(hex) {
  if (!hex) return 0;
  return parseInt(hex, 16) / 1e8;
}

function fmt(ckb) {
  if (ckb >= 1000000) return (ckb/1000000).toFixed(2) + 'M';
  if (ckb >= 1000) return (ckb/1000).toFixed(2) + 'k';
  return ckb.toFixed(2);
}

function shortId(id) {
  if (!id) return '—';
  return id.slice(0, 10) + '…' + id.slice(-6);
}

function stateClass(state) {
  if (!state) return 'pill-blue';
  const s = state.toLowerCase();
  if (s.includes('ready')) return 'pill-green';
  if (s.includes('closing') || s.includes('closed')) return 'pill-red';
  return 'pill-yellow';
}

function copyText(text) {
  navigator.clipboard?.writeText(text);
}

async function loadNodeInfo() {
  const res = await rpc('get_node_info');
  const info = res.result;
  const err  = res.error;

  const dot  = document.getElementById('status-dot');
  const stxt = document.getElementById('status-text');

  if (err || !info) {
    dot.className = 'dot red';
    stxt.textContent = err?.message || 'Offline';
    document.getElementById('node-info-body').innerHTML =
      `<div class="empty"><div class="icon">⚠️</div><p>${err?.message || 'Cannot connect to Fiber RPC'}</p></div>`;
    return;
  }

  dot.className = 'dot green';
  stxt.textContent = `Online · v${info.version || '?'}`;
  lastData.nodeInfo = info;

  document.getElementById('node-info-body').innerHTML = `
    <div class="info-row"><span class="info-key">Node ID</span><span class="info-val mono" title="${info.node_id || ''}" onclick="copyText('${info.node_id || ''}')" style="cursor:pointer">${shortId(info.node_id)}</span></div>
    <div class="info-row"><span class="info-key">Version</span><span class="info-val">${info.version || '—'}</span></div>
    <div class="info-row"><span class="info-key">Network</span><span class="info-val">${info.chain || '—'}</span></div>
    <div class="info-row"><span class="info-key">Peers</span><span class="info-val">${info.active_channels?.length ?? (info.connected_peers ?? '—')}</span></div>
    ${info.udt_cfg_infos?.length ? `<div class="info-row"><span class="info-key">UDTs</span><span class="info-val">${info.udt_cfg_infos.length} configured</span></div>` : ''}
    <div style="margin-top:0.6rem">
      <div style="font-size:0.7rem;color:var(--muted);margin-bottom:0.3rem">Full Node ID (click to copy)</div>
      <div class="node-id" onclick="copyText('${info.node_id || ''}')" title="Click to copy">${info.node_id || '—'}</div>
    </div>
  `;

  const addrs = info.addresses || [];
  document.getElementById('addresses-body').innerHTML = addrs.length
    ? `<div class="addr-list">${addrs.map(a => `<div class="addr-item" onclick="copyText('${a}')" title="Click to copy">${a}</div>`).join('')}</div>`
    : `<div class="empty"><div class="icon">📡</div><p>No announced addresses<br><small>Add your public IP to config to announce your node</small></p></div>`;
}

async function loadChannels() {
  const res = await rpc('list_channels', [{}]);
  const channels = res.result?.channels || [];

  let totalLocal = 0, totalRemote = 0, openCount = 0;
  channels.forEach(c => {
    const local  = shan(c.local_balance);
    const remote = shan(c.remote_balance);
    totalLocal  += local;
    totalRemote += remote;
    if (c.state?.state_name === 'CHANNEL_READY') openCount++;
  });

  document.getElementById('stat-channels').textContent = openCount;
  document.getElementById('stat-local').textContent    = fmt(totalLocal) + ' CKB';
  document.getElementById('stat-remote').textContent   = fmt(totalRemote) + ' CKB';
  document.getElementById('channel-count').textContent = `${channels.length} total`;

  if (!channels.length) {
    document.getElementById('channels-body').innerHTML =
      `<tr><td colspan="7"><div class="empty"><div class="icon">⚡</div><p>No channels yet</p></div></td></tr>`;
    return;
  }

  document.getElementById('channels-body').innerHTML = channels.map(c => {
    const local   = shan(c.local_balance);
    const remote  = shan(c.remote_balance);
    const total   = local + remote;
    const pct     = total > 0 ? Math.round((local / total) * 100) : 0;
    const state   = c.state?.state_name?.replace(/_/g, ' ') || 'Unknown';

    return `<tr>
      <td class="mono" title="${c.peer_id}">${shortId(c.peer_id)}</td>
      <td><span class="pill ${stateClass(state)}">${state}</span></td>
      <td>
        <div style="display:flex;align-items:center;gap:0.5rem">
          <div class="liq-bar" style="flex:1"><div class="liq-fill" style="width:${pct}%"></div></div>
          <span style="font-size:0.7rem;color:var(--muted);width:28px;text-align:right">${pct}%</span>
        </div>
      </td>
      <td>${fmt(local)} <small style="color:var(--muted)">CKB</small></td>
      <td>${fmt(remote)} <small style="color:var(--muted)">CKB</small></td>
      <td>${c.is_public ? '<span class="pill pill-blue">Public</span>' : '<span class="pill pill-yellow">Private</span>'}</td>
      <td class="mono" title="${c.channel_id}" onclick="copyText('${c.channel_id}')" style="cursor:pointer">${shortId(c.channel_id)}</td>
    </tr>`;
  }).join('');
}

async function loadPayments() {
  const res = await rpc('list_payments', [{}]);
  const payments = res.result?.payments || res.result || [];
  const el = document.getElementById('payments-body');

  if (!payments.length) {
    el.innerHTML = `<div class="empty"><div class="icon">💸</div><p>No payments yet</p></div>`;
    return;
  }

  el.innerHTML = payments.slice(0, 10).map(p => {
    const amount   = shan(p.amount || p.paid_amount || 0);
    const status   = p.status || 'unknown';
    const isSent   = p.direction !== 'received';
    const color    = status === 'success' ? 'var(--green)' : status === 'failed' ? 'var(--red)' : 'var(--yellow)';
    return `<div class="payment-row">
      <div class="payment-dir">${isSent ? '↑' : '↓'}</div>
      <div class="payment-info">
        <div class="payment-hash">${shortId(p.payment_hash || p.id)}</div>
        <div class="payment-status" style="color:${color}">${status}</div>
      </div>
      <div class="payment-amount" style="color:${isSent ? 'var(--text)' : 'var(--green)'}">${isSent ? '-' : '+'}${fmt(amount)} CKB</div>
    </div>`;
  }).join('');
}

async function loadPeers() {
  const res = await rpc('list_peers', [{}]);
  const peers = res.result?.peers || res.result || [];
  const el = document.getElementById('peers-body');

  if (!peers.length) {
    el.innerHTML = `<div class="empty"><div class="icon">🌐</div><p>No connected peers<br><small>Open a channel to connect to peers</small></p></div>`;
    return;
  }

  el.innerHTML = `<div class="addr-list">${peers.slice(0, 8).map(p => {
    const id   = p.peer_id || p.id || '';
    const addr = p.address || p.multiaddr || '';
    return `<div style="padding:0.4rem 0;border-bottom:1px solid var(--border);font-size:0.8rem">
      <div class="mono" style="color:var(--accent);font-size:0.72rem">${shortId(id)}</div>
      ${addr ? `<div style="color:var(--muted);font-size:0.7rem;margin-top:0.15rem">${addr}</div>` : ''}
    </div>`;
  }).join('')}</div>`;
}

async function loadAll() {
  document.getElementById('status-text').textContent = 'Refreshing…';
  await Promise.all([
    loadNodeInfo(),
    loadChannels(),
    loadPayments(),
    loadPeers(),
  ]);
}

loadAll();
setInterval(loadAll, 15000);
</script>
</body>
</html>
"""

# ── HTTP Handler ───────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # silence access logs

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, html):
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_html(HTML)
        elif self.path == "/health":
            self.send_json({"ok": True, "fiber_rpc": FIBER_RPC})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if not self.path.startswith("/api/"):
            self.send_response(404); self.end_headers(); return

        length  = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length)) if length else {}

        target  = self.path[5:]  # strip /api/
        if target == "fiber":
            url = FIBER_RPC
            result = rpc_call(url, payload.get("method"), payload.get("params", []), BISCUIT)
        elif target == "ckb":
            url = CKB_RPC
            result = rpc_call(url, payload.get("method"), payload.get("params", []))
        else:
            self.send_json({"error": "unknown target"}, 400)
            return

        self.send_json(result)

# ── Main ───────────────────────────────────────────────────────────────────────
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except:
        return "127.0.0.1"

if __name__ == "__main__":
    server = HTTPServer((args.host, DASHBOARD_PORT), Handler)
    local_ip = get_local_ip()

    print(f"""
╔══════════════════════════════════════════════════╗
║         Fiber Network Node Dashboard             ║
╚══════════════════════════════════════════════════╝

  Dashboard:  http://{local_ip}:{DASHBOARD_PORT}
  Local:      http://127.0.0.1:{DASHBOARD_PORT}

  Fiber RPC:  {FIBER_RPC}
  CKB RPC:    {CKB_RPC}

  Ctrl+C to stop
""")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Dashboard stopped.")
