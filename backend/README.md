# heat-environment-platform 后端应用接口服务

本工程是城市主客观热暴露与体感打卡时空分析平台的后端服务，基于 **FastAPI + SQLAlchemy 2.0 + PostGIS** 构建，严格遵循 [后端应用接口层_详细设计.md](../后端应用接口层_详细设计.md) 契约规范。

## 1. 技术栈与设计特性

- **Web 框架**：FastAPI 0.115+、Uvicorn、Pydantic v2
- **空间数据库**：PostgreSQL 16 + PostGIS 3.6（使用独立 `platform` Schema 与既有研究资产/OSM 图层隔离）
- **开放气象接入**：Open-Meteo 无需认证的 48~168 小时预报（ECMWF IFS 0.25° / GFS Seamless），具备本地版本化发布快照（`EnvRelease`）与离线回退机制
- **坐标与空间投影**：
  - 公共接口统一采用 WGS84（EPSG:4326）
  - UGC 打卡公开坐标基于 EPSG:32651 投影原点粗化为 200m 网格中心点，实现隐私防护
- **业务机制**：
  - 幂等性：`Idempotency-Key` 请求去重（24小时窗口）
  - 乐观并发控制：`If-Match` 修订号控制（缺失报 428，冲突报 412）
  - 视图生命周期：`view_id` 绑定选定时空快照（24小时有效，过期报 410）
  - 安全防护：会话 HttpOnly Cookie / Bearer Token、CSV 导出 UTF-8-SIG 与电子表格公式注入转义

## 2. 预置账号

| 用户名 | 密码 | 角色 | 权限说明 |
| --- | --- | --- | --- |
| `user_test` | `user123456` | `user` | 普通热感知测试员，可提交、查看、修改打卡及导出个人数据 |
| `admin_test` | `admin123456` | `admin` | 系统运维管理员，可管理全部任务、查看审计与导出 |

## 3. 快速启动

和风天气 JWT 接入已提供，配置方法与认证检查命令见 [和风天气配置](和风天气配置.md)。通过 `backend/.env` 中的 `WEATHER_PROVIDER=qweather` 选择；未设置时保留 Open-Meteo 默认。供应商接入与前端通用接口联调是独立工作，实际验证范围见该文档。

### 3.1 环境准备与依赖安装

```powershell
# 激活项目根目录虚拟环境
..\..\.venv\Scripts\Activate.ps1

# 安装依赖（若已安装可跳过）
pip install -r requirements.txt
```

### 3.2 数据库初始化

```powershell
# 执行平台 Schema 与基础种子数据初始化
python -m app.db.init_db
```

### 3.3 启动后端服务

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

服务启动后访问交互式接口文档：
- **Swagger UI**：[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **ReDoc**：[http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)
- **健康检查**：[http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

## 4. 自动化测试套件

运行全部六大模块（A01~A06）的自动化测试：

```powershell
pytest -v
```

测试覆盖清单：
- `test_a01_scenes.py`: 场景目录、图层清单、POI 检索、OSM 建筑/路网要素空间查询
- `test_a02_environment.py`: 产品 Catalog、Releases 版本、创建固定 View（now/at）、同版点查询（含超范围校验）、时序 Series 查询
- `test_a03_ugc.py`: UGC 打卡幂等创建、未来时间/边界拒绝、200m 网格粗化与公开投影脱敏、If-Match 修订控制、软删除、空间聚合网格统计、内容举报
- `test_a04_auth.py`: 密码哈希校验、测试用户登录、会话获取、登出销毁、会话失效
- `test_a05_tasks_status.py`: 场景运行状态、ETag 与 If-None-Match 304 缓存验证、任务进度跟踪
- `test_a06_exports.py`: 环境数据表格导出、个人打卡导出、UTF-8-SIG 编码与防公式注入校验、文件下载

## 5. 核心接口清单速览

所有业务接口均挂载在 `/api/v1` 前缀下：

| 模块 | 方法 | 路径 | 说明 |
| --- | --- | --- | --- |
| **A01 场景与图层** | GET | `/api/v1/scenes` | 获取可用场景列表 |
| | GET | `/api/v1/scenes/{scene_id}` | 获取场景边界与默认配置 |
| | GET | `/api/v1/scenes/{scene_id}/layers` | 获取场景配置的矢量/三维图层 |
| | GET | `/api/v1/scenes/{scene_id}/places` | POI 地点关键词与 BBox 检索 |
| | GET | `/api/v1/scenes/{scene_id}/features` | 分层空间要素矢量查询 |
| **A02 环境探索** | GET | `/api/v1/scenes/{scene_id}/environment/catalog` | 产品与物理变量指标清单 |
| | GET | `/api/v1/scenes/{scene_id}/environment/releases` | 已发布环境气象版本列表 |
| | POST | `/api/v1/scenes/{scene_id}/environment/views` | 创建固定时间与版本的视图快照（24h） |
| | GET | `/api/v1/environment/views/{view_id}` | 获取视图快照配置与新鲜度 |
| | GET | `/api/v1/environment/views/{view_id}/point` | 经纬度位置环境同版点读数 |
| | GET | `/api/v1/environment/views/{view_id}/series` | 经纬度位置环境时间序列 |
| **A03 UGC 打卡** | POST | `/api/v1/check-ins` | 幂等提交体感打卡（自动异步气象匹配） |
| | GET | `/api/v1/check-ins` | 公开打卡记录列表（200m 粗化位置脱敏） |
| | GET | `/api/v1/check-ins/aggregates` | 空间网格体感聚合统计 |
| | GET | `/api/v1/check-ins/{check_in_id}` | 查看打卡详情（公开脱敏或所有者完整详情） |
| | GET | `/api/v1/me/check-ins` | 当前登录用户个人打卡列表 |
| | PATCH | `/api/v1/check-ins/{check_in_id}` | 乐观锁修订打卡记录（需 If-Match） |
| | DELETE | `/api/v1/check-ins/{check_in_id}` | 软删除打卡（需 If-Match） |
| | POST | `/api/v1/check-ins/{check_in_id}/reports` | 提交违规内容举报 |
| **A04 身份鉴权** | POST | `/api/v1/auth/login` | 测试用户登录，设置 Cookie 并返回会话 Token |
| | POST | `/api/v1/auth/logout` | 登出并注销服务端会话 |
| | GET | `/api/v1/auth/session` | 查询当前登录会话状态与角色 |
| **A05 状态与任务** | GET | `/api/v1/scenes/{scene_id}/status` | 场景运行状态与 ETag 条件缓存 |
| | GET | `/api/v1/tasks/{task_id}` | 异步任务进度与执行结果 |
| **A06 数据导出** | POST | `/api/v1/exports` | 异步创建环境或打卡数据导出任务 |
| | GET | `/api/v1/exports/{export_id}` | 查询导出进度与下载地址 |
| | GET | `/api/v1/exports/{export_id}/download` | 下载 UTF-8-SIG CSV 或 GeoJSON 成果文件 |
