# “””
Limelight AprilTag Tracker

Connects via NetworkTables (on-robot) and/or HTTP REST API (direct laptop).
Calculates distance, tag ID, and pose estimation from AprilTag detections.
Serves live data to a web dashboard on http://localhost:5000
“””

import math
import time
import json
import threading
import argparse
from dataclasses import dataclass, asdict
from typing import Optional
import requests
from flask import Flask, jsonify, render_template_string
from flask_cors import CORS

# ── Optional NetworkTables import ────────────────────────────────────────────

try:
from ntcore import NetworkTableInstance
NT_AVAILABLE = True
except ImportError:
NT_AVAILABLE = False
print(”[WARN] ntcore not installed — NetworkTables disabled. Run: pip install pynetworktables2js or robotpy-ntcore”)

# ═══════════════════════════════════════════════════════════════════════════════

# CONFIGURATION  — edit these to match your setup

# ═══════════════════════════════════════════════════════════════════════════════

class Config:
# Limelight network address
LIMELIGHT_IP        = “10.TE.AM.11”   # Replace TE.AM with your team number, e.g. “10.49.36.11”
LIMELIGHT_HTTP_PORT = 5807

```
# Camera mounting (measure on your robot)
CAMERA_HEIGHT_METERS    = 0.60    # Height of camera lens from floor (meters)
CAMERA_PITCH_DEGREES    = 25.0    # Camera tilt upward from horizontal (degrees)

# AprilTag target height — FRC 2024 default tag center heights
# Speaker tags: ~1.45m, Amp: ~1.36m, etc. Adjust per game manual.
TARGET_HEIGHT_METERS    = 1.45

# NetworkTables
NT_SERVER_IP            = "10.TE.AM.2"  # Rio address, OR "localhost" for simulation
NT_TABLE                = "limelight"

# Dashboard
DASHBOARD_PORT          = 5000
POLL_HZ                 = 20      # How often to poll Limelight (times/sec)
```

# ═══════════════════════════════════════════════════════════════════════════════

# DATA MODELS

# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class TagData:
tag_id:            int     = -1
tx:                float   = 0.0   # Horizontal offset (degrees)
ty:                float   = 0.0   # Vertical offset (degrees)
ta:                float   = 0.0   # Target area (% of image)
distance_meters:   float   = 0.0
distance_inches:   float   = 0.0
distance_feet:     float   = 0.0
pitch_deg:         float   = 0.0   # Tag pitch
yaw_deg:           float   = 0.0   # Tag yaw
roll_deg:          float   = 0.0   # Tag roll
pose_x:            float   = 0.0   # Robot pose X (botpose)
pose_y:            float   = 0.0   # Robot pose Y
pose_z:            float   = 0.0   # Robot pose Z
pose_yaw:          float   = 0.0   # Robot heading
latency_ms:        float   = 0.0
valid:             bool    = False
source:            str     = “none”
timestamp:         float   = 0.0

# ═══════════════════════════════════════════════════════════════════════════════

# DISTANCE CALCULATION

# ═══════════════════════════════════════════════════════════════════════════════

def calculate_distance(ty_degrees: float) -> float:
“””
Classic FRC distance formula using vertical angle to target.
d = (h2 - h1) / tan(a1 + a2)
h1 = camera height, h2 = target height,
a1 = camera mount angle, a2 = ty from limelight
Returns distance in meters.
“””
angle_rad = math.radians(Config.CAMERA_PITCH_DEGREES + ty_degrees)
if abs(angle_rad) < 1e-6:
return 0.0
height_diff = Config.TARGET_HEIGHT_METERS - Config.CAMERA_HEIGHT_METERS
return height_diff / math.tan(angle_rad)

# ═══════════════════════════════════════════════════════════════════════════════

# HTTP CLIENT  (direct laptop connection, no robot needed)

# ═══════════════════════════════════════════════════════════════════════════════

