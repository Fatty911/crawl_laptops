#!/bin/bash
# 笔记本爬虫工作流+Pages自动监控（移植自 crawl_cars，适配 laptops 数据链）
# 检查 Crawl ZOL / Crawl JD / Crawl PConline / Merge and Filter / Deploy Pages
# 仅首次运行起的7天内有效，每天运行一次
# 用法: bash scripts/monitor_workflows.sh
set -euo pipefail

cd "$(dirname "$0")/.."
command -v gh >/dev/null 2>&1 || { echo "错误：未安装 gh CLI"; exit 1; }

# 7天自动过期
START_MARKER="/tmp/workflow_monitor_start"
if [ ! -f "$START_MARKER" ]; then date +%Y%m%d > "$START_MARKER"; fi
START_DATE=$(cat "$START_MARKER")
DAYS_ELAPSED=$(( ($(date +%s) - $(date -d "$START_DATE" +%s)) / 86400 ))
if [ $DAYS_ELAPSED -ge 7 ]; then
    echo "[$(date)] 监控已运行 $DAYS_ELAPSED 天，超过7天限制，自动停止"
    rm -f "$START_MARKER"
    exit 0
fi
echo "[$(date)] 监控第 $((DAYS_ELAPSED + 1)) 天 (最多7天)"

CURRENT_DATE=$(date -u +%Y%m%d)
TODAY=$(date +%Y%m%d)

# ── 1. 检查三个爬虫最近运行状态 ──
latest_conclusion() {
    gh run list --workflow="$1" --limit=1 --json conclusion -q '.[0].conclusion' 2>/dev/null || echo "unknown"
}
latest_status() {
    gh run list --workflow="$1" --limit=1 --json status -q '.[0].status' 2>/dev/null || echo "unknown"
}

ZOL_CONCLUSION=$(latest_conclusion crawl-zol.yml)
JD_CONCLUSION=$(latest_conclusion crawl-jd.yml)
PCONLINE_CONCLUSION=$(latest_conclusion crawl-pconline.yml)
ZOL_STATUS=$(latest_status crawl-zol.yml)
JD_STATUS=$(latest_status crawl-jd.yml)
PCONLINE_STATUS=$(latest_status crawl-pconline.yml)

# ── 2. 检查最新 artifact ──
artifact_info() {
    gh api repos/Fatty911/crawl_laptops/actions/artifacts \
        --jq "[.artifacts[] | select(.name|test(\"$1\")) | select(.expired != true)] | max_by(.created_at) | {name,size_kb:(.size_in_bytes/1024|floor),created_at}" \
        2>/dev/null || echo "none"
}
ZOL_ARTIFACT=$(artifact_info "zol-data-")
JD_ARTIFACT=$(artifact_info "jd-data-")
PCONLINE_ARTIFACT=$(artifact_info "pconline-data-")

# ── 3. 检查 Pages manifest ──
MANIFEST=$(curl -s --max-time 10 https://nbs.jiucai.eu.org/data/manifest.json 2>/dev/null || echo "{}")
PAGE_ROWS=$(echo "$MANIFEST" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('rowCount','?'))" 2>/dev/null || echo "?")
PAGE_SOURCES=$(echo "$MANIFEST" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('sourceCounts',{}))" 2>/dev/null || echo "?")
PAGE_GENERATED=$(echo "$MANIFEST" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('generatedAt','?')[:10])" 2>/dev/null || echo "?")

echo "爬虫结论: ZOL=$ZOL_CONCLUSION($ZOL_STATUS) JD=$JD_CONCLUSION($JD_STATUS) PConline=$PCONLINE_CONCLUSION($PCONLINE_STATUS)"
echo "Pages: rows=$PAGE_ROWS sources=$PAGE_SOURCES generated=$PAGE_GENERATED"

# ── 4. 诊断 ──
ISSUES=""
for src in "ZOL:$ZOL_CONCLUSION:crawl-zol.yml" "JD:$JD_CONCLUSION:crawl-jd.yml" "PConline:$PCONLINE_CONCLUSION:crawl-pconline.yml"; do
    NAME="${src%%:*}"; REST="${src#*:}"; CONCL="${REST%%:*}"; WF="${REST#*:}"
    if [ "$CONCL" = "failure" ]; then
        ISSUES="$ISSUES\n- $NAME 爬虫失败（$WF），AI Auto Fix Monitor 应已建诊断 issue"
    fi
done

artifact_age_days() {
    local artifact_json="$1"
    [ "$artifact_json" = "none" ] && { echo 999; return; }
    local created
    created=$(echo "$artifact_json" | python3 -c "import json,sys; print(json.load(sys.stdin).get('created_at','2000-01-01')[:10])" 2>/dev/null || echo "2000-01-01")
    local epoch
    epoch=$(date -d "$created" +%s 2>/dev/null || echo 0)
    echo $(( ($(date +%s) - epoch) / 86400 ))
}
ZOL_AGE=$(artifact_age_days "$ZOL_ARTIFACT")
JD_AGE=$(artifact_age_days "$JD_ARTIFACT")
PCONLINE_AGE=$(artifact_age_days "$PCONLINE_ARTIFACT")

[ "$ZOL_AGE" -gt 3 ] && [ "$ZOL_STATUS" != "in_progress" ] && [ "$ZOL_STATUS" != "queued" ] && \
    ISSUES="$ISSUES\n- ZOL artifact 已${ZOL_AGE}天未更新"
[ "$JD_AGE" -gt 3 ] && [ "$JD_STATUS" != "in_progress" ] && [ "$JD_STATUS" != "queued" ] && \
    ISSUES="$ISSUES\n- JD artifact 已${JD_AGE}天未更新"
[ "$PCONLINE_AGE" -gt 3 ] && [ "$PCONLINE_STATUS" != "in_progress" ] && [ "$PCONLINE_STATUS" != "queued" ] && \
    ISSUES="$ISSUES\n- PConline artifact 已${PCONLINE_AGE}天未更新"

# ── 5. 自动修复（24h 防抖） ──
fix_applied=false
throttle_24h() {
    local marker="$1"
    [ -f "$marker" ] || return 1
    local ts
    ts=$(cat "$marker" 2>/dev/null) || return 1
    case "$ts" in ''|*[!0-9]*) return 1 ;; esac
    [ $(($(date +%s) - ts)) -lt 86400 ]
}

