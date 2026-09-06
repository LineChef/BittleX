#!/usr/bin/env python3
"""Live camera preview + on-demand capture for the Grove Vision AI V2.

Opens the module over USB serial, applies the low-light settings (480 capture +
auto-exposure lift), runs whatever detection model is loaded, and serves a live
feed with the detection box drawn at http://localhost:8080. While "Start
capturing" is armed it saves clean frames (no overlay) plus a `.json` sidecar
carrying the detection boxes -- the input `tools/curate_captures.py` needs for
pre-labels.

    python tools/camera_preview.py            # start the preview server
    python tools/camera_preview.py --info      # print port + loaded model, exit
    python tools/camera_preview.py --help

Environment variables (all optional):
    G2_CAM_PORT    serial device      (default: first /dev/cu.usbmodem*)
    G2_CAP_OUT     where to save       (default: ~/Desktop/g2_face_capture)
    G2_CAP_LABEL   filename prefix     (default: self)  -> <label>_0001.jpg
    G2_CAM_RES     sensor option       0=240x240  1=480x480 (default)  2=640x480
    G2_CAM_AEBUMP  auto-exposure lift  hex/int, default 0x30; 0 disables

Deps (dev machine): pyserial, Pillow.  Stop with:  pkill -f camera_preview.py
"""
import base64
import glob
import io
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import serial
from PIL import Image, ImageDraw

_ports = glob.glob("/dev/cu.usbmodem*")
PORT_SERIAL = os.environ.get("G2_CAM_PORT") or (_ports[0] if _ports else "/dev/cu.usbmodem58FA1045341")
BAUD = 921600
HTTP_PORT = 8080
OUT = os.environ.get("G2_CAP_OUT") or os.path.expanduser("~/Desktop/g2_face_capture")
LABEL = os.environ.get("G2_CAP_LABEL", "self")
CAM_RES = os.environ.get("G2_CAM_RES", "1")
AE_BUMP = int(os.environ.get("G2_CAM_AEBUMP", "0x30"), 0)

state = {
    "jpg": b"", "capturing": False, "saved": 0,
    "every": 4,          # save 1 of every N frames while capturing (~15 fps -> ~4/s)
    "_seen": 0, "fps": 0.0, "label": LABEL,
    "ndet": 0, "last_score": 0, "hit_frames": 0, "tot_frames": 0,
}


def _open():
    s = serial.Serial(PORT_SERIAL, BAUD, timeout=0.4)
    time.sleep(2.0)
    s.reset_input_buffer()
    return s


def _apply_camera_settings(s):
    """480 capture + OV5647 auto-exposure lift (WPT/BPT target regs). Stock
    Himax tuning aims dim (~0x32/0x24); +0x30 lifts the face a lot. Runtime
    only -- re-applied every start."""
    if CAM_RES in ("0", "1", "2"):
        s.write(f"AT+SENSOR=1,1,{CAM_RES}\r\n".encode())    # id, enable, opt
        time.sleep(0.8)
        s.reset_input_buffer()
    if AE_BUMP:
        for a, v in (("3A0F", 0x32), ("3A10", 0x24), ("3A1B", 0x32), ("3A1E", 0x24)):
            s.write(f'AT+SETREG="0x{a}","0x{min(0xF0, v + AE_BUMP):02X}"\r\n'.encode())
            time.sleep(0.25)
        s.reset_input_buffer()


def info_and_exit():
    """--info: which port, which model is on the module, sensor state."""
    print(f"port      : {PORT_SERIAL}")
    if not _ports:
        print("status    : NO /dev/cu.usbmodem* -- camera unplugged, or a Chrome/"
              "SenseCraft tab still owns the port (close it)")
        return
    try:
        s = _open()
    except Exception as e:
        print(f"status    : cannot open -- {e}  (close the SenseCraft tab)")
        return
    def ask(c, w=0.5):
        s.write((c + "\r\n").encode()); time.sleep(w)
        return s.read(8192).decode("utf-8", "replace").strip()
    ask("AT+SENSOR=1,1,1", 0.8)
    try:
        blob = json.loads(ask("AT+INFO?"))["data"]["info"]
        d = json.loads(base64.b64decode(blob + "=" * (-len(blob) % 4)).decode("utf-8", "replace"))
        print(f"model     : {d.get('name') or d.get('model_id')}  "
              f"classes={d.get('classes')}  custom={d.get('isCustom')}")
    except Exception:
        print("model     : (could not read AT+INFO?)")
    print(f"sensor    : {ask('AT+SENSOR?')[:160]}")
    s.close()


