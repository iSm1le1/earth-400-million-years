# 引用与数据来源 · CITATION

## 主数据（板块重建模型）

**Merdith, A.S., Williams, S.E., Collins, A.S., Tetley, M.G., Mulder, J.A.,
Blades, M.L., Young, A., Armistead, S.E., Cannon, J., Zahirovic, S., Müller, R.D.
(2021).** *Extending full-plate tectonic models into deep time: Linking the
Neoproterozoic and the Phanerozoic.* **Earth-Science Reviews, 214, 103477.**
doi:10.1016/j.earscirev.2020.103477

- 数据页面 / 下载：
  `https://earthbyte.org/webdav/ftp/Data_Collections/Merdith_etal_2021_ESR/SM2-Merdith_et_al_1_Ga_reconstruction_v1.1.zip`
  （v1.1，8.6 MB，zip 已随包提供以便复现）
- **许可：CC-BY 3.0**（EarthByte / GPlates 数据集）。使用、再分发与改编均允许，
  但必须保留上方作者列表与论文出处（本段即为所要求的署名）。
- 本工程实际使用的三个原始文件：
  - `1000_0_rotfile_Merdith_et_al.rot`（板块旋转文件）
  - `shapes_coastlines_Merdith_et_al_v2.gpmlz`（时间依赖海岸线几何）
  - `shapes_static_polygons_Merdith_et_al.gpml`（现代静态板块多边形，
    用于确定 marker 的板块归属）

## 重建工具

- **pygplates 1.0.0**（EarthByte 的 Python 板块重建库，BSD-3-Clause），
  由 `build.py` 调用执行 0–400 Ma 的几何重建与 marker 轨迹积分。

## 事件叙事引用的文献（按事件时间）

- ~201 Ma 中大西洋岩浆省（CAMP）：**Marzoli, A., et al. (1999).** *Extensive
  200-million-year-old continental flood basalts of the Central Atlantic
  Magmatic Province.* Science, 284, 616–618.
- 早古生代亚洲古地理（中国陆块低纬起点）：**Domeier, M. (2018).** *Early
  Paleozoic tectonics of Asia: Towards a full-plate model.* Geoscience
  Frontiers, 9(3), 789–862.
- 印度—亚洲碰撞：**Molnar, P., & Tapponnier, P. (1975).** *Cenozoic tectonics
  of Asia: Effects of a continental collision.* Science, 189, 419–426.
- 南极冰盖扩张（~34 Ma）：**Zachos, J., Pagani, M., Sloan, L., Thomas, E.,
  & Billups, K. (2001).** *Trends, rhythms, and aberrations in global climate
  65 Ma to present.* Science, 292, 686–693.

> 事件文本中所有距离、速度、纬度、连通率百分比均由 `build.py` 从本数据
> 现场计算注入（见 `checks.json`）；文献只提供地质年代与机制解释。
