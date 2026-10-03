#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
《地球的四亿年》观察仪 —— make_preview.py

读 build.py 产出的 earth.json / checks.json，内联进一个自包含的 preview.html
（离线打开，不调任何 API）。这一版按高级视觉指令重做：

    · 地图全屏当主角，顶栏 52px 只放标题/时间/事件/播放/方法入口
    · 左侧窄的半透明浮动时间轴（400 在上，0 在下），事件节点可点
    · 默认干净：没有七条轨迹乱线、没有双城虚线；轨迹与详情都靠点击揭示
    · 右侧抽屉按需打开（事件/现代地标/方法），地图保持可见
    · 分析功能：双时代对比、事件故事、地图内事件导航
    · 曲线左 400 Ma 右 0 Ma

    .venv/bin/python make_preview.py
前置：先跑 .venv/bin/python build.py。
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EARTH_PATH = os.path.join(HERE, "earth.json")
CHECKS_PATH = os.path.join(HERE, "checks.json")
OUT_PATH = os.path.join(HERE, "preview.html")

TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>地球的四亿年 · 观察仪</title>
<style>
  :root{
    --bg:#060B12; --bg2:#0B1420; --fg:#EAF2F5; --fg2:#91A7B6;
    --land:#C7D9D2; --coast:#6E8D86; --grid:#243448;
    --time:#FFD166; --event:#FFB86B; --city:#66E3D1; --limit:#EF8A7A; --data:#7DD3FC;
  }
  *{box-sizing:border-box}
  html,body{margin:0;height:100%;overflow:hidden;background:var(--bg);color:var(--fg);
    font:13px/1.5 -apple-system,"SF Pro Text","PingFang SC","Microsoft YaHei",sans-serif}
  #top{height:52px;display:flex;align-items:center;gap:14px;padding:0 16px;
    background:linear-gradient(180deg,#0B1420,#080F18);border-bottom:1px solid #16222F;position:relative;z-index:4}
  /* 窄屏：顶栏允许横向滚动（按钮缩成图标仍可够着），而不是被裁掉 */
  @media (max-width:900px){
    #top{overflow-x:auto;scrollbar-width:none;padding:0 10px;gap:10px}   /* 实在极窄时允许横向滚到 buttons，而非裁掉 */
    #top::-webkit-scrollbar{display:none}
  }
  #top .brand{font-size:15px;font-weight:700;color:var(--time);letter-spacing:1px;white-space:nowrap}
  #top .brand .sub{font-weight:400;font-size:11px;color:var(--fg2);margin-left:8px;letter-spacing:0}
  #clock{font-size:16px;font-weight:700;color:var(--time);font-variant-numeric:tabular-nums;white-space:nowrap;
    padding:3px 8px;border:1px solid #273C50;border-radius:6px;background:#0E1A29}
  #clock small{font-size:11px;color:var(--fg2);font-weight:400}
  #era{display:none}
  #era b{color:var(--event);font-weight:600}
  .sp{flex:1}
  button{background:#111E2E;color:var(--fg);border:1px solid #243A52;border-radius:6px;
    padding:5px 11px;cursor:pointer;font-size:12px;white-space:nowrap}
  button:hover{background:#1A2C44;border-color:#3A5A76}
  button.on{background:#1B3346;border-color:var(--time);color:var(--time)}
  button:disabled{opacity:.35;cursor:not-allowed;border-color:#243A52;color:var(--fg2)}
  #stage{position:absolute;inset:52px 0 0 0;overflow:hidden}
  #stage canvas{position:absolute;inset:0;width:100%;height:100%;display:block}
  #cv{cursor:crosshair}                      /* 其余层不挡事件 */
  #cvBg,#cvGrat,#cvLand,#cvCoast{pointer-events:none}
  /* 左侧浮动时间轴 */
  #tl{position:absolute;left:18px;top:22px;bottom:58px;width:60px;z-index:3;
    background:rgba(11,20,32,.78);border:1px solid #213246;border-radius:18px;backdrop-filter:blur(8px);
    cursor:ns-resize;touch-action:none;user-select:none}                /* 可点可拖 */
  #tl .axis{position:absolute;top:4%;bottom:4%;left:29px;width:1px;background:#314256;pointer-events:none}
  #tl .tick{position:absolute;left:0;right:0;height:1px;pointer-events:none}
  #tl .tick:before{content:'';position:absolute;left:23px;top:0;width:12px;height:1px;background:#52677C}
  #tl .tick span{position:absolute;left:5px;top:-7px;width:17px;text-align:right;font-size:9px;color:#8296A7}
  #tl .end{position:absolute;left:0;right:0;text-align:center;font-size:10px;color:var(--fg2);pointer-events:none}
  #tl .end.top{top:7px} #tl .end.bot{bottom:7px}
  #tlCur{position:absolute;left:20px;width:19px;height:19px;top:50%;margin-top:-9px;
    border:2px solid var(--time);border-radius:50%;background:#0B1420;box-shadow:0 0 12px rgba(255,209,102,.35);pointer-events:none}
  .tlEv{position:absolute;left:25px;width:9px;height:2px;border-radius:2px;
    background:#607487;cursor:pointer;transform:translateY(-1px)}
  .tlEv.cur{left:22px;width:15px;background:var(--time);box-shadow:0 0 8px rgba(255,209,102,.55)}
  #tlSplice{display:none}
  #tlTip{position:fixed;z-index:9;display:none;background:#0E1A29;border:1px solid #2C445E;border-radius:8px;
    padding:8px 10px;max-width:250px;pointer-events:none;font-size:12px;box-shadow:0 6px 24px #000a}
  #tlTip b{color:var(--event)}
  #eventPeek{position:absolute;left:94px;top:16px;width:min(360px,34vw);z-index:3;
    padding:10px 13px;background:linear-gradient(135deg,rgba(11,20,32,.94),rgba(11,20,32,.72));
    border:1px solid #2B4055;border-left:3px solid var(--event);border-radius:9px;
    box-shadow:0 8px 26px #0006;backdrop-filter:blur(10px);cursor:pointer}
  #eventPeek .k{font-size:10px;color:var(--event);letter-spacing:.08em;text-transform:uppercase}
  #eventPeek .t{margin-top:2px;font-size:14px;font-weight:700;color:var(--fg)}
  #eventPeek .x{margin-top:3px;color:var(--fg2);font-size:11px;line-height:1.45;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
  #eventPeek .evEvidence{display:none;margin-top:9px;padding-top:8px;border-top:1px solid #26394D;color:var(--data);font-size:11px;line-height:1.45}
  #eventPeek.expanded{width:min(460px,42vw);max-height:220px;overflow:auto;border-color:#39546C;box-shadow:0 12px 34px #0009}
  #eventPeek.expanded .x{display:block;-webkit-line-clamp:unset}
  #eventPeek.expanded .evEvidence{display:block}
  #eventPeek:hover{border-color:#58728B;transform:translateY(-1px)}
  /* 右上主控台：播放与数据说明聚在同一组 */
  #tools{position:absolute;top:16px;right:18px;z-index:3;display:flex;align-items:center;gap:4px;
    padding:5px;background:rgba(11,20,32,.9);border:1px solid #26394D;border-radius:8px;
    box-shadow:0 6px 22px #0005;backdrop-filter:blur(10px)}
  #tools button{padding:6px 10px;background:transparent;border-color:transparent}
  #tools button:hover{background:#1A2C44;border-color:#304A63}
  #tools .toolSep{height:22px;width:1px;background:#2A3B4E;margin:0 3px}
  /* 对比面板 */
  #cmpPanel{position:absolute;left:50%;transform:translateX(-50%);top:12px;z-index:3;display:none;
    gap:8px;align-items:center;background:rgba(11,20,32,.7);border:1px solid #1B2B40;border-radius:10px;padding:6px 10px}
  #cmpPanel.show{display:flex}
  #cmpPanel label{font-size:11px;color:var(--fg2)}
  /* 展示版只保留时间轴和地图分析；故事内容融入当前事件卡片。 */
  #storyBtn,#cmpBtn,#cmpPanel,#banner{display:none!important}
  /* 底部指标条 */
  #hud{position:absolute;left:0;right:0;bottom:0;height:38px;display:flex;align-items:center;justify-content:center;
    gap:0;z-index:2;pointer-events:none;font-size:12px;color:var(--fg2);
    background:linear-gradient(0deg,rgba(6,11,18,.85),rgba(6,11,18,0))}
  #polarMask{position:absolute;left:0;right:0;bottom:0;height:64px;z-index:1;pointer-events:none;
    background:linear-gradient(180deg,rgba(6,11,18,.35),#060B12 28%,#060B12)}
  #hud .h{padding:0 14px;border-left:1px solid #1C2A3A;white-space:nowrap}
  #hud .h:first-child{border:none}
  #hud b{color:var(--fg);font-variant-numeric:tabular-nums}
  #hud .ph{color:var(--time)}
  #hud .warn{color:var(--limit)}
  /* 故事旁白 */
  #banner{position:absolute;left:50%;bottom:54px;transform:translateX(-50%);z-index:6;display:none;
    width:min(620px,90vw);background:rgba(11,20,32,.92);border:1px solid #2C445E;border-radius:12px;
    padding:14px 18px;box-shadow:0 10px 40px #000c}
  #banner.show{display:block}
  #banner .bT{font-size:14px;font-weight:700;color:var(--time);margin-bottom:4px}
  #banner .bX{font-size:12.5px;color:var(--fg);max-height:88px;overflow:auto}
  #banner .bE{font-size:11px;color:var(--data);margin-top:6px;border-top:1px solid #1C2A3A;padding-top:6px}
  #banner .row{display:flex;gap:8px;margin-top:10px}
  #hint{position:absolute;right:14px;bottom:44px;z-index:2;font-size:11px;color:#54687A;pointer-events:none}
  /* 右侧抽屉 */
  #drawer{position:absolute;top:0;right:0;bottom:0;width:380px;max-width:94vw;z-index:5;
    background:rgba(11,20,32,.96);border-left:1px solid #22364E;transform:translateX(106%);
    transition:transform .25s ease;display:flex;flex-direction:column;backdrop-filter:blur(8px)}
  #drawer.open{transform:none}
  #tabs{display:none}
  #dBody{flex:1;overflow-y:auto;padding:14px 16px}
  #dClose{position:absolute;top:6px;right:8px;background:none;border:none;color:var(--fg2);font-size:15px;cursor:pointer;z-index:1}
  .dSec{margin-bottom:16px}
  .dSec h3{margin:0 0 4px;font-size:15px;color:var(--time)}
  .dSec .tm{color:var(--fg2);font-size:12px;margin-bottom:6px}
  .evBox{background:#101A29;border:1px solid #22344C;border-radius:8px;padding:10px 12px;margin-bottom:10px;font-size:12px}
  .lbl{font-size:10px;color:#5D7085;letter-spacing:1px;margin:10px 0 4px}
  .note{font-size:11px;color:var(--fg2);margin-top:8px}
  table{border-collapse:collapse;width:100%;font-size:12px}
  td,th{padding:4px 6px;border-bottom:1px solid #1A2636;text-align:right}
  th{color:var(--fg2);font-weight:400;text-align:left}
  select{background:#111E2E;color:var(--fg);border:1px solid #243A52;border-radius:6px;padding:3px 6px;font-size:12px}
  svg text{fill:var(--fg2);font-size:10px}
  .limit{margin-bottom:8px;padding-left:12px;border-left:2px solid #3A5A76;font-size:12px}
  .limit b{color:var(--limit)}
  @media (max-width:760px){
    #top .brand .sub{display:none} #era{display:none}
    #top .bt{display:none}                   /* B10：窄屏按钮只留符号，全部装得下 */
    #play,#storyBtn,#cmpBtn,#mvBtn{padding:5px 9px}
    #top .brand{font-size:13px}
    #tl{width:54px;left:6px}
    #tl .axis{left:26px} #tl .tick:before{left:20px;width:10px} #tl .tick span{left:3px}
    #tlCur{left:17px;width:19px}
    #tools{top:10px;right:8px;gap:1px;padding:4px}
    #tools button{padding:6px 7px}
    #eventPeek{left:72px;top:12px;width:min(300px,calc(100vw - 86px))}
    #eventPeek.expanded{width:min(330px,calc(100vw - 86px));max-height:190px}
    .h:nth-child(n+4){display:none}
  }
</style></head><body>
<div id="top">
  <div class="brand">地球的四亿年<span class="sub">Merdith et al. 2021 · CC-BY 3.0 · 0–400 Ma · 81 切片（每 5 Ma）</span></div>
  <div id="clock"><b>0</b><small> Ma</small></div>
  <div id="era"></div>
  <div class="sp"></div>
  <button id="storyBtn" aria-label="开始地球故事">✦ <span class="bt">开始地球故事</span></button>
  <button id="cmpBtn" aria-label="对比两个时代">◫ <span class="bt">对比两个时代</span></button>
</div>
<div id="stage">
  <!-- 图层栈：背景/海洋 → 经纬网 → 陆地填充 → 海岸描边 → 特效与交互 -->
  <canvas id="cvBg" aria-hidden="true"></canvas>
  <canvas id="cvGrat" aria-hidden="true"></canvas>
  <canvas id="cvLand" aria-hidden="true"></canvas>
  <canvas id="cvCoast" aria-hidden="true"></canvas>
  <canvas id="cv" role="img" aria-label="古地理地图：Merdith 2021 板块重建 0–400 Ma，方向键步进时间"></canvas>
  <div id="tl" role="slider" tabindex="0" aria-label="时间轴：400 Ma 到 0 Ma，拖动时间滑块"
      aria-valuemin="0" aria-valuemax="400" aria-valuenow="0"><div class="end top">400 Ma</div><div class="axis"></div>
    <div class="tick" style="top:27%"><span>300</span></div><div class="tick" style="top:50%"><span>200</span></div>
    <div class="tick" style="top:73%"><span>100</span></div><div class="tick" style="top:84.5%"><span>50</span></div>
    <div class="end bot">0 Ma</div><div id="tlCur"></div></div>
  <div id="tlTip"></div>
  <div id="eventPeek" role="button" tabindex="0" aria-expanded="false" aria-label="展开当前事件"><div class="k">当前事件 · 点击展开</div><div class="t"></div><div class="x"></div><div class="evEvidence"></div></div>
  <div id="tools" role="group" aria-label="播放与地图工具">
    <button id="play" aria-label="从四亿年前播放" title="播放时间轴">▶ <span class="bt">播放</span></button>
    <span class="toolSep" aria-hidden="true"></span>
    <button id="mvBtn" aria-label="模型说明" title="方法与数据">ⓘ <span class="bt">方法</span></button>
    <button id="geoQaBtn" title="开发模式：把带病 ring（跨180°边/自交/退化/非法坐标）用红圈标出来" style="display:none">⌗ 几何检查</button>
  </div>
  <div id="cmpPanel">
    <label>左 <select id="cmpA"></select></label>
    <label>右 <select id="cmpB"></select></label>
    <button id="cmpX">退出对比</button>
  </div>
  <div id="polarMask" aria-hidden="true"></div>
  <div id="hud"></div>
  <div id="hint">时间刻度 · ← 往古老 · → 往现代 · 空格播放</div>
  <div id="banner">
    <div class="bT"></div><div class="bX"></div><div class="bE"></div>
    <div class="row"><button id="bNext">继续 →</button><button id="bExit">退出故事</button></div>
  </div>
  <div id="drawer">
    <button id="dClose">✕</button>
    <div id="tabs"></div>
    <div id="dBody"></div>
  </div>
</div>
<script>
const EARTH = __EARTH__, CHK = __CHECKS__;
const SL = EARTH.slices, EV = EARTH.events;
const R_KM = 6371.0088, DEG = Math.PI/180;
function mix4(hex){                    // alpha .4 叠在背景 #060B12 上的等效不透明色
  const n = parseInt(hex.slice(1),16), r = n>>16, g = (n>>8)&255, b = n&255;
  return `rgb(${Math.round(.4*r+3.6)},${Math.round(.4*g+6.6)},${Math.round(.4*b+10.8)})`;
}
const cv = document.getElementById('cv'), ctx = cv.getContext('2d');
const cvBg = document.getElementById('cvBg'), bgCtx = cvBg.getContext('2d');
const cvGrat = document.getElementById('cvGrat'), gratCtx = cvGrat.getContext('2d');
const cvLand = document.getElementById('cvLand'), landCtx = cvLand.getContext('2d');
const cvCoast = document.getElementById('cvCoast'), coastCtx = cvCoast.getContext('2d');
const cw = () => cv.width/devicePixelRatio, ch = () => cv.height/devicePixelRatio;
const pal = {land:'#D7E7E1', coast:'#86A9A0', grid:'#243448', time:'#FFD166',
          landS: mix4('#C7D9D2'), coastS: mix4('#6E8D86'),   // 预合成：重叠不叠色
          coastO: 'rgba(110,141,134,.4)',          // 叠在陆地上的海岸色（原设计）
             event:'#FFB86B', city:'#66E3D1', limit:'#EF8A7A', data:'#7DD3FC'};

/* ---------------- 状态：默认克制，一切靠点击揭示 ---------------- */
let cur = 0, timer = null;
let curEv = EV[0];
let compare = {on:false, a:40, b:0}; // 切片下标：40 = 200 Ma
const geoQa = {on:false};                        // 开发模式：几何质量检查（默认关）
if (location.hash === '#geoqa') geoQa.on = true;   // 截图用：直接点亮几何检查模式
const story = {on:false, idx:0};

/* ---------------- 投影 ---------------- */
function proj(x0, w){ return { X: lon => x0 + (lon+180)/360*w, Y: lat => (90-lat)/180*ch() }; }
let P = proj(0, 0);
function resize(){
  const r = document.getElementById('stage').getBoundingClientRect();
  for (const c of [cv, cvBg, cvGrat, cvLand, cvCoast]){   // 五个图层同步尺寸，否则默认 300x150 被 CSS 拉伸
    c.width = r.width*devicePixelRatio; c.height = r.height*devicePixelRatio;
  }
  for (const g of [ctx,bgCtx,gratCtx,landCtx,coastCtx])
    g.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0);
  silC = edgeC = null;                        // 离屏剪影按新尺寸重建
  sliceCache.clear();                         // 光栅缓存按新尺寸重建
  drawBg(); buildGrat(); draw();
}
// 背景层 = 海洋：深色纯色（不用渐变掩盖任何几何问题）
function drawBg(){
  // 海洋底色：纵向微渐变（顶/底缘各加深一档，中段保持 #060B12）。
  // 幅度刻意压到几乎看不见——只增加一点纵深，不干扰对海岸几何的观察。
  const w = cw(), h = ch();
  const g = bgCtx.createLinearGradient(0, 0, 0, h);
  g.addColorStop(0, '#050A10');
  g.addColorStop(0.18, '#060B12');
  g.addColorStop(0.82, '#060B12');
  g.addColorStop(1, '#040810');
  bgCtx.fillStyle = g; bgCtx.fillRect(0, 0, w, h);
}
const gcKm = (a, b) => {
  const la=a.lat*DEG, lb=b.lat*DEG, dl=(b.lon-a.lon)*DEG;
  return Math.acos(Math.max(-1,Math.min(1,Math.sin(la)*Math.sin(lb)+Math.cos(la)*Math.cos(lb)*Math.cos(dl))))*R_KM;
};
const fmtKm = d => Math.round(d).toLocaleString()+' 公里';
const latStr = v => Math.abs(v).toFixed(1)+(v >= 0 ? '°N' : '°S');   // B1：半球跟着数值走
const lonStr = v => Math.abs(v).toFixed(1)+(v >= 0 ? '°E' : '°W');
const fmtLL = (lo, la) => `${lonStr(lo)}，${latStr(la)}`;
function moveText(a, b){                                             // B8：阈值换算成公里 + 方位词序
  const d = gcKm(a, b), v = d/5*0.1;
  if (d <= 50) return {d, v, s: `基本原地（移动 ${Math.round(d)} km）`};
  const az = Math.atan2(Math.sin((b.lon-a.lon)*DEG)*Math.cos(b.lat*DEG),
      Math.cos(a.lat*DEG)*Math.sin(b.lat*DEG) - Math.sin(a.lat*DEG)*Math.cos(b.lat*DEG)*Math.cos((b.lon-a.lon)*DEG));
  const deg = (az/DEG + 360) % 360;
  const dirs = ['北','东北','东','东南','南','西南','西','西北'];
  const dir = dirs[Math.round(deg/45) % 8];
  return {d, v, s: `向<b>${dir}</b>移动 <b>${Math.round(d)} km</b>，模型速度约 <b>${v.toFixed(1)} cm/年</b>`};
}

/* 陆地切片 LRU 光栅缓存：每片 1300+ 环的路径填充只需一次，
   之后同帧回放/来回拖时间轴都是一次 drawImage（约 1-2ms vs 数十 ms）。
   缓存只在普通模式使用；对比模式两个半图各自绘路径（命中低，不值得）。
   尺寸变化时整体作废（resize 里清）。 */
const sliceCache = new Map();              // time_Ma → 陆地层光栅副本
const SLICE_CACHE_MAX = 12;                // ≈ 12 × 1440×761×4B ≈ 52 MB

function drawSliceCached(s, pr){
  const t = s.time_Ma;
  const cached = sliceCache.get(t);
  const W = cvLand.width, H = cvLand.height;
  if (cached){
    landCtx.save(); landCtx.setTransform(1, 0, 0, 1, 0, 0);
    landCtx.clearRect(0, 0, W, H);
    landCtx.drawImage(cached, 0, 0);
    landCtx.restore();
    sliceCache.delete(t); sliceCache.set(t, cached);      // LRU 提前
    return;
  }
  drawSlice(s, pr);                                        // 首次：真实路径绘制
  const c = document.createElement('canvas');
  c.width = W; c.height = H;
  c.getContext('2d').drawImage(cvLand, 0, 0);              // 快照
  if (sliceCache.size >= SLICE_CACHE_MAX){
    sliceCache.delete(sliceCache.keys().next().value);     // 淘最旧
  }
  sliceCache.set(t, c);
}

/* ---------------- 地图绘制 ---------------- */
/* 网格 + 标签缓存到离屏画布：resize 时重建，不必每帧重画 */
const grat = {normal:null, cmpL:null, cmpR:null, key:''};
function buildGrat(){
  const w = cw(), h = ch(), half = w/2;
  const mk = (x0, vw) => { const c = document.createElement('canvas');
    c.width = w*devicePixelRatio; c.height = h*devicePixelRatio;
    const g = c.getContext('2d'); g.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0);
    const X = lon => x0 + (lon+180)/360*vw, Y = lat => (90-lat)/180*h;
    // 经纬网只做定位参考，保持低对比度，避免和极区边界/时间轴边框
    // 在左下区域叠成一条醒目的“白色直角”。
    // 只保留经纬度标签，不绘制贯穿整幅地图的网格线；这些线会与
    // 极区合成边和左侧时间轴边界叠加成“白色横竖线”。
    g.strokeStyle = 'transparent'; g.lineWidth = 0.5; g.globalAlpha = .7;
    g.fillStyle = 'transparent'; g.font = '10px sans-serif'; g.textAlign = 'center';
    for (let lo=-180; lo<=180; lo+=30){
      g.beginPath(); g.moveTo(X(lo),0); g.lineTo(X(lo),h); g.stroke();
      g.fillText(lo+'°', Math.min(Math.max(X(lo),20+ (x0? x0:0)), (x0? x0+vw : w)-20), 10);
    }
    g.textAlign = 'left';
    for (let la=-90; la<=90; la+=30){
      g.beginPath(); g.moveTo(X(-180),Y(la)); g.lineTo(X(180),Y(la)); g.stroke();
      g.fillText(la<0? (-la)+'S' : la>0? la+'N' : '0', Math.max(X(-181)+2, x0+2), Y(la)-3);
    }
    return c; };
  grat.normal = mk(0, w); grat.cmpL = mk(0, half); grat.cmpR = mk(half, half);
  grat.key = w+'x'+h;
}
let silC = null, edgeC = null;                    // 离屏：陆地剪影 / 1px 海岸边带

function drawGratTo(cache){                       // 经纬网画到独立层（缓存图像）
  // 展示版不绘制经纬网：极区和反子午线的合成边不应以直线形式
  // 出现在海洋中，坐标信息通过悬停提示提供。
  return;
}

function drawSlice(s, pr, accumulate = false){     // 只画陆/海岸层，不含网格
  const w = cw(), h = ch();
  // 陆地先画成不透明"剪影"：600+ 重叠碎片只在内部填色，不再互相叠深、也不留内部描边
  const W = cv.width, H = cv.height;              // 物理像素
  if (!silC || silC.width !== W){ silC = document.createElement('canvas'); silC.width = W; silC.height = H; }
  if (!edgeC || edgeC.width !== W){ edgeC = document.createElement('canvas'); edgeC.width = W; edgeC.height = H; }
  const sc = silC.getContext('2d');
  sc.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0);
  // 对比模式会连续绘制左右两个视口：第二次调用要保留第一次的剪影。
  // 普通模式和每次新帧则从干净的离屏画布开始。
  if (!accumulate) sc.clearRect(0, 0, w, h);
  sc.fillStyle = pal.landS;
  // union 之后陆地已经是连续整块（build.py merge_land），不存在"拼块缝"，
  // 所以这里只做纯填充，不再需要同色描边外扩。
  const openCoasts = [];
  // build.py 会在围极环的首尾补上精确的 ±90° 顶点，以及沿极点的
  // [-180/0] 或 [0/180] 边。它们只用于填充闭合，不是真实海岸线。
  // 描边前去掉这些合成顶点，避免在等距圆柱投影上留下长直线。
  const realCoast = ring => {
    let lo = 0, hi = ring.length;
    while (lo < hi && Math.abs(ring[lo][1]) >= 89.999) lo++;
    while (hi > lo && Math.abs(ring[hi - 1][1]) >= 89.999) hi--;
    return ring.slice(lo, hi);
  };
  // 等距圆柱投影在两极是奇点；±90 是闭合用的合成点。裁到 ±89.9：
  // 既不把极点直接画到画布边缘（奇点），又让极冠一直填充到底部 1px 内——
  // 否则极冠会在 86.5° 处被齐平切断，留下一道横贯全图的直线底边（"大长方形"）。
  const POLAR_CUTOFF = 89.9;
  const safePoint = p => [p[0], Math.max(-POLAR_CUTOFF, Math.min(POLAR_CUTOFF, p[1]))];
  for (const ring of s.land){
    // 亚像素综合：投影后两个维度都不足 2px 的碎礁跳过不画——数据里它们是
    // 真实小岛，但在屏幕上只是 1-2 个孤立色点，帧间随简化/旋转忽隐忽现，
    // 看着像突然冒出来的霉斑（"南美西面太平洋上的小点"就是它）。2px ≈ 0.5°。
    let loMin = 1e9, loMax = -1e9, laMin = 1e9, laMax = -1e9;
    for (const p of ring){
      if (p[0] < loMin) loMin = p[0]; if (p[0] > loMax) loMax = p[0];
      if (p[1] < laMin) laMin = p[1]; if (p[1] > laMax) laMax = p[1];
    }
    if ((loMax - loMin) * w / 360 < 2 && (laMax - laMin) * h / 180 < 2) continue;
    // 所有环在数据层面都是闭合多边形（shapely 校验过，见 build.py QA）。
    // closePath() 唯一的危险是隐式闭合边跨日界线/横穿半个地球成一条假对角线——
    // 所以门控看"闭合边会不会是世界级长边"，而不是要求首尾几乎重合。
    const a = ring[0], z = ring[ring.length - 1];
    const lonGap = Math.abs(z[0] - a[0]);
    const latGap = Math.abs(z[1] - a[1]);
    // 极点楔形只在「两端点同在南/北极区」或「首尾真跨日界线」时才需要。
    // 旧条件还给"环内部含极点顶点、但两端点正常"的大环（如冈瓦纳 super-ring）
    // 套楔形：楔形边把环自身内部的 evenodd 奇偶性翻转，整片陆地被画成海
    // （用户报告的「海洋长条状形状」）。这种环的自然弦闭合（往往只有 1-2°）
    // 才是数据本意（shapely 口径）。
    // 极点楔形只在「首尾真跨日界线」时才需要。
    // 两端点同在极区、或环路径本身已穿过极点（含 ±89.5 以上顶点）时，
    // 自然弦闭合就是数据本意：路径围绕/穿过极点，闭合弦只封口，不穿海。
    // 旧条件给这类环加楔形会把极区路径重复遍历，evenodd 抵消→陆地画成海
    // （北极高纬「分辨率低/海洋长条」的直接来源）。
    const sameMeridian = Math.abs(z[0]) >= 175 && Math.abs(a[0]) >= 175
      && Math.sign(z[0]) === Math.sign(a[0]);        // 首末同在 ±180 同侧：弦=经线段
    const dateline = lonGap >= 170 && !sameMeridian;
    const isPolar = dateline;
    const closedEnough = !isPolar;
    sc.beginPath();
    for (let i=0;i<ring.length;i++){ const p = safePoint(ring[i]);
      i?sc.lineTo(pr.X(p[0]),pr.Y(p[1])):sc.moveTo(pr.X(p[0]),pr.Y(p[1])); }
    if (closedEnough) { sc.closePath(); sc.fill('evenodd'); }
    else if (isPolar) {
      // 围极环：build.py 的 fix_polar_wrap 把围住极点的环切在 [-180,0] 或 [0,180]
      // 区间里，于是首尾点经度差恰好 180°。这个环在球面上是闭合的——闭合边是
      // 「沿一条经线走到极点 → 横过极点 → 沿另一条经线走回来」，但数据里这条边
      // 没有顶点。直接 closePath 会在屏幕上画一条横穿全图的假边，把填充区域算错，
      // 于是整片大陆（union 之后这类环能到 5000 万 km²）变成空白。
      // 这里显式补上那两段：到尾点所在的经线走到极点，横穿到起点所在的经线。
      let latSum = 0;
      for (const p of ring) latSum += p[1];
      const pole = (latSum / ring.length) < 0 ? -90 : 90;
      const safePole = Math.max(-POLAR_CUTOFF, Math.min(POLAR_CUTOFF, pole));
      sc.lineTo(pr.X(z[0]), pr.Y(safePole));
      sc.lineTo(pr.X(a[0]), pr.Y(safePole));
      sc.closePath(); sc.fill('evenodd');
      // 极区环的闭合段和极点附近顶点都是合成几何，不画海岸描边。
    }
    else {
      // 首尾落在同一条经线上（纬度差大）：沿经线闭合本来就是对的
      sc.closePath(); sc.fill('evenodd');
      const coast = realCoast(ring);
      if (coast.length > 1) openCoasts.push(coast);
    }
  }
  // 洞（内海 / 湖泊）：从剪影里挖掉。挖完 edgeC 会自然沿洞沿描出一圈海岸线。
  const holeRings = s.holes || [];
  if (holeRings.length){
    sc.globalCompositeOperation = 'destination-out';
    for (const ring of holeRings){
      sc.beginPath();
      for (let i=0;i<ring.length;i++){ const p = safePoint(ring[i]);
        i?sc.lineTo(pr.X(p[0]),pr.Y(p[1])):sc.moveTo(pr.X(p[0]),pr.Y(p[1])); }
      sc.closePath(); sc.fill();
    }
    sc.globalCompositeOperation = 'source-over';
  }
  // 海岸 = 剪影 ⊖ 四向平移剪影：只在陆地外缘留 1px 边带，再染成海岸色
  const ec = edgeC.getContext('2d');
  ec.setTransform(1, 0, 0, 1, 0, 0);
  ec.clearRect(0, 0, W, H);
  ec.drawImage(silC, 0, 0);
  ec.globalCompositeOperation = 'destination-out';
  ec.drawImage(silC, 1, 0); ec.drawImage(silC, -1, 0);
  ec.drawImage(silC, 0, 1); ec.drawImage(silC, 0, -1);
  ec.globalCompositeOperation = 'source-in';
  ec.fillStyle = pal.coastO;
  ec.fillRect(0, 0, W, H);
  ec.globalCompositeOperation = 'source-over';
  // silC 在极点或日界线处可以贴住画布边缘；形态学外扩会把这种
  // 合成闭合边误识别成 1px 海岸。四周是投影边界，不应显示海岸线。
  const edge = Math.max(2, Math.ceil(devicePixelRatio) + 1);
  ec.clearRect(0, 0, W, edge);
  ec.clearRect(0, H-edge, W, edge);
  ec.clearRect(0, 0, edge, H);
  ec.clearRect(W-edge, 0, edge, H);
  // ---- 亚像素水道填平：3×3 邻域膨胀（≤1.5px 的海缝/海峡填掉） ----
  // 依据：数据里 <1.5px 的海峡在 1:1 图上不可分辨，且随 5 Ma 帧的旋转
  // 与简化忽隐忽现，表现为"陆地上突然出现的海洋蓝细线"。
  // 用纯膨胀而非闭运算：不丢任何陆块（只向海侧外扩 <1px，面积 +<0.3%），
  // 且完整保留海岸抗锯齿。奇偶校验仍按原始环判定（纯渲染层综合，见 report）。
  // 对比模式两次调用：第二次 accumulate 时 silC 已含左右两半，膨胀一次即可。
  if (!accumulate && !(location.search || '').includes('nodilate')){
    const cl = document.createElement('canvas'); cl.width = W; cl.height = H;
    const cc = cl.getContext('2d');
    cc.drawImage(silC, 0, 0);
    for (let dx=-1; dx<=1; dx++) for (let dy=-1; dy<=1; dy++)
      if (dx || dy) cc.drawImage(silC, dx, dy);               // 8 邻域叠加 = 膨胀
    sc.setTransform(1, 0, 0, 1, 0, 0);
    sc.clearRect(0, 0, W, H);
    sc.drawImage(cl, 0, 0);                                   // silC ← 膨胀结果
    sc.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0);
  }
  // 陆地填充层 与 海岸描边层 分离：fill 和 stroke 不再互相污染
  landCtx.save(); landCtx.setTransform(1, 0, 0, 1, 0, 0);
  landCtx.clearRect(0, 0, W, H);
  landCtx.drawImage(silC, 0, 0);                  // 陆地（不透明）
  // 说明：旧数据把围极环沿 0° 经线切成两半，0° 处会留抗锯齿缝，需要这里
  // 补缝带；build.py 已改为统一走 ±180 切分 + isPolar 极点闭合，0° 经线上
  // 不再有合成缝，此分支移除（也避免了缝带越海画竖线）。
  landCtx.restore();
  // 不再把自动形态学边缘绘制到地图上：极区闭合环、反子午线切缝和
  // 自回折海岸会被误判成真实海岸线。陆地填充本身已经提供清晰轮廓。
  coastCtx.save(); coastCtx.setTransform(1, 0, 0, 1, 0, 0);
  coastCtx.clearRect(0, 0, W, H);
  coastCtx.restore();
}
/* ---------------- 几何质量检查（开发模式，默认关闭）---------------- */
const segCross = (o,a,b) => (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0]);
function segInt(a,b,cd,dd){                       // 规范相交（相交于内部，端点重合不算）
  const d1 = segCross(cd,dd,a), d2 = segCross(cd,dd,b), d3 = segCross(a,b,cd), d4 = segCross(a,b,dd);
  return ((d1>0&&d2<0)||(d1<0&&d2>0)) && ((d3>0&&d4<0)||(d3<0&&d4>0));
}
function ringSelfInt(ring){                       // O(n²)，只用于 n<=200 的环
  const n = ring.length;
  for (let i=0;i<n;i++){
    const a = ring[i], b = ring[(i+1)%n];
    for (let j=i+2;j<n;j++){
      if (i===0 && j===n-1) continue;            // 相邻边
      if (segInt(a,b,ring[j],ring[(j+1)%n])) return true;
    }
  }
  return false;
}
function geoProblems(s){
  const out = [];
  for (let k=0;k<s.land.length;k++){
    const ring = s.land[k], n = ring.length, why = [];
    if (n < 3){ out.push({k, n, why:['顶点不足']}); continue; }
    let maxEdge = 0, nan = false;
    for (let i=0;i<=n;i++){
      const a = ring[i%n], b = ring[(i+1)%n];
      if (!isFinite(a[0])||!isFinite(a[1])||!isFinite(b[0])||!isFinite(b[1])){ nan = true; break; }
      maxEdge = Math.max(maxEdge, Math.abs(b[0]-a[0]));
    }
    if (nan){ out.push({k, n, why:['非法坐标(NaN/Infinity)']}); continue; }
    if (maxEdge > 180) why.push('跨180°边(' + maxEdge.toFixed(0) + '°)');
    let area = 0;
    for (let i=0;i<n;i++){ const a=ring[i], b=ring[(i+1)%n]; area += a[0]*b[1]-b[0]*a[1]; }
    if (Math.abs(area/2) < 1e-7) why.push('退化(面积≈0)');
    if (n <= 200 && ringSelfInt(ring)) why.push('自交');
    if (why.length) out.push({k, n, why});
  }
  return out;
}
function drawGeoQa(pr){
  if (!pr) return;
  const s = SL[cur], probs = geoProblems(s);
  ctx.save();
  ctx.strokeStyle = '#EF8A7A'; ctx.fillStyle = '#EF8A7A'; ctx.lineWidth = 1.4;
  for (const p of probs){
    const ring = s.land[p.k];
    ctx.beginPath();
    for (let i=0;i<=ring.length;i++){ const q = ring[i%ring.length];
      i?ctx.lineTo(pr.X(q[0]),pr.Y(q[1])):ctx.moveTo(pr.X(q[0]),pr.Y(q[1])); }
    ctx.stroke();
    let cx=0, cy=0;
    for (const q of ring){ cx += pr.X(q[0]); cy += pr.Y(q[1]); }
    cx/=ring.length; cy/=ring.length;
    ctx.beginPath(); ctx.arc(cx,cy,4,0,7); ctx.fill();
    ctx.font = '10px sans-serif';
    ctx.fillText('#'+p.k+' '+p.why.join(','), Math.min(cx+8, cw()-150), Math.max(cy,12));
  }
  if (!probs.length){                                      // 干净也反馈，否则按钮像没反应
    ctx.fillStyle = 'rgba(11,20,32,.85)';
    ctx.fillRect(12, 12, 250, 26);
    ctx.fillStyle = '#7DD3FC'; ctx.font = '12px sans-serif';
    ctx.fillText('几何检查：' + s.time_Ma + ' Ma 无带病 ring ✓', 20, 29);
  }
  if (probs.length){
    ctx.fillStyle = 'rgba(11,20,32,.85)';
    ctx.fillRect(12, 12, 320, 26);
    ctx.fillStyle = '#EF8A7A'; ctx.font = '12px sans-serif';
    ctx.fillText('几何检查：' + s.time_Ma + ' Ma 有 ' + probs.length + ' 个带病 ring（红圈标出）', 20, 29);
  }
  ctx.restore();
}

/* ---------------- 总 draw ---------------- */
function clearLayers(){                          // 各层只清自己（背景层不动）
  const w = cw(), h = ch();
  for (const g of [gratCtx, landCtx, coastCtx]){
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.clearRect(0, 0, cv.width, cv.height);
    g.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0);
  }
  ctx.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0);
  ctx.clearRect(0, 0, w, h);
}

function draw(){
  const w = cw(), h = ch();
  ctx.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0);
  ctx.globalAlpha = 1; ctx.setLineDash([]); ctx.textAlign = 'left'; ctx.lineWidth = 1;   // 防状态泄漏
  clearLayers();                                  // 先清四层，再按序画（对比模式两次 drawSlice 累加）
  if (compare.on){
    const half = w/2;
    drawGratTo(grat.cmpL); drawGratTo(grat.cmpR);   // 两张半宽网格直接叠在网格层
    drawSlice(SL[compare.a], proj(0, half));
    drawSlice(SL[compare.b], proj(half, half), true);
    ctx.strokeStyle = '#2A3F58'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(half,0); ctx.lineTo(half,h); ctx.stroke();
    ctx.fillStyle = pal.time; ctx.font = '15px sans-serif'; ctx.textAlign = 'left';
    ctx.fillText(SL[compare.a].time_Ma+' Ma', 10, 26);
    ctx.fillText(SL[compare.b].time_Ma+' Ma', half+10, 26);
  } else {
    drawGratTo(grat.normal);
    drawSliceCached(SL[cur], P = proj(0, w));
  }
  if (geoQa.on) drawGeoQa(compare.on ? null : P);   // 几何质检模式（默认关）

  updateHud();
}

