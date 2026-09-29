#!/bin/bash
# 指定したPythonダウンロードスクリプトを、途中で落ちても「完了。」が出るまで自動的に再実行し続ける。
# 使い方: scripts/run_until_done.sh <ログファイル> <python引数...>
set -u

LOG_FILE="$1"
shift

cd "$(dirname "$0")/.."

while true; do
  python3 -u "$@" >> "$LOG_FILE" 2>&1
  if grep -q "^完了。" "$LOG_FILE"; then
    echo "[run_until_done] 完了を検知しました。終了します。" >> "$LOG_FILE"
    break
  fi
  echo "[run_until_done] $(date -u +%FT%TZ) プロセスが終了しました(完了していません)。5秒後に再実行します。" >> "$LOG_FILE"
  sleep 5
done