retrigger() {
    local conclusion="$1" workflow="$2" marker="$3" label="$4"
    if [ "$conclusion" = "failure" ] || [ "$conclusion" = "cancelled" ]; then
        if ! throttle_24h "$marker"; then
            echo "[$(date)] $label 爬虫${conclusion}→重新触发"
            gh workflow run "$workflow"
            date +%s > "$marker"
            fix_applied=true
        fi
    fi
}
retrigger "$ZOL_CONCLUSION" crawl-zol.yml /tmp/zol_fail_trigger "ZOL"
retrigger "$JD_CONCLUSION" crawl-jd.yml /tmp/jd_fail_trigger "JD"
retrigger "$PCONLINE_CONCLUSION" crawl-pconline.yml /tmp/pconline_fail_trigger "PConline"

# artifact 超过3天未更新且无运行中爬虫 → 重新触发
stale_retrigger() {
    local age="$1" status="$2" workflow="$3" marker="$4" label="$5"
    if [ "$age" -gt 3 ] && [ "$status" != "in_progress" ] && [ "$status" != "queued" ]; then
        if ! throttle_24h "$marker"; then
            echo "[$(date)] $label artifact ${age}天未更新→重新触发"
            gh workflow run "$workflow"
            date +%s > "$marker"
            fix_applied=true
        fi
    fi
}
stale_retrigger "$ZOL_AGE" "$ZOL_STATUS" crawl-zol.yml /tmp/zol_stale_trigger "ZOL"
stale_retrigger "$JD_AGE" "$JD_STATUS" crawl-jd.yml /tmp/jd_stale_trigger "JD"
stale_retrigger "$PCONLINE_AGE" "$PCONLINE_STATUS" crawl-pconline.yml /tmp/pconline_stale_trigger "PConline"

# 三个源 artifact 都新鲜但 Pages 未更新 → 触发合并
fresh() { [ "$(artifact_age_days "$1")" -le 3 ]; }
if fresh "$ZOL_ARTIFACT" && fresh "$JD_ARTIFACT" && fresh "$PCONLINE_ARTIFACT"; then
    PAGE_STALE=false
    if [ "$PAGE_GENERATED" != "?" ] && [ "$PAGE_GENERATED" != "$(date -u +%Y-%m-%d)" ]; then
        PAGE_STALE=true
    fi
    if [ "$PAGE_STALE" = "true" ]; then
        if ! throttle_24h /tmp/merge_trigger; then
            echo "[$(date)] 三个源 artifact 均新鲜但 Pages 未更新→触发合并"
            gh workflow run merge-and-filter.yml
            date +%s > /tmp/merge_trigger
            fix_applied=true
        fi
    fi
fi

if [ "$fix_applied" = true ]; then
    echo "[$(date)] 已自动修复，等待下次监控验证"
elif [ -n "$ISSUES" ]; then
    echo "[$(date)] 发现问题但无法自动修复，需人工介入:"
    echo -e "$ISSUES"
else
    echo "[$(date)] 一切正常"
fi