/* ---------------- HUD / 顶栏 ---------------- */
function updateHud(){
  const s = SL[cur], t = s.time_Ma, m = s.metrics;
  curEv = EV.filter(e => e.time_Ma >= t).pop() || EV[EV.length-1];
  document.getElementById('clock').innerHTML = `<b>${t}</b><small> Ma</small>`;
  document.getElementById('era').innerHTML = `<b>${curEv.time_Ma} Ma · ${curEv.title}</b>`;
  const peek = document.getElementById('eventPeek');
  peek.querySelector('.t').textContent = `${curEv.time_Ma} Ma · ${curEv.title}`;
  peek.querySelector('.x').textContent = curEv.text;
  peek.querySelector('.evEvidence').textContent = `依据：${curEv.evidence}`;
  const dt = compare.on ? SL[compare.b].time_Ma : t;        // O3：对比模式时间轴跟随右图
  document.getElementById('tlCur').style.top = tlPos(dt)+'px';
  document.getElementById('tl').setAttribute('aria-valuenow', String(dt));
  document.querySelectorAll('.tlEv').forEach(d =>
    d.classList.toggle('cur', +d.dataset.t === curEv.time_Ma));
  if (compare.on){
    const A = SL[compare.a], B = SL[compare.b];
    const dA = B.metrics.land_area_km2/1e6 - A.metrics.land_area_km2/1e6;
    const dC = (B.metrics.comp_frac - A.metrics.comp_frac)*100;
    hud(`左 <b>${A.time_Ma} Ma</b>`, `右 <b>${B.time_Ma} Ma</b>`,
        `陆地变化 <b>${dA>=0?'+':''}${(dA/100).toFixed(2)} 亿 km²</b>`,
        `连通率变化 <b>${dC>=0?'+':''}${dC.toFixed(1)}%</b>`,
        `分量数 <b>${A.metrics.n_comp} → ${B.metrics.n_comp}</b>`);
    return;
  }
  const ph = t<=250 && t>=160 ? `<span class="ph">潘吉亚最高平台期</span>` :
             (t<=35 && t>=20 ? `<span class="warn">南方大陆分散期</span>` :
              t===0 ? `<span class="ph">现代</span>` : '');
  hud(`连通率 <b>${(m.comp_frac*100).toFixed(1)}%</b>`,
      `陆地 <b>${(m.land_area_km2/1e8).toFixed(2)} 亿 km²</b>`,
      `分量 <b>${m.n_comp}</b>`,
      `顶点 <b>${s.vertex_count.toLocaleString()}</b>`,
      ph);
}
const hud = (...parts) => {
  document.getElementById('hud').innerHTML =
    parts.filter(Boolean).map(p => `<span class="h">${p}</span>`).join('');
};
const tlPos = t => { const tl = document.getElementById('tl');
  return tl.clientHeight*.04 + (400-t)/400*(tl.clientHeight*.92) - 9.5; };

