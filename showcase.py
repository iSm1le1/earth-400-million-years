#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the clean Showcase edition of the deep-time map."""
from pathlib import Path
import json
import math

HERE = Path(__file__).resolve().parent


def _angle_lerp(a, b, u):
    d = (b - a + 180) % 360 - 180
    return a + d * u


def _interp(age, ages, values):
    """Interpolate a descending Ma keyframe track."""
    if age >= ages[0]:
        return values[0]
    if age <= ages[-1]:
        return values[-1]
    for i in range(len(ages) - 1):
        hi, lo = ages[i], ages[i + 1]
        if hi >= age >= lo:
            u = (hi - age) / (hi - lo)
            a, b = values[i], values[i + 1]
            return (_angle_lerp(a[0], b[0], u), a[1] + (b[1] - a[1]) * u)
    return values[-1]


def _blob(cx, cy, rx, ry, rotation, seed, points=72):
    """Draw an organic continent silhouette without crossing the map seam."""
    out = []
    cr, sr = math.cos(rotation), math.sin(rotation)
    for i in range(points):
        a = 2 * math.pi * i / points
        wave = 1 + .10 * math.sin(3 * a + seed) + .055 * math.cos(7 * a - seed * .7)
        x, y = rx * wave * math.cos(a), ry * wave * math.sin(a)
        out.append([round(cx + x * cr - y * sr, 3), round(cy + x * sr + y * cr, 3)])
    return out


def _build_original_model():
    """Create the showcase's own stylised deep-time plate model.

    This is intentionally an authored visual model rather than a copy of the
    previous project's coastline dataset. It keeps the broad tectonic story
    legible while guaranteeing clean, seam-free polygons for a web demo.
    """
    ages = [400, 300, 250, 180, 100, 50, 0]
    # Positions are hand-authored keyframes in lon/lat. The independent masses
    # converge around 250 Ma and then drift apart into the modern arrangement.
    defs = {
        'North America': ([( -105, 22), (-100, 25), (-92, 29), (-100, 36), (-108, 40), (-105, 43), (-105, 43)], (38, 21), .16, 1.1),
        'South America': ([( -28, -34), (-25, -30), (-18, -28), (-42, -25), (-55, -18), (-60, -12), (-61, -12)], (27, 37), -.20, 2.7),
        'Africa': ([( 18, -27), (20, -24), (22, -18), (18, -7), (20, 2), (22, 8), (23, 8)], (30, 27), .08, 3.4),
        'Europe': ([( -5, 31), (0, 34), (8, 38), (14, 45), (18, 50), (16, 52), (15, 52)], (29, 14), -.12, 4.9),
        'Asia': ([( 72, 28), (78, 31), (88, 34), (96, 40), (104, 48), (105, 52), (104, 52)], (55, 23), .10, 6.2),
        'India': ([( 55, -25), (58, -20), (64, -11), (72, 2), (78, 12), (79, 20), (79, 20)], (15, 11), -.38, 7.5),
        'Australia': ([( 92, -32), (98, -30), (110, -28), (125, -27), (136, -26), (140, -25), (140, -25)], (28, 17), .18, 8.8),
        # Keep the authored polar plate inside the viewport. This avoids
        # canvas-edge clipping that can read as a stray vertical seam.
        'Antarctica': ([( 30, -64), (32, -65), (30, -67), (25, -69), (22, -70), (20, -70), (20, -70)], (42, 10), -.05, 10.1),
    }
    slices = []
    for age in range(400, -1, -5):
        rings = []
        for name, (track, size, spin, seed) in defs.items():
            cx, cy = _interp(age, ages, track)
            # Slightly larger, warmer silhouettes in the deep past; breakup
            # gradually sharpens the modern outlines.
            u = (400 - age) / 400
            rx, ry = size[0] * (1.05 - .06 * u), size[1] * (1.03 - .04 * u)
            rings.append(_blob(cx, cy, rx, ry, spin + (u - .5) * .22, seed))
        area = sum(math.pi * (d[1][0] * d[1][1]) for d in defs.values()) * (1.02 - .05 * ((400 - age) / 400))
        slices.append({
            'time_Ma': age,
            'land': rings,
            'holes': [],
            'vertex_count': sum(len(r) for r in rings),
            'metrics': {
                'land_area_km2': round(area * 17400),
                'comp_frac': round(.68 + .24 * math.exp(-((age - 250) / 115) ** 2), 4),
                'n_comp': 4 if age <= 30 else (5 if age <= 100 else (7 if age <= 190 else 4)),
            },
        })
    marker_specs = [
        ('纽约', 'North America', -4, 4), ('里约', 'South America', -5, -3),
        ('开普敦', 'Africa', 2, -4), ('北京', 'Asia', 3, 5),
        ('孟买', 'India', 0, 0), ('悉尼', 'Australia', 4, -1),
    ]
    markers = []
    for label, mass, dx, dy in marker_specs:
        track = defs[mass][0]
        markers.append({'name': label, 'track': [
            {'lon': round(_interp(age, ages, track)[0] + dx, 2),
             'lat': round(_interp(age, ages, track)[1] + dy, 2)}
            for age in range(400, -1, -5)
        ]})
    events = [
        {'time_Ma': 400, 'title': '陆块开始在南纬汇聚'},
        {'time_Ma': 340, 'title': '海洋通道重新打开'},
        {'time_Ma': 300, 'title': '大陆桥逐渐连成一片'},
        {'time_Ma': 250, 'title': '超级大陆 · 汇聚峰值'},
        {'time_Ma': 180, 'title': '裂谷从内部撕开'},
        {'time_Ma': 100, 'title': '大西洋拉开距离'},
        {'time_Ma': 50, 'title': '印度撞上亚洲'},
        {'time_Ma': 0, 'title': '我们所处的地球'},
    ]
    return {'meta': {'model': 'original-authored-plate-drift'}, 'slices': slices, 'markers': markers, 'events': events}


