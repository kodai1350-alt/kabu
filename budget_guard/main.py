"""
Cloud Function: 予算超過アラートで Cloud Scheduler ジョブを自動停止する

トリガー: Google Cloud Billing Budget → Pub/Sub → この関数
動作:
  - 予算の80%超過 → Discordに警告送信
  - 予算の100%超過 → 全Schedulerジョブを一時停止 + Discord通知
"""
import base64
import json
import os
import requests
from google.cloud import scheduler_v1


PROJECT_ID = os.environ["GCP_PROJECT_ID"]
LOCATION   = os.environ.get("GCP_LOCATION", "asia-northeast1")
DISCORD_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

JOB_NAMES = [
    f"projects/{PROJECT_ID}/locations/{LOCATION}/jobs/kabu-morning",
    f"projects/{PROJECT_ID}/locations/{LOCATION}/jobs/kabu-morning-close",
    f"projects/{PROJECT_ID}/locations/{LOCATION}/jobs/kabu-midday",
    f"projects/{PROJECT_ID}/locations/{LOCATION}/jobs/kabu-close",
]


def _discord(msg: str) -> None:
    if DISCORD_URL:
        requests.post(DISCORD_URL, json={"content": msg}, timeout=10)


def budget_alert(event, context):
    """Pub/Sub から呼び出されるエントリーポイント"""
    data = json.loads(base64.b64decode(event["data"]).decode("utf-8"))

    budget_amount   = data.get("budgetAmount", 0)
    cost_amount     = data.get("costAmount", 0)
    currency        = data.get("currencyCode", "USD")
    threshold_pct   = (cost_amount / budget_amount * 100) if budget_amount > 0 else 0

    print(f"予算アラート: {cost_amount:.4f}/{budget_amount:.4f} {currency} ({threshold_pct:.1f}%)")

    if threshold_pct >= 100:
        # 予算100%超過 → 全ジョブ停止
        _pause_all_jobs()
        _discord(
            f"🚨 **GCPコスト上限到達！全スケジューラーを停止しました**\n"
            f"  使用額: {cost_amount:.4f} {currency} / 上限: {budget_amount:.4f} {currency}\n"
            f"  ジョブを再開するには GCP Console → Cloud Scheduler で手動で再開してください"
        )

    elif threshold_pct >= 80:
        # 80%超過 → 警告のみ
        remaining = budget_amount - cost_amount
        _discord(
            f"⚠️ **GCPコスト警告 ({threshold_pct:.0f}%)**\n"
            f"  使用額: {cost_amount:.4f} {currency} / 上限: {budget_amount:.4f} {currency}\n"
            f"  残り: {remaining:.4f} {currency}  このペースで続くと自動停止されます"
        )


def _pause_all_jobs() -> None:
    client = scheduler_v1.CloudSchedulerClient()
    for job_name in JOB_NAMES:
        try:
            client.pause_job(name=job_name)
            print(f"停止: {job_name}")
        except Exception as e:
            print(f"停止失敗 {job_name}: {e}")