/* ---------------- 时间轴 ---------------- */
const tl = document.getElementById('tl');
// 时间轴保留当前滑块与事件节点；事件详情在地图内展开。
function tlLayout(){
  tl.querySelectorAll('.tlEv').forEach(n => n.remove());
  EV.forEach(ev => {
    const n = document.createElement('div');
    n.className = 'tlEv'; n.dataset.t = ev.time_Ma; n.title = `${ev.time_Ma} Ma · ${ev.title}`;
    n.style.top = tlPos(ev.time_Ma) + 'px';
    tl.appendChild(n);
  });
}
function timeFromY(y){                                  // 纵向像素 → 最近的网格时间
  const r = tl.getBoundingClientRect();
  const t = Math.round(400 - Math.min(Math.max(y-r.top-r.height*.04,0), r.height*.92)/(r.height*.92)*400);
  const step = SL.length > 1 ? SL[1].time_Ma - SL[0].time_Ma : 1;   // 网格步长（数据驱动）
  return Math.min(400, Math.max(0, Math.round(t/step)*step));       // 贴网格，否则 findIndex 落空
}
tl.addEventListener('mousemove', e => {
  const tip = document.getElementById('tlTip');
  const r = tl.getBoundingClientRect();
  const t = Math.round(400 - Math.min(Math.max(e.clientY-r.top-22,0), r.height-52)/(r.height-52)*400);
  const ev = EV.filter(x => x.time_Ma >= t).pop() || EV[EV.length-1];
  tip.style.display = 'block';
  tip.style.left = (e.clientX+14)+'px'; tip.style.top = (e.clientY-10)+'px';
  tip.innerHTML = `<b>${t} Ma</b> · ${ev.title}<br><span style="color:#5D7085">点击跳转到这个时间</span>`;
});
tl.addEventListener('mouseleave', () => document.getElementById('tlTip').style.display = 'none');
// 滚轮在时间轴上滚动 = 步进一个切片（5 Ma）：拖动之外的另一种精确操作
tl.addEventListener('wheel', e => {
  e.preventDefault();
  const step = SL.length > 1 ? SL[1].time_Ma - SL[0].time_Ma : 1;
  const d = e.deltaY > 0 ? -step : step;      // 向下滚 = 更现代
  setTime(SL.findIndex(s => s.time_Ma === Math.min(400, Math.max(0, SL[cur].time_Ma + d))));
}, {passive:false});
// 定点标记：Shift+点击地图任意位置 → 记录 [当前时间, 经纬度]，用于向构建方
// 精确报告"看起来不对"的地点（代替口头描述方位）。面板可一键复制、清空。
cv.addEventListener('click', e => {
  if (!e.shiftKey) return;
  const r = cv.getBoundingClientRect();
  const px = (e.clientX - r.left) * (cv.width / r.width / devicePixelRatio);
  const py = (e.clientY - r.top) * (cv.height / r.height / devicePixelRatio);
  const lon = px / cw() * 360 - 180;
  const lat = 90 - py / ch() * 180;
  const t = SL[cur] ? SL[cur].time_Ma : 0;
  if (!window.__spots) window.__spots = [];
  window.__spots.push([t, +lon.toFixed(1), +lat.toFixed(1)]);
  let p = document.getElementById('spotPanel');
  if (!p){
    p = document.createElement('div');
    p.id = 'spotPanel';
    p.style.cssText = 'position:fixed;right:12px;bottom:12px;z-index:99;background:#0b1420;' +
      'border:1px solid #2a3a4d;border-radius:8px;padding:8px 10px;max-width:340px;' +
      'font:12px/1.5 sans-serif;color:#cfe3f2;box-shadow:0 4px 18px rgba(0,0,0,.5)';
    p.innerHTML = '<div><b>标记点</b>（Shift+点地图） <button id="spotCopy">复制</button> ' +
      '<button id="spotClear">清空</button> <button id="spotClose">关闭</button></div>' +
      '<ol id="spotList" style="margin:4px 0 0 16px;padding:0"></ol>';
    document.body.appendChild(p);
    document.getElementById('spotCopy').onclick = () => {
      const txt = window.__spots.map(s => s[0] + ' Ma, lon ' + s[1] + ', lat ' + s[2]).join('\n');
      navigator.clipboard && navigator.clipboard.writeText(txt);
      document.getElementById('spotCopy').textContent = '已复制';
      setTimeout(() => document.getElementById('spotCopy').textContent = '复制', 1200);
    };
    document.getElementById('spotClear').onclick = () => {
      window.__spots = []; document.getElementById('spotList').innerHTML = '';
    };
    document.getElementById('spotClose').onclick = () => p.remove();
  }
  const li = document.createElement('li');
  li.textContent = t + ' Ma, lon ' + lon.toFixed(1) + ', lat ' + lat.toFixed(1);
  document.getElementById('spotList').appendChild(li);
});
tl.addEventListener('click', e => {
  if (dragMoved) return;                                 // 拖完松手那次 click 不算
  const node = e.target.closest('.tlEv');
  if (node){ setTime(SL.findIndex(s => s.time_Ma === +node.dataset.t)); openEventDetail(true); return; }
  setTime(SL.findIndex(s => s.time_Ma === timeFromY(e.clientY)));
});
/* 按住拖动：边拖边走时间 */
let dragMoved = false, dragY0 = 0;
tl.addEventListener('pointerdown', e => {
  dragY0 = e.clientY; dragMoved = false;
  tl.setPointerCapture(e.pointerId);
  if (timer){ clearInterval(timer); timer = null;       // 拖拽时别让播放计时器抢方向盘
    document.getElementById('play').innerHTML = '▶ <span class="bt">继续</span>'; }
  setTime(SL.findIndex(s => s.time_Ma === timeFromY(e.clientY)));
});
tl.addEventListener('pointermove', e => {
  if (!tl.hasPointerCapture(e.pointerId)) return;
  if (Math.abs(e.clientY - dragY0) > 4) dragMoved = true;
  setTime(SL.findIndex(s => s.time_Ma === timeFromY(e.clientY)));
});
tl.addEventListener('pointerup', () => {
  setTimeout(() => { dragMoved = false; }, 0);   // pointerup 早于 click，滞后重置才不漏
});