class LimelightHTTP:
def **init**(self, ip: str, port: int):
self.base = f”http://{ip}:{port}”
self.session = requests.Session()
self.session.timeout = 0.5

```
def get_results(self) -> Optional[dict]:
    try:
        r = self.session.get(f"{self.base}/results", timeout=0.5)
        return r.json()
    except Exception as e:
        return None

def parse(self, raw: dict) -> TagData:
    td = TagData(timestamp=time.time(), source="http")
    if not raw:
        return td
    try:
        results = raw.get("Results", raw)
        td.tx = results.get("tx", 0.0)
        td.ty = results.get("ty", 0.0)
        td.ta = results.get("ta", 0.0)
        td.valid = results.get("tv", 0) == 1

        # Fiducial (AprilTag) data
        fiducials = results.get("Fiducial", [])
        if fiducials:
            f = fiducials[0]
            td.tag_id = int(f.get("fID", -1))
            td.pitch_deg = f.get("t6r_fs", [0]*6)[0] if len(f.get("t6r_fs", [])) > 0 else 0.0
            td.yaw_deg   = f.get("t6r_fs", [0]*6)[1] if len(f.get("t6r_fs", [])) > 1 else 0.0
            td.roll_deg  = f.get("t6r_fs", [0]*6)[2] if len(f.get("t6r_fs", [])) > 2 else 0.0

        # Robot pose (botpose_wpiblue or botpose)
        botpose = results.get("botpose_wpiblue", results.get("botpose", []))
        if len(botpose) >= 6:
            td.pose_x, td.pose_y, td.pose_z = botpose[0], botpose[1], botpose[2]
            td.pose_yaw = botpose[5]

        td.latency_ms = results.get("tl", 0.0) + results.get("cl", 0.0)

        if td.valid:
            td.distance_meters = calculate_distance(td.ty)
            td.distance_feet   = td.distance_meters * 3.28084
            td.distance_inches = td.distance_meters * 39.3701
    except Exception as e:
        print(f"[HTTP parse error] {e}")
    return td
```

# ═══════════════════════════════════════════════════════════════════════════════

# NETWORKTABLES CLIENT  (on-robot / competition use)

# ═══════════════════════════════════════════════════════════════════════════════

class LimelightNT:
def **init**(self, server_ip: str, table_name: str):
if not NT_AVAILABLE:
raise RuntimeError(“ntcore not available”)
self.inst = NetworkTableInstance.getDefault()
self.inst.setServerTeam(254)  # fallback; overridden below
self.inst.startClient4(“limelight-tracker”)
self.inst.setServer(server_ip)
self.table = self.inst.getTable(table_name)
print(f”[NT] Connecting to {server_ip}…”)

```
def parse(self) -> TagData:
    td = TagData(timestamp=time.time(), source="networktables")
    try:
        td.tx     = self.table.getEntry("tx").getDouble(0.0)
        td.ty     = self.table.getEntry("ty").getDouble(0.0)
        td.ta     = self.table.getEntry("ta").getDouble(0.0)
        td.valid  = self.table.getEntry("tv").getDouble(0) == 1.0
        td.tag_id = int(self.table.getEntry("tid").getDouble(-1))

        botpose = self.table.getEntry("botpose_wpiblue").getDoubleArray([])
        if len(botpose) >= 6:
            td.pose_x, td.pose_y, td.pose_z = botpose[0], botpose[1], botpose[2]
            td.pose_yaw = botpose[5]
            td.latency_ms = botpose[6] if len(botpose) > 6 else 0.0

        if td.valid:
            td.distance_meters = calculate_distance(td.ty)
            td.distance_feet   = td.distance_meters * 3.28084
            td.distance_inches = td.distance_meters * 39.3701
    except Exception as e:
        print(f"[NT parse error] {e}")
    return td
```

# ═══════════════════════════════════════════════════════════════════════════════

# TRACKER  — polls both sources, merges best result

# ═══════════════════════════════════════════════════════════════════════════════

