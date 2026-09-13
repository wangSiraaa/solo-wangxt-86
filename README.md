# 收入确认核算应用（RevRec）

围绕**账号订阅、一次性实施、按量服务**三类履约义务建立的核算应用，帮助财务分清三件事：
**签了多少合同、收了多少钱、当期真正履约确认了多少收入**。开票与收款独立建模，
不直接当成收入；确认计划由分配版本驱动，任何金额都能追到具体分配版本。

> ⚠️ 本项目采用的分摊/确认政策为**示例政策，仅用于本项目演示，不宣称覆盖所有会计准则**。

## 技术栈

- **前端** Vue 3 + Vite（合同组成、分配版本、确认计划、递延余额逐期对照）
- **后端** Django 5 + Django REST Framework（金额一律 `Decimal`，分位 `ROUND_HALF_UP`）
- **数据库** PostgreSQL 16（履约义务、独立售价 SSP、验收证据、确认计划均落库）

## 示例政策（仅用于本项目）

1. **交易价格分摊**：按各履约义务独立售价（SSP）占比分摊合同总价；
2. **尾差归属**：分摊尾差（如 ±0.01）稳定归属 **SSP 最高的履约义务**（并列取 id 最小者），
   规则固定、可复算，归属标记在分配行上；
3. **确认时点**：
   - 订阅：服务期内按日历天直线确认，最后一期兜底尾差，保证合计 = 分摊额；
   - 实施：以**验收证据**日期所在期间一次性确认；**无证据保持待确认**（不占期间、不冲递延）；
   - 按量：实际用量 ×（分摊额 ÷ 预计总量），累计封顶分摊额；
4. **开票/收款 ≠ 收入**：发票与收款只影响应收/递延与现金口径，不产生确认记录；
5. **期间关闭**：关闭后其中的确认、开票、收款、证据、用量记录均不能直接编辑；
   存在已关闭期间确认记录的合同禁止重新分摊（已冻结）。

## 数据模型（PostgreSQL）

```
Contract 合同 ─┬─ PerformanceObligation 履约义务（类型/SSP/服务期/预计总量）
               ├─ AllocationVersion 分配版本 ─ AllocationLine 分配行（SSP快照/比例/金额/尾差标记）
               ├─ Invoice 开票 / Payment 收款（按期间归集，不产生确认）
               └─ （经义务）RecognitionEntry 确认计划行 → 引用 AllocationLine → 可追溯版本
Evidence 验收证据（义务 1:1）   UsageRecord 用量记录   AccountingPeriod 会计期间（可关闭）
```

## 三个演示案例（`python manage.py seed_demo`）

| 案例 | 要点 | 关键数字 |
|---|---|---|
| A `HT-2025-001` | **跨年度**订阅 2025-07~2026-06 + 实施已验收，全额开票收款 | 签约 131,000，SSP 合计 140,000，折扣 9,000 按比例分摊 |
| B `HT-2025-002` | **部分验收**：阶段一已验收、阶段二缺证据**待确认**；SSP 3/11、3/11、5/11 产生 **-0.01 尾差**归属订阅 | 签约 100,000；待确认 27,272.73 |
| C `HT-2026-003` | **预收未开通**：全额预收 54,000，订阅服务期在未来（全部计划态），按量已确认两期 | 按量单价 0.90/次，已确认 4,950，递延 49,050 |

期间 2025-01 ~ 2026-08 已关闭，当前期间 2026-09 打开。

## 运行

```bash
# 1. 启动 PostgreSQL（用户空间实例，端口 54329）
/workspace/.pg/bin/pg_ctl -D /workspace/.pg/data -l /workspace/.pg/logfile -o "-p 54329 -k /tmp" start

# 2. 后端（迁移 + 演示数据 + 服务）
cd backend && python3 manage.py migrate && python3 manage.py seed_demo
python3 manage.py runserver 8000

# 3. 前端（开发）
cd frontend && npm install && npm run dev     # 或 npm run build 后由 Django 直接托管
```

访问 `http://127.0.0.1:8000/`（Django 托管前端构建产物）。

测试：`cd backend && python3 manage.py test`（15 个用例：分摊/尾差/直线/待确认/封顶/关闭期间/对照恒等式）。

## 主要 API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/summary/` | 签约/开票/收款/已确认/待确认/递延 汇总 |
| GET | `/api/contracts/` `/api/contracts/{id}/` | 合同列表 / 详情（组成+分配+确认计划+递延对照） |
| POST | `/api/contracts/{id}/reallocate/` | 生成新分配版本（旧版本保留追溯） |
| GET/POST | `/api/periods/` `/api/periods/{id}/close/` | 期间列表 / 关闭期间 |
| POST | `/api/evidence/` | 登记验收证据 → 触发实施确认 |
| POST | `/api/usage-records/` | 登记用量 → 触发按量确认 |
| POST | `/api/invoices/` `/api/payments/` | 登记开票/收款（不影响确认） |

## 核对恒等式（前端对照表即按此逐期展示）

- 每行确认计划：`期末递延 = 期初 + 当期开票 − 当期确认`（收款单列，不参与）
- 每个合同：`已确认 + 待确认 + 未来计划 = 已分摊合计 = 签约额`（按量未耗用量除外）
- 每条确认金额：`RecognitionEntry → AllocationLine → AllocationVersion` 全链路可追溯