/* ---------------- 抽屉 ---------------- */
const TABKEY = {lim:'模型说明'};
const drawer = document.getElementById('drawer'), dBody = document.getElementById('dBody');
document.getElementById('dClose').addEventListener('click', () => drawer.classList.remove('open'));
document.getElementById('mvBtn').addEventListener('click', () => openDrawer('模型说明'));
function openDrawer(which){ drawer.classList.add('open'); renderLimits(); }
function openEventDetail(force = null){
  const peek = document.getElementById('eventPeek');
  const expanded = force === null ? !peek.classList.contains('expanded') : force;
  peek.classList.toggle('expanded', expanded);
  peek.setAttribute('aria-expanded', String(expanded));
  peek.querySelector('.k').textContent = expanded ? '当前事件 · 点击收起' : '当前事件 · 点击展开';
}
document.getElementById('eventPeek').addEventListener('click', () => openEventDetail());
document.getElementById('eventPeek').addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openEventDetail(); } });
function renderLimits(){
  dBody.innerHTML = `
    <div class="dSec"><h3>方法与数据</h3>
      <div class="tm">一份简明的阅读说明</div>
      <div class="evBox"><b>数据来源</b><br>Merdith et al. (2021) 全球板块重建模型，覆盖 400 Ma 到今天，每 5 Ma 一个切片。</div>
      <div class="evBox"><b>怎么读地图</b><br>拖动左侧时间轴，或点击时间轴上的事件节点；地图旁的当前事件卡片会跟着年代变化。</div>
      <div class="evBox"><b>面板用途</b><br>事件详情讲解当前年代，方法说明交代数据来源与阅读方式。</div>
      <div class="note">地图用于观察地球陆地格局的长期变化。</div></div>`;
}

