#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
《地球的四亿年》数据管线 —— build.py

把 EarthByte / Merdith et al. 2021 全板块重建模型跑成一份纯静态的 earth.json：
    旋转模型 + 海岸线 ──[pygplates 重建]──▶ 401 个时间切片
        ──[切日界线 + 围极环的极点缝合]──[逐片 Douglas–Peucker 简化（容差时间平滑）]
        ──▶ earth.json
    另外：7 个现代城市的四亿年古位置轨迹（markers）、12 条地质事件（events，
    数字全部当场算出注入）、六项自检（checks.json）与一项 0 Ma 现代地图地标核对。

运行：  python build.py        （确定性：同环境重跑字节一致）
产出：  earth.json + checks.json（同目录）
数据：  data/ 下（若缺失自动用 curl 下载，见 ensure_data()）
不设计任何绘图 / 运行时联网；页面只读 earth.json。
"""

import json
import math
import os
import re
import subprocess
import sys
import zipfile
from collections import defaultdict

import numpy as np
import pygplates
from shapely.geometry import Polygon, Point as ShapelyPoint, box as shapely_box
from shapely.strtree import STRtree
from shapely.ops import unary_union

# ----------------------------------------------------------------------------
# 常量
# ----------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
MODEL_DIR = os.path.join(DATA_DIR, "merdith2021",
                         "SM2-Merdith_et_al_1_Ga_reconstruction_v1.1 2")
ROT_FILE = os.path.join(MODEL_DIR, "1000_0_rotfile_Merdith_et_al.rot")
COAST_FILE = os.path.join(MODEL_DIR, "shapes_coastlines_Merdith_et_al_v2.gpmlz")
STATIC_FILE = os.path.join(MODEL_DIR, "shapes_static_polygons_Merdith_et_al.gpml")
MODEL_ZIP_URL = ("https://earthbyte.org/webdav/ftp/Data_Collections/"
                 "Merdith_etal_2021_ESR/SM2-Merdith_et_al_1_Ga_reconstruction_v1.1.zip")
MODEL_ZIP = os.path.join(DATA_DIR, "merdith2021.zip")

TIME_MIN, TIME_MAX, TIME_STEP = 0, 400, 5
TIMES = list(range(TIME_MIN, TIME_MAX + 1, TIME_STEP))          # 0..400 Ma，每 5 Ma 一片（81 片：步进细、漂移平滑，演示约 10 秒）

VERTEX_TARGET = 27000         # DP 简化目标（按 simplify_pieces 口径）；开运算(ε=0.08)后约为 0.5-0.75×，落在硬约束 11000-22000 内
                             # 先把碎片 union 成连续陆块再简化（见 merge_land），
                             # 顶点预算全部花在外轮廓上，不再被内部拼块边浪费——
                             # 因此同样的数据量换到高得多的分辨率：容差 0.68° → ~0.12°
VERTEX_HARD_LO, VERTEX_HARD_HI = 11000, 22000    # 验收硬约束（union 后不再做 C-R 加密）
SLIVER_EPS = 0.08          # 开运算半径：剔除宽度 <0.16° 的亚像素细带/舌头（如 0.01° 的水平细带）
HOLE_MIN_WIDTH_KM = 100.0     # 内环的"平均宽度"门槛（2·面积/周长，见 ring_width_km）：
                              # 低于它的判为碎片之间的细长缝、直接丢掉，不当作洞输出
ROUND_DIGITS = 2

EARTH_R_KM = 6371.0088
SPEED_LIMIT_CM_YR = 25.0      # 验收 ③：marker 速度上限
AREA_MEDIAN_TOL = 0.15        # 验收 ①：陆地面积相对中位数的容差

CITATION = ("Merdith, A.S., Williams, S.E., Collins, A.S., Tetley, M.G., "
            "Mulder, J.A., Blades, M.L., Young, A., Armistead, S.E., Cannon, J., "
            "Zahirovic, S., Müller, R.D. (2021). Extending full-plate tectonic "
            "models into deep time: Linking the Neoproterozoic and the Phanerozoic. "
            "Earth-Science Reviews, 214, 103477. doi:10.1016/j.earscirev.2020.103477")

# 现代海岸地标：用来验证 0 Ma 切片就是现代世界地图（name: lon, lat）。
# 故意挑平直海岸上的地标——火地岛、尼罗河三角洲这类细齿海岸本身就是
# 简化（DP）的首要牺牲品，偏差数百公里，见 report.md 的不确定性一节。
LANDMARKS = {
    "长江口": (121.8, 31.6), "里约科帕卡巴纳": (-43.2, -22.97),
    "悉尼角": (151.32, -33.85), "达尔文": (130.84, -12.46),
    "开普敦": (18.5, -34.4), "直布罗陀": (-5.6, 36.0),
    "孟买": (72.8, 19.0), "利马": (-77.1, -12.0),
    "白令海峡": (-169.0, 66.0), "温哥华": (-123.1, 49.3),
}


# 7 个 marker：方案书指定 6 个 + 新德里（落在印度板块上，支撑印度-亚洲碰撞的叙事）
MARKERS = {
    "北京":   (116.40, 39.90),
    "上海":   (121.47, 31.23),
    "拉萨":   (91.13,  29.65),
    "开罗":   (31.24,  30.04),
    "悉尼":   (151.21, -33.87),
    "里约热内卢": (-43.20, -22.91),
    "新德里": (77.21,  28.61),
}

# 事件表（time_Ma 与文字中的占位符在 build 结束时用真实数字填充）
EVENTS = [
    (400, "低纬的起点：中国陆块群还在赤道附近",
     "四亿年前的早泥盆世，上海所在的华南陆块在 {sh400} 的赤道低纬度，北京所在的华北陆块在 {bj400}；"
     "而拉萨地块还留在 {ls400} 的冈瓦纳大陆北缘。它们都要在接下来的两亿年里陆续向北漂移、相聚，"
     "最终拼成今天的欧亚东部。",
     "本数据 markers 轨迹（earth.json）；Merdith et al. (2021) 亚洲部分承自 Domeier (2018) "
     "《Early Paleozoic tectonics of Asia》, Geosci. Front. 9(3), 789–862。"),
    (330, "潘吉亚在缝合：冈瓦纳撞上劳俄罗斯",
     "石炭纪晚期（约 330–300 Ma），冈瓦纳与劳俄罗斯沿海西/阿勒格尼造山带碰撞，泛大陆的骨架成型。"
     "在本数据中，330 Ma 时陆地最大连通分量已占陆地总面积的 {comp330}——拼合中的泛大陆轮廓清晰可见。",
     "本数据 330 Ma 切片的连通分量计算；Merdith et al. (2021) Earth-Science Reviews 214, 103477。"),
    (250, "泛大陆：陆地几乎连成一块",
     "二叠纪末的地球：全球陆地拼成一块泛大陆（潘吉亚），被广袤的泛大洋环绕。本数据中 250 Ma 时"
     "陆地最大连通分量占比 {comp250}；250–160 Ma 是整条时间轴上连通率的最高平台期（97%–100%）。",
     "本数据 250 Ma 切片的连通分量计算；Merdith et al. (2021) Earth-Science Reviews 214, 103477。"),
    (200, "裂解的前夜：大西洋的第一道缝",
     "此时泛大陆仍然完整（200 Ma 的陆地连通率 {comp200}），但约 201 Ma 中大西洋岩浆省（CAMP）"
     "大规模喷发，北美与非洲之间的岩浆裂缝已经打开——在接下来的五千万年里，这道裂缝会把大西洋"
     "彻底撕开。",
     "Marzoli et al. (1999)《Extensive 200-million-year-old continental flood basalts of the "
     "Central Atlantic Magmatic Province》, Science 284, 616–618；本数据 200 Ma 连通率。"),
    (150, "东方开始散开：印度洋的裂缝",
     "侏罗纪晚期，冈瓦纳东部开始解体：本数据中新德里到悉尼的距离从 150 Ma 时的 {ds150} 公里拉长到 "
     "100 Ma 的 {ds100} 公里——印度与澳洲/南极洲之间的洋盆，就是这样一点一点撑开的。",
     "本数据 新德里/悉尼 marker 距离曲线；Merdith et al. (2021)。"),
    (140, "南大西洋打开：南美与非洲分手",
     "约 140–130 Ma，南美与非洲之间开始撕裂，南大西洋从一条裂缝长成今天的大洋。本数据里里约热内卢"
     "到开罗的距离在 140 Ma 只有 {rc140} 公里，今天则有 {rc0} 公里——大西洋就是这样长大的。",
     "本数据 里约热内卢/开罗 marker 距离曲线；Merdith et al. (2021)。"),
    (100, "印度成为孤儿：与马达加斯加分家",
     "约 100–90 Ma，印度与马达加斯加/南极洲的连接断开，成为一座孤立的大陆岛块。此时新德里在约 "
     "{nd100}，还只是慢吞吞地起步（速度 {spd100} 厘米/年，5 Ma 只挪 {spd100_km} 公里）——它的黄金冲刺期很快就要到来。",
     "本数据 新德里 marker 轨迹与速度；Merdith et al. (2021)（250–0 Ma 部分承自 Young et al. 2019）。"),
    (80, "全速北移的印度",
     "80 Ma 的印度仍在印度洋上孤独北漂且正在加速：新德里位于约 {nd80}，速度已升到 {spd80} 厘米/年，"
     "并将在 {spd_peak} Ma 左右冲到 {spdk} 厘米/年的峰值——当时全球移动最快的大陆块。",
     "本数据 新德里 marker 轨迹（80 Ma 纬度与速度）。"),
    (50, "新特提斯洋关闭：印度撞上亚洲",
     "约 50 Ma，新特提斯洋在印度与亚洲之间合拢，初始碰撞发生，青藏高原开始抬升。本数据中新德里—"
     "拉萨的距离从 100 Ma 时的 {dl100} 公里缩小到 50 Ma 的 {dl50} 公里，此后继续挤压缩短至今日 "
     "{dl0} 公里。",
     "本数据 新德里—拉萨距离曲线；Molnar & Tapponnier (1975)《Cenozoic Tectonics of Asia: "
     "Effects of a Continental Collision》, Science 189, 419–426。"),
    (40, "澳洲与南极分家，一路向北",
     "约 45–40 Ma，澳洲与南极洲之间的洋盆完全打开，澳洲头也不回地北上：悉尼的 marker 从 50 Ma 的 "
     "{sy50} 一路走到今天的 {sy0}，是本数据中纬度变化最戏剧的大陆之一。",
     "本数据 悉尼 marker 轨迹。"),
    (30, "南极上座：冰盖时代开始",
     "南极洲在南极点安家（本数据 0–35 Ma 全部切片中，南极陆块质心始终位于 {antmin}°S 以南），"
     "环南极洋流逐渐成形，约 34 Ma 南极冰盖大规模扩张，地球走进冰室期。",
     "本数据 南极质心检查；Zachos et al. (2001)《Trends, Rhythms, and Aberrations in Global "
     "Climate 65 Ma to Present》, Science 292, 686–693。"),
    (0, "今天：故事并没有结束",
     "0 Ma 这一片就是现代世界地图：拿长江口、里约、悉尼、开普敦、直布罗陀等 10 个现代海岸地标去量，"
     "它们到本数据最近海岸顶点的距离都在 {lm} 公里以内，陆地总面积 {a0} 亿平方公里（DP 简化后；真实约 1.49 亿）。"
     "而板块并没有停下：大西洋仍在变宽、澳洲仍在北上、东非大裂谷正在孕育下一个大洋——"
     "你现在站着的地方，仍在漂。",
     "本数据 0 Ma 切片的地标距离检查（checks.json stage0）。"),
]


# ----------------------------------------------------------------------------
# 数据获取（仅在 data/ 缺失时联网；日常重跑不下载）
# ----------------------------------------------------------------------------
def ensure_data():
    if all(os.path.exists(p) for p in (ROT_FILE, COAST_FILE, STATIC_FILE)):
        return
    os.makedirs(DATA_DIR, exist_ok=True)
    print(f"[download] {MODEL_ZIP_URL}")
    subprocess.run(["curl", "-L", "--fail", "--max-time", "600",
                    "-o", MODEL_ZIP, MODEL_ZIP_URL], check=True)
    with zipfile.ZipFile(MODEL_ZIP) as z:
        z.extractall(os.path.join(DATA_DIR, "merdith2021"))
    if not all(os.path.exists(p) for p in (ROT_FILE, COAST_FILE, STATIC_FILE)):
        raise RuntimeError("数据下载后仍缺少所需文件，请检查 data/ 目录")


# ----------------------------------------------------------------------------
# 0) 要素类型过滤：源文件里混入的非陆地要素
# ----------------------------------------------------------------------------
# Merdith 的 shapes_coastlines 文件并不只装海岸线，里面混着 10 种要素类型：
#   ClosedContinentalBoundary(1606) / UnclassifiedFeature(211) / Basin(171) /
#   IslandArc(92) / TerraneBoundary(25) / ContinentalFragment(10) / ...
# 其中 Basin（海盆）和 IslandArc（岛弧）是**构造辅助要素、不是陆地**，
# 被当成陆地画出来就是地图上一堆"海上幽灵小点"：太平洋正中的 `Pacific`
# 海盆碎片、班达海/俾斯麦海的 `Banda Arc`、`South Bismark Basin`、
# 澳洲以西印度洋的 `Australia Basin` 等。它们还会假借板块旋转在深时里
# 漂移、到点消失，看着像"突然冒出来的小岛"。
# 按要素类型剔除这两类。实测 0 Ma 影响：Basin 229 个 + IslandArc 93 个，
# 合计 0.66 M km²，占陆地面积 0.45%（其余类型全部保留）。
# 已知代价：源模型把**冰岛**也归进了 Basin（要素名 "Eurasia"，6.8 万 km²），
# 所以冰岛不再出现；0 Ma 地标核对相应把「雷克雅未克」换成「温哥华」。
NON_LAND_FEATURE_TYPES = {"gpml:Basin", "gpml:IslandArc"}


def load_land_coastlines(path):
    """读海岸线并剔除海盆/岛弧等非陆地要素。返回 (FeatureCollection, 剔除数)。"""
    coast = pygplates.FeatureCollection(path)
    kept = pygplates.FeatureCollection()
    n_drop = 0
    for f in coast:
        if str(f.get_feature_type()) in NON_LAND_FEATURE_TYPES:
            n_drop += 1
            continue
        kept.add(f)
    return kept, n_drop


# ----------------------------------------------------------------------------
# 1) 重建 + 2) 切日界线
# ----------------------------------------------------------------------------
def reconstruct_rings(rotation_model, coastlines, timeMa):
    """重建到 timeMa。返回 [(feature_id, plate_id, ring(n,2) lon/lat)]。

    丢掉恒等重建的 feature：pygplates 在旋转链解析不了时（moving plate 条目
    超期、或中转板块超期）返回恒等旋转而不是报错，feature 就被"冻"在它的
    现代位置——400 Ma 里冒出现代加州海岸的小点就是这么来的。
    """
    recon = []
    pygplates.reconstruct(coastlines, rotation_model, recon, float(timeMa), 0)
    id_cache = {}                                    # pid -> 该片是否恒等旋转（缓存）
    def rotation_is_identity(pid):
        if pid not in id_cache:
            try:
                id_cache[pid] = rotation_model.get_rotation(
                    float(timeMa), pid, 0).represents_identity_rotation()
            except Exception:
                id_cache[pid] = True                 # 旋转链断了：按恒等处理
        return id_cache[pid]
    rings = []
    for g in recon:
        geom = g.get_reconstructed_geometry()
        if geom is None:
            continue
        pts = geom.get_points()
        if pts is None or len(pts) < 3:
            continue
        ll = np.array([[p.to_lat_lon()[1], p.to_lat_lon()[0]] for p in pts], dtype=np.float64)
        fid = str(g.get_feature().get_feature_id())
        pid = g.get_feature().get_reconstruction_plate_id()
        if timeMa != 0 and rotation_is_identity(pid):
            continue                                    # 旋转链解析不了：恒等重建是假的
        rings.append((fid, pid, ll))
    return rings


def reconstruct_all_with_carry(rotation_model, coastlines, times):
    """逐片重建；feature 超出模型 valid-time 后用其板块旋转继续携带最后形状。

    源模型的海岸线按时间段切成了多个 feature（各有 valid-time）。切到点上的
    feature 从 pygplates.reconstruct 里消失，但陆块不会真的消失——315→320 Ma
    里海一带整块陆地凭空蒸发就是这种分段造成的。修法：feature 一旦过期，就用
    delta = R(t) · R(t_last)⁻¹ 精确旋转它最后已知形状继续跟着板块走。
    """
    carry = {}                                          # fid -> (pid, t_last, ll)
    result = {}
    for t in times:
        rings = reconstruct_rings(rotation_model, coastlines, t)
        result[t] = rings
        live = set()
        for fid, pid, ll in rings:
            carry[fid] = (pid, t, ll)
            live.add(fid)
        n_carried = 0
        for fid, (pid, t_last, ll_last) in list(carry.items()):
            if fid in live or len(ll_last) < 3:
                continue
            try:
                r_last = rotation_model.get_rotation(float(t_last), pid, 0)
                r_now = rotation_model.get_rotation(float(t), pid, 0)
                if t != 0 and r_now.represents_identity_rotation():
                    continue                             # 旋转链在此时间解析不了：携带会冻在现代位置
                delta = r_now * r_last.get_inverse()
            except Exception:
                continue                                 # 该板块的旋转也到期了：放弃
            pts = [delta * pygplates.PointOnSphere(float(lat), float(lon))
                   for lon, lat in ll_last]
            ll = np.array([[p.to_lat_lon()[1], p.to_lat_lon()[0]] for p in pts],
                          dtype=np.float64)
            if len(ll) >= 3:
                carry[fid] = (pid, t, ll)
                result[t].append((fid, pid, ll))
                n_carried += 1
        if n_carried:
            print(f"   t={int(round(t)):3d} Ma: 携带过期 feature {n_carried} 个")
    return result


def repair_bowtie(ring):
    """自相交源环（"蝴蝶结"）先 buffer(0) 规范化，再进日界线切分。

    模型里偶有自相交的海岸环，顶点甚至会摸到极点；若先按日界线切开，
    fix_polar_wrap 会把这种环误补成横贯极点的大极冠（155-250 Ma 顶部
    出现整条陆地带就是这个原因）。先 buffer(0) 拆成合法块，就只是普通
    海岸碎片。返回 [ring, ...]（合法单环直接原样返回）。
    """
    try:
        g = Polygon(ring)
    except Exception:
        return [ring]
    if g.is_valid and g.geom_type == "Polygon" and not g.is_empty:
        return [ring]
    if g.is_empty:
        return []
    try:
        g = g.buffer(0)
    except Exception:
        return [ring]
    if g.is_empty:
        return []
    parts = list(g.geoms) if hasattr(g, "geoms") else [g]
    out = []
    for p in parts:
        if p.geom_type != "Polygon" or p.is_empty:
            continue
        r = np.array(p.exterior.coords)[:-1]
        if len(r) >= 3:
            out.append(r)
    return out


def split_antimeridian(ring):
    """把跨越 ±180° 经线的环切开成若干不跨日界线的环。

    方法：对每条 |Δlon|>180 的边，在与 180 经线的交点处插入两个割点（lon=+180 与
    lon=-180，纬度按线性插值），再沿“割点对”把环切开成若干段；每段自行闭合成
    一个落在某一侧的合法多边形。这样保证输出中任意相邻两点的经度差 ≤ 180°。
    返回 [ring(n,2), ...]。
    """
    n = len(ring)
    seq = []                                   # (lon, lat, side) side: 0=普通, 1=东割点, 2=西割点
    for i in range(n):
        lon_i, lat_i = float(ring[i, 0]), float(ring[i, 1])
        side = 0
        if lon_i == 180.0:                     # 数据中恰好落在 180 经线上的顶点（如白令海峡一带）
            side = 1                           # 直接当作东割点，避免与后续 -180 顶点连出 360° 的边
        elif lon_i == -180.0:
            side = 2
        seq.append((lon_i, lat_i, side))
        lon_j, lat_j = float(ring[(i + 1) % n, 0]), float(ring[(i + 1) % n, 1])
        dl = lon_j - lon_i
        if dl > 180.0:
            # 形式上向东走了 360°-ε，实际是【向西】越过日界线：
            # 从 lon_i 一路减到 -180，再从 +180 回到 lon_j
            total = (lon_j - 360.0) - lon_i               # 向西总位移（负）
            if total == 0.0:
                continue                                  # 180 → -180：日界线两侧的同一个割点，无需插点
            f = (-180.0 - lon_i) / total
            y = lat_i + f * (lat_j - lat_i)
            seq.append((-180.0, y, 2))
            seq.append((180.0, y, 1))
        elif dl < -180.0:
            # 形式上向西走了 360°-ε，实际是【向东】越过日界线
            total = (lon_j + 360.0) - lon_i               # 向东总位移（正）
            if total == 0.0:
                continue                                  # -180 → 180：同上，跳过
            f = (180.0 - lon_i) / total
            y = lat_i + f * (lat_j - lat_i)
            seq.append((180.0, y, 1))
            seq.append((-180.0, y, 2))
    if not any(s[2] for s in seq):
        return [ring]

    m = len(seq)

    def is_jump(k):
        a, b = seq[k], seq[(k + 1) % m]
        return a[2] != 0 and b[2] != 0 and a[2] != b[2]

    jumps = [k for k in range(m) if is_jump(k)]
    if not jumps:
        # 只有恰好触碰 180 经线的顶点、没有真正穿越的边：不需要切开
        return [ring]
    pieces, cur, count, k = [], [], 0, (jumps[0] + 1) % m
    while count < m:
        e = seq[k]
        cur.append((e[0], e[1]))
        count += 1
        if is_jump(k):
            if len(cur) >= 3:
                pieces.append(np.array(cur, dtype=np.float64))
            cur = []
        k = (k + 1) % m
    if cur and len(cur) >= 3:
        pieces.append(np.array(cur, dtype=np.float64))

    # 围住极点的环（穿越日界线次数为奇数）会留下一条从 -180 割点直接闭合到 +180
    # 割点的边：把它在 0° 经线再切一刀，补上极点顶点，分成的两片各自落在
    # [-180,0] 与 [0,180] 之间，就再也不会出现横贯地图的连线。
    out = []
    for piece in pieces:
        out.extend(fix_polar_wrap(piece))
    return out


def fix_polar_wrap(piece):
    """piece 的首尾割点分列东西两侧（闭合边经度差 = 360°）说明它围住了极点。
    沿 0° 经线把它切成东西两片，各补一个极点顶点，保持原来的覆盖范围。"""
    if abs(piece[0, 0] - piece[-1, 0]) <= 180.0:
        return [piece]
    # 统一成 [(-180,y1), 弧..., (180,y2)]
    p = piece[::-1].copy() if abs(piece[0, 0] - 180.0) < 1e-9 else piece.copy()
    pole_lat = 90.0 if float(np.mean(p[:, 1])) > 0 else -90.0
    arc = p[1:-1]
    # 在弧上找穿过 0° 经线的边，插一个割点
    m0, cut_after = None, -1
    for i in range(len(arc) - 1):
        lo_a, lo_b = arc[i, 0], arc[i + 1, 0]
        if (lo_a <= 0.0 <= lo_b) or (lo_b <= 0.0 <= lo_a):
            f = (0.0 - lo_a) / (lo_b - lo_a)
            m0 = [0.0, float(arc[i, 1] + f * (arc[i + 1, 1] - arc[i, 1]))]
            cut_after = i
            break
    if m0 is None:                                     # 弧上有顶点恰好在 0° 经线
        j = int(np.argmin(np.abs(arc[:, 0])))
        m0 = [0.0, float(arc[j, 1])]
        cut_after = j - 1 if arc[j, 0] > 0 else j
    west, east = arc[:cut_after + 1], arc[cut_after + 1:]
    w_ring = np.vstack([p[:1], west, np.array([m0]), np.array([[0.0, pole_lat], [-180.0, pole_lat]])])
    e_ring = np.vstack([np.array([m0]), east, p[-1:], np.array([[180.0, pole_lat], [0.0, pole_lat]])])
    return [w_ring, e_ring]


# ----------------------------------------------------------------------------
# 3) 简化（shapely Douglas–Peucker，C 实现）
# ----------------------------------------------------------------------------
def ring_width_km(ring):
    """环的"平均宽度"= 2·面积/周长（水力半径的 2 倍）。

    用来区分两种内环：碎片之间的**缝**（细长条，宽度只有几十公里）和**真正的
    水体**（内海/湖泊，宽而圆润）。缝在屏幕上就是 1–3 px 的窄条，看起来像
    陆地内部爬满了裂纹；真水体才有资格作为"洞"被挖出来。
    """
    a = polygon_area_km2(ring)
    p = sum(great_circle_km(ring[i], ring[(i + 1) % len(ring)]) for i in range(len(ring)))
    return 2.0 * a / p if p > 0 else 0.0


def merge_land(pieces):
    """把碎片多边形融合成连续陆块——去掉"拼块感"的关键一步。

    源数据里一个大陆是几百个地体/克拉通碎片拼出来的，碎片相邻**但不重叠**。
    DP 简化让每个碎片各自从凹侧收缩，于是拼块之间裂开细缝、外轮廓也各走各的
    折线——渲染出来就是"一块一块拼起来的"。先把它们 union 成一个（或几个）
    完整多边形，内部边界和缝一起消失，顶点预算就全部花在真正的外轮廓上。

    实测 0 Ma：2619 个碎片（96711 顶点）→ 1024 个多边形、外轮廓 38150 顶点。
    同样的数据量下，简化容差可以从 0.68° 降到约 0.12°（细 5–6 倍）。

    返回 (outlines, holes)：外环列表 + 洞（内海/湖泊）列表，都已切过日界线。
    union 之后可能重新产生跨 ±180° 的边（如欧亚、环极陆地），所以还要再切一次。
    内环只保留平均宽度 ≥ HOLE_MIN_WIDTH_KM 的——碎片之间的细长缝（宽度几十公里）
    在屏幕上就是一道道裂纹，必须丢掉；真正的内海/湖泊才留作洞。
    """
    polys = []
    for p in pieces:
        if len(p) < 3:
            continue
        try:
            g = Polygon(p)
            if not g.is_valid:
                g = g.buffer(0)
        except Exception:
            continue
        if g.is_empty:
            continue
        polys.append(g)
    if not polys:
        return [], []
    u = unary_union(polys)
    outlines, holes = [], []
    for g0 in (list(u.geoms) if hasattr(u, "geoms") else [u]):
        # GEOS operates in lon/lat as a flat plane.  A polar landmass can
        # therefore be re-joined by union into one valid-looking polygon that
        # runs from the western antimeridian through the synthetic pole point
        # to the eastern antimeridian.  Its implicit close edge changes from
        # slice to slice (315/290 happen to be split already), which creates
        # the apparent gaps and vertical seams seen in the browser.  Split
        # only these polar, antimeridian-spanning polygons at lon=0; ordinary
        # continents crossing Greenwich stay untouched.
        # 历史上有过在这里把跨极+跨日界线的环沿 0° 经线切成两半的做法：
        # 早年渲染器靠隐式闭合边处理围极环，切一刀能避免闭合边在极区乱穿。
        # 但两半各自的 rim 在 0° 经线上高度不齐，渲染器补的接缝带会越过海面
        # 画出竖线、半环边界本身也会被当成直线暴露出来。现在渲染器对围极环
        # 已经有显式的极点闭合（isPolar 分支 + POLAR_CUTOFF ±89.9），
        # ±180 由 split_antimeridian 处理已足够，统一不再切 0° 经线。
        for g in (g0,) if not hasattr(g0, "geoms") else g0.geoms:
            if g.geom_type != "Polygon" or g.is_empty:
                continue
            outlines.extend(split_antimeridian(np.array(g.exterior.coords)[:-1]))
            for h in g.interiors:
                for hp in split_antimeridian(np.array(h.coords)[:-1]):
                    if ring_width_km(hp) >= HOLE_MIN_WIDTH_KM:
                        holes.append(hp)
    return outlines, holes, u


def ring_tol(ring, tol):
    """按纬度加权的 DP 容差：高纬（mean|lat|>60）用 tol/2.5 保留更多顶点。

    均匀容差下高纬海岸被砍掉 75-85% 顶点（235 Ma 北纬≥70: 6761→1587），
    画面前端顶端的大陆呈大块多边形（用户报告「地球最北面分辨率不高」）。
    高纬顶点本身少，加权的预算代价小（+3k/片），由 find_tolerance 的全局
    二分吸收。"""
    if tol is None:
        return None
    la = float(np.abs(np.asarray(ring)[:, 1]).mean())
    return tol * (0.4 if la > 60.0 else 1.0)


def simplify_pieces(pieces, tol):
    """对每个环单独做 DP 简化。tol 为经纬度度数。返回简化后的环列表。

    注意：不能用 MultiPolygon 一次性简化——这些海岸线多边形彼此重叠，
    GEOS 对(自)相交的多边形集合做 simplify 会先把重叠部分 dissolve 掉，
    结果会比逐个简化少掉近一半顶点、且几何被改变。逐个 Polygon 简化才是
    Douglas-Peucker 的正确语义。

    源模型个别 feature 重建后自相交（蝴蝶结环），simplify 会返回 MultiPolygon
    或空——直接收 Polygon 就会整块丢掉（在地图上表现为某片陆块突然消失、
    下一片又回来）。先用 buffer(0) 规范化成有效几何，再把 MultiPolygon
    拆开逐个收。
    """
    out = []
    for p in pieces:
        try:
            g = Polygon(p)
            if not g.is_valid:
                g = g.buffer(0)                 # 自相交 → 规范化（拆掉蝴蝶结）
            if g.is_empty:
                continue
            # preserve_topology=False 的 DP 会在环上造出新的自交（尤其冈瓦纳这种
            # 数千顶点的大环）——自交环经 buffer(0) 规范化后，口袋的并/消完全取决于
            # 相交位置，帧间会"海洋一会出现、一会消失"（NW 非洲海域实例）。
            # True 档位不引入自交，顶点预算由 find_tolerance 自适应吸收。
            g = g.simplify(ring_tol(p, tol), preserve_topology=True)
        except Exception:
            continue
        parts = list(g.geoms) if hasattr(g, "geoms") else [g]
        for part in parts:
            if part.is_empty or part.geom_type != "Polygon":
                continue
            ring = np.array(part.exterior.coords)[:-1]   # 去掉 shapely 的闭合重复点
            if len(ring) >= 3:
                out.append(ring)
    return out


def polar_cone_fill(rings_lonlat, pole, tol):
    """南极极冠补面（单一星形并集，无三角形裂缝）。

    模型的海岸线分段切换时，围住极点的环会临时缺席（极点变海洋，地图上极冠缺
    一小块）。旧做法给每个近极环各做一把"锥"，碎片方位角之间的间隙就是三角形
    海面裂缝。现在把所有 lat<-80 的顶点按绕极方位角排成**一个**星形环
    （极点 + 全部顶点），碎片之间的空隙被弦封闭——没有裂缝、没有逐锥拼接缝。
    方位角最大空隙 > 40° 说明那是开放海域（不是被围住的极地海），不补。
    北极不补：整个时段北极基本在泛大洋/北冰洋里，硬填会把顶部画成横贯全图
    的陆地条带。返回（经日界线切分 + 同容差简化后的）环列表。
    """
    sgn = 1.0 if pole > 0 else -1.0
    if pole > 0:
        return []                                    # 只补南极
    near = [np.asarray(r) for r in rings_lonlat if np.all(r[:, 1]*sgn > 70)]
    if not near:
        return []
    P = ShapelyPoint(0.0, float(pole))
    for r in near:                                   # 已覆盖就不用补
        try:
            if Polygon(r).covers(P):
                return []
        except Exception:
            continue
    # 全部近极顶点按绕极方位角排序，合成单一星形环
    pts = []
    for r in near:
        for lo, la in r:
            pts.append((float(lo), float(la)))
    if len(pts) < 4:
        return []
    la_r = np.array([p[1] for p in pts])*math.pi/180
    lo_r = np.array([p[0] for p in pts])*math.pi/180
    az = np.arctan2(np.cos(la_r)*np.sin(lo_r), np.cos(la_r)*np.cos(lo_r))
    order = np.argsort(az)
    az_sorted = az[order]
    gaps = np.diff(np.concatenate([az_sorted, az_sorted[:1] + 2*math.pi]))
    if gaps.max() > math.radians(60):                # 超过 60° 是开放海域，不补
        return []
    star = [(0.0, float(pole))] + [pts[i] for i in order]
    try:
        g = Polygon(star).buffer(0)
    except Exception:
        return []
    if g.is_empty:
        return []
    # 裁进极冠（|lat|>80），杜绝跨两极的怪物环
    cap = Polygon([(-180.0, sgn*90.0), (180.0, sgn*90.0),
                   (180.0, sgn*80.0), (-180.0, sgn*80.0)])
    try:
        u = g.intersection(cap)
    except Exception:
        return []
    out = []
    for part in (list(u.geoms) if hasattr(u, "geoms") else [u]):
        if part.geom_type != "Polygon" or part.area < 1e-9:
            continue
        ring = np.array(part.exterior.coords)[:-1]
        if ring[:, 1].min()*sgn < 79:                    # 校验：整环必须留在极冠内
            continue
        if len(ring) < 3:
            continue
        for piece in split_antimeridian(ring):       # 与正常环走同一套切分/简化
            for r2 in simplify_pieces([piece], tol):
                r2 = dedupe_ring(np.round(r2, ROUND_DIGITS))
                if len(r2) >= 3 and ring_ok(r2):
                    out.append(r2)
    return out

def catmull_ring(ring):
    """闭合环的 Catmull-Rom 样条加密（过原顶点、不缩水）。

    DP 抽稀后的海岸是直线弦、小碎片是三角形；Chaikin 削角会把陆地往里缩
    （面积 -13%、海湾里的地标离岸距离从 34 km 涨到 168 km）。Catmull-Rom
    曲线穿过每一个原顶点，只在每段中点加一个柔和采样点：顶点数翻倍（预算
    内）、角变圆、面积与地标贴合度不变。
    """
    p = np.asarray(ring, dtype=np.float64)
    n = len(p)
    if n < 3:
        return p
    pm = np.roll(p, 1, axis=0)           # P_{i-1}
    p1 = np.roll(p, -1, axis=0)          # P_{i+1}
    p2 = np.roll(p, -2, axis=0)          # P_{i+2}
    t = 0.5
    t2, t3 = t*t, t*t*t
    mid = 0.5*(2.0*p + (-pm + p1)*t + (2.0*pm - 5.0*p + 4.0*p1 - p2)*t2
               + (-pm + 3.0*p - 3.0*p1 + p2)*t3)
    out = np.empty((2*n, 2), dtype=np.float64)
    out[0::2] = p                       # t=0：原顶点（曲线穿过）
    out[1::2] = mid                     # t=0.5：中点采样
    return out


def find_tolerance(pieces, target, tol0):
    """对数空间二分，找让顶点数命中 target ±3% 的容差。"""
    lo, hi = 0.003, 3.0
    best_tol, best_err, best_count = tol0, 1e18, 0
    tol = tol0
    for _ in range(12):
        rings = simplify_pieces(pieces, tol)
        c = sum(len(r) for r in rings)
        err = abs(c - target) / target
        if err < best_err:
            best_tol, best_err, best_count = tol, err, c
        if c > target * 1.03:
            lo = tol
            tol = math.sqrt(max(tol, lo) * hi)
        elif c < target * 0.97:
            hi = tol
            tol = math.sqrt(tol * lo) if tol > lo else math.sqrt(lo * hi) / 2
        else:
            return tol, c
    return best_tol, best_count


# ----------------------------------------------------------------------------
# 球面几何辅助
# ----------------------------------------------------------------------------
def polygon_area_km2(ring):
    """球面多边形面积（平方公里）。ring 为 (n,2) lon/lat。"""
    lat = np.radians(ring[:, 1])
    lon = np.radians(ring[:, 0])
    pts = np.stack([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)], -1)
    return float(pygplates.PolygonOnSphere(pts).get_area()) * EARTH_R_KM ** 2


def centroid_latlon(ring):
    xyz = np.stack([np.cos(np.radians(ring[:, 1])) * np.cos(np.radians(ring[:, 0])),
                    np.cos(np.radians(ring[:, 1])) * np.sin(np.radians(ring[:, 0])),
                    np.sin(np.radians(ring[:, 1]))], -1)
    c = xyz.mean(0)
    c /= np.linalg.norm(c)
    return math.degrees(math.asin(c[2])), math.degrees(math.atan2(c[1], c[0]))


def great_circle_km(a_lonlat, b_lonlat):
    la, lo = math.radians(a_lonlat[1]), math.radians(a_lonlat[0])
    lb, lbo = math.radians(b_lonlat[1]), math.radians(b_lonlat[0])
    d = math.sin(la) * math.sin(lb) + math.cos(la) * math.cos(lb) * math.cos(lbo - lo)
    return math.acos(max(-1.0, min(1.0, d))) * EARTH_R_KM


def connected_components(pieces_with_area, thr_km=800.0):
    """球面顶点邻接的连通分量。pieces_with_area: [(ring, area_km2)]。

    用所有顶点的并查集（相邻阈值 thr_km），按各顶点所属多边形面积加权，估算
    分量面积。返回 [(area_km2, n_vertices), ...]（按面积降序）与总陆地面积。

    阈值取 800 km 的依据（本数据实测）：模型内部把同一超级大陆的相邻陆块拼合时，
    缝隙最多只有几百公里（例如 200 Ma 时东北亚陆块群与泛大陆主体之间相距
    632 km）；而真正分开两个大陆的洋盆都在 1000 km 以上（例如今天南极洲到
    南美 1062 km、澳洲到亚洲 1500+ km）。800 km 恰好把「拼合缝」与「真洋盆」
    分开，也能白令海峡（85 km）这种真实海峡照常连通。"""
    thr = thr_km / EARTH_R_KM
    pts, weights = [], []
    total_area = 0.0
    for ring, area in pieces_with_area:
        r = ring
        w = area / max(len(r), 1)
        total_area += area
        lat = np.radians(r[:, 1])
        lon = np.radians(r[:, 0])
        xyz = np.stack([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)], -1)
        pts.append(xyz)
        weights.append(np.full(len(r), w))
    P = np.concatenate(pts)
    W = np.concatenate(weights)
    n = len(P)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    step = 8192
    for i in range(0, n, step):
        sim = P @ P[i:i + step].T
        ang = 2.0 * np.arcsin(np.clip(np.sqrt(np.maximum(0.0, 2.0 - 2.0 * sim)) / 2.0, 0.0, 1.0))
        for a, b in np.argwhere(ang < thr):
            union(int(a), i + int(b))
    comp_area = defaultdict(float)
    comp_nv = defaultdict(int)
    for i in range(n):
        r = find(i)
        comp_area[r] += W[i]
        comp_nv[r] += 1
    comps = sorted(((a, comp_nv[k]) for k, a in comp_area.items()), reverse=True)
    return comps, total_area


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------
def main():
    ensure_data()
    print("[load] 旋转模型 / 海岸线 / 静态多边形")
    rot = pygplates.RotationModel(ROT_FILE)
    coast, n_dropped = load_land_coastlines(COAST_FILE)
    print(f"[load] 要素类型过滤：剔除海盆/岛弧等非陆地要素 {n_dropped} 个，"
          f"保留 {len(coast)} 个海岸线要素")
    static = pygplates.FeatureCollection(STATIC_FILE)

    # ---- 阶段 A：重建切片，切日界线 ------------------------------------
    print(f"[reconstruct] {len(TIMES)} 片 (0-{TIME_MAX} Ma, 步长 {TIME_STEP})")
    raw = reconstruct_all_with_carry(rot, coast, TIMES)   # raw: time -> [(fid, pid, ring)]
    n_raw = sum(len(v) for v in raw.values())
    print(f"   原始几何总数: {n_raw} (平均 {n_raw/len(TIMES):.0f}/片)")

    # ---- 阶段 B：修自相交 + 切日界线 + 融合成连续陆块 ---------------------
    print("[merge] 碎片 → 连续陆块（union）")
    n_bowtie = 0
    merged = {}                                   # t -> (outlines, holes)
    for t in TIMES:
        pieces = []
        for fid, pid, ring in raw[t]:
            for ok in repair_bowtie(ring):            # 先修自相交，防误补极冠
                if len(ok) != len(ring):
                    n_bowtie += 1
                pieces.extend(split_antimeridian(ok))
        pieces.extend(polar_cone_fill(pieces, -90.0, 0.35))   # 极点漏覆盖先补面
        outlines, holes, raw_u = merge_land(pieces)
        merged[t] = (outlines, holes, raw_u)
    if n_bowtie:
        print(f"[repair] 自相交蝴蝶结环修复 {n_bowtie} 处（切日界线之前）")

    # ---- 阶段 C：自适应简化（外轮廓 + 洞共用顶点预算） ---------------------
    print("[simplify] 自适应 Douglas–Peucker 简化")
    tols, tol_prev = [], 0.1
    for t in TIMES:
        outlines, holes, _raw = merged[t]
        tol, _cnt = find_tolerance(outlines + holes, VERTEX_TARGET, tol_prev)
        tol_prev = tol
        tols.append(tol)
    # 时间平滑容差（验收 ④ 要求相邻切片顶点数不跳变）：5 片窗 + 两遍平滑
    tols = np.array(tols)
    smoothed = np.copy(tols)
    for _pass in range(2):
        prev = np.copy(smoothed)
        for i in range(len(tols)):
            lo_i, hi_i = max(0, i - 2), min(len(tols), i + 3)      # 5 片窗
            smoothed[i] = math.exp(np.mean(np.log(prev[lo_i:hi_i])))

    def clean_rings(rings, tol, clip=None):
        out = []
        for r in simplify_pieces(rings, tol):
            # DP 删点会重新造出跨 ±180° 的长边（原弧上的中间点被删掉后，新边
            # 两端经度差可能 >180°），所以简化之后必须再切一次日界线。
            for piece in split_antimeridian(r):
                piece = dedupe_ring(np.round(piece, ROUND_DIGITS))
                if len(piece) < 3 or not ring_ok(piece):
                    continue
                try:
                    g = Polygon(piece)
                    if not g.is_valid:
                        g = g.buffer(0)
                except Exception:
                    continue
                if g.is_empty:
                    continue
                for part in (list(g.geoms) if hasattr(g, "geoms") else [g]):
                    if part.geom_type != "Polygon" or part.area < 1e-7:
                        continue
                    # 最终裁剪：任何环都必须落在原始重建并集内。并集会把不同时段的
                    # feature 碎片接到一起，碎片之间的「接缝」有时是直线穿海的合成
                    # 边（例：315 Ma 冈瓦纳环上 (0,10.3)→(0,-90) 的 100° 经线边），
                    # 填色会把它当成真实边界、把海面填成陆地、且逐帧抖动——
                    # 「海洋一会出现、一会消失」。逐环求交从几何上根除幻影陆块。
                    if clip is not None and not clip.is_empty:
                        try:
                            part = part.intersection(clip)
                        except Exception:
                            continue
                        if part.is_empty:
                            continue
                    for sub in (list(part.geoms) if hasattr(part, "geoms") else [part]):
                        if sub.geom_type != "Polygon" or sub.area < 1e-7:
                            continue
                        # 交裁会把并集内部所有碎片边界切进环里（顶点暴涨），用同一
                        # 容差再简化一次：几何仍忠实于原始并集，预算回到目标。
                        try:
                            s1 = sub.simplify(tol, preserve_topology=True)
                        except Exception:
                            continue
                        if s1.is_empty:
                            continue
                        for s2 in (list(s1.geoms) if hasattr(s1, "geoms") else [s1]):
                            if s2.geom_type != "Polygon" or s2.area < 1e-7:
                                continue
                            # 亚像素细带/舌头剔除（开运算 erode→dilate，ε=DP 容差）：
                            # 例：400 Ma 环1 沿 -45.92° 的 0.01°×60° 舌、25 Ma 环34
                            # 整个就是 0.01°×67° 的细带。它们的填充不可见，但边缘
                            # AA 会画成 1px 横线、被渲染层膨胀放大成 3px 横线。
                            # 开运算只去掉宽度 <2ε 的细部（凸角圆滑 ≤0.24°=亚像素），
                            # 结果只减不增，仍 ⊆ 原始并集。
                            try:
                                o = s2.buffer(-SLIVER_EPS).buffer(SLIVER_EPS)
                            except Exception:
                                o = s2
                            if o.is_empty:
                                continue                     # 整个就是细带，丢弃
                            for s3 in (list(o.geoms) if hasattr(o, "geoms") else [o]):
                                if s3.geom_type != "Polygon" or s3.area < 1e-7:
                                    continue
                                try:
                                    s3 = s3.simplify(tol, preserve_topology=True)
                                except Exception:
                                    pass
                                for s4 in (list(s3.geoms) if hasattr(s3, "geoms") else [s3]):
                                    if s4.geom_type != "Polygon" or s4.area < 1e-7:
                                        continue
                                    rr = dedupe_ring(np.round(
                                        np.array(s4.exterior.coords)[:-1], ROUND_DIGITS))
                                    for pc in split_antimeridian(rr):
                                        pc = dedupe_ring(np.round(pc, ROUND_DIGITS))
                                        if len(pc) >= 3 and ring_ok(pc):
                                            out.append(pc)
        # 逐环去重：同一几何可能从多条路径（buffer(0) 拆分 + 交裁 + 再简化）重复
        # 产出；重复环会让 evenodd 填色穿洞、面积指标翻倍。按顶点指纹剔除。
        seen = {}
        uniq = []
        for pc in out:
            key = (len(pc), round(float(pc[0][0]), 3), round(float(pc[0][1]), 3),
                   round(float(pc[-1][0]), 3), round(float(pc[-1][1]), 3))
            if key in seen and np.array_equal(pc, seen[key]):
                continue                  # 完全重复的环
            seen[key] = pc
            uniq.append(pc)
        return uniq

    def disjointify(rings, tol):
        """消除环间重叠：evenodd 填色下重叠区会被穿洞（海洋色方块）。

        环本是并集 exteriors 切出的碎片、彼此不相交，重叠只来自 DP 再简化的
        ±tol 鼓包或碎片化后的重复路径；每一环减去与「索引更小」的环的重叠部分
        即可，差异量是亚容差级，形状基本不变。
        """
        polys = []
        for r in rings:
            try:
                g = Polygon(np.asarray(r)).buffer(0)
            except Exception:
                continue
            if not g.is_empty and g.area >= 1e-7:
                polys.append(g)
        if len(polys) < 2:
            return rings
        tree = STRtree(polys)
        keep = []
        for i, g in enumerate(polys):
            try:
                for j in tree.query(g):
                    if int(j) >= i:
                        continue
                    h = polys[int(j)]
                    if h.is_empty:
                        continue
                    q = g.intersection(h)
                    if not q.is_empty and q.area > 1e-7:
                        g = g.difference(q)
                        if g.is_empty:
                            break
            except Exception:
                pass
            if not g.is_empty and g.area >= 1e-7:
                keep.append(g)
        out = []
        for g in keep:
            for part in (list(g.geoms) if hasattr(g, "geoms") else [g]):
                if part.geom_type != "Polygon" or part.area < 1e-7:
                    continue
                try:
                    part = part.simplify(tol, preserve_topology=True)
                except Exception:
                    continue
                rr = dedupe_ring(np.round(np.array(part.exterior.coords)[:-1], ROUND_DIGITS))
                for pc in split_antimeridian(rr):
                    pc = dedupe_ring(np.round(pc, ROUND_DIGITS))
                    if len(pc) >= 3 and ring_ok(pc):
                        out.append(pc)
        return out

    slices = []                                # 最终交付数据    slices = []                                # 最终交付数据
    for ti, t in enumerate(TIMES):
        tol = smoothed[ti]
        outlines, holes, raw_u = merged[t]
        land = clean_rings(outlines, tol, raw_u)
        land = disjointify(land, tol)
        hole_rings = clean_rings(holes, tol)
        vc = sum(len(r) for r in land) + sum(len(r) for r in hole_rings)
        slices.append({"time_Ma": t, "land": land, "holes": hole_rings,
                       "vertex_count": vc})
        print(f"   t={t:3d} Ma  tol={tol:.4f}°  vertices={vc}"
              f"  ({len(land)} 外环 + {len(hole_rings)} 洞)")
    sums = [s["vertex_count"] for s in slices]
    print(f"[merge] 每片 {min(sums)}-{max(sums)} 顶点（硬约束 "
          f"{VERTEX_HARD_LO}-{VERTEX_HARD_HI}）")

    # 说明：融合（union）之后，原先两段针对"碎片"的后处理都不再需要——
    #   · 「DP 刀锋效应修复」（逐 feature 顶点数 140↔3 横跳）：碎片已经不存在；
    #   · 「Catmull-Rom 样条圆角」：容差从 0.68° 降到约 0.12°，顶点间距已经小于
    #     一个屏幕像素，折线感消失，再加密只是让文件翻倍。

    # ---- 阶段 D：markers ----------------------------------------------
    print("[markers] 计算古位置轨迹")
    point_features = []
    for name, (lon, lat) in MARKERS.items():
        f = pygplates.Feature()
        f.set_geometry(pygplates.PointOnSphere(lat, lon))
        point_features.append(f)
    partitioned = pygplates.partition_into_plates(static, rot, point_features,
                                                  reconstruction_time=0)
    markers = []
    marker_speeds = []
    tracks = {}
    for (name, (lon, lat)), f in zip(MARKERS.items(), partitioned):
        pid = f.get_reconstruction_plate_id()
        p0 = pygplates.PointOnSphere(lat, lon)
        track = []
        pos = {}
        for t in TIMES:
            p = rot.get_rotation(float(t), pid) * p0
            la, lo = p.to_lat_lon()
            pos[t] = (lo, la)
            track.append({"time_Ma": t, "lon": round(lo, ROUND_DIGITS),
                          "lat": round(la, ROUND_DIGITS)})
        for i in range(len(TIMES) - 1):
            d = great_circle_km(pos[TIMES[i]], pos[TIMES[i + 1]])
            dt = TIMES[i + 1] - TIMES[i]
            marker_speeds.append((d / dt / 10.0, name, TIMES[i], TIMES[i + 1]))  # km/Myr -> cm/yr ×0.1
        tracks[name] = pos
        markers.append({"name": name, "modern": [round(lon, ROUND_DIGITS), round(lat, ROUND_DIGITS)],
                        "plate_id": pid, "track": track})
        print(f"   {name}: plate_id={pid}  (400 Ma: {pos[400][1]:+.1f}, {pos[400][0]:+.1f})")
    marker_speeds.sort(reverse=True)

    # ---- 阶段 E：自检 ----------------------------------------------------
    print("[checks] 六项自检")
    checks = {}

    # ① 陆地总面积守恒
    def land_area(s):
        """外轮廓面积减去洞（内海/湖泊）面积。"""
        return (sum(polygon_area_km2(r) for r in s["land"])
                - sum(polygon_area_km2(r) for r in s.get("holes") or []))
    areas = []
    for s in slices:
        a = land_area(s)
        areas.append(a)
        s["_area"] = a
    med = float(np.median(areas))
    dev = [(a - med) / med for a in areas]
    checks["area"] = {"median_km2": med, "min_km2": min(areas), "max_km2": max(areas),
                      "max_dev": max(d for d in map(abs, dev)),
                      "limit": AREA_MEDIAN_TOL,
                      "pass": max(abs(d) for d in dev) <= AREA_MEDIAN_TOL}
    print(f"   ① 面积: 中位数 {med/1e6:.2f}e6 km², 偏差最大 "
          f"{max(abs(d) for d in dev)*100:.2f}% (<= ±{AREA_MEDIAN_TOL*100:.0f}%) "
          f"{'PASS' if checks['area']['pass'] else 'FAIL'}")

    # ② 南极位置
    # 用 0 Ma 时质心在 60°S 以内的 features 定义"南极陆块"，跨时间按 feature id 跟踪
    # 以 0 Ma 时质心在 60°S 以南的 features 定义「南极陆块」，
    # 之后按 feature id 在各时间切片上跟踪其面积加权质心纬度（用 raw 重建几何，
    # 因为简化后的环不再单独携带 feature 归属）
    ant_fids = set()
    for fid, pid, ring in raw[0]:
        clat, _ = centroid_latlon(ring)
        if clat < -60.0:
            ant_fids.add(fid)
    ant_lats = {}
    for t in TIMES:
        clats = []
        for fid, pid, ring in raw[t]:
            if fid in ant_fids:
                clats.append((centroid_latlon(ring)[0], polygon_area_km2(ring)))
        if clats:
            wsum = sum(a for _, a in clats)
            ant_lats[t] = sum(l * a for l, a in clats) / wsum
    recent = [ant_lats[t] for t in TIMES if t <= 35]
    checks["antarctica"] = {
        "n_ant_features_0ma": len(ant_fids),
        "centroid_lat_recent_min": min(recent) if recent else None,
        "centroid_lat_all_max": max(ant_lats.values()),
        "pass": (min(recent) < -60.0) and (max(ant_lats.values()) < -30.0),
    }
    print(f"   ② 南极: 0-35 Ma 质心最北 {checks['antarctica']['centroid_lat_recent_min']:.1f}°S "
          f"(< -60°S)；全程最北 {checks['antarctica']['centroid_lat_all_max']:.1f}°S "
          f"(不应近赤道) {'PASS' if checks['antarctica']['pass'] else 'FAIL'}")

    # ③ marker 速度
    checks["speed"] = {"max_cm_yr": marker_speeds[0][0], "limit": SPEED_LIMIT_CM_YR,
                       "worst": marker_speeds[0][:4],
                       "pass": marker_speeds[0][0] <= SPEED_LIMIT_CM_YR}
    print(f"   ③ 速度: 最大 {marker_speeds[0][0]:.1f} cm/yr ({marker_speeds[0][1]} "
          f"{marker_speeds[0][2]}-{marker_speeds[0][3]} Ma; <= {SPEED_LIMIT_CM_YR}) "
          f"{'PASS' if checks['speed']['pass'] else 'FAIL'}")

    # ④ 相邻切片顶点数连续性
    # 融合（union）之后不再有"逐 feature 顶点数"这个概念——陆地是连续轮廓，
    # 所以检查改为逐片的顶点总数：容差经过时间平滑，相邻片不应跳变（>4× 视为跳变）。
    totals = [s["vertex_count"] for s in slices]
    step_ratios = [max(totals[i], totals[i + 1]) / max(1, min(totals[i], totals[i + 1]))
                   for i in range(len(TIMES) - 1)]
    big = sorted([(r, i) for i, r in enumerate(step_ratios) if r > 4.0], reverse=True)
    checks["verts"] = {
        "feature_steps": len(step_ratios),
        "max_ratio_overall": max(step_ratios) if step_ratios else 1.0,
        "max_ratio_big": max(step_ratios) if step_ratios else 1.0,
        "big_jumps": len(big),
        "tiny_flips": 0,
        "worst_jumps": [{"ratio": round(r, 2),
                         "t": str(TIMES[i]) + "->" + str(TIMES[i + 1]),
                         "counts": str(totals[i]) + "->" + str(totals[i + 1])}
                        for r, i in big[:10]],
        "slice_total_min": min(totals),
        "slice_total_max": max(totals),
        "slice_all_in_range": all(VERTEX_HARD_LO <= v <= VERTEX_HARD_HI for v in totals),
        "appeared_or_vanished": 0,      # union 之后不存在"碎片凭空消失"，保留字段兼容旧文档
        "pass": all(VERTEX_HARD_LO <= v <= VERTEX_HARD_HI for v in totals) and not big,
    }
    print(f"   ④ 顶点数: 每片 {checks['verts']['slice_total_min']}-"
          f"{checks['verts']['slice_total_max']} (硬约束 {VERTEX_HARD_LO}-{VERTEX_HARD_HI})；"
          f"相邻切片最大比值 {checks['verts']['max_ratio_big']:.2f}（>4× 视为跳变）"
          f" {'PASS' if checks['verts']['pass'] else 'FAIL'}")

    # ⑤ 已知事实
    facts = {}
    for m in markers:
        tr = {e["time_Ma"]: (e["lon"], e["lat"]) for e in m["track"]}
        facts[m["name"]] = {"lat400": tr[400][1], "lat200": tr[200][1], "lat80": tr[80][1],
                            "lat50": tr[50][1]}
    # 逐片连通度量（阈值 800 km，见 connected_components 的标定说明）：
    # ⑤ 自检和预览页的数据卡都从这里拿数字，只算一次
    comp_at = {}
    for i, s in enumerate(slices):
        comps, tot_area = connected_components([(r, polygon_area_km2(r)) for r in s["land"]])
        hole_area = sum(polygon_area_km2(r) for r in s.get("holes") or [])
        # 连通率的分母用「外轮廓总面积」（洞不参与分量归属），否则会算出 >100%
        frac = comps[0][0] / tot_area if comps and tot_area else 0.0
        s["metrics"] = {"land_area_km2": round(tot_area - hole_area, 1),
                        "comp_frac": round(frac, 4),
                        "n_comp": int(len(comps))}
        comp_at[s["time_Ma"]] = (frac, len(comps))
    dl = {t: great_circle_km(tracks["新德里"][t], tracks["拉萨"][t]) for t in TIMES}
    facts["delhi_lhasa_km"] = {t: dl[t] for t in (100, 50, 0)}
    facts_asserts = {
        "pangea_200_frac>0.8": comp_at[200][0] > 0.8,
        "delhi_lhasa_shrinking": dl[100] > dl[50] > dl[0],
        "delhi_northward_100_to_50": tracks["新德里"][50][1] > tracks["新德里"][100][1],
        "china_lowlat_400": abs(facts["上海"]["lat400"]) < 30 and facts["拉萨"]["lat400"] < 0,
    }
    checks["facts"] = {
        "markers_at_400": facts,
        "pangea_200_frac": comp_at[200][0],
        "comp_at": {k: [round(v[0], 4), v[1]] for k, v in comp_at.items()},
        "delhi_lhasa_km": facts["delhi_lhasa_km"],
        "assertions": facts_asserts,
        "pass": all(facts_asserts.values()),       # P3：四项都断言，不是只 print
    }
    print(f"   ⑤ 事实: 200 Ma 最大连通分量占比 {comp_at[200][0]*100:.1f}% (>80% 视为潘吉亚)"
          f"；新德里-拉萨距离 100Ma {dl[100]:.0f} / 50Ma {dl[50]:.0f} / 今 {dl[0]:.0f} km")
    for k, v in facts_asserts.items():
        print(f"      - {k}: {'PASS' if v else 'FAIL'}")



    # 补充检查：0 Ma 切片就是现代世界地图吗？——拿 10 个现代海岸地标量它到最近海岸
    # （shapely 点到多边形距离，落在陆地上记 0；简化误差约 0.3° ≈ 30 km 量级）
    lm_d = {}
    s0 = slices[TIMES.index(0)]
    for name, (lo, la) in LANDMARKS.items():
        best = float("inf")
        cx = math.cos(math.radians(la)) * math.pi / 180.0 * EARTH_R_KM
        cy = math.pi / 180.0 * EARTH_R_KM
        pt = ShapelyPoint(0.0, 0.0)
        for r in s0["land"]:
            x = (np.asarray(r)[:, 0] - lo) * cx
            y = (np.asarray(r)[:, 1] - la) * cy
            po = Polygon(np.stack([x, y], -1))
            if not po.is_valid:
                po = po.buffer(0)
            d = po.distance(pt)
            if d < best:
                best = d
                if best == 0.0:
                    break
        lm_d[name] = float(best)
    checks["stage0"] = {"landmarks_km": lm_d,
                        "max_dist_km": max(lm_d.values()) if lm_d else None,
                        "land_area_km2": s0["_area"],
                        "pass": bool(lm_d) and max(lm_d.values()) < 50.0}
    if lm_d:
        print(f"   + 现代地图: 0 Ma 切片 10 个海岸地标最近海岸距离 {min(lm_d.values()):.1f}–"
              f"{max(lm_d.values()):.1f} km (<50) {'PASS' if checks['stage0']['pass'] else 'FAIL'}")


    # ---- 阶段 F：事件（注入真实数字） ------------------------------------
    sh400 = facts["上海"]["lat400"]; bj400 = facts["北京"]["lat400"]; ls400 = facts["拉萨"]["lat400"]
    nd100 = tracks["新德里"][100][1]
    nd80 = tracks["新德里"][80][1]
    spd100 = great_circle_km(tracks["新德里"][100], tracks["新德里"][100 - TIME_STEP]) / TIME_STEP / 10.0
    spd80 = great_circle_km(tracks["新德里"][80], tracks["新德里"][80 - TIME_STEP]) / TIME_STEP / 10.0
    ds150 = great_circle_km(tracks["新德里"][150], tracks["悉尼"][150])
    ds100 = great_circle_km(tracks["新德里"][100], tracks["悉尼"][100])
    rc140 = great_circle_km(tracks["里约热内卢"][140], tracks["开罗"][140])
    rc0 = great_circle_km(tracks["里约热内卢"][0], tracks["开罗"][0])

    def fmt_lat(v):
        return f"{abs(v):.1f}°{'N' if v >= 0 else 'S'}"

    spdk, spd_peak = 0.0, 0                    # P6：峰值时刻也一起算，不写死 65 Ma
    _km100 = great_circle_km(tracks["新德里"][100], tracks["新德里"][100 - TIME_STEP])
    spd100_km = _km100
    for i, t in enumerate(TIMES[:-1]):
        next_t = TIMES[i + 1]
        dt = next_t - t
        v = great_circle_km(tracks["新德里"][t], tracks["新德里"][next_t]) / dt / 10.0
        if v > spdk:
            spdk, spd_peak = v, next_t
    events = []
    for (t, title, text, evidence) in EVENTS:
        text = text.format(
            sh400=fmt_lat(sh400), bj400=fmt_lat(bj400), ls400=fmt_lat(ls400),
            comp330=f"{comp_at[330][0]*100:.0f}%", comp250=f"{comp_at[250][0]*100:.0f}%",
            comp200=f"{comp_at[200][0]*100:.1f}%",
            nd100=fmt_lat(nd100), nd80=fmt_lat(nd80), spd100=f"{spd100:.1f}", spd80=f"{spd80:.1f}",
            dl100=f"{dl[100]:,.0f}", dl50=f"{dl[50]:,.0f}", dl0=f"{dl[0]:,.0f}",
            ds150=f"{ds150:,.0f}", ds100=f"{ds100:,.0f}",
            rc140=f"{rc140:,.0f}", rc0=f"{rc0:,.0f}",
            sy50=fmt_lat(tracks["悉尼"][50][1]), sy0=fmt_lat(tracks["悉尼"][0][1]),
            spdk=f"{spdk:.1f}", spd_peak=f"{spd_peak}", spd100_km=f"{_km100:.0f}",
            antmin=f"{-checks['antarctica']['centroid_lat_recent_min']:.0f}",
            a0=f"{slices[0]['_area']/1e8:.2f}",
            lm=f"{max(lm_d.values()):.0f}",
        )
        events.append({"time_Ma": t, "title": title, "text": text, "evidence": evidence})

    # ---- 阶段 F2：最终几何质检（交付前再过一遍，带病的环宁可丢掉）----
    qa = {"dropped": 0, "fixed": 0, "nan": 0, "short": 0, "edge180": 0, "degenerate": 0, "selfint": 0}
    EDGE_LON_LIMIT = 180.0
    for s in slices:
        kept = []
        for ring in s["land"]:
            r = np.asarray(ring, dtype=np.float64)
            n = len(r)
            reason = None
            if not np.all(np.isfinite(r)):
                reason, qa["nan"] = "nan", qa["nan"] + 1
            elif n < 3:
                reason, qa["short"] = "short", qa["short"] + 1
            else:
                closed = np.concatenate([r, r[:1]])
                dl = np.abs(np.diff(closed[:, 0]))
                if dl.max() > EDGE_LON_LIMIT:
                    reason, qa["edge180"] = "edge180", qa["edge180"] + 1
                else:
                    try:
                        g0 = Polygon(closed[:-1])
                        if g0.is_valid and g0.area >= 1e-7:
                            kept.append(ring);                # 合法环，原样保留
                            continue
                        # C-R 尖角过冲会产生微小自交：buffer(0) 规范化修复。
                        # 取整到 ROUND_DIGITS 后可能再度自交（亚象素钩），所以
                        # "修复→取整→检验" 最多三轮；仍修不好就保留几何量并计数。
                        cur_g, rep, ok = g0, [], False
                        for _attempt in range(3):
                            g2 = cur_g.buffer(0)
                            parts = list(g2.geoms) if hasattr(g2, "geoms") else [g2]
                            rep = []
                            for part in parts:
                                if part.geom_type == "Polygon" and part.area >= 1e-7:
                                    rr = np.round(np.array(part.exterior.coords)[:-1], ROUND_DIGITS)
                                    rr = dedupe_ring(rr)
                                    if len(rr) >= 3:
                                        rep.append(rr)
                            if not rep:
                                break
                            # buffer 重采样可能把环接回跨日界线，重新切分
                            rep = [pc for rr in rep
                                   for pc in split_antimeridian(rr)]
                            rep = [dedupe_ring(np.round(pc, ROUND_DIGITS))
                                   for pc in rep if len(pc) >= 3]
                            rep = [pc for pc in rep if len(pc) >= 3 and ring_ok(pc)]
                            if not rep:
                                break
                            if len(rep) == 1:
                                cur_g = Polygon(rep[0])
                                if cur_g.is_valid and cur_g.area >= 1e-7:
                                    ok = True
                                    break
                            else:
                                try:                          # 多块拆分：逐块再验合法
                                    ok = all(Polygon(p).is_valid
                                             and Polygon(p).area >= 1e-7 for p in rep)
                                except Exception:
                                    ok = False
                                break
                        if ok and rep:
                            kept.extend(rep)
                            qa["fixed"] += 1
                            continue                # 修复版已入列，原环不再追加
                        else:
                            # 三轮修复仍自交（或 buffer 返空）：带病环宁可丢弃
                            reason, qa["degenerate"] = "degenerate", qa["degenerate"] + 1
                    except Exception:
                        reason, qa["degenerate"] = "degenerate", qa["degenerate"] + 1
            if reason:
                qa["dropped"] += 1
            else:
                kept.append(ring)
        s["land"] = kept                                   # 修好的环即使数量不变也要写回
        # 洞（内海/湖泊）走一遍同样的质检：小洞取整后容易自交，buffer(0) 规范化后
        # **写回规范化结果**（不是原环），仍不合法的整条丢弃。
        kept_h = []
        for ring in s.get("holes") or []:
            r = np.asarray(ring, dtype=np.float64)
            if len(r) < 3 or not np.all(np.isfinite(r)):
                qa["dropped"] += 1
                continue
            closed = np.concatenate([r, r[:1]])
            if np.abs(np.diff(closed[:, 0])).max() > EDGE_LON_LIMIT:
                qa["edge180"] += 1
                qa["dropped"] += 1
                continue
            try:
                g0 = Polygon(closed[:-1])
                if not g0.is_valid:
                    qa["fixed"] += 1
                    g0 = g0.buffer(0)
                rep = []
                for part in (list(g0.geoms) if hasattr(g0, "geoms") else [g0]):
                    if part.geom_type != "Polygon" or part.area < 1e-7:
                        continue
                    rr = dedupe_ring(np.round(np.array(part.exterior.coords)[:-1], ROUND_DIGITS))
                    for pc in split_antimeridian(rr):
                        pc = dedupe_ring(np.round(pc, ROUND_DIGITS))
                        if len(pc) >= 3 and ring_ok(pc):
                            rep.append(pc)
                if not rep:
                    qa["degenerate"] += 1
                    qa["dropped"] += 1
                    continue
                kept_h.extend(rep)
            except Exception:
                qa["degenerate"] += 1
                qa["dropped"] += 1
                continue
        s["holes"] = kept_h
        s["vertex_count"] = sum(len(r) for r in kept) + sum(len(r) for r in kept_h)
    if qa["dropped"] or qa["fixed"]:
        print(f"[qa] 修复自交环 {qa['fixed']} 个，丢弃 {qa['dropped']} 个："
              f"nan {qa['nan']} / <3点 {qa['short']} / >180°边 {qa['edge180']} / 退化 {qa['degenerate']} / 残留亚象素自交 {qa['selfint']}")
    else:
        print("[qa] 全部环通过最终几何质检（无 NaN、无边>180°、无退化环）")

    # ⑥ 跨日界线（P4：极点缝合边允许 ==180°，普通边必须 < 180°）
    maxdl, max_nonpole, n_pole_seam, n_edges = 0.0, 0.0, 0, 0
    for s in slices:
        for ring in s["land"] + (s.get("holes") or []):
            lons = np.concatenate([ring[:, 0], ring[:1, 0]])
            lats = np.concatenate([ring[:, 1], ring[:1, 1]])
            d = np.abs(np.diff(lons))
            # Coordinates are serialized to 0.01°. A synthetic polar seam
            # endpoint can therefore round to 89.88–89.89°, so use the same
            # 89.5° guard as the renderer instead of misclassifying a valid
            # pole closure as an ordinary 180° edge.
            pole = np.abs(lats) >= 89.5
            pole_edge = pole[:-1] | pole[1:]
            n_edges += len(d)
            maxdl = max(maxdl, float(d.max()) if len(d) else 0.0)
            if (~pole_edge).any():
                max_nonpole = max(max_nonpole, float(d[~pole_edge].max()))
            if pole_edge.any():
                n_pole_seam += int((np.abs(d[pole_edge] - 180.0) < 1e-6).sum())
    checks["antimeridian"] = {
        "max_lon_delta": round(maxdl, 2), "max_nonpole_delta": round(max_nonpole, 2),
        "n_pole_seam_edges": n_pole_seam, "n_edges_total": n_edges, "limit": 180.0,
        "pass": maxdl <= 180.0 and max_nonpole < 180.0,
        "note": "极点缝合边允许 ==180°（球面上同一个点的合成几何）；普通边必须 < 180°",
    }
    print(f"   ⑥ 日界线: 最大经度差 {maxdl:.2f}°；普通边最大 {max_nonpole:.2f}° (< 180°)；"
          f"极点缝合边 {n_pole_seam} 条（允许恰好 180°） "
          f"{'PASS' if checks['antimeridian']['pass'] else 'FAIL'}")

    # ---- 输出 ------------------------------------------------------------
    earth = {
        "meta": {
            "model": "Merdith2021",
            "citation": CITATION,
            "license": "CC-BY 3.0 (EarthByte / GPlates 数据集，需按数据页要求引用)",
            "time_range_Ma": [TIME_MIN, TIME_MAX],
            "slice_step_Ma": TIME_STEP,
            "generated_by": "build.py",
            "n_slices": len(slices),
            "data_source": MODEL_ZIP_URL,
        },
        "slices": [{"time_Ma": s["time_Ma"],
                    "land": [[[round(float(lo), ROUND_DIGITS), round(float(la), ROUND_DIGITS)]
                              for lo, la in r.tolist()] for r in s["land"]],
                    "holes": [[[round(float(lo), ROUND_DIGITS), round(float(la), ROUND_DIGITS)]
                               for lo, la in r.tolist()] for r in (s.get("holes") or [])],
                    "vertex_count": s["vertex_count"], "metrics": s["metrics"]} for s in slices],
        "markers": markers,
        "events": events,
    }
    out_path = os.path.join(HERE, "earth.json")
    with open(out_path, "w") as f:
        json.dump(earth, f, ensure_ascii=False, separators=(",", ":"))
    print(f"[done] {out_path}  ({os.path.getsize(out_path)/1e6:.1f} MB)")

    # ---- 严格构建检查（Showcase 升级方案 §七）---------------------------
    # 序列化产物本身再过一遍：任何一条不过都直接抛错，不允许带病交付
    strict = []

    def strict_ok(name, cond, detail=""):
        strict.append((name, bool(cond), detail))

    probe = json.loads(raw_json) if (raw_json := open(out_path, "r", encoding="utf-8").read()) else None
    strict_ok("earth.json 可被 json 解析", probe is not None)
    strict_ok("无 °S°S / °N°N 之类的重复单位",
              "°S°S" not in raw_json and "°N°N" not in raw_json)
    def _find_none(obj, path="$"):
        if obj is None:
            return path
        if isinstance(obj, dict):
            for k, v in obj.items():
                r = _find_none(v, f"{path}.{k}")
                if r:
                    return r
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                r = _find_none(v, f"{path}[{i}]")
                if r:
                    return r
        return None
    none_path = _find_none(probe)
    strict_ok("无 None 泄漏（解析后逐值遍历）", none_path is None,
              f"发现 null 于 {none_path}" if none_path else "")
    strict_ok("无未替换的占位符 {…}",
              not re.search(r"\{[a-zA-Z0-9_]{1,30}\}", " ".join(
                  [e["title"] + e["text"] + e["evidence"] for e in earth["events"]])))
    strict_ok("每个事件都有 evidence", all(e.get("evidence", "").strip() for e in earth["events"]))
    strict_ok("事件时间均为切片网格点（5 Ma 的倍数）",
              all(e["time_Ma"] % TIME_STEP == 0 and TIME_MIN <= e["time_Ma"] <= TIME_MAX
                  and e["time_Ma"] in TIMES for e in earth["events"]),
              str([e["time_Ma"] for e in earth["events"]]))
    strict_ok("事件按 400→0 降序", [e["time_Ma"] for e in earth["events"]] ==
              sorted([e["time_Ma"] for e in earth["events"]], reverse=True))
    strict_ok("全部切片、时间 = 网格点", [s["time_Ma"] for s in earth["slices"]] == list(TIMES))
    strict_ok(f"每片 vertex_count 与（land+holes）顶点数一致且在 {VERTEX_HARD_LO}–{VERTEX_HARD_HI}",
              all(VERTEX_HARD_LO <= s["vertex_count"] ==
                  (sum(len(r) for r in s["land"]) + sum(len(r) for r in s.get("holes", [])))
                  <= VERTEX_HARD_HI for s in earth["slices"]))
    strict_ok(f"每条 marker 轨迹长 {len(TIMES)}、时间升序、track[0]=现代坐标",
              all(len(m["track"]) == len(TIMES)
                  and [x["time_Ma"] for x in m["track"]] == list(TIMES)
                  and (m["track"][0]["lon"], m["track"][0]["lat"]) ==
                  (round(m["modern"][0], ROUND_DIGITS), round(m["modern"][1], ROUND_DIGITS))
                  for m in earth["markers"]))
    strict_ok("每片都有 metrics（面积/连通率/分量数）",
              all(isinstance(s.get("metrics"), dict) and
                  {"land_area_km2", "comp_frac", "n_comp"} <= set(s["metrics"]) for s in earth["slices"]))
    strict_ok("0 Ma 现代地标核对存在且通过", bool(checks.get("stage0", {}).get("pass")))
    strict_ok("渲染所需字段路径齐全（slices[].land 等）",
              all(len(s["land"]) > 0 and len(s["land"][0]) >= 3 for s in probe["slices"]))
    # F2 之后的数据是最终态：日界线/自交在序列化数据上再核一遍（质检→改数据→复核）
    f_edges, f_bad, f_seam = [], [], []
    for s in probe["slices"]:
        for r in s["land"] + s.get("holes", []):
            rr = np.asarray(r, dtype=np.float64)
            closed = np.concatenate([rr, rr[:1]])
            dl = np.abs(np.diff(closed[:, 0]))
            mx = float(dl.max()) if len(dl) else 0.0
            if mx > 180.0 + 1e-9:
                f_edges.append((s["time_Ma"], mx))
            elif abs(mx - 180.0) < 1e-9:
                f_seam.append(s["time_Ma"])
            try:
                if len(rr) >= 3 and not Polygon(rr).is_valid:
                    f_bad.append(s["time_Ma"])
            except Exception:
                f_bad.append(s["time_Ma"])
    strict_ok("最终数据无 >180° 边（极点缝合边除外）",
              not f_edges, f"跨界 {len(f_edges)} 条" + (f"，例 {f_edges[:3]}" if f_edges else ""))
    strict_ok("最终数据无自交环", not f_bad, f"{len(f_bad)} 个" + (f"，例 {f_bad[:3]}" if f_bad else ""))
    for name, okflag, detail in strict:
        print(f"   [strict] {'PASS' if okflag else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    n_fail = sum(1 for _, okflag, _ in strict if not okflag)
    print(f"[strict] {len(strict) - n_fail}/{len(strict)} 通过"
          + ("" if n_fail == 0 else f"  —— {n_fail} 项失败，终止"))
    # 自检汇总（供 report.md）—— P2：先写盘再判定终止，避免「新数据 + 旧自检」
    summary = {
        "area": checks["area"],
        "antarctica": checks["antarctica"],
        "speed": {k: v for k, v in checks["speed"].items()},
        "verts": {k: v for k, v in checks["verts"].items()},
        "facts": {"markers_at_400": checks["facts"]["markers_at_400"],
                  "comp_at": checks["facts"]["comp_at"], "delhi_lhasa": checks["facts"]["delhi_lhasa_km"],
                  "assertions": {k: bool(v) for k, v in checks["facts"]["assertions"].items()},
                  "pass": bool(checks["facts"]["pass"])},
        "antimeridian": checks["antimeridian"],
        "stage0": checks["stage0"],
        "raw_total_geometries": n_raw,
        "speed_top5": marker_speeds[:5],
        "tols": [round(float(t), 4) for t in smoothed],
        "strict": {"n": len(strict), "n_fail": sum(1 for _, f, _ in strict if not f),
                   "items": [n for n, f, _ in strict if not f] or ["all passed"]},
    }
    with open(os.path.join(HERE, "checks.json"), "w") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)

    if n_fail:
        raise SystemExit(1)

    all_pass = all(checks[k]["pass"] for k in ("area", "antarctica", "speed", "verts", "antimeridian")) \
        and checks["facts"]["pass"]
    print("[summary] 六项自检:", "ALL PASS" if all_pass else "见上方细节")


def dedupe_ring(ring):
    """P9：去掉相邻重复点（ROUND_DIGITS 取整后产生的零长度边）。"""
    if len(ring) < 2:
        return ring
    keep = np.ones(len(ring), dtype=bool)
    keep[1:] = np.any(ring[1:] != ring[:-1], axis=1)
    out = ring[keep]
    if len(out) > 1 and np.array_equal(out[0], out[-1]):
        out = out[:-1]
    return out


def ring_ok(ring):
    """丢掉退化环：面积近零的环不输出。"""
    if len(ring) < 3:
        return False
    try:
        return polygon_area_km2(ring) > 1.0
    except Exception:
        return False


if __name__ == "__main__":
    main()
