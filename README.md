# 城市热暴露时空可视分析平台 (Heat Environment Platform)

> 《GIS综合实习》选题9：**城市主客观热暴露差异及其影响机制的 GIS 分析**

本项目为城市热暴露时空可视分析平台，采用 B/S 分离架构，融合了多源客观微气候模拟、气象同化网格、高分辨率客观城市三维空间形态要素（建筑高度/密度/路网/水绿体）以及公众主观热感知（UGC 体感打卡与空间感知反馈），实现城市主客观热环境的多维三维时空交互与量化可视分析。

---

## 快速导航

- [平台架构与技术栈](#平台架构与技术栈)
- [跨设备快速上手](#跨设备快速上手)
- [目录与文档体系](#目录与文档体系)
- [安全与隐私规范](#安全与隐私规范)

---

## 平台架构与技术栈

- **前端展示层 (`frontend/`)**：
  - **核心框架**：Vue 3 (Composition API) + TypeScript + Vite
  - **三维空间底座**：CesiumJS（支持 3D 建筑白模高度自适应拉伸、DEM 地形晕渲叠加、天地图矢量与注记底图）
  - **图表与样式**：ECharts + Tailwind CSS + Lucide Icons
  - **状态与适配**：Pinia 全局工作空间状态，具备纯前端 Demo 模式与全功能 API 模式无缝切换能力
- **后端服务层 (`backend/`)**：
  - **应用接口**：FastAPI + Uvicorn + Pydantic v2
  - **空间计算与 ORM**：SQLAlchemy 2.0 + GeoAlchemy2 + Shapely + PyProj
  - **气象与同化算法**：支持 Open-Meteo 全球数值模型与和风天气高精度预报，内置空间控制点粗差剔除与辐射降尺度计算
- **空间数据库**：
  - PostgreSQL 14+ 与 PostGIS 3.0+ 空间扩展，规划 `platform` 业务模式与 `public` 地理信息数据底座

---

## 跨设备快速上手

### 1. 准备环境与安装依赖
在平台根目录下运行一键安装脚本（自动配置 Python 虚拟环境与前端 npm 包）：
```powershell
# Windows
.\setup_env.ps1
# 或直接双击 setup_env.bat

# Linux / macOS
chmod +x setup_env.sh && ./setup_env.sh
```

### 2. 准备数据（全栈模式）
配置好本地 PostgreSQL 后，在 `backend/.env` 中修改数据库连接密码，然后执行一键数据导入脚本：
```powershell
& .\.venv\Scripts\python.exe scripts\init_database.py
```
> **提示**：若暂未配置数据库，可使用免数据库的纯前端演示模式直接运行：`.\start.ps1 -Demo`。

### 3. 一键启动
双击运行平台根目录下的 `start.bat`（或在 PowerShell 中执行 `.\start.ps1`）：
- **Web 前端**：[http://127.0.0.1:5178](http://127.0.0.1:5178)
- **API 文档 (Swagger)**：[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

## 目录与文档体系

```text
heat-environment-platform/
├── backend/                   # FastAPI 后端服务源码
│   ├── app/                   # 路由、数据模型、业务计算与同化逻辑
│   ├── requirements.txt       # Python 依赖清单
│   └── tests/                 # 自动化接口与单元测试
├── frontend/                  # Vue3 + Cesium 前端源码
│   ├── src/                   # 三维场景渲染、组件与业务逻辑
│   └── package.json           # 前端依赖配置
├── data_package/              # 内置核心空间数据包 (可开箱即用)
│   ├── 01_platform_seed.sql   # 业务表结构与系统种子数据
│   ├── 02_public_admin_boundary.sql # 上海市界与16区行政边界
│   └── 03_public_spatial_core_sample.sql # 上海核心示范区8000座3D建筑与路水绿要素
├── docs/                      # 平台详细设计与数据规范文档
│   ├── 数据使用指南.md         # 跨设备数据准备、模式说明与迁移手册
│   ├── 启动说明.md            # 服务启动与日志排障
│   ├── 系统分层与模块架构.md   # 系统整体架构设计
│   ├── 前端交互与三维展示层_详细设计.md
│   ├── 后端应用接口层_详细设计.md
│   ├── 环境计算与空间分析层_详细设计.md
│   ├── 实时气象视图_详细设计.md
│   ├── 太阳辐射物理降尺度方案.md
│   ├── 和风天气配置.md         # 和风天气 JWT 接入指南
│   └── 平台代码评审报告_20260916.md
├── scripts/                   # 运维、数据打包与数据库初始化脚本
│   ├── init_database.py       # 一键建库与数据包导入
│   └── export_platform_data.py # 核心数据包提取与导出
├── setup_env.bat / .ps1 / .sh # 跨平台一键环境安装脚本
├── start.bat / .ps1           # 前后端联动一键启动与端口自愈脚本
└── .gitignore                 # Git 忽略配置 (防隐私泄露与缓存无污染)
```

---

## 安全与隐私规范

1. **防隐私泄露**：本地 `.env`、私钥证书（`secrets/`、`*.pem`）、浏览器会话、运行日志与个人 Token 均已加入 `.gitignore`，严禁上传代码仓库；
2. **脱敏保护**：公众体感打卡（UGC）对外提供 200m 网格聚合脱敏显示，严格保护个人打卡真实精准坐标与时空隐私；
3. **安全配置**：数据库密码与 API 密钥通过各自独立的 `.env` 文件以环境变量方式注入，源码内不硬编码任何私人凭证。