/* ---------------- 播放 ---------------- */
/* 重画调度：rAF 合并 + 时间没变就跳过（拖拽时 pointermove 远多于切片粒度） */
let drawQueued = false;
function sync(){ requestDraw(); }
function requestDraw(){
  if (drawQueued) return;
  drawQueued = true;
  requestAnimationFrame(() => { drawQueued = false; draw(); });
}
function awaitFrame(){ return new Promise(r => requestAnimationFrame(() => r())); }
function curIdx(){ return compare.on ? compare.b : cur; }   // O3：对比模式时间轴接管右图
function setTime(i){                                        // clamp + 按模式写回
  i = Math.max(0, Math.min(SL.length-1, i));
  if ((compare.on ? compare.b : cur) === i) return;         // 同一片：不重画
  if (compare.on) compare.b = i; else cur = i;
  sync();
}
document.getElementById('play').addEventListener('click', () => {
  const btn = document.getElementById('play');
  if (story.on) endStory();                                  // B2：别让计时器抢故事的方向盘
  if (timer){ clearInterval(timer); timer = null; btn.innerHTML = '▶ <span class="bt">继续</span>'; return; }
  if (cur <= 0) cur = SL.length-1;
  btn.innerHTML = '⏸ <span class="bt">暂停</span>';
  timer = setInterval(() => {
    if (cur <= 0){ clearInterval(timer); timer = null;
      document.getElementById('play').innerHTML = '▶ <span class="bt">重播</span>'; return; }
    cur--; sync();
  }, 130);
});
window.addEventListener('keydown', e => {
  if (e.target.closest('input, select, textarea, button')) return;   // B7：别劫持表单控件
  if (e.key === 'ArrowLeft'){                                        // ← 古老，→ 现代
    const i = curIdx();
    if (i >= SL.length-1){ bump('已到时间轴最古端（400 Ma）'); return; }
    setTime(i+1);
  }
  if (e.key === 'ArrowRight'){
    const i = curIdx();
    if (i <= 0){ bump('已到时间轴最新端（今天）'); return; }
    setTime(i-1);
  }
  if (e.key === ' '){ e.preventDefault(); document.getElementById('play').click(); }
});
let bumpTimer = null;
function bump(msg){                                                   // 端点反馈
  const h = document.getElementById('hint');
  h.dataset.keep = h.textContent;
  h.textContent = msg; h.style.color = pal.time;
  clearTimeout(bumpTimer);
  bumpTimer = setTimeout(() => { h.textContent = h.dataset.keep || ''; h.style.color = ''; }, 1200);
}

/* ---------------- 工具层按钮 ---------------- */
document.getElementById('geoQaBtn').addEventListener('click', e => {   // 开发模式开关
  geoQa.on = !geoQa.on; e.currentTarget.classList.toggle('on', geoQa.on); draw();
});

/* ---------------- 对比模式 ---------------- */
const cmpA = document.getElementById('cmpA'), cmpB = document.getElementById('cmpB');
const fillCmp = () => {
  cmpA.innerHTML = cmpB.innerHTML = SL.map(s => `<option value="${s.time_Ma}">${s.time_Ma} Ma</option>`).join('');
  cmpA.value = 200; cmpB.value = 0;
};
document.getElementById('cmpBtn').addEventListener('click', () => {
  compare.on = !compare.on;
  document.getElementById('cmpBtn').classList.toggle('on', compare.on);
  document.getElementById('cmpPanel').classList.toggle('show', compare.on);
  if (compare.on){
    fillCmp();
  }
  draw();
});
document.getElementById('cmpX').addEventListener('click', () => {
  compare.on = false;
  document.getElementById('cmpBtn').classList.remove('on');
  document.getElementById('cmpPanel').classList.remove('show');
  draw();
});
cmpA.addEventListener('change', () => { compare.a = SL.findIndex(s => s.time_Ma === +cmpA.value); draw(); });
cmpB.addEventListener('change', () => { compare.b = SL.findIndex(s => s.time_Ma === +cmpB.value); draw(); });

/* ---------------- 故事模式 ---------------- */
function startStory(){
  if (timer){ clearInterval(timer); timer = null;          // B2：进故事先停掉自动播放
    document.getElementById('play').innerHTML = '▶ <span class="bt">从四亿年前播放</span>'; }
  story.on = true; story.idx = 0;
  document.getElementById('storyBtn').innerHTML = '■ <span class="bt">故事进行中</span>';
  stepStory();
}
function stepStory(){
  if (story.idx >= EV.length){ endStory(); return; }
  const e = EV[story.idx];
  cur = SL.findIndex(s => s.time_Ma === e.time_Ma);
  curEv = e;
  sync();
  const b = document.getElementById('banner');
  b.querySelector('.bT').textContent = `${e.time_Ma} Ma · ${e.title}`;
  b.querySelector('.bX').innerHTML = e.text;
  b.querySelector('.bE').innerHTML = '依据：' + e.evidence;
  b.classList.add('show');
  document.getElementById('bNext').textContent = story.idx < EV.length-1 ? '继续 →' : '故事讲完了';
}
function endStory(){
  story.on = false;
  document.getElementById('banner').classList.remove('show');
  document.getElementById('storyBtn').innerHTML = '✦ <span class="bt">开始地球故事</span>';
  draw();
}
document.getElementById('bNext').addEventListener('click', () => {
  if (story.idx >= EV.length-1){ endStory(); return; }
  story.idx++; stepStory();
});
document.getElementById('bExit').addEventListener('click', endStory);
document.getElementById('storyBtn').addEventListener('click', () => {
  if (story.on) endStory(); else startStory();
});

/* ---------------- 鼠标经纬度 ---------------- */
cv.addEventListener('mousemove', e => {
  const r = cv.getBoundingClientRect();
  const mx = e.clientX-r.left, my = e.clientY-r.top;
  let lo, la;
  if (compare.on){                                          // B3：半屏内各自铺满 -180..180
    const half = r.width/2;
    lo = (mx < half ? mx/r.width*2 : (mx-half)/r.width*2)*360-180;
  } else {
    lo = mx/r.width*360-180;
  }
  la = 90-(my/r.height)*180;
  document.getElementById('hint').textContent =
    `经度 ${lo.toFixed(1)}°  纬度 ${la.toFixed(1)}°  ·  ← 往古老 · → 往现代 · 空格播放`;
});
cv.addEventListener('mouseleave', () => {
  cv.style.cursor = 'crosshair';
});

/* ---------------- 初始化 ---------------- */
window.addEventListener('resize', () => { resize(); tlLayout(); });
resize(); tlLayout(); sync();

