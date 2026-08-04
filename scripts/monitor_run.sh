#!/bin/bash
# 定时监控工作流和 Pages 数据（调试期最多运行 14 次，之后自动停止）
# 移植自 crawl_phones，适配 laptops 数据链（nbs.jiucai.eu.org）
set -e
cd "$(dirname "$0")/.."
REPO_DIR="$(pwd)"

COUNTER_FILE="$REPO_DIR/scripts/.monitor_count"
MAX_RUNS=14
RUN_COUNT=1

if [ -f "$COUNTER_FILE" ]; then
  RUN_COUNT=$(($(cat "$COUNTER_FILE") + 1))
fi

if [ "$RUN_COUNT" -gt "$MAX_RUNS" ]; then
  crontab -l 2>/dev/null | grep -v "monitor_run" | crontab - || true
  echo "$(date '+%Y-%m-%d %H:%M:%S') 已运行 ${RUN_COUNT} 次（超过 ${MAX_RUNS} 次上限），自动停止" >> "$REPO_DIR/scripts/monitor.log"
  exit 0
fi

echo "$RUN_COUNT" > "$COUNTER_FILE"

LOG_FILE="$REPO_DIR/scripts/monitor_$(date +%Y%m%d_%H%M).log"
echo "=== 笔记本工作流监控 #$RUN_COUNT/$MAX_RUNS $(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$LOG_FILE"

if command -v opencode >/dev/null 2>&1; then
  opencode run "$(cat "$REPO_DIR/scripts/monitor_prompt.md")" 2>&1 | tee -a "$LOG_FILE"
else
  echo "opencode 未安装，退化为脚本监控" | tee -a "$LOG_FILE"
  bash "$REPO_DIR/scripts/monitor_workflows.sh" 2>&1 | tee -a "$LOG_FILE"
fi
