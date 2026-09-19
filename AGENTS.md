# AGENTS.md — heat-environment-platform

《GIS综合实习》选题9：**城市主客观热暴露差异及其影响机制的 GIS 分析**。上海市热暴露时空可视分析平台：FastAPI + PostGIS 后端、Vue 3 + CesiumJS 前端，融合客观微气候/辐射数据与公众主观体感打卡（UGC）。文档与沟通默认中文。父目录 `..\AGENTS.md` 是整个实习目录的总指南。

## 目录结构

- `backend/app/`：`routers/`（api_v1 下挂 auth / scenes / environment / check_ins / exports / tasks / forecast / spatial）、`services/`（业务计算与气象接入）、`db/models.py`（SQLAlchemy 模型，仅 `platform` schema）、`schemas/`（Pydantic 契约与响应包装）
- `frontend/src/`：`services/`（`api.ts` 传输层与模式切换、`backend-adapter.ts` 后端响应归一化、`demo.ts` 纯前端合成演示、`contracts.ts` 前端内部契约）、`stores/workspace.ts`（唯一 Pinia store，编排全部状态）、`features/scene/`（`MapScene.vue` + `adapter.ts`，Cesium 渲染）、`features/environment/`（时间轴）、`components/`（面板与弹窗）
- `data_package/`：开箱 SQL 数据包（platform 种子、上海 16 区边界、核心区 8000 栋 3D 建筑与路水绿要素），用 `scripts/init_database.py` 导入
- `docs/`：全部设计文档，改敏感区域前先查（见文末索引）

## 常用命令

| 用途 | 命令 |
| --- | --- |
| 一键启动前后端 | 根目录 `.\start.bat` 或 `.\start.ps1`（`-Demo` 为纯演示模式；`-Check` 只体检；后端默认热重载 `backend/app` 的 `.py`，`-NoReload` 关闭） |
| 后端单元测试（离线，无 DB） | `cd backend` 后 `<python> -m pytest unit_tests -q`（36 例，秒级） |
| 后端接口测试（需本地 PostgreSQL） | `cd backend` 后 `<python> -m pytest tests -q` |
| 前端测试 | `cd frontend` 后 `npm run test`（vitest） |
| 前端类型检查 | `cd frontend` 后 `npx vue-tsc --noEmit`（`npm run build` 内含） |
| 数据库导入 | `<python> scripts\init_database.py` |

**没有配置任何 linter**（无 ESLint / Ruff / mypy）；质量门槛 = 上述测试 + vue-tsc。Python 解释器用父目录 `E:\大学\GIS综合实习\.venv\Scripts\python.exe`（依赖已装齐；start.ps1 按 `backend/.venv` → 平台 `.venv` → 父 `.venv` → PATH 顺序查找）。

## 运行模式与端口

- 模式判定（`services/api.ts` 的 `isDemo`）：URL `?mode=` 优先，其次 `VITE_DATA_MODE`，仅当值等于 `'demo'` 才是演示模式，其余值（api/live）都走真实后端。`start.ps1` 进程内强制 `VITE_DATA_MODE=api|demo`，不改写 `.env`。
- 端口：前端固定 5178（strictPort）；后端 start.ps1 默认 8000，被占用自动后移并同步代理。**vite.config.ts 的代理兜底目标是 8001**——手动 `npm run dev` 时须设 `API_PROXY_TARGET` 指向实际后端端口，以启动窗口打印的地址为准。
- Cesium：dev server 从 `node_modules/cesium/Build/Cesium` 服务 `/cesium/` 静态资源，build 时复制进 `dist/cesium`；ion token 经 `/api/cesium-token` 中间件读取 `frontend/.cesium-token.local`（gitignored）。天地图 key 由后端场景接口下发（`backend/.env` 的 `TIANDITU_KEY`）。
- 后端 lifespan 启动即自动建表并按供应商同步天气发布；气象供应商默认 `open_meteo_ecmwf`，可切 `qweather`（JWT 配置见 `docs/和风天气配置.md`，私钥在 `backend/secrets/`，严禁入库）。

## 架构红线（改代码前必读）

1. **契约流**：后端 OpenAPI 是唯一契约源，响应包装 `{data, meta:{request_id, server_time}}`，错误 `{error:{code, message, details}, meta}`。前端 `contracts.ts` 是内部契约，`backend-adapter.ts` 负责 wire → contracts 归一化；`demo.ts` 按 contracts 造合成数据。**改后端接口必须同步 adapter（或 demo）**——历史上契约不一致导致 API 模式整体不可用（评审报告 C1），且 `MapScene.vue` 会静默降级、失败不报错。
2. **时间语义**：数据库一律存 timestamptz 时刻（UTC）。禁止对 +08:00 的 aware datetime 用 `strftime("%Y-%m-%dT%H:%M:%SZ")`——`Z` 语义等于 +00:00，会把时刻错标 8 小时（评审报告 C2）；用 `.isoformat()` 或先转 UTC。前端统一 `new Date().toISOString()`。
3. **UGC 隐私**：对外打卡坐标必须经 200m 网格脱敏（`services/format.ts` 的 `publicLocation`，EPSG:32651），任何新接口不得泄露精确坐标。
4. **展示规则**：UTCI 图例为固定 15–35 °C 区间，不随帧数据缩放（2026-09-19 用户指定；超出区间用端点色，unit_tests 有断言）；其他变量按帧 p1–p99 百分位动态取范围；数据缺失 ≠ 0，缺测须带 `reason_code` 说明原因；屏幕光影只是视觉演示，不作科学读数。
5. **层次职责**（详见 `docs/系统分层与模块架构.md` 五层划分）：前端只展示已发布结果；后端接口层不在地图查询请求里做大规模射线计算；供应商密钥只存在于服务端。

## 已知坑

- `platform` schema 由 `Base.metadata.create_all()` 自动建表，**无版本化迁移**；改 `db/models.py` 后需手工 ALTER 或删表重建。`public` schema 的空间底座数据来自 data_package SQL，不要用 ORM 覆盖。
- `backend/tests` 跑真库（`gis_thermal_shanghai`@127.0.0.1:5432，PostgreSQL 16 + PostGIS 3.6）；`backend/unit_tests` 全 monkeypatch，离线可跑。预置账号 `user_test/user123456`、`admin_test/admin123456`。
- 业务机制：幂等 `Idempotency-Key`（24h）、乐观并发 `If-Match`（缺失 428 / 冲突 412）、`view_id` 快照 24h 过期（410）、429 带 Retry-After——新接口尽量沿用，前端 `api.ts` 已按状态码出文案。
- 工作区当前有未提交改动（spatial、图层、时间轴、adapter 等），且 `workspace.test.ts` 有 1 个失败用例（播放时间步进 16:15 vs 17:00），属 WIP 中间态，提交前需修复或确认。

## 文档索引

- `docs/系统分层与模块架构.md` — 五层职责与模块边界（动架构前必读）
- `docs/平台代码评审报告_20260916.md` — 已知缺陷清单（C1 契约、C2 时间），避免复发
- `docs/后端应用接口层_详细设计.md` + `backend/README.md` — API 契约规范与业务机制
- `docs/数据使用指南.md` — 双 schema 数据组织、数据包与跨设备迁移
- `docs/实时气象视图_详细设计.md`、`docs/太阳辐射物理降尺度方案.md` — 气象与辐射产品逻辑
- `docs/和风天气配置.md` — QWeather JWT 接入与供应商切换