/* ---------------- 深链（#50 / #50:ev），也供截图验收 ---------------- */
(function(){
  const h = location.hash.slice(1); if (!h) return;
  const [t, tk] = h.split(':');
  const i = SL.findIndex(s => s.time_Ma === +t);
  if (i >= 0) cur = i;
  sync();                                  // 先把 curEv/地图刷新到目标时间，再开抽屉
  if (tk === 'ev') openEventDetail(true);
  else if (tk && TABKEY[tk]) openDrawer(TABKEY[tk]);
})();
if (location.hash.startsWith('#probe:comp:')){     // 诊断：五层合成后用户实际看到的颜色
  const [t, x0, x1, y0, y1] = location.hash.slice(13).split(',').map(Number);
  const i = SL.findIndex(s => s.time_Ma === t);
  if (i >= 0) cur = i;
  draw();
  const w = Math.floor(cw()), h = Math.floor(ch());
  const tmp = document.createElement('canvas'); tmp.width = w; tmp.height = h;
  const tc = tmp.getContext('2d');
  for (const cvv of [cvBg, cvGrat, cvLand, cvCoast, cv]){
    try { tc.drawImage(cvv, 0, 0); } catch(e){}
  }
  const d = tc.getImageData(0,0,w,h).data;
  const dbg = 'dpr=' + devicePixelRatio + ' cvW=' + cv.width + ' cvH=' + cv.height +
    ' cw=' + cw() + ' ch=' + ch() + ' | tc@721,652=' + d[(652*w+721)*4] + ',' + d[(652*w+721)*4+1] + ',' + d[(652*w+721)*4+2] +
    ' landCtx@721,652=' + (() => { const q = landCtx.getImageData(721,652,1,1).data; return q[0]+','+q[1]+','+q[2]; })();
  let out = dbg + '\n';
  for (let y=y0|0; y<(y1|0); y+=1){
    for (let x=x0|0; x<(x1|0); x+=1){
      const p = (y*w+x)*4, rr=d[p], gg=d[p+1], bb=d[p+2];
      const landish = rr>60 && rr<115 && gg>70 && gg<125 && bb>70 && bb<125;
      const oceany = rr<20 && gg<25 && bb<35;         // 海洋深色
      if (landish) out += '█';
      else if (oceany) out += '·';
      else out += '?';                                  // 既非陆也非海 = 杂色线
    }
    out += '\n';
  }
  const pre = document.createElement('pre');
  pre.id = 'probeComp'; pre.textContent = out;
  document.body.appendChild(pre);
  document.title = 'comp done';
}
if (location.hash.slice(0,12) === '#probe:zoom:'){    // 诊断：高分辨率局部 ASCII
  const [t, x0, x1, y0, y1] = location.hash.slice(12).split(',').map(Number);
  const i = SL.findIndex(s => s.time_Ma === t);
  if (i >= 0) cur = i;
  draw();
  const w = Math.floor(cw()), h = Math.floor(ch());
  const d = landCtx.getImageData(0,0,w,h).data;
  let out = '';
  for (let y=y0|0; y<(y1|0); y+=1){
    for (let x=x0|0; x<(x1|0); x+=1){
      const p = (y*w+x)*4, rr=d[p], gg=d[p+1], bb=d[p+2];
      if (rr>65 && rr<110 && gg>75 && gg<120 && bb>75 && bb<125) out += '█';
      else if (rr+gg+bb > 110) out += '▓';
      else out += '·';
    }
    out += '\n';
  }
  const pre = document.createElement('pre');
  pre.id = 'probeZoom'; pre.textContent = out;
  document.body.appendChild(pre);
  document.title = 'zoom done';
}
if (location.hash.startsWith('#probe:rects')){   // 诊断：哪些元素包围盒盖住某点
  const CX = 400, CY = 441;
  for (const el of document.querySelectorAll('body *')){
    const r = el.getBoundingClientRect();
    if (r.left <= CX && CX <= r.right && r.top <= CY && CY <= r.bottom){
      const cs = getComputedStyle(el);
      const cv = el.tagName === 'CANVAS' ? 'canvas' : '';
      let px = null;
      if (el.tagName === 'CANVAS'){
        const x = el.getContext('2d');
        try { const d = x.getImageData(CX - r.left, CY - r.top, 1, 1).data; px = [d[0], d[1], d[2], d[3]]; } catch(e){ px = '' + e; }
      }
      console.log('COVER:', el.id || el.className || el.tagName, r.left, r.top, r.width, r.height,
        cs.color, cs.backgroundColor.slice(0, 40), cv, px);
    }
  }
  document.title = 'rects done';
}
if (location.hash === '#probe:audit'){   // 诊断：全帧分区覆盖审计 + 长直线检测
  const NX = 8, NY = 4, res = [];
  const W = cv.width, H = cv.height;
  for (let i = 0; i < SL.length; i++){
    cur = i; draw();
    const img = landCtx.getImageData(0, 0, W, H).data;
    const cells = new Float32Array(NX*NY);
    const cw = W/NX, ch = H/NY;
    for (let y = 0; y < H; y += 4){            // 4px 抽样
      const cy = Math.min(NY-1, (y/ch)|0);
      for (let x = 0; x < W; x += 4){
        const cx = Math.min(NX-1, (x/cw)|0);
        if (img[(y*W+x)*4+3] > 128) cells[cy*NX+cx]++;
      }
    }
    const tot = cells.reduce((s,v)=>s+v,0);
    res.push({t: SL[i].time_Ma, cells: Array.from(cells), tot});
  }
  // 瞬失检测：该格在前后两帧都有陆地、只在中间帧消失（BUG 特征：
  // 板块平稳移动不会让某片陆地只在一帧里消失）
  const drops = [];
  for (let i = 1; i < res.length - 1; i++){
    const p = res[i-1].cells, b = res[i].cells, n = res[i+1].cells;
    for (let c = 0; c < b.length; c++){
      const ref = Math.min(p[c], n[c]);
      if (ref > 12 && b[c] < ref*0.4)
        drops.push({t: res[i].t, cell: [c%NX, (c/NX)|0], prev: p[c], cur: b[c], next: n[c]});
    }
  }
  const totDrops = [];
  for (let i = 1; i < res.length; i++)
    if (res[i].tot < res[i-1].tot*0.8) totDrops.push({t: res[i].t, from: res[i-1].tot, to: res[i].tot});
  const div = document.createElement('div'); div.id = 'probeAudit';
  div.textContent = JSON.stringify({drops, totDrops, nFrames: res.length}); document.body.appendChild(div);
  document.title = 'audit done';
}
if (location.hash.startsWith('#probe:edges')){   // 诊断：长直边检测（合成缝定位）
  const W = cv.width, H = cv.height;
  const out = [];
  for (let i = 0; i < SL.length; i++){
    cur = i; draw();
    const img = landCtx.getImageData(0, 0, W, H).data;
    const M = new Uint8Array(W*H);
    for (let y = 0; y < H; y += 2)
      for (let x = 0; x < W; x += 2)
        if (img[(y*W+x)*4+3] > 128) M[y*W+x] = 1;
    // 竖边：同一 x 上连续 ≥80px（40 抽样行）的 land↔sea 跳变
    const vEdges = [];
    for (let x = 6; x < W-6; x += 2){
      let run = 0, runSide = 0;
      for (let y = 2; y < H-2; y += 2){
        const side = M[y*W+x] ? 1 : -1;
        if (side === runSide && Math.abs(side) === 1){ run++; continue; }
        if (run >= 40){
          const left = M[(y-2*run)*W + x-6] || M[(y-2*run)*W + x-4], right = M[(y-2*run)*W + x+4] || M[(y-2*run)*W + x+6];
          vEdges.push({x, y1: y-2*run, len: run*2, side: runSide});
        }
        run = 1; runSide = side;
      }
    }
    const syn = vEdges.filter(e => Math.min(Math.abs(e.x-720), e.x, Math.abs(e.x-W+2)) < 14);
    if (syn.length) out.push({t: SL[i].time_Ma, syn: syn.map(e => [e.x, e.y1, e.len]).slice(0, 3)});
  }
  const div = document.createElement('div'); div.id = 'probeEdges';
  div.textContent = JSON.stringify(out); document.body.appendChild(div); document.title = 'edges done';
}
if (location.hash.startsWith('#probe:q')){      // 诊断：陆像素数/平均透明度/边缘 AA 分布
  const a = location.hash.split(',').map(s => +s.trim());
  const ts = a.slice(1);
  const out = [];
  const w = Math.floor(cw()), h = Math.floor(ch());
  for (const t of ts){
    cur = SL.findIndex(s => s.time_Ma === t); if (cur < 0) continue;
    draw();
    const d = landCtx.getImageData(0,0,w,h).data;
    let n = 0, s = 0, edge = 0, edgeS = 0;
    for (let i=3; i<d.length; i+=4){
      const al = d[i];
      if (al > 0){ n++; s += al; }
      if (al > 0 && al < 250){ edge++; edgeS += al; }
    }
    out.push([t, n, Math.round(s/n), edge, edge ? Math.round(edgeS/edge) : 0]);
  }
  const div = document.createElement('div'); div.id = 'probeQ';
  div.textContent = JSON.stringify(out);
  document.body.appendChild(div); document.title = 'q done';
}
if (location.hash.startsWith('#probe:sliver')){  // 诊断：陆地内部的"海色细缝"像素数
  const a = location.hash.split(',').map(s => +s.trim());
  const ts = a.slice(1);
  const out = [];
  const w = Math.floor(cw()), h = Math.floor(ch());
  for (const t of ts){
    cur = SL.findIndex(s => s.time_Ma === t); if (cur < 0) continue;
    draw();
    const d = landCtx.getImageData(0,0,w,h).data;
    let sliver = 0;
    for (let y=2; y<h-2; y++){
      for (let x=2; x<w-2; x++){
        const p = (y*w+x)*4;
        if (d[p+3] > 200) continue;                        // 已是陆地
        // 周围 8 邻里主要是陆地 → 这是个内部海缝
        let n = 0;
        for (let dy=-1; dy<=1; dy++) for (let dx=-1; dx<=1; dx++){
          if (d[((y+dy)*w+x+dx)*4+3] > 200) n++;
        }
        if (n >= 7) sliver++;
      }
    }
    out.push([t, sliver]);
  }
  const div = document.createElement('div'); div.id = 'probeSliver';
  div.textContent = JSON.stringify(out);
  document.body.appendChild(div); document.title = 'sliver done';
}
if (location.hash.startsWith('#probe:erase')){   // 诊断：哪个环/哪一步让某像素变海
  const a = location.hash.split(',').map(s => +s.trim());
  const px = a[1], py = a[2];
  cur = a[3] >= 0 ? SL.findIndex(s => s.time_Ma === a[3]) : 0;
  const s = SL[cur];
  draw();                                        // 先真正画到 cvLand，再逐步对照
  const CUT = 89.9;
  const X = lon => (lon + 180) / 360 * cw(), Y = lat => (90 - Math.max(-CUT, Math.min(CUT, lat))) / 180 * ch();
  const mkPath = (g, ring) => {
    g.beginPath();
    const pts = ring.map(p => [p[0], Math.max(-CUT, Math.min(CUT, p[1]))]);
    pts.forEach((p, k) => k ? g.lineTo(X(p[0]), Y(p[1])) : g.moveTo(X(p[0]), Y(p[1])));
    g.closePath();
  };
  const rd = ctx => ctx.getImageData(px, py, 1, 1).data;
  const out = {steps: []};
  // 1) 只画环 50
  {
    const tc = document.createElement('canvas'); tc.width = cv.width; tc.height = cv.height;
    const tx = tc.getContext('2d'); tx.fillStyle = '#ffffff';
    mkPath(tx, s.land[50]); tx.fill('evenodd');
    const d = rd(tx); out.steps.push(['only50', d[0], d[3]]);
  }
  // 2) 所有陆环
  {
    const tc = document.createElement('canvas'); tc.width = cv.width; tc.height = cv.height;
    const tx = tc.getContext('2d'); tx.fillStyle = '#ffffff';
    for (const ring of s.land){ mkPath(tx, ring); tx.fill('evenodd'); }
    const d = rd(tx); out.steps.push(['allLand', d[0], d[3]]);
  }
  // 3) 所有陆环 + 挖洞（destination-out）
  {
    const tc = document.createElement('canvas'); tc.width = cv.width; tc.height = cv.height;
    const tx = tc.getContext('2d'); tx.fillStyle = '#ffffff';
    for (const ring of s.land){ mkPath(tx, ring); tx.fill('evenodd'); }
    tx.globalCompositeOperation = 'destination-out';
    for (const ring of (s.holes || [])){ mkPath(tx, ring); tx.fill(); }
    const d = rd(tx); out.steps.push(['land+holes', d[0], d[3]]);
  }
  // 4) 实际渲染层
  out.steps.push(['cvLand', rd(landCtx)[0], rd(landCtx)[3]]);
  // 5) 洞列表在 (px,py) 的覆盖（每个洞单独）
  out.holesAt = [];
  for (let i = 0; i < (s.holes||[]).length; i++){
    const tc = document.createElement('canvas'); tc.width = cv.width; tc.height = cv.height;
    const tx = tc.getContext('2d'); tx.fillStyle = '#ffffff';
    mkPath(tx, s.holes[i]); tx.fill('evenodd');
    const d = rd(tx);
    if (d[3] > 0) out.holesAt.push([i, s.holes[i].length, d[3]]);
  }
  const div = document.createElement('div'); div.id = 'probeErase';
  div.textContent = JSON.stringify(out);
  document.body.appendChild(div); document.title = 'erase done';
}
if (location.hash.startsWith('#probe:wr2')){   // 诊断：逐环（含 isPolar 闭合）定位某像素
  const a = location.hash.split(',').map(s => +s.trim());
  const px = a[1], py = a[2];
  cur = a[3] >= 0 ? SL.findIndex(s => s.time_Ma === a[3]) : 0;
  const s = SL[cur];
  const W = cv.width, H = cv.height, CUT = 89.9;
  const X = lon => (lon + 180) / 360 * cw(), Y = lat => (90 - Math.max(-CUT, Math.min(CUT, lat))) / 180 * ch();
  const found = [];
  for (let i = 0; i < s.land.length; i++){
    const ring = s.land[i];
    const tc = document.createElement('canvas'); tc.width = W; tc.height = H;
    const tx = tc.getContext('2d');
    tx.fillStyle = '#ff0000'; tx.beginPath();
    const pts = ring.map(p => [p[0], Math.max(-CUT, Math.min(CUT, p[1]))]);
    pts.forEach((p, k) => k ? tx.lineTo(X(p[0]), Y(p[1])) : tx.moveTo(X(p[0]), Y(p[1])));
    const z = pts[pts.length-1], aa = pts[0];
    const lonGap = Math.abs(z[0] - aa[0]);
    const sameMeridian = Math.abs(z[0]) >= 175 && Math.abs(aa[0]) >= 175
      && Math.sign(z[0]) === Math.sign(aa[0]);
    const dateline = lonGap >= 170 && !sameMeridian;
    const isPolar = dateline;
    if (!isPolar){ tx.closePath(); tx.fill('evenodd'); }
    else {
      const latSum = pts.reduce((s2, p) => s2 + p[1], 0);
      const pole = latSum / pts.length < 0 ? -CUT : CUT;
      tx.lineTo(X(z[0]), Y(pole));
      tx.lineTo(X(aa[0]), Y(pole));
      tx.closePath(); tx.fill('evenodd');
    }
    const d = tx.getImageData(px, py, 1, 1).data;
    if (d[3] > 128) found.push([i, ring.length, isPolar]);
  }
  const div = document.createElement('div'); div.id = 'probeWr2';
  div.textContent = JSON.stringify({t: s.time_Ma, px, py, rings: found});
  document.body.appendChild(div); document.title = 'wr2 done';
}
if (location.hash.startsWith('#probe:ascii')){   // 诊断：直读画布掩码 ASCII
  const a = location.hash.split(',').map(s => s.trim());
  const t = +(a[1]||0), y0 = +(a[2]||0), x0 = +(a[3]||0), y1 = +(a[4]||761), x1 = +(a[5]||1440);
  cur = SL.findIndex(s => s.time_Ma === t); if (cur < 0) cur = 0;
  draw();
  const W = cv.width, H = cv.height;
  const img = landCtx.getImageData(0, 0, W, H).data;
  const sy = Math.max(1, Math.round((y1-y0)/46)), sx = Math.max(1, Math.round((x1-x0)/150));
  let out = [];
  for (let y = y0; y < y1; y += sy){
    let row = '';
    for (let x = x0; x < x1; x += sx)
      row += (img[(y*W+x)*4+3] > 128) ? '#' : '.';
    out.push(y + ' ' + row);
  }
  const div = document.createElement('div'); div.id = 'probeAscii';
  div.textContent = 'sy=' + sy + ' sx=' + sx + '\n' + out.join('\n');
  document.body.appendChild(div); document.title = 'ascii done';
}
if (location.hash.startsWith('#probe:region')){   // 诊断：读某区域的画布陆地像素
  const pt = +(location.hash.split(',')[1] || 0);
  cur = SL.findIndex(s => s.time_Ma === pt); if (cur < 0) cur = 0;
  draw();
  const W = cv.width, H = cv.height;
  const img = landCtx.getImageData(0, 0, W, H).data;
  const cnt = {tl: 0, tr: 0};
  for (let y = 0; y < 200; y += 2)
    for (let x = 0; x < 336; x += 2)
      if (img[(y*W+x)*4+3] > 128) cnt.tl++;
  for (let y = 0; y < 200; y += 2)
    for (let x = 1104; x < W; x += 2)
      if (img[(y*W+x)*4+3] > 128) cnt.tr++;
  const div = document.createElement('div'); div.id = 'probeRegion';
  div.textContent = JSON.stringify({t: SL[cur].time_Ma, tl: cnt.tl*4, tr: cnt.tr*4});
  document.body.appendChild(div); document.title = 'region done';
}
if (location.hash.startsWith('#probe:art')){   // 诊断：全帧自动检出渲染缺陷
  // 1) 被陆地四面包围的海洋连通块（"空白方块/长方形"） 2) 长竖缝（两侧皆陆的海洋竖条）
  const W = cv.width, H = cv.height;
  const findings = [];
  for (let i = 0; i < SL.length; i++){
    cur = i; draw();
    const img = landCtx.getImageData(0, 0, W, H).data;
    const M = new Uint8Array(W*H);                    // 1 = 陆地
    for (let y = 0; y < H; y += 2)
      for (let x = 0; x < W; x += 2)
        if (img[(y*W+x)*4+3] > 128) M[y*W+x] = 1;
    // 2x2 抽样网格：W2=720, H2=380
    const W2 = W>>1, H2 = H>>1;
    const sea = new Uint8Array(W2*H2);                // 0=未访问, 1=海
    const stk = [];
    const enc = [];
    for (let yy = 0; yy < H2; yy++) for (let xx = 0; xx < W2; xx++){
      const idx = yy*W2+xx;
      if (M[idx*2] || sea[idx]) continue;             // 是陆地或已访问
      // BFS：此连通块是否触及边界带（20px ≈ 10 抽样格）
      stk.length = 0; stk.push(idx); sea[idx] = 1;
      let touches = false, cells = 0, x0=1e9,x1=-1,y0=1e9,y1=-1;
      while (stk.length){
        const p = stk.pop(); cells++;
        const px = p % W2, py = (p/W2)|0;
        if (px < x0) x0 = px; if (px > x1) x1 = px;
        if (py < y0) y0 = py; if (py > y1) y1 = py;
        if (px <= 10 || px >= W2-11 || py <= 10 || py >= H2-11) touches = true;
        const nb = [p-1, p+1, p-W2, p+W2];
        for (const q of nb){
          if (q < 0 || q >= W2*H2) continue;
          if (!sea[q] && !M[q*2]){ sea[q] = 1; stk.push(q); }
        }
      }
      if (!touches && cells >= 20){                    // ≥20 抽样格 = ≥80px
        const bw = (x1-x0+1)*2, bh = (y1-y0+1)*2, fill = cells/( (x1-x0+1)*(y1-y0+1) );
        enc.push({x: x0*2, y: y0*2, w: bw, h: bh, c: cells*4, fill: +fill.toFixed(2)});
      }
    }
    if (enc.length){
      // 只报长方形度高的（fill>0.5）或大的
      const bad = enc.filter(e => (e.fill > 0.5 && e.w*e.h >= 1600) || e.w*e.h >= 20000);
      if (bad.length) findings.push({t: SL[i].time_Ma, holes: bad});
    }
  }
  const div = document.createElement('div'); div.id = 'probeArt';
  div.textContent = JSON.stringify(findings); document.body.appendChild(div);
  document.title = 'art done';
}
if (location.hash.startsWith('#probe:stack')){   // 诊断：画布尺寸 + 陆地像素的 y 分布
  cur = SL.findIndex(s => s.time_Ma === +(location.hash.split(',')[1] || 0));
  draw();
  const W = cv.width, H = cv.height;
  const img = landCtx.getImageData(0, 0, W, H).data;
  let yMin = 1e9, yMax = -1, cnt = 0, rows = {};
  for (let y = 0; y < H; y += 2){
    let r = 0;
    for (let x = 0; x < W; x += 4) if (img[(y*W+x)*4+3] > 128) r++;
    if (r > 2){ cnt++; rows[y] = r; if (y < yMin) yMin = y; if (y > yMax) yMax = y; }
  }
  const div = document.createElement('div'); div.id = 'probeStack';
  div.textContent = JSON.stringify({t: SL[cur].time_Ma, cvW: W, cvH: H, ih: innerHeight,
    yMin, yMax, sampleRows: [yMax, yMax-20, yMax-40, yMax-60].map(y => [y, rows[y] || 0])});
  document.body.appendChild(div); document.title = 'stack done';
}
if (location.hash === '#probe:tldrag'){   // 诊断：真实合成拖拽事件的时间映射
  const out = [];
  const r = tl.getBoundingClientRect();
  const fire = (type, y) => tl.dispatchEvent(new PointerEvent(type, { clientY: y, clientX: 40, pointerId: 7, bubbles: true }));
  // timeFromY 逻辑直接验证 + click 路径（click 不依赖 pointer capture）
  out.push(['timeFromY 顶/中/底', timeFromY(r.top + 26), timeFromY(r.top + r.height/2), timeFromY(r.top + r.height - 26)]);
  tl.dispatchEvent(new MouseEvent('click', { clientY: r.top + 26, clientX: 40, bubbles: true }));
  out.push(['点击顶部', SL[cur].time_Ma]);
  tl.dispatchEvent(new MouseEvent('click', { clientY: r.top + r.height - 26, clientX: 40, bubbles: true }));
  out.push(['点击底部', SL[cur].time_Ma]);
  const div = document.createElement('div'); div.id = 'probeTl';
  div.textContent = JSON.stringify(out); document.body.appendChild(div);
  document.title = 'tldrag done';
}
if (location.hash.startsWith('#probe:whichring')){   // 诊断：某个像素在当前切片里由哪个环绘制
  const px = 400, py = 389;
  if (location.hash.includes(',')){
    const pt = +location.hash.split(',')[1];
    const i = SL.findIndex(s => s.time_Ma === pt); if (i >= 0) cur = i;
  }
  const s = SL[cur];
  const probes = [[px, py], [px-1, py], [px+1, py], [px, py-1], [px, py+1]];
  const found = [];
  for (let i = 0; i < s.land.length; i++){
    const ring = s.land[i];
    const tc = document.createElement('canvas'); tc.width = cv.width; tc.height = cv.height;
    const tx = tc.getContext('2d');
    tx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
    tx.fillStyle = '#ff0000';
    tx.beginPath();
    for (let k = 0; k < ring.length; k++){
      const p = ring[k];
      const X = (p[0] + 180) / 360 * cw(), Y = (90 - p[1]) / 180 * ch();
      k ? tx.lineTo(X, Y) : tx.moveTo(X, Y);
    }
    tx.closePath(); tx.fill('evenodd');
    for (const [qx, qy] of probes){
      const d = tx.getImageData(qx, qy, 1, 1).data;
      if (d[3] > 0){ found.push({ring: i, n: ring.length, at: [qx, qy], p0: ring[0], p1: ring[ring.length-1]}); break; }
    }
  }
  const div = document.createElement('div'); div.id = 'probeWhich';
  div.textContent = JSON.stringify({t: s.time_Ma, nRings: s.land.length, found});
  document.body.appendChild(div); document.title = 'which done';
}
if (location.hash === '#probe:playseq'){   // 播放全过程逐帧采样陆地覆盖率
  const samples = [];
  const ck = () => { const a = landCtx.getImageData(0,0,cv.width,cv.height).data;
    let n=0; for (let i=3;i<a.length;i+=16) if (a[i]>0) n++; return n/(a.length/16); };
  samples.push([SL[cur].time_Ma, +ck().toFixed(3)]);
  document.getElementById('play').click();
  const iv = setInterval(() => {
    samples.push([SL[cur].time_Ma, +ck().toFixed(3)]);
    if (SL[cur].time_Ma === 0 || samples.length > 90){
      clearInterval(iv);
      const div = document.createElement('div'); div.id = 'probePlayseq';
      div.textContent = JSON.stringify(samples);
      document.body.appendChild(div);
      document.title = 'playseq done';
    }
  }, 100);
}
if (location.hash.slice(0,10) === '#probe:geo'){   // 诊断：当前切片的带病 ring 清单（可 #probe:geo,250 指定时间）
  if (location.hash[10] === ','){
    const i = SL.findIndex(s => s.time_Ma === +location.hash.slice(11));
    if (i >= 0) cur = i;
  }
  const probs = geoProblems(SL[cur]);
  const agg = {};
  for (const p of probs) for (const w of p.why) agg[w.split('(')[0]] = (agg[w.split('(')[0]]||0)+1;
  const div = document.createElement('div'); div.id = 'probeGeo';
  div.textContent = JSON.stringify({t: SL[cur].time_Ma, n_bad: probs.length,
    n_rings: SL[cur].land.length, by_kind: agg,
    worst: probs.slice(0, 10).map(p => ({ring: p.k, n: p.n, why: p.why}))});
  document.body.appendChild(div);
  document.title = 'geo done';
}
if (location.hash.startsWith('#probe:pick:')){  // 诊断：采样若干点的颜色（#probe:pick:220,100,2;...）
  const parts = location.hash.slice(12).split(';');
  const i0 = SL.findIndex(s => s.time_Ma === +parts[0]);
  if (i0 >= 0) cur = i0;
  const pts = parts.slice(1);
  draw();
  const w = Math.floor(cw()), h = Math.floor(ch());
  const d = landCtx.getImageData(0,0,w,h).data;
  const out = pts.map(s => {
    const [x, y] = s.split(',').map(Number);
    const p = (y*w+x)*4;
    return [x, y, d[p], d[p+1], d[p+2]];
  });
  const div = document.createElement('div');
  div.id = 'probePick'; div.textContent = JSON.stringify(out);
  document.body.appendChild(div);
  document.title = 'pick done';
}
if (location.hash.slice(0,12) === '#probe:ascii'){  // 诊断：把画布打成 ASCII 文字图（#probe:ascii,250 指定时代）
  if (location.hash[12] === ','){
    const i = SL.findIndex(s => s.time_Ma === +location.hash.slice(13));
    if (i >= 0) cur = i;
  }
  draw();
  const w = Math.floor(cw()), h = Math.floor(ch());
  const d = landCtx.getImageData(0,0,w,h).data;
  const R = 48, C = 96;                          // 行×列
  let out = '';
  const at = (x, y) => { const p = (Math.floor(y)*w + Math.floor(x))*4;
    return [d[p], d[p+1], d[p+2]]; };
  for (let r=0; r<R; r++){
    for (let c=0; c<C; c++){
      const [rr, gg, bb] = at((c+.5)/C*w, (r+.5)/R*h);
      if (rr>65 && rr<110 && gg>75 && gg<120 && bb>75 && bb<125) out += '█';      // 陆地
      else if (rr+gg+bb > 120) out += '▓';                                       // 海岸/网格/其他墨迹
      else out += '·';                                                            // 海洋
    }
    out += '\n';
  }
  const pre = document.createElement('pre');
  pre.id = 'probeAscii';
  pre.textContent = out;
  document.body.appendChild(pre);
  document.title = 'ascii done';
}
if (location.hash.slice(0,11) === '#probe:diff'){  // 诊断：两片之间的逐像素陆地差
  const [ta, tb] = location.hash.slice(12).split(',').map(Number);
  const ia = SL.findIndex(s => s.time_Ma === ta), ib = SL.findIndex(s => s.time_Ma === tb);
  const w = Math.floor(cw()), h = Math.floor(ch());
  const isLand = (x, y, d) => { const p = (y*w+x)*4;
    return d[p]>65 && d[p]<110 && d[p+1]>75 && d[p+1]<120 && d[p+2]>75 && d[p+2]<125; };
  cur = ia; draw(); const da = landCtx.getImageData(0,0,w,h).data;
  cur = ib; draw(); const db = landCtx.getImageData(0,0,w,h).data;
  let gone = 0, come = 0, gx = 0, gy = 0;
  // 找"消失"像素的重心
  let sx = 0, sy = 0;
  for (let y=0;y<h;y+=2) for (let x=0;x<w;x+=2){
    const a = isLand(x, y, da), b = isLand(x, y, db);
    if (a && !b){ gone++; sx += x; sy += y; }
    if (b && !a) come++;
  }
  const div = document.createElement('div');
  div.id = 'probeDiff';
  div.textContent = JSON.stringify({gone, come,
    centroid: gone ? [Math.round(sx/gone/ w*360-180), Math.round(90-sy/gone/h*180)] : null,
    gonePct: (gone/(w*h/4)*100).toFixed(2), comePct: (come/(w*h/4)*100).toFixed(2)});
  document.body.appendChild(div);
  document.title = 'diff probe done';
}
if (location.hash.slice(0,12) === '#probe:grid'){   // 诊断：逐片陆地像素按 15°×15° 网格计数
  const out = [];
  for (let i=0;i<SL.length;i++){
    cur = i; draw();
    const w = Math.floor(cw()), h = Math.floor(ch()), gw = 24, gh = 12;
    const d = landCtx.getImageData(0,0,w,h).data;
    const cells = new Array(gw*gh).fill(0);
    for (let y=0;y<h;y+=2) for (let x=0;x<w;x+=2){
      const p = (y*w+x)*4;
      if (d[p]>65 && d[p]<110 && d[p+1]>75 && d[p+1]<120 && d[p+2]>75 && d[p+2]<125)
        cells[Math.min(gh-1, Math.floor(y/h*gh))*gw + Math.min(gw-1, Math.floor(x/w*gw))]++;
    }
    out.push([SL[i].time_Ma, cells]);
  }
  const div = document.createElement('div');
  div.id = 'probeGrid';
  div.textContent = JSON.stringify(out);
  document.body.appendChild(div);
  document.title = 'grid probe done';
}
if (location.hash === '#probe:band'){      // 诊断：逐片"顶部条带/底部覆盖"扫描
  const w = Math.floor(cw()), h = Math.floor(ch());
  const isLand = p => p[0]>65 && p[0]<110 && p[1]>75 && p[1]<120 && p[2]>75 && p[2]<125;
  const bands = [[0,3],[3,8],[45,48],[40,45]];   // 顶部3行/再5行/底部3行/倒数4-8行（1/48 画面高）
  const out = [];
  for (let i=0; i<SL.length; i++){
    cur = i; draw();
    const d = landCtx.getImageData(0,0,w,h).data;
    const fr = bands.map(([y0,y1]) => {
      let land = 0, tot = 0;
      for (let y=Math.floor(y0*h/48); y<Math.floor(y1*h/48); y+=2)
        for (let x=0; x<w; x+=2){ tot++;
          const p = (y*w+x)*4;
          if (isLand([d[p],d[p+1],d[p+2]])) land++; }
      return land/tot;
    });
    out.push([SL[i].time_Ma, +fr[0].toFixed(3), +fr[1].toFixed(3), +fr[2].toFixed(3), +fr[3].toFixed(3)]);
  }
  const div = document.createElement('div');
  div.id = 'probeBand';
  div.textContent = JSON.stringify(out);
  document.body.appendChild(div);
  document.title = 'band scan done';
}
if (location.hash === '#probe:perf'){     // 诊断：渲染耗时（顶点翻倍后回答"会不会卡"）
  const N = 30; const ts = [];
  for (let i=0;i<N;i++){ const a = performance.now();
    cur = (i*7)%SL.length; draw(); ts.push(performance.now()-a); }
  const mean = ts.reduce((x,y)=>x+y,0)/N, max = Math.max(...ts);
  const div = document.createElement('div'); div.id = 'probePerf';
  div.textContent = JSON.stringify({n:N, mean_ms:Math.round(mean*100)/100,
    max_ms:Math.round(max*100)/100, vertices:SL[cur].land.reduce((s,r)=>s+r.length,0)});
  document.body.appendChild(div);
  document.title = 'perf done';
}
if (location.hash === '#probe:frames'){     // 诊断：逐片渲染像素统计（找"缺一块"的元凶）
  const out = [];
  for (let i=0;i<SL.length;i++){
    cur = i; draw();   // 同步直绘：无头环境 rAF 不推进
    const w = Math.floor(cw()), h = Math.floor(ch());     // 全帧
    const d = landCtx.getImageData(0,0,w,h).data;
    let n = 0;
    for (let p=0;p<d.length;p+=4) {
      // 陆地按 globalAlpha .4 合成后的颜色 ≈ (83,93,95)；海洋/网格不计
      if (d[p]>65 && d[p]<110 && d[p+1]>75 && d[p+1]<120 && d[p+2]>75 && d[p+2]<125) n++;
    }
    out.push([SL[i].time_Ma, n, SL[i].metrics.land_area_km2, n/(w*h)]);
  }
  const div = document.createElement('div');
  div.id = 'probeFrames';
  div.textContent = JSON.stringify(out);
  document.body.appendChild(div);
  document.title = 'frames probe done';
}
if (location.hash === '#probe:scanpx'){          // 诊断：该像素在 81 片中何时被画
  const px = 400, py = 441;
  const hits = [];
  for (let i = 0; i < SL.length; i++){
    cur = i; draw();
    const d = ctx.getImageData(px, py-52, 1, 1).data;          // fx 层
    const d2 = landCtx.getImageData(px, py-52, 1, 1).data;     // 陆地层
    if (d[3] > 0 || d2[3] > 0) hits.push([SL[i].time_Ma, [...d].slice(0,3), [...d2].slice(0,3)]);
  }
  const div = document.createElement('div'); div.id = 'probeScan';
  div.textContent = JSON.stringify(hits); document.body.appendChild(div);
  document.title = 'scan done';
}
if (location.hash.slice(0,12) === '#probe:layer'){   // 诊断：某像素在哪个画布层被画
  const parts = location.hash.slice(13).split(',').map(Number);   // '#probe:layer,' 共 13 字符
  const [px, py] = parts; const pt = parts[2];
  if (pt !== undefined){ const i = SL.findIndex(s => s.time_Ma === pt); if (i >= 0) cur = i; }
  draw();                                       // 同步画完再读
  const out = {};
  const ids = ['cvBg','cvGrat','cvLand','cvCoast','cv'];
  for (const id of ids){
    const cvl = document.getElementById(id);
    const cx = cvl.getContext('2d');
    const d = cx.getImageData(px * devicePixelRatio, (py - 52) * devicePixelRatio, 1, 1).data;
    out[id] = [d[0], d[1], d[2], d[3]];
  }
  const els = document.elementsFromPoint(px, py).map(e =>
    (e.id ? '#' + e.id : e.tagName) + (e.className && e.className.baseVal === undefined ? '.' + String(e.className).split(' ')[0] : ''));
  out.elsAt = els;
  const cvl2 = document.getElementById('cv');
  out.meta = { dpr: devicePixelRatio, iw: innerWidth, ih: innerHeight,
    cvW: cvl2.width, cvH: cvl2.height,
    rectTop: document.getElementById('stage').getBoundingClientRect().top };
  const cx2 = cvl2.getContext('2d');
  const cand = [[px, py-52], [px, py], [px*devicePixelRatio, (py-52)*devicePixelRatio], [px, py*2]];
  out.cvCandidates = cand.map(([x,y]) => { const d = cx2.getImageData(x, y, 1, 1).data; return [Math.round(x), Math.round(y), d[0], d[1], d[2], d[3]]; });
  const div = document.createElement('div'); div.id = 'probeLayer';
  div.textContent = JSON.stringify(out);
  document.body.appendChild(div); document.title = 'layer done';
}
if (location.hash === '#probe'){           // 验收用：把布局体检写进 title
  document.title = JSON.stringify({
    sw: document.documentElement.scrollWidth, sh: document.documentElement.scrollHeight,
    iw: innerWidth, ih: innerHeight,
    btnCut: [...document.querySelectorAll('#top button')]
      .filter(b => b.getBoundingClientRect().right > innerWidth + 1).map(b => b.id),  // B10：被裁≠不可见
    cur: SL[cur].time_Ma});
}
</script></body></html>
"""


def main():
    if not os.path.exists(EARTH_PATH) or not os.path.exists(CHECKS_PATH):
        sys.exit("先跑 .venv/bin/python build.py 生成 earth.json / checks.json")
    earth = json.load(open(EARTH_PATH, "r", encoding="utf-8"))
    checks = json.load(open(CHECKS_PATH, "r", encoding="utf-8"))
    html = (TEMPLATE
            .replace("__EARTH__", json.dumps(earth, separators=(",", ":"), ensure_ascii=False))
            .replace("__CHECKS__", json.dumps(checks, separators=(",", ":"), ensure_ascii=False))
            )
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[write] {OUT_PATH}  ({os.path.getsize(OUT_PATH)/1e6:.1f} MB，数据内联，离线可开)")
    for key in ("slices", "markers", "events"):
        if key not in earth:
            sys.exit(f"earth.json 缺字段 {key}")


if __name__ == "__main__":
    main()