earth = _build_original_model()

HTML = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>深时漂移台 · 地球的四亿年</title>
<style>
:root{--bg:#05090f;--panel:#0b1420;--line:#203247;--text:#e8f0ed;--muted:#8195a0;--amber:#ffc857;--cyan:#74e0d0;--land:#b9ccc5;--land2:#9bb5ad}
*{box-sizing:border-box}html,body{margin:0;width:100%;height:100%;overflow:hidden;background:var(--bg);color:var(--text);font:13px/1.5 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}
#app{position:relative;width:100%;height:100%;overflow:hidden;background:radial-gradient(ellipse at 55% 42%,#102331 0,#07111b 47%,#05090f 100%)}
canvas{position:absolute;inset:0;width:100%;height:100%;display:block}#map{cursor:crosshair}
#top{position:absolute;inset:0 0 auto;height:72px;display:flex;align-items:center;padding:0 30px;gap:18px;z-index:5;background:linear-gradient(180deg,rgba(5,9,15,.98),rgba(5,9,15,.2));pointer-events:none}
.brand{font-size:18px;font-weight:700;letter-spacing:.08em;color:var(--amber);white-space:nowrap}.brand small{font-size:10px;font-weight:500;color:var(--muted);letter-spacing:.02em;margin-left:10px}
#age{font-variant-numeric:tabular-nums;font-size:30px;font-weight:700;color:#fff;margin-left:auto}#age small{font-size:12px;color:var(--amber);font-weight:600;margin-left:4px}
#chapter{max-width:31vw;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}#chapter b{color:var(--amber);font-weight:600}
#play{pointer-events:auto;border:1px solid #496276;background:#102131;color:var(--amber);border-radius:999px;width:42px;height:32px;font-size:15px;cursor:pointer}#play:hover{background:#18334a}
#stageInfo{position:absolute;left:30px;top:104px;z-index:4;max-width:330px;pointer-events:none}.eyebrow{color:var(--cyan);font-size:10px;letter-spacing:.22em;text-transform:uppercase}.hero{margin-top:8px;font-size:26px;line-height:1.15;font-weight:700;letter-spacing:.02em}.sub{margin-top:10px;color:var(--muted);max-width:300px}
#readout{position:absolute;right:30px;top:102px;width:238px;padding:14px 16px;z-index:4;background:rgba(8,17,27,.72);border:1px solid rgba(89,122,139,.35);border-radius:14px;backdrop-filter:blur(12px)}
#readout .k{color:var(--muted);font-size:10px;letter-spacing:.12em;margin-bottom:7px}#readout .v{font-size:18px;color:var(--amber);font-weight:700}#readout .meta{margin-top:8px;color:var(--muted);font-size:11px;line-height:1.7}#readout .meta b{color:var(--text);font-weight:600}
#timeline{position:absolute;left:30px;right:30px;bottom:28px;height:70px;z-index:6;padding:0 2px}.track{position:absolute;left:0;right:0;top:26px;height:2px;background:#294052}.fill{position:absolute;left:0;top:26px;height:2px;background:linear-gradient(90deg,var(--amber),var(--cyan));transform-origin:left}.knob{position:absolute;top:17px;width:20px;height:20px;border-radius:50%;background:var(--amber);border:4px solid #08121b;box-shadow:0 0 0 1px var(--amber),0 0 20px #ffc85799;transform:translateX(-10px);pointer-events:none}.ticks{position:absolute;left:0;right:0;top:36px;display:flex;justify-content:space-between;color:#718793;font-size:10px;pointer-events:none}.ticks b{color:var(--text);font-weight:500}.eventDot{position:absolute;top:21px;width:10px;height:10px;margin-left:-5px;border-radius:50%;background:#e5a34f;border:2px solid #07101a;pointer-events:none}.eventDot span{display:none;position:absolute;top:13px;left:50%;transform:translateX(-50%);white-space:nowrap;color:var(--muted);font-size:10px}.eventDot:hover span{display:block}
#tip{position:absolute;left:30px;bottom:108px;color:#647b87;font-size:11px;z-index:4;pointer-events:none}.hintkey{display:inline-block;border:1px solid #385064;border-radius:4px;padding:1px 5px;color:#a9bbc2;margin:0 3px}
@media(max-width:800px){#top{padding:0 16px;height:60px}.brand{font-size:14px}.brand small,#chapter{display:none}#age{font-size:24px}.hero{font-size:20px}.sub{display:none}#stageInfo{left:18px;top:82px}#readout{right:18px;top:78px;width:190px;padding:10px 12px}#timeline{left:18px;right:18px}.ticks{font-size:9px}}
</style></head><body><main id="app"><canvas id="map"></canvas>
<header id="top"><div class="brand">深时漂移台<small>DEEP TIME OBSERVATORY · ORIGINAL PLATE STUDY</small></div><div id="age">0<small>Ma</small></div><div id="chapter"></div><button id="play" aria-label="播放时间轴">▶</button></header>
<section id="stageInfo"><div class="eyebrow">A LIVING PLANET · 400 Ma → NOW</div><div class="hero">大陆没有停下，<br>只是漂得很慢。</div><div class="sub">一套为 Showcase 创作的板块轨迹模型：拖动时间轴，看八个陆块如何汇聚、裂开，再漂到今天。</div></section>
<aside id="readout"><div class="k">CURRENT FRAME</div><div class="v" id="rTitle">现代地球</div><div class="meta" id="rMeta"></div></aside>
<div id="tip"><span class="hintkey">←</span><span class="hintkey">→</span> 步进 5 Ma · <span class="hintkey">空格</span> 播放 · 点击城市查看轨迹</div>
<section id="timeline"><div class="track"></div><div class="fill" id="fill"></div><div class="knob" id="knob"></div><div class="ticks"><b>400 Ma</b><span>300</span><span>200</span><span>100</span><b>现在</b></div><div id="events"></div></section>
</main><script>
const DATA=__DATA__, SL=DATA.slices, MK=DATA.markers, EV=DATA.events;
const C={bg:'#05090f',land:'#b9ccc5',land2:'#9bb5ad',amber:'#ffc857',cyan:'#74e0d0',muted:'#8195a0'};
const canvas=document.getElementById('map'),ctx=canvas.getContext('2d'),landCanvas=document.createElement('canvas'),landCtx=landCanvas.getContext('2d');let dpr=1,w=0,h=0,cur=(()=>{const m=location.hash.match(/(\d+)/),t=m?Number(m[1]):0;return Math.max(0,Math.min(SL.length-1,Math.round((400-t)/5)))})(),timer=null,drag=false;
const age=document.getElementById('age'),chapter=document.getElementById('chapter'),rTitle=document.getElementById('rTitle'),rMeta=document.getElementById('rMeta'),fill=document.getElementById('fill'),knob=document.getElementById('knob');
const names=Object.fromEntries(MK.map(m=>[m.name,m])); let selected=null,hover=null;
function resize(){const r=canvas.getBoundingClientRect();dpr=Math.min(2,devicePixelRatio||1);canvas.width=r.width*dpr;canvas.height=r.height*dpr;landCanvas.width=canvas.width;landCanvas.height=canvas.height;w=r.width;h=r.height;ctx.setTransform(dpr,0,0,dpr,0,0);landCtx.setTransform(dpr,0,0,dpr,0,0);draw()}
function project(lon,lat){const top=72,bottom=102,range=164;return [(lon+180)/360*w,top+(82-lat)/range*Math.max(1,h-top-bottom)]}
function safe(p){return [p[0],Math.max(-86.5,Math.min(86.5,p[1]))]}
function frame(){return SL[cur]}
function paint(){ctx.clearRect(0,0,w,h);ctx.fillStyle=C.bg;ctx.fillRect(0,0,w,h);const s=frame();
  // Every plate exists in every frame. We render opaque, closed paths and
  // keep them inside a padded latitude window so no canvas edge can create a
  // fake coastline or make a plate appear to blink out.
  landCtx.clearRect(0,0,w,h);landCtx.fillStyle=C.land;landCtx.globalAlpha=1;
  for(const ring of s.land){landCtx.beginPath();for(let i=0;i<ring.length;i++){const p=safe(ring[i]);if(i===0)landCtx.moveTo(...project(...p));else landCtx.lineTo(...project(...p))}landCtx.closePath();landCtx.fill()}
  ctx.drawImage(landCanvas,0,0,w,h);
  for(const m of MK){const p=m.track[cur],q=project(p.lon,p.lat),hot=selected===m.name||hover===m.name;ctx.beginPath();ctx.arc(q[0],q[1],hot?6:4,0,Math.PI*2);ctx.fillStyle=hot?C.amber:C.cyan;ctx.fill();ctx.strokeStyle=C.bg;ctx.lineWidth=2;ctx.stroke();if(hot){ctx.font='12px sans-serif';ctx.fillStyle='#e8f0ed';ctx.fillText(m.name,q[0]+10,q[1]-8)}}
}
function update(){const s=frame(),t=s.time_Ma,ratio=(400-t)/400;age.innerHTML=`${t}<small>Ma</small>`;const e=EV.filter(x=>x.time_Ma>=t).pop()||EV[EV.length-1];chapter.innerHTML=`<b>${e.time_Ma} Ma</b> · ${e.title}`;rTitle.textContent=t===0?'现代地球':e.title;rMeta.innerHTML=`陆地面积 <b>${(s.metrics.land_area_km2/1e8).toFixed(2)} 亿 km²</b><br>连通率 <b>${(s.metrics.comp_frac*100).toFixed(1)}%</b><br>陆块分量 <b>${s.metrics.n_comp}</b>`;fill.style.width=(ratio*100)+'%';knob.style.left=(ratio*100)+'%';paint()}
function draw(){resize._busy=true;paint();update()}
function setIndex(i){cur=Math.max(0,Math.min(SL.length-1,i));update()}
function atX(x){const r=document.getElementById('timeline').getBoundingClientRect();const ratio=Math.max(0,Math.min(1,(x-r.left)/r.width));return Math.round((SL.length-1)*(1-ratio))}
function play(){if(timer){clearInterval(timer);timer=null;document.getElementById('play').textContent='▶';return}if(cur===0)cur=SL.length-1;document.getElementById('play').textContent='Ⅱ';timer=setInterval(()=>{if(cur<=0){clearInterval(timer);timer=null;document.getElementById('play').textContent='▶';return}setIndex(cur-1)},120)}
document.getElementById('play').onclick=play;const tl=document.getElementById('timeline');tl.onpointerdown=e=>{drag=true;tl.setPointerCapture(e.pointerId);setIndex(atX(e.clientX))};tl.onpointermove=e=>{if(drag)setIndex(atX(e.clientX))};tl.onpointerup=()=>drag=false;
window.onkeydown=e=>{if(e.target.closest('input,select,button'))return;if(e.key==='ArrowLeft')setIndex(cur+1);if(e.key==='ArrowRight')setIndex(cur-1);if(e.key===' ') {e.preventDefault();play()}};
canvas.onclick=e=>{const r=canvas.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top;let best=null,bd=14;for(const m of MK){const p=m.track[cur],q=project(p.lon,p.lat),d=Math.hypot(q[0]-x,q[1]-y);if(d<bd){bd=d;best=m.name}}selected=best;update()};canvas.onmousemove=e=>{const r=canvas.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top;let best=null,bd=14;for(const m of MK){const p=m.track[cur],q=project(p.lon,p.lat),d=Math.hypot(q[0]-x,q[1]-y);if(d<bd){bd=d;best=m.name}}if(best!==hover){hover=best;paint()}};
for(const e of EV){const d=document.createElement('i');d.className='eventDot';d.style.left=((400-e.time_Ma)/400*100)+'%';d.title=e.title;d.innerHTML=`<span>${e.time_Ma} Ma</span>`;document.getElementById('events').appendChild(d)}
window.onresize=resize;resize();
</script></body></html>'''

out = HTML.replace('__DATA__', json.dumps(earth, ensure_ascii=False, separators=(',', ':')))
(HERE / 'preview.html').write_text(out, encoding='utf-8')
print(f'[write] {HERE / "preview.html"} ({len(out)/1e6:.1f} MB)')