class LimelightTracker:
def **init**(self, use_http=True, use_nt=True):
self._lock = threading.Lock()
self._latest = TagData()
self._history = []   # last 100 readings
self._http_client: Optional[LimelightHTTP] = None
self._nt_client:   Optional[LimelightNT]   = None

```
    if use_http:
        self._http_client = LimelightHTTP(Config.LIMELIGHT_IP, Config.LIMELIGHT_HTTP_PORT)
        print(f"[HTTP] Polling http://{Config.LIMELIGHT_IP}:{Config.LIMELIGHT_HTTP_PORT}")

    if use_nt and NT_AVAILABLE:
        try:
            self._nt_client = LimelightNT(Config.NT_SERVER_IP, Config.NT_TABLE)
        except Exception as e:
            print(f"[NT] Failed to init: {e}")

    self._thread = threading.Thread(target=self._poll_loop, daemon=True)
    self._thread.start()

def _poll_loop(self):
    interval = 1.0 / Config.POLL_HZ
    while True:
        td = TagData(timestamp=time.time())

        # Try HTTP first
        if self._http_client:
            raw = self._http_client.get_results()
            if raw is not None:
                td = self._http_client.parse(raw)

        # NT overrides if it has a valid target
        if self._nt_client:
            nt_td = self._nt_client.parse()
            if nt_td.valid:
                td = nt_td

        with self._lock:
            self._latest = td
            self._history.append(asdict(td))
            if len(self._history) > 100:
                self._history.pop(0)

        time.sleep(interval)

def get_latest(self) -> TagData:
    with self._lock:
        return self._latest

def get_history(self) -> list:
    with self._lock:
        return list(self._history)
```

# ═══════════════════════════════════════════════════════════════════════════════

# FLASK DASHBOARD

# ═══════════════════════════════════════════════════════════════════════════════

DASHBOARD_HTML = “””<!DOCTYPE html>

<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Limelight AprilTag Tracker</title>
<link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Exo+2:wght@300;600;800&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #090c10;
    --panel: #0d1117;
    --border: #1e2d3d;
    --accent: #00e5ff;
    --accent2: #ff6b35;
    --green: #39ff14;
    --red: #ff2d55;
    --text: #c9d1d9;
    --dim: #4a5568;
    --glow: 0 0 12px rgba(0,229,255,0.4);
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'Exo 2', sans-serif;
    min-height: 100vh;
    overflow-x: hidden;
  }
  /* Scanline overlay */
  body::before {
    content: '';
    position: fixed; inset: 0;
    background: repeating-linear-gradient(0deg,transparent,transparent 2px,rgba(0,0,0,0.07) 2px,rgba(0,0,0,0.07) 4px);
    pointer-events: none; z-index: 1000;
  }

header {
display: flex; align-items: center; justify-content: space-between;
padding: 18px 32px;
border-bottom: 1px solid var(–border);
background: linear-gradient(90deg, rgba(0,229,255,0.05), transparent);
}
.logo { display: flex; align-items: center; gap: 12px; }
.logo-icon {
width: 40px; height: 40px;
border: 2px solid var(–accent); border-radius: 8px;
display: grid; place-items: center;
font-size: 20px;
box-shadow: var(–glow);
}
h1 { font-size: 1.4rem; font-weight: 800; letter-spacing: 0.08em; color: #fff; }
h1 span { color: var(–accent); }
.status-pill {
display: flex; align-items: center; gap: 8px;
padding: 6px 16px; border-radius: 20px;
border: 1px solid var(–border);
font-family: ‘Share Tech Mono’, monospace; font-size: 0.8rem;
}
.dot {
width: 8px; height: 8px; border-radius: 50%;
background: var(–dim); transition: background 0.3s;
}
.dot.live { background: var(–green); box-shadow: 0 0 6px var(–green); animation: pulse 1.5s infinite; }
.dot.dead { background: var(–red); }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }

main { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 20px; padding: 28px 32px; }

