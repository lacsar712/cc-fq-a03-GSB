# FASTQ 质控流水线台（FASTQ QC Pipeline Console）

从零实现的全栈演示：上传/选择小型 FASTQ → **Actor 队列流水线**质控 → 查看阶段状态与指标。

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.11 · FastAPI · SQLAlchemy · PostgreSQL |
| 流水线 | `ParseActor` → `QualityHistActor` → `NContentActor` → `ReportActor`（asyncio.Queue） |
| 前端 | Vue 3 · Vite · Quasar · 中文 UI · nginx `/api` 反代 |
| 基建 | docker compose（db / backend / seed / frontend） |

## 端口

| 服务 | 地址 |
|------|------|
| Frontend | http://localhost:3184 |
| Backend API | http://localhost:8184 |
| PostgreSQL | localhost:54384 |

## 账号

| 用户 | 密码 | 权限 |
|------|------|------|
| `bioops` | `fastq123456` | 可提交质控作业 |
| `auditor` | `audit123456` | 只读结果，不可提交 |

## 一键启动

```bash
cd projects/09-fastq-qc-pipeline
docker compose up --build
```

镜像源：Postgres/Node/Nginx 使用 `docker.m.daocloud.io`；npm 使用 `registry.npmmirror.com`；pip 使用清华源。

启动后 seed 会写入：

- `demo-good-r1`：合格样例（可算出 `mean_quality` / `n_rate`）
- `demo-broken-malformed`：损坏样例（`ParseActor` 失败，后续阶段 skipped）

## Verification（验收）

1. 打开 http://localhost:3184 ，用 `bioops` / `fastq123456` 登录。
2. **样例库** 看到 2 条样例 → 选合格样例 **提交质控作业**。
3. 作业详情页看到四个 Actor 阶段均为成功，指标卡出现 `reads` / `mean_quality` / `n_rate`。
4. 再跑损坏样例：`ParseActor` = failed，其余 = skipped。
5. 退出，用 `auditor` / `audit123456` 登录：可看历史与详情，提交作业接口返回 403 / 前端无提交入口。
6. 健康检查：`curl http://localhost:8184/api/health`

## 耗时与超时门禁台

导航栏 **耗时台**(`/timing`)集中展示流水线耗时与超时门禁,所有耗时与超时判定均由**服务端**在流水线运行时实测(`time.perf_counter`)并落库,前端只读展示,不做展示层估算。

- **单作业四阶段耗时**:每个 Actor 阶段的毫秒耗时、生效的超时上限快照、是否超限;作业详情页时间线同步展示。
- **平均耗时**:最近 N(5/10/20/50/100 可选)个成功作业的各阶段平均/最大耗时,服务端 SQL 聚合。
- **超时配置**:运维(bioops)可修改每个 Actor 的超时毫秒上限并落库(`actor_timeout_configs` 表,默认 5000ms);`0 ms` 表示"任何非零耗时即判超时",用于门禁演练。审计员(auditor)可看清单与耗时,改配置返回 403。
- **超时清单**:任一阶段超限的作业自动进入清单,行内标出超限阶段(实测耗时 / 上限),可跳转作业详情。超时只标记不阻断,作业状态仍按流水线结果判定。

### 自测口令

1. 用 `bioops` 登录 → 耗时台 → 把 `ParseActor` 超时上限改为 `0` ms 保存。
2. 重新提交合格样例 `demo-good-r1`。
3. 耗时台 **超时清单** 出现该作业,行内标出 `ParseActor` 超限 → 点 **详情** 可进作业详情页,时间线上该阶段带红色"超时"徽章。

## API

- `POST /api/auth/login`
- `GET  /api/health`
- `GET  /api/samples`
- `POST /api/jobs` `{ "sampleId": 1 }` 或 `{ "fastqText": "..." }`
- `GET  /api/jobs`
- `GET  /api/jobs/{id}`
- `GET  /api/jobs/{id}/stages`(含服务端 `duration_ms` / `timed_out` / `timeout_ms_limit`)
- `GET  /api/timing/config` / `PUT /api/timing/config/{actorName}` `{ "timeout_ms": 0 }`(PUT 仅 bioops)
- `GET  /api/timing/jobs/{id}`(单作业四阶段毫秒耗时)
- `GET  /api/timing/summary?limit=20`(最近 N 个成功作业各阶段平均耗时)
- `GET  /api/timing/timeouts`(超时清单,行内带超限阶段)

## 本地单测（可选）

```bash
cd backend
pip install -r requirements.txt
pytest -q
```

覆盖：畸形 FASTQ 在 `ParseActor` 失败；正常样例产出 `mean_quality`；阶段耗时服务端落库；低超时上限触发超时清单；审计员改超时配置返回 403。

## 目录结构

```
09-fastq-qc-pipeline/
  PRD.md
  README.md
  docker-compose.yml
  backend/
    Dockerfile
    seed.py
    data/{good,broken}.fastq
    app/
      main.py api.py auth.py models.py schemas.py timing.py
      pipeline/{actors,runner}.py
    tests/{test_actors,test_timing}.py
  frontend/
    Dockerfile nginx.conf
    src/pages/{Login,Samples,JobSubmit,JobDetail,JobHistory,Timing}Page.vue
```
