"""Localhost depth + point-cloud browser preview — self-contained in the extension.

A Replicator ``distance_to_image_plane`` annotator on each camera yields a metric
depth array every frame; the latest frame per camera is buffered as 16-bit
millimetres and a small threaded HTTP server hands it to the browser, which
colour-maps depth over each camera's near/far range and back-projects an
interactive 3D point cloud — all client-side.  Independent of the ROS graphs, so it
runs alongside variant publishing (or on its own).

Annotator reads happen only on the app update thread; the HTTP thread just serves
the buffered bytes under a lock (Kit is not thread-safe).
"""
import carb
import omni.kit.app

PORT = 8211                 # served at http://localhost:<port>/
HZ = 10                     # frame refresh rate (Hz)
MAX_W = None                # None -> full camera resolution; else cap preview width

_HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>e-con DepthVista — depth viewer</title>
<style>
 body{background:#111;color:#ddd;font:13px system-ui,sans-serif;margin:16px}
 h1{font-size:16px;font-weight:600}
 .cams{display:flex;flex-wrap:wrap;gap:18px}
 .cam{background:#1b1b1b;border:1px solid #333;border-radius:8px;padding:10px}
 .cam h2{font-size:13px;margin:0 0 6px}
 .cam canvas{image-rendering:pixelated;background:#000;border-radius:4px;cursor:crosshair;width:100%;height:auto}
 .read{margin-top:6px;font-variant-numeric:tabular-nums}
 .read b{color:#7ec8ff}
 .ctl{display:flex;align-items:center;gap:8px;margin:8px 0;font-size:12px;color:#aaa;flex-wrap:wrap}
 select,button{background:#222;color:#ddd;border:1px solid #444;border-radius:4px;padding:3px 8px}
 input[type=range]{width:110px}
 .pick{display:inline-flex;flex-wrap:wrap;gap:12px}
 .pick label{cursor:pointer}
 .pcards{display:flex;flex-wrap:wrap;gap:16px}
 .pcard{background:#1b1b1b;border:1px solid #333;border-radius:8px;padding:10px}
 .pcl-canvas{width:460px;height:360px;display:block;background:#0a0a0a;
   border:1px solid #333;border-radius:6px;margin-top:8px;cursor:grab}
 .info{color:#7ec8ff}
</style>
<script type="importmap">
{ "imports": { "three": "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js" } }
</script>
</head><body>
<h1>e-con DepthVista — live depth (colour = distance)</h1>
<div class="cams" id="cams"></div>

<h1 style="margin-top:26px">Point clouds (colour = distance)</h1>
<div class="ctl">cameras: <span id="pcl-pick" class="pick"></span></div>
<div class="pcards" id="pcl-cards"></div>

<script>
const HZ = __HZ__;
function hsv(h){ // h in [0,360) -> [r,g,b] 0..255, full sat/val
  const c=1, x=1-Math.abs((h/60)%2-1);
  let r,g,b;
  if(h<60){r=c;g=x;b=0}else if(h<120){r=x;g=c;b=0}else if(h<180){r=0;g=c;b=x}
  else if(h<240){r=0;g=x;b=c}else if(h<300){r=x;g=0;b=c}else{r=c;g=0;b=x}
  return [r*255,g*255,b*255];
}
async function initTiles(){
  const cams = await (await fetch('cameras.json')).json();
  const root = document.getElementById('cams');
  for(const cam of cams){
    const W=cam.width, H=cam.height;
    const box=document.createElement('div'); box.className='cam';
    box.innerHTML=`<h2>${cam.label}  <span style="color:#888">${W}×${H}</span></h2>`;
    const cv=document.createElement('canvas'); cv.width=W; cv.height=H; cv.style.maxWidth='480px';
    const ctx=cv.getContext('2d'); const img=ctx.createImageData(W,H);
    const read=document.createElement('div'); read.className='read'; read.textContent='—';
    box.append(cv,read); root.append(box);
    const near=cam.near*1000, far=Math.max(cam.far*1000, near+1), span=far-near;
    const centre={x:(W>>1), y:(H>>1)};
    let hover=null, clicked=null, last=null;
    const toPix=e=>({x:Math.min(W-1,Math.max(0,Math.floor(e.offsetX/cv.clientWidth*W))),
                     y:Math.min(H-1,Math.max(0,Math.floor(e.offsetY/cv.clientHeight*H)))});
    cv.onmousemove=e=>hover=toPix(e);
    cv.onmouseleave=()=>hover=null;
    cv.onclick=e=>clicked=toPix(e);
    async function tick(){
      try{
        const buf=await (await fetch('depth/'+cam.id+'?t='+Date.now())).arrayBuffer();
        last=new Uint16Array(buf); const px=img.data;
        for(let i=0;i<last.length;i++){
          const v=last[i], o=i*4;
          if(!v){px[o]=px[o+1]=px[o+2]=18; px[o+3]=255; continue;}
          let t=(v-near)/span; t=t<0?0:t>1?1:t;
          const c=hsv(t*240);               // near = red, far = blue
          px[o]=c[0]; px[o+1]=c[1]; px[o+2]=c[2]; px[o+3]=255;
        }
        ctx.putImageData(img,0,0);
        const p = hover||clicked||centre;
        const src = hover?'cursor':clicked?'clicked':'centre';
        const mm = last[p.y*W+p.x];
        read.innerHTML = `(${p.x}, ${p.y}) <span style="color:#777">${src}</span> → `+
          (mm?`<b>${(mm/1000).toFixed(3)} m</b>`:`<b>no return</b>`);
      }catch(_){}
    }
    setInterval(tick, 1000/HZ);
  }
}
initTiles();
</script>

<script type="module">
import * as THREE from 'three';
import { OrbitControls } from 'https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/controls/OrbitControls.js';

const HZ = __HZ__;
const STRIDE = 2;                 // sub-sample pixels to keep each cloud light
function hsv(h){
  const c=1, x=1-Math.abs((h/60)%2-1);
  let r,g,b;
  if(h<60){r=c;g=x;b=0}else if(h<120){r=x;g=c;b=0}else if(h<180){r=0;g=c;b=x}
  else if(h<240){r=0;g=x;b=c}else if(h<300){r=x;g=0;b=c}else{r=c;g=0;b=x}
  return [r*255,g*255,b*255];
}

const cardsWrap=document.getElementById('pcl-cards');
const pick=document.getElementById('pcl-pick');
let CAMS=[]; const cards=new Map();

class PclCard{
  constructor(cam){
    this.cam=cam; this.alive=true; this.needFrame=true;
    this.opt=null; this.rgb=null; this.n=0;
    const card=document.createElement('div'); card.className='pcard';
    card.innerHTML=`<div class="ctl"><b>${cam.label}</b>`+
      ` point <input type="range" class="ps" min="1" max="6" step="0.5" value="2">`+
      ` <button class="dl">Download .ply</button> <span class="info"></span></div>`;
    const canvas=document.createElement('canvas'); canvas.className='pcl-canvas';
    card.append(canvas); cardsWrap.append(card);
    this.dom=card; this.info=card.querySelector('.info');

    const renderer=new THREE.WebGLRenderer({canvas, antialias:true});
    renderer.setPixelRatio(Math.min(devicePixelRatio,2));
    const scene=new THREE.Scene(); scene.background=new THREE.Color(0x0a0a0a);
    const view=new THREE.PerspectiveCamera(50,1,0.01,200); view.position.set(0,0,2);
    const controls=new OrbitControls(view, renderer.domElement); controls.enableDamping=true;
    const geom=new THREE.BufferGeometry();
    const mat=new THREE.PointsMaterial({size:2, sizeAttenuation:false, vertexColors:true});
    scene.add(new THREE.Points(geom, mat));
    Object.assign(this,{renderer,scene,view,controls,geom,mat});

    card.querySelector('.ps').oninput=e=>mat.size=+e.target.value;
    card.querySelector('.dl').onclick=()=>this.download();
    this._resize=()=>{ const w=canvas.clientWidth||460,h=canvas.clientHeight||360;
      renderer.setSize(w,h,false); view.aspect=w/h; view.updateProjectionMatrix(); };
    new ResizeObserver(this._resize).observe(canvas);
    this.poll=setInterval(()=>this.tick(), 1000/HZ);
    this._resize();
    const loop=()=>{ if(!this.alive) return; requestAnimationFrame(loop);
      controls.update(); renderer.render(scene,view); };
    loop();
  }
  async tick(){
    try{ const buf=await (await fetch('depth/'+this.cam.id+'?t='+Date.now())).arrayBuffer();
         this.build(new Uint16Array(buf)); }catch(_){}
  }
  build(d){
    const c=this.cam, W=c.width, H=c.height, fx=c.fx, fy=c.fy, cx=c.cx, cy=c.cy;
    const near=c.near, far=Math.max(c.far, near+0.01), span=far-near;
    const maxN=Math.ceil(W/STRIDE)*Math.ceil(H/STRIDE);
    const pos=new Float32Array(maxN*3), col=new Float32Array(maxN*3);
    const opt=new Float32Array(maxN*3), rgb=new Uint8Array(maxN*3);
    let n=0;
    for(let v=0; v<H; v+=STRIDE){
      for(let u=0; u<W; u+=STRIDE){
        const mm=d[v*W+u]; if(!mm) continue;
        const Z=mm/1000, dx=(u-cx)/fx, dy=(v-cy)/fy;
        const X=dx*Z, Y=dy*Z;
        opt[n*3]=X; opt[n*3+1]=Y; opt[n*3+2]=Z;
        pos[n*3]=X; pos[n*3+1]=-Y; pos[n*3+2]=-Z;
        let t=(Z-near)/span; t=t<0?0:t>1?1:t;
        const cc=hsv(t*240);              // near = red, far = blue
        col[n*3]=cc[0]/255; col[n*3+1]=cc[1]/255; col[n*3+2]=cc[2]/255;
        rgb[n*3]=cc[0]; rgb[n*3+1]=cc[1]; rgb[n*3+2]=cc[2]; n++;
      }
    }
    this.geom.setAttribute('position', new THREE.BufferAttribute(pos.subarray(0,n*3),3));
    this.geom.setAttribute('color',    new THREE.BufferAttribute(col.subarray(0,n*3),3));
    this.opt=opt; this.rgb=rgb; this.n=n;
    this.info.textContent = n.toLocaleString()+' points';
    if(this.needFrame && n>0){
      this.geom.computeBoundingSphere(); const s=this.geom.boundingSphere;
      const r=Math.max(s.radius,0.05);
      this.controls.target.copy(s.center);
      this.view.position.set(s.center.x, s.center.y, s.center.z + r*2.2);
      this.view.near=Math.max(r/100,0.001); this.view.far=r*100;
      this.view.updateProjectionMatrix();
      this.controls.minDistance=r*0.15; this.controls.maxDistance=r*25;
      this.controls.update(); this.needFrame=false;
    }
  }
  download(){
    if(!this.n) return; const n=this.n, o=this.opt, g=this.rgb;
    const head='ply\\nformat ascii 1.0\\nelement vertex '+n+
      '\\nproperty float x\\nproperty float y\\nproperty float z'+
      '\\nproperty uchar red\\nproperty uchar green\\nproperty uchar blue\\nend_header\\n';
    const rows=new Array(n);
    for(let i=0;i<n;i++) rows[i]=o[i*3].toFixed(4)+' '+o[i*3+1].toFixed(4)+' '+o[i*3+2].toFixed(4)+
      ' '+g[i*3]+' '+g[i*3+1]+' '+g[i*3+2];
    const blob=new Blob([head+rows.join('\\n')+'\\n'], {type:'application/octet-stream'});
    const a=document.createElement('a'); a.href=URL.createObjectURL(blob);
    a.download=this.cam.id+'.ply'; a.click(); URL.revokeObjectURL(a.href);
  }
  destroy(){ this.alive=false; clearInterval(this.poll);
    removeEventListener('resize', this._resize); this.renderer.dispose(); this.dom.remove(); }
}

function sync(){
  const want=new Set([...pick.querySelectorAll('input:checked')].map(i=>i.value));
  for(const [id,card] of cards) if(!want.has(id)){ card.destroy(); cards.delete(id); }
  for(const id of want) if(!cards.has(id)){ cards.set(id, new PclCard(CAMS.find(c=>c.id===id))); }
}
(async function init(){
  CAMS = await (await fetch('cameras.json')).json();
  CAMS.forEach((c,i)=>{
    const lab=document.createElement('label');
    const cb=document.createElement('input'); cb.type='checkbox'; cb.value=c.id; cb.checked=(i===0);
    cb.onchange=sync; lab.append(cb, document.createTextNode(' '+c.label)); pick.append(lab);
  });
  sync();
})();
</script>
</body></html>"""


class WebViewer:
    """Serve a live, colour-mapped depth preview of every camera over localhost.

    ``units`` = [{"unit_id": str, "cams": {key: {"path": str, "params": dict}}}].
    """

    def __init__(self, units):
        import threading
        import json
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import numpy as np
        import omni.replicator.core as rep

        self._np = np
        self._lock = threading.Lock()
        self._frames = {}            # cam_id -> latest uint16-LE depth bytes
        self._cams = []
        self._last_pull = 0.0
        self._sub = None
        self._httpd = None

        for unit in units:
            for key, cam in unit["cams"].items():
                p = cam["params"]
                fw, fh = int(p["width"]), int(p["height"])
                if MAX_W and fw > MAX_W:
                    scale = MAX_W / float(fw)
                    vw, vh = max(1, int(fw * scale)), max(1, int(fh * scale))
                else:
                    scale, vw, vh = 1.0, fw, fh
                try:
                    rp = rep.create.render_product(cam["path"], (vw, vh))
                    annot = rep.AnnotatorRegistry.get_annotator("distance_to_image_plane")
                    annot.attach(rp)
                except Exception as exc:
                    carb.log_warn(f"[econ.itof.ros] web annotator failed for {cam['path']}: {exc}")
                    continue
                self._cams.append(dict(
                    id=f"{unit['unit_id']}_{key}", label=f"{unit['unit_id']}  {key}",
                    width=vw, height=vh, near=p["near_m"], far=p["far_m"],
                    fx=p["fx"] * scale, fy=p["fy"] * scale,
                    cx=p["cx"] * scale, cy=p["cy"] * scale, annot=annot))

        if not self._cams:
            raise RuntimeError("no camera annotators could be created")

        meta = [{k: c[k] for k in ("id", "label", "width", "height",
                                   "near", "far", "fx", "fy", "cx", "cy")}
                for c in self._cams]
        html = _HTML.replace("__HZ__", str(int(HZ)))
        viewer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, ctype, body):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                path = self.path.split("?", 1)[0]
                if path in ("/", "/index.html"):
                    self._send(200, "text/html; charset=utf-8", html.encode())
                elif path == "/cameras.json":
                    self._send(200, "application/json", json.dumps(meta).encode())
                elif path.startswith("/depth/"):
                    cam_id = path[len("/depth/"):]
                    with viewer._lock:
                        buf = viewer._frames.get(cam_id)
                    if buf is None:
                        self._send(503, "text/plain", b"warming up")
                    else:
                        self._send(200, "application/octet-stream", buf)
                else:
                    self._send(404, "text/plain", b"not found")

        self._httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        self._sub = omni.kit.app.get_app().get_update_event_stream() \
            .create_subscription_to_pop(self._on_update, name="ros2_itof_webviewer")
        carb.log_info(f"[econ.itof.ros] web viewer at http://localhost:{PORT}/ "
                      f"({len(self._cams)} camera(s))")

    def _on_update(self, _):
        import time
        now = time.monotonic()
        if now - self._last_pull < 1.0 / max(1, HZ):
            return
        self._last_pull = now
        np = self._np
        for cam in self._cams:
            try:
                data = cam["annot"].get_data()
            except Exception:
                continue
            arr = np.asarray(data, dtype=np.float32)
            if arr.size == 0:
                continue
            mm = arr.copy()
            mm[~np.isfinite(mm)] = 0.0
            mm = np.clip(mm * 1000.0, 0, 65535).astype("<u2")
            with self._lock:
                self._frames[cam["id"]] = mm.tobytes()

    def destroy(self):
        self._sub = None
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception:
                pass
            self._httpd = None
        for cam in self._cams:
            try:
                cam["annot"].detach()
            except Exception:
                pass
        self._cams = []