/* Cards */
.card {
background: var(–panel);
border: 1px solid var(–border);
border-radius: 12px;
padding: 20px;
position: relative;
overflow: hidden;
transition: border-color 0.3s;
}
.card::after {
content: ‘’; position: absolute; top: 0; left: 0; right: 0; height: 2px;
background: linear-gradient(90deg, transparent, var(–accent), transparent);
opacity: 0.5;
}
.card.detected { border-color: var(–accent); box-shadow: var(–glow); }
.card.span2 { grid-column: span 2; }
.card.span3 { grid-column: span 3; }
.card-label {
font-size: 0.7rem; font-weight: 600; letter-spacing: 0.15em;
color: var(–dim); text-transform: uppercase; margin-bottom: 12px;
}
.big-value {
font-family: ‘Share Tech Mono’, monospace;
font-size: 3rem; font-weight: 600; color: #fff; line-height: 1;
transition: color 0.3s;
}
.big-value.active { color: var(–accent); text-shadow: var(–glow); }
.big-unit { font-size: 1rem; color: var(–dim); margin-left: 4px; }

/* Metrics grid */
.metrics { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.metric { background: rgba(255,255,255,0.03); border-radius: 8px; padding: 12px 14px; }
.metric-label { font-size: 0.65rem; letter-spacing: 0.12em; color: var(–dim); text-transform: uppercase; margin-bottom: 6px; }
.metric-value { font-family: ‘Share Tech Mono’, monospace; font-size: 1.3rem; color: var(–accent2); }
.metric-value.ok { color: var(–accent); }

/* Compass */
.compass-wrap { display: flex; align-items: center; justify-content: center; padding: 10px; }
.compass {
width: 120px; height: 120px; border-radius: 50%;
border: 2px solid var(–border);
position: relative; display: grid; place-items: center;
background: radial-gradient(circle, rgba(0,229,255,0.04) 0%, transparent 70%);
}
.compass-needle {
width: 2px; height: 50px; background: linear-gradient(to top, var(–red), var(–accent));
position: absolute; transform-origin: bottom center;
bottom: 50%; left: calc(50% - 1px);
border-radius: 2px;
transition: transform 0.3s ease;
}
.compass-center { width: 8px; height: 8px; border-radius: 50%; background: #fff; position: absolute; z-index: 2; }
.compass-labels { position: absolute; width: 100%; height: 100%; }
.compass-labels span {
position: absolute; font-size: 0.65rem; font-family: ‘Share Tech Mono’, monospace;
color: var(–dim);
}
.cn { top: 4px; left: 50%; transform: translateX(-50%); }
.cs { bottom: 4px; left: 50%; transform: translateX(-50%); }
.ce { right: 6px; top: 50%; transform: translateY(-50%); }
.cw { left: 6px; top: 50%; transform: translateY(-50%); }

/* History chart */
.chart-area { height: 100px; position: relative; }
canvas#distChart { width: 100%; height: 100%; }

/* Pose table */
.pose-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.pose-item { text-align: center; }
.pose-item .metric-label { margin-bottom: 4px; }
.pose-item .pose-val {
font-family: ‘Share Tech Mono’, monospace;
font-size: 1.1rem; color: var(–accent2);
}

/* Footer */
footer { padding: 14px 32px; border-top: 1px solid var(–border); display: flex; justify-content: space-between; align-items: center; }
.footer-info { font-size: 0.72rem; color: var(–dim); font-family: ‘Share Tech Mono’, monospace; }

/* No target overlay */
.no-target {
position: absolute; inset: 0; display: flex; flex-direction: column;
align-items: center; justify-content: center; gap: 8px;
background: rgba(9,12,16,0.7); border-radius: 12px;
opacity: 0; transition: opacity 0.4s; pointer-events: none;
}
.no-target.show { opacity: 1; }
.no-target-icon { font-size: 2rem; filter: grayscale(1) opacity(0.4); }
.no-target-text { font-size: 0.75rem; color: var(–dim); letter-spacing: 0.1em; text-transform: uppercase; }

@media (max-width: 900px) {
main { grid-template-columns: 1fr 1fr; }
.card.span3 { grid-column: span 2; }
}
</style>

</head>
<body>
<header>
  <div class="logo">
    <div class="logo-icon">🎯</div>
    <div>
      <h1>LIME<span>LIGHT</span> TRACKER</h1>
      <div style="font-size:0.7rem;color:var(--dim);letter-spacing:0.1em">APRILTAG · DISTANCE · POSE</div>
    </div>
  </div>
  <div class="status-pill">
    <div class="dot" id="statusDot"></div>
    <span id="statusText">CONNECTING</span>
  </div>
</header>

<main>
  <!-- Tag ID -->
  <div class="card" id="tagCard">
    <div class="card-label">Detected Tag ID</div>
    <div class="big-value" id="tagId">—</div>
    <div style="margin-top:10px;font-size:0.75rem;color:var(--dim)" id="tagSub">No target</div>
  </div>

  <!-- Distance -->

  <div class="card" id="distCard">
    <div class="card-label">Distance to Target</div>
    <div class="big-value" id="distVal">—<span class="big-unit">m</span></div>
    <div style="margin-top:8px; display:flex; gap:16px;">
      <span style="font-family:'Share Tech Mono',monospace;font-size:0.9rem;color:var(--dim)" id="distFt">— ft</span>
      <span style="font-family:'Share Tech Mono',monospace;font-size:0.9rem;color:var(--dim)" id="distIn">— in</span>
    </div>
  </div>

  <!-- Compass / Heading -->

  <div class="card">
    <div class="card-label">Horizontal Offset (tx)</div>
    <div class="compass-wrap">
      <div class="compass">
        <div class="compass-labels">
          <span class="cn">N</span><span class="cs">S</span>
          <span class="ce">E</span><span class="cw">W</span>
        </div>
        <div class="compass-needle" id="compassNeedle"></div>
        <div class="compass-center"></div>
      </div>
    </div>
    <div style="text-align:center;font-family:'Share Tech Mono',monospace;font-size:1.1rem;color:var(--accent)" id="txVal">0.0°</div>
  </div>

  <!-- Angles -->

  <div class="card span2">
    <div class="card-label">Camera Angles</div>
    <div class="metrics">
      <div class="metric">
        <div class="metric-label">TX (horizontal)</div>
        <div class="metric-value ok" id="txMetric">0.00°</div>
      </div>
      <div class="metric">
        <div class="metric-label">TY (vertical)</div>
        <div class="metric-value ok" id="tyMetric">0.00°</div>
      </div>
      <div class="metric">
        <div class="metric-label">Target Area</div>
        <div class="metric-value" id="taMetric">0.00%</div>
      </div>
      <div class="metric">
        <div class="metric-label">Latency</div>
        <div class="metric-value" id="latMetric">0 ms</div>
      </div>
    </div>
  </div>

  <!-- Tag Pose -->

  <div class="card">
    <div class="card-label">Tag Orientation</div>
    <div class="metrics">
      <div class="metric">
        <div class="metric-label">Pitch</div>
        <div class="metric-value" id="pitchVal">0.0°</div>
      </div>
      <div class="metric">
        <div class="metric-label">Yaw</div>
        <div class="metric-value" id="yawVal">0.0°</div>
      </div>
    </div>
  </div>

  <!-- Robot Pose -->

  <div class="card span3">
    <div class="card-label">Robot Field Pose (WPILib Blue Origin)</div>
    <div class="pose-grid">
      <div class="pose-item">
        <div class="metric-label">X</div>
        <div class="pose-val" id="poseX">0.000 m</div>
      </div>
      <div class="pose-item">
        <div class="metric-label">Y</div>
        <div class="pose-val" id="poseY">0.000 m</div>
      </div>
      <div class="pose-item">
        <div class="metric-label">Z</div>
        <div class="pose-val" id="poseZ">0.000 m</div>
      </div>
      <div class="pose-item">
        <div class="metric-label">Heading</div>
        <div class="pose-val" id="poseYaw">0.0°</div>
      </div>
    </div>
  </div>

  <!-- Distance History -->

  <div class="card span3">
    <div class="card-label">Distance History (last 100 readings)</div>
    <div class="chart-area">
      <canvas id="distChart"></canvas>
    </div>
  </div>
</main>

<footer>
  <span class="footer-info" id="sourceInfo">source: —</span>
  <span class="footer-info" id="tsInfo">—</span>
  <span class="footer-info">↻ 20 Hz POLL</span>
</footer>

<script>
const API = '/api/latest';
const HIST = '/api/history';
let distHistory = [];

async function fetchData() {
  try {
    const [latRes, histRes] = await Promise.all([fetch(API), fetch(HIST)]);
    const data = await latRes.json();
    const hist = await histRes.json();
    update(data);
    updateChart(hist);
  } catch(e) {}
}

function update(d) {
  const valid = d.valid;
  // Status
  const dot = document.getElementById('statusDot');
  const stxt = document.getElementById('statusText');
  dot.className = 'dot ' + (d.source !== 'none' ? 'live' : 'dead');
  stxt.textContent = d.source !== 'none' ? d.source.toUpperCase() + ' LIVE' : 'NO SIGNAL';

  // Tag ID
  const tagCard = document.getElementById('tagCard');
  document.getElementById('tagId').textContent = valid && d.tag_id >= 0 ? d.tag_id : '—';
  document.getElementById('tagId').className = 'big-value' + (valid ? ' active' : '');
  document.getElementById('tagSub').textContent = valid ? 'Tag in view ✓' : 'No target';
  tagCard.className = 'card' + (valid ? ' detected' : '');

  // Distance
  const distCard = document.getElementById('distCard');
  document.getElementById('distVal').innerHTML = valid
    ? d.distance_meters.toFixed(2) + '<span class="big-unit">m</span>'
    : '—<span class="big-unit">m</span>';
  document.getElementById('distVal').className = 'big-value' + (valid ? ' active' : '');
  document.getElementById('distFt').textContent = valid ? d.distance_feet.toFixed(1) + ' ft' : '— ft';
  document.getElementById('distIn').textContent = valid ? d.distance_inches.toFixed(0) + ' in' : '— in';
  distCard.className = 'card' + (valid ? ' detected' : '');

  // Compass
  const tx = d.tx || 0;
  document.getElementById('compassNeedle').style.transform = `rotate(${tx}deg)`;
  document.getElementById('txVal').textContent = tx.toFixed(1) + '°';

  // Metrics
  document.getElementById('txMetric').textContent = d.tx.toFixed(2) + '°';
  document.getElementById('tyMetric').textContent = d.ty.toFixed(2) + '°';
  document.getElementById('taMetric').textContent = d.ta.toFixed(2) + '%';
  document.getElementById('latMetric').textContent = d.latency_ms.toFixed(0) + ' ms';

  // Orientation
  document.getElementById('pitchVal').textContent = d.pitch_deg.toFixed(1) + '°';
  document.getElementById('yawVal').textContent = d.yaw_deg.toFixed(1) + '°';

  // Pose
  document.getElementById('poseX').textContent = d.pose_x.toFixed(3) + ' m';
  document.getElementById('poseY').textContent = d.pose_y.toFixed(3) + ' m';
  document.getElementById('poseZ').textContent = d.pose_z.toFixed(3) + ' m';
  document.getElementById('poseYaw').textContent = d.pose_yaw.toFixed(1) + '°';

  // Footer
  document.getElementById('sourceInfo').textContent = 'source: ' + d.source;
  document.getElementById('tsInfo').textContent = new Date(d.timestamp * 1000).toLocaleTimeString();
}

// Mini canvas chart
function updateChart(hist) {
  const canvas = document.getElementById('distChart');
  const ctx = canvas.getContext('2d');
  canvas.width = canvas.offsetWidth;
  canvas.height = canvas.offsetHeight;
  const W = canvas.width, H = canvas.height;

  const dists = hist.map(h => h.valid ? h.distance_meters : null);
  const valid = dists.filter(v => v !== null);
  if (valid.length < 2) return;

  const maxD = Math.max(...valid, 5);
  const minD = 0;

  ctx.clearRect(0, 0, W, H);

  // Grid
  ctx.strokeStyle = 'rgba(255,255,255,0.05)';
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = H - (i / 4) * H;
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
  }

  // Line
  ctx.beginPath();
  ctx.strokeStyle = '#00e5ff';
  ctx.lineWidth = 2;
  ctx.shadowColor = '#00e5ff';
  ctx.shadowBlur = 6;
  let first = true;
  dists.forEach((d, i) => {
    if (d === null) { first = true; return; }
    const x = (i / (dists.length - 1)) * W;
    const y = H - ((d - minD) / (maxD - minD)) * H;
    if (first) { ctx.moveTo(x, y); first = false; }
    else ctx.lineTo(x, y);
  });
  ctx.stroke();

  // Fill
  ctx.shadowBlur = 0;
  ctx.beginPath();
  ctx.fillStyle = 'rgba(0,229,255,0.07)';
  let firstFill = true;
  dists.forEach((d, i) => {
    if (d === null) return;
    const x = (i / (dists.length - 1)) * W;
    const y = H - ((d - minD) / (maxD - minD)) * H;
    if (firstFill) { ctx.moveTo(x, H); ctx.lineTo(x, y); firstFill = false; }
    else ctx.lineTo(x, y);
  });
  ctx.lineTo(W, H); ctx.closePath(); ctx.fill();
}

fetchData();
setInterval(fetchData, 80);  // ~12 Hz refresh
</script>

</body>
</html>
"""

def create_app(tracker: LimelightTracker) -> Flask:
app = Flask(**name**)
CORS(app)

```
@app.route("/")
def dashboard():
    return DASHBOARD_HTML

@app.route("/api/latest")
def latest():
    return jsonify(asdict(tracker.get_latest()))

@app.route("/api/history")
def history():
    return jsonify(tracker.get_history())

return app
```

# ═══════════════════════════════════════════════════════════════════════════════

# MAIN

# ═══════════════════════════════════════════════════════════════════════════════

def main():
parser = argparse.ArgumentParser(description=“Limelight AprilTag Tracker”)
parser.add_argument(”–no-http”,   action=“store_true”, help=“Disable HTTP polling”)
parser.add_argument(”–no-nt”,     action=“store_true”, help=“Disable NetworkTables”)
parser.add_argument(”–limelight”, default=Config.LIMELIGHT_IP, help=“Limelight IP”)
parser.add_argument(”–rio”,       default=Config.NT_SERVER_IP, help=“RoboRIO / NT server IP”)
parser.add_argument(”–port”,      type=int, default=Config.DASHBOARD_PORT, help=“Dashboard port”)
args = parser.parse_args()

```
Config.LIMELIGHT_IP  = args.limelight
Config.NT_SERVER_IP  = args.rio

print("=" * 60)
print("  Limelight AprilTag Tracker")
print("=" * 60)
print(f"  Limelight IP : {Config.LIMELIGHT_IP}")
print(f"  NT Server    : {Config.NT_SERVER_IP}")
print(f"  Camera height: {Config.CAMERA_HEIGHT_METERS} m")
print(f"  Camera pitch : {Config.CAMERA_PITCH_DEGREES}°")
print(f"  Target height: {Config.TARGET_HEIGHT_METERS} m")
print(f"  Dashboard    : http://localhost:{args.port}")
print("=" * 60)

tracker = LimelightTracker(
    use_http=not args.no_http,
    use_nt=not args.no_nt
)
app = create_app(tracker)
app.run(host="0.0.0.0", port=args.port, debug=False, use_reloader=False)
```

if **name** == “**main**”:
main()
