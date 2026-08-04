监控笔记本爬虫（crawl_laptops）GitHub Actions 工作流运行情况和 Pages 页面数据是否符合预期。

## 数据链
Crawl ZOL / Crawl JD / Crawl PConline → Merge and Filter → Deploy Pages
Pages: https://nbs.jiucai.eu.org/data/latest.json 与 data/manifest.json

## 检查清单
1. 查看最近 5 个 GitHub Actions 运行状态（crawl-zol/crawl-jd/crawl-pconline/merge-and-filter/deploy-pages）
2. 查看 https://nbs.jiucai.eu.org/data/manifest.json 的 rowCount 与 sourceCounts
3. 检查三个爬虫是否有 detail_risk_verification 风控或代理失败
4. 检查 merge-and-filter 是否正常消费三个 artifact（JD 行是否进入发布）
5. 检查 Pages 是否部署成功、多源率是否提升
6. 检查 AI Auto Fix Monitor 是否已为失败 run 建诊断 issue

## ⚠️ 关键规则
- 发布门禁不可绕过：数字小键盘 + 键盘背光 + 标压/高性能 CPU，未知即拒
- 先用 bash/gh/curl 调查问题，不要凭猜测改代码
- 任何代码修改必须遵守仓库 AGENTS.md 评审规则，禁止 --no-verify
- 增量爬虫 exit 10 保存进度属正常行为，不是失败

## 如果发现问题
读取失败 workflow 日志 → 分析根因（站点结构/代理/风控/数据门禁/临时故障）→ 按仓库规则修复 → 验证 → 提交推送。