def serial_loop():
    s = _open()
    _apply_camera_settings(s)
    s.write(b"AT+INVOKE=-1,0,0\r\n")          # loop inference, results WITH jpeg
    buf, tprev = b"", time.time()
    while True:
        buf += s.read(32768)
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.strip()
            if not line.startswith(b"{"):
                continue
            try:
                m = json.loads(line.decode("utf-8", "replace"))
            except json.JSONDecodeError:
                continue
            if m.get("name") != "INVOKE" or m.get("type") != 1:
                continue
            data = m.get("data", {})
            img = data.get("image")
            if not img:
                continue
            raw = base64.b64decode(img)
            clean_raw = raw                       # frame WITHOUT overlay (for training)
            boxes = data.get("boxes", []) or []
            resolution = data.get("resolution", [240, 240])
            state["ndet"] = len(boxes)
            state["tot_frames"] += 1
            if boxes:
                state["hit_frames"] += 1
                state["last_score"] = max(int(b[4]) for b in boxes)
                try:                             # draw the detections for the preview
                    im = Image.open(io.BytesIO(raw)).convert("RGB")
                    d = ImageDraw.Draw(im)
                    for b in boxes:
                        cx, cy, w, h, sc = b[0], b[1], b[2], b[3], b[4]
                        d.rectangle([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2],
                                    outline=(0, 255, 0), width=2)
                        d.text((cx - w / 2 + 2, cy - h / 2 + 2), f"{sc}", fill=(0, 255, 0))
                    out = io.BytesIO()
                    im.save(out, "JPEG", quality=80)
                    raw = out.getvalue()
                except Exception:
                    pass
            state["jpg"] = raw
            now = time.time()
            state["fps"] = 0.8 * state["fps"] + 0.2 * (1.0 / max(1e-3, now - tprev))
            tprev = now
            if state["capturing"]:
                state["_seen"] += 1
                if state["_seen"] % state["every"] == 0:
                    state["saved"] += 1
                    existing = len([f for f in os.listdir(OUT) if f.endswith(".jpg")])
                    stem = f"{OUT}/{state['label']}_{existing + 1:04d}"
                    with open(stem + ".jpg", "wb") as f:
                        f.write(clean_raw)                  # clean frame
                    with open(stem + ".json", "w") as f:   # sidecar for curate
                        json.dump({"resolution": resolution, "boxes": boxes}, f)


PAGE = """<!doctype html><meta charset=utf-8><title>G2 camera capture</title>
<style>
 body{background:#111;color:#eee;font:14px system-ui;text-align:center;margin:0;padding:18px}
 #v{width:min(90vw,520px);border-radius:8px;transform:rotate(90deg);
    transform-origin:center;margin:40px 0}
 button{font:600 15px system-ui;padding:10px 18px;margin:4px;border:0;border-radius:8px;cursor:pointer}
 .go{background:#2f7d4f;color:#fff}.stop{background:#b23b34;color:#fff}.rot{background:#444;color:#eee}
 #s{margin-top:8px;font-family:ui-monospace,monospace;color:#9ad}
 .hint{color:#888;max-width:480px;margin:10px auto;line-height:1.5}
</style>
<h2>G2 camera capture &mdash; live preview</h2>
<img id=v src="/frame.jpg">
<div>
 <button class=go onclick="fetch('/start').then(u)">Start capturing</button>
 <button class=stop onclick="fetch('/stop').then(u)">Stop</button>
 <button class=rot onclick="rot()">Rotate view</button>
</div>
<div id=s>...</div>
<p class=hint>The preview is rotated so you look upright. Check whether the
<b>raw</b> feed (rotate back to 0&deg;) is upright &mdash; if not, physically
rotate the camera module so its native output is upright, and note that as the
mount orientation. Frame your face to fill a good chunk; vary distance, angle,
lighting between short bursts.</p>
<script>
 let r=90;
 function rot(){r=(r+90)%360;document.getElementById('v').style.transform='rotate('+r+'deg)'}
 async function u(res){let j=await res.json();
   let hr = j.tot_frames? (100*j.hit_frames/j.tot_frames).toFixed(0):'0';
   document.getElementById('s').innerHTML=
     '<b style="color:'+(j.ndet?'#4f4':'#888')+'">'+
     (j.ndet? j.ndet+' DETECTED  score '+j.last_score : 'no detection')+'</b>'+
     '  &nbsp; hit-rate '+hr+'%  &nbsp; '+j.fps.toFixed(1)+' fps'+
     (j.capturing?'  &nbsp; ● CAPTURING saved '+j.saved:'')}
 setInterval(()=>{document.getElementById('v').src='/frame.jpg?t='+Date.now()},90);
 setInterval(()=>fetch('/status').then(u),700);
</script>
"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({k: state[k] for k in
            ("capturing", "saved", "fps", "ndet", "last_score", "hit_frames", "tot_frames")
        }).encode())

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(PAGE.encode())
        elif p == "/frame.jpg":
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(state["jpg"])
        elif p in ("/start", "/stop"):
            state["capturing"] = (p == "/start")
            self._json()
        elif p == "/status":
            self._json()
        else:
            self.send_response(404); self.end_headers()


def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__); return
    if "--info" in sys.argv:
        info_and_exit(); return
    if not _ports:
        print("no /dev/cu.usbmodem* -- plug the camera in, or close the "
              "SenseCraft/Chrome tab that owns the port.")
        return
    threading.Thread(target=serial_loop, daemon=True).start()
    print(f"preview -> http://localhost:{HTTP_PORT}   saving to {OUT}   "
          f"(prefix {LABEL}_*, sensor opt {CAM_RES}, AE +{hex(AE_BUMP)})")
    ThreadingHTTPServer(("127.0.0.1", HTTP_PORT), H).serve_forever()


if __name__ == "__main__":
    main()
