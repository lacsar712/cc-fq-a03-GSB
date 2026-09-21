# FASTQ 质控流水线台（FASTQ QC Pipeline Console）

从零实现的全栈演示：上传/选择小型 FASTQ → **Actor 队列流水线**质控 → 查看阶段状态与指标，并在**耗时台**查看单作业/平均阶段毫秒耗时、运维可配各 Actor 超时门禁、超时作业进清单。

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.11 · FastAPI · SQLAlchemy · PostgreSQL |
| 流水线 | `ParseActor` → `QualityHistActor` → `NContentActor` → `ReportActor`（asyncio.Queue） |
| 耗时门禁 | 服务端 `perf_counter` 毫秒计时 · 每 Actor 超时上限落库 · 超限阶段标红、作业判超时 |
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
| `bioops` | `fastq123456` | 可提交质控作业、可修改各 Actor 超时配置 |
| `auditor` | `audit123456` | 只读：可看历史/详情/耗时台/超时清单，不可提交、不可改超时配置（PUT 返回 403） |

## 一键启动

```bash
cd projects/09-fastq-qc-pipeline
docker compose up --build
```

镜像源：Postgres/Node/Nginx 使用 `docker.m.daocloud.io`；npm 使用 `registry.npmmirror.com`；pip 使用清华源。

启动后 seed 会写入：

- `demo-good-r1`：合格样例（可算出 `mean_quality` / `n_rate`）
- `demo-broken-malformed`：损坏样例（`ParseActor` 失败，后续阶段 skipped）
- 四个 Actor 的默认超时上限（各 2000 ms，写入 `actor_timeout_configs` 表）

## 耗时台与超时门禁

导航栏 **耗时台**（`/timing`，两种角色均可查看）分四块：

1. **各 Actor 超时上限（毫秒）**：bioops 可编辑并保存（落库、记录更新人）；auditor 只读。
2. **最近成功作业各阶段平均耗时**：可选最近 5/10/20/50 个成功作业，服务端聚合返回平均/最小/最大。
3. **单作业四阶段毫秒耗时**：输入作业 ID，逐阶段看 `duration_ms` / `timeout_ms` / 是否超限，可一键进详情。
4. **超时作业清单**：每个超时作业一行，行内红色标出超限阶段（`耗时 / 上限`），可进详情。

**服务端计算原则**：阶段耗时（`perf_counter` 实测整数毫秒）、平均耗时、是否超时、超限阶段全部在后端计算并由 API 返回；前端只渲染，不做任何展示层估算。作业启动时对当时的超时配置做快照（`job_stages.timeout_ms`），事后改配置不影响历史判定。

> 说明：玩具样例本身在微秒级完成，会让四阶段都显示 0 ms、毫秒门禁无法触发。因此每个 Actor 在其**计时窗口内**额外 `await` 一小段确定性模拟处理延迟（Parse 12 / QualityHist 18 / NContent 10 / Report 6 ms）。显示的仍是真实测量的服务端耗时，只是让演示负载非瞬时；默认上限 2000 ms 足够宽松，正常作业一律通过。

### 自测口令（验收 7）

> **把解析超时调很低后重跑合格样例，超时清单出现该单且可进详情。**

1. bioops 登录 → 耗时台，把 `ParseActor` 超时上限改为 `1` 并保存（或 `PUT /api/timing/config`）。
2. 在样例库对 `demo-good-r1` **重新提交质控作业**。
3. 作业状态变为 **超时**：`ParseActor` = failed 并标 `超限 12 > 1 ms`，其余阶段 skipped。
4. 耗时台 **④超时作业清单** 出现该单，行内标出 `ParseActor：12 / 1 ms`，点 **详情** 可进作业详情页查看同样的服务端耗时与标记。
5. auditor 登录同样能看到清单与单作业耗时，但改超时配置接口返回 403。

## Verification（验收）

1. 打开 http://localhost:3184 ，用 `bioops` / `fastq123456` 登录。
2. **样例库** 看到 2 条样例 → 选合格样例 **提交质控作业**。
3. 作业详情页看到四个 Actor 阶段均为成功，指标卡出现 `reads` / `mean_quality` / `n_rate`，每阶段显示服务端毫秒耗时。
4. 再跑损坏样例：`ParseActor` = failed，其余 = skipped（普通失败，不计入超时清单）。
5. 退出，用 `auditor` / `audit123456` 登录：可看历史、详情、耗时台、超时清单；提交作业与修改超时配置接口均返回 403，前端无对应入口。
6. 健康检查：`curl http://localhost:8184/api/health`
7. 按上面的 **自测口令** 验证超时门禁。

## API

- `POST /api/auth/login`
- `GET  /api/health`
- `GET  /api/samples`
- `POST /api/jobs` `{ "sampleId": 1 }` 或 `{ "fastqText": "..." }`
- `GET  /api/jobs`
- `GET  /api/jobs/{id}`
- `GET  /api/jobs/{id}/stages`
- `GET  /api/timing/config` —— 各 Actor 超时上限（登录可读）
- `PUT  /api/timing/config` —— 修改上限 `{ "items": [ { "actor_name", "timeout_ms" } ] }`（仅 bioops）
- `GET  /api/timing/overview?window=10` —— 最近 N 个成功作业各阶段平均/最小/最大耗时
- `GET  /api/timing/timeouts` —— 超时作业清单（行内 `over_stages` 标出超限阶段）
- `GET  /api/jobs/{id}/timing` —— 单作业四阶段服务端耗时与门禁结果

## 本地单测（可选）

```bash
cd backend
pip install -r requirements.txt
pytest -q
```

覆盖：畸形 FASTQ 在 `ParseActor` 失败；正常样例产出 `mean_quality`；调低解析超时后合格样例进入超时清单且详情含超限阶段；最近成功作业平均耗时由服务端聚合；auditor 改配置 403、bioops 可改。测试使用临时 SQLite 库（经 `DATABASE_URL` 注入），无需 PostgreSQL。

## 目录结构

```
fastq-qc-pipeline/
  README.md
  docker-compose.yml
  backend/
    Dockerfile
    seed.py
    data/{good,broken}.fastq
    app/
      main.py api.py auth.py models.py schemas.py timing_service.py
      pipeline/{actors,runner,timing}.py
    tests/{conftest,test_actors,test_timing_api}.py
  frontend/
    Dockerfile nginx.conf
    src/pages/{Login,Samples,JobSubmit,JobDetail,JobHistory,Timing}Page.vue
```
