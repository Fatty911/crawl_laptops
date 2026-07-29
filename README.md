# crawl_laptops

一个面向实际选购的笔记本电脑多源数据管线：按热度抓取 ZOL、按销量抓取京东，进行跨来源身份去重和证据合并，只把满足严格准入条件的数据发布到 GitHub Pages。

站点域名：`https://nbs.jiucai.eu.org`

## 发布准入

Pages 中的每条数据都必须同时满足：

- 明确有数字小键盘；
- 明确有键盘背光；
- CPU 型号明确以 `H`、`HX`、`HS` 或 `HK` 结尾。

`U`、`Y`、`UL`、`UP`、`G1`、`G4`、`G7` 等低压后缀和无法识别的 CPU 都会 fail closed。前端默认隐藏独立显卡机型，但用户可以取消该可选条件；三个发布准入条件始终锁定。

## 数据流

```text
ZOL 热度榜 ──► zol-data-YYYYMMDD ─┐
                                   ├─► 身份去重/证据合并
京东销量榜 ─► jd-data-YYYYMMDD ───┘       │
                                          ├─► 严格准入
上次 Release 基线 ─► 保留 + 防缩小 ───────┤
                                          ├─► 审计 + 证据报告
                                          └─► data-latest Release
                                                    │
                                                    └─► Pages SPA
```

每个 crawler artifact 少于 50 行会立即失败。合并采用稳定身份键，`atomic_source_names` 将“中关村在线/ZOL”和“京东/JD”等别名归一为原子来源。上次已发布且仍满足规则的机型会被保留，superset 校验会阻止意外丢数，审计还会拦截来源整体回归。

## 仓库结构

- `scripts/crawl_zol.py`：ZOL 热度榜和产品参数页。
- `scripts/crawl_jd.py`：京东官方销量排行榜和产品参数页。
- `scripts/merge_data.py`：身份去重、来源归一、证据合并和发布准入。
- `scripts/preserve_publish_baseline.py`：合并上次发布基线。
- `scripts/verify_publish_superset.py`：防止已发布身份被缩小。
- `scripts/audit_pages_payload.py`：结构、资格、重复和来源回归审计。
- `scripts/download_latest_crawler_artifact.py`：从 Actions 获取各来源最新成功 artifact。
- `scripts/analysis/merge_evidence_report.py`：生成合并证据统计。
- `docs/`：无框架的响应式 Pages 单页应用。
- `config/filter_conditions.json`：强制条件、默认条件和筛选分组的单一配置源。

## 本地开发

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt pytest
python -m pytest tests/ -v
```

抓取原始数据：

```bash
python scripts/crawl_zol.py --output data/raw/zol/latest.json
python scripts/crawl_jd.py --output data/raw/jd/latest.json
```

京东搜索页已改为 React 客户端渲染，并可能对数据中心 IP 返回风险验证。爬虫因此使用京东官方服务端渲染的销售排行榜（15 日销量降序）；详情页如被验证拦截，只从排行榜中的真实商品标题提取可确认字段，其余字段保持未知，不会把验证 HTML 当作数据。

合并和本地预览：

```bash
python scripts/merge_data.py \
  data/raw/zol/latest.json data/raw/jd/latest.json \
  --output dist/laptops-latest.json \
  --rejected-output dist/rejected.json
python scripts/prepare_pages_payload.py \
  --input dist/laptops-latest.json --docs-dir docs
python -m http.server 8000 --directory docs
```

访问 `http://localhost:8000`。不要直接用 `file://` 打开页面，因为浏览器会阻止 `fetch()` 读取 JSON。

## Actions 与发布

- `crawl-zol.yml`：每周一 UTC 03:17 或手动运行。
- `crawl-jd.yml`：每周二 UTC 03:47 或手动运行。
- `merge-and-filter.yml`：任一爬虫成功后，下载两个来源各自最新的完整 artifact，合并、审计、更新滚动 Release，再触发 Pages。
- `deploy-pages.yml`：从 `data-latest` Release 下载已审计 JSON，准备 `docs/data/latest.json` 并使用 GitHub Pages Actions 部署。

仓库需在 **Settings → Pages → Source** 中选择 **GitHub Actions**。自定义域由 `docs/CNAME` 声明为 `nbs.jiucai.eu.org`，DNS 侧应将该域名 CNAME 到 `fatty911.github.io`。私有仓库能否公开使用 Pages 取决于 GitHub 账户方案。

工作流全部使用 action 的 `@main`（第三方 action 如引入则使用 `@main`/`@master`），不 pin commit SHA。

## 数据契约摘要

Release 资产 `laptops-latest.json` 顶层包含 `schema_version`、`generated_at`、`count`、`sources`、`items` 和 `pipeline`。每个 item 至少包含：

- `identity_key`、`title`、`brand`、`model`
- `cpu`、`cpu_voltage_type`
- `numeric_keypad`、`keyboard_backlight`
- `gpu`、`gpu_type`、`dedicated_gpu`
- `atomic_source_names`、`source_count`、`source_urls`、`source_ranks`
- 抓取来源 URL、排名及 `evidence`

价格与库存随时会变化，站点仅提供结构化选购线索，最终信息以来源页面为准。
