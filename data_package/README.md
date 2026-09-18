# 平台内置数据包 (Data Package) 说明

本目录包含城市热暴露时空可视分析平台的核心离线数据资产，专为跨设备快速迁移、免除 GB 级原始数据拷贝而构建。

---

## 1. 数据清单与结构

| 文件名 | 类型 | 记录数 | 坐标系 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| `01_platform_seed.sql` | 平台基础业务表与种子数据 | 1,129 条 | WGS84 (EPSG:4326) | 包含平台专属 schema `platform` 的全部 DDL（用户、权限会话、场景配置、天气小时预报批次、时空聚合视图、UGC体感打卡、系统任务与导出元数据）。预置测试用户 `user_test`、管理员 `admin_test` 以及上海全域场景 `scene_shanghai`。 |
| `02_public_admin_boundary.sql` | 空间基础边界要素表 | 17 条 | WGS84 (EPSG:4326) | 包含 `public.base_admin_boundary` 表 DDL 与上海市域边界、16个行政区划边界多边形，带有 GiST 空间索引与面积属性。 |
| `03_public_spatial_core_sample.sql` | 核心示范区客观环境矢量要素 | 16,714 条 | WGS84 (EPSG:4326) | 覆盖上海核心城市示范区（BBOX: `[121.44, 31.20, 121.53, 31.26]`，涵盖人民广场、外滩、陆家嘴、南京路、静安寺、新天地与黄浦江沿岸）。包含：<br>- `osm_buildings` (8,000 座精细3D建筑，含实测/估算建筑高度 `height_m`、基底面积、体积与楼层)<br>- `osm_roads` (5,000 条主干路与街巷矢量线)<br>- `osm_water` (99 个黄浦江及苏州河水体多边形)<br>- `osm_green` (615 处城市公园与绿地要素)<br>- `osm_poi` (3,000 个代表性城市设施点) |

---

## 2. 随工程自带的静态数据

除上述 SQL 数据外，工程中还自带了以下就绪资产：
1. **气象控制点与审计网格**：
   - 路径：`backend/app/data/shanghai_audit_points.json`、`shanghai_control_points.json`、`shanghai_audit_points_100.json`
   - 用途：用于多源气象数据空间降尺度与空间同化融合计算。
2. **DEM 晕渲地形图层**：
   - 路径：`frontend/public/layers/shanghai_dem_hillshade.png` 与 `shanghai_dem_hillshade.json`
   - 用途：三维 Cesium 场景地表高程微起伏底图叠加。

---

## 3. 一键数据导入方法

在目标设备上，确保 PostgreSQL 已经安装并开启 PostGIS 插件后，执行：

```powershell
# 在平台根目录运行
python scripts/init_database.py
```

该脚本会自动：
1. 检查或创建 `gis_thermal_shanghai` 数据库；
2. 开启 `postgis` 空间扩展；
3. 顺序执行 `01_platform_seed.sql`、`02_public_admin_boundary.sql` 与 `03_public_spatial_core_sample.sql`；
4. 打印校验表记录数。

详细数据口径与迁移指南参见 `docs/数据使用指南.md`。
