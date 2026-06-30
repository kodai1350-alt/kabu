#!/bin/bash
# GCP セットアップスクリプト（初回のみ実行）
# 使い方: bash setup_gcp.sh
set -e

# ── 設定（ここを変更）────────────────────────────────────────────
PROJECT_ID="kabu-report-$(date +%s | tail -c 5)"  # 例: kabu-report-12345
REGION="asia-northeast1"       # 東京
IMAGE="gcr.io/${PROJECT_ID}/kabu-report:latest"
BUDGET_AMOUNT="1"              # 上限 $1 USD
ALERT_EMAIL="your-email@gmail.com"  # ← あなたのGmailに変更
# ─────────────────────────────────────────────────────────────────

echo "=== GCPプロジェクト作成 ==="
gcloud projects create ${PROJECT_ID} --name="株レポート"
gcloud config set project ${PROJECT_ID}

echo "=== 課金アカウントをリンク（手動で確認が必要）==="
echo "  https://console.cloud.google.com/billing/projects を開いて"
echo "  ${PROJECT_ID} に課金アカウントをリンクしてください"
echo "  完了したら Enter を押してください"
read -r

echo "=== API 有効化 ==="
gcloud services enable \
  run.googleapis.com \
  cloudscheduler.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  cloudfunctions.googleapis.com \
  pubsub.googleapis.com \
  billingbudgets.googleapis.com \
  secretmanager.googleapis.com

echo "=== Secret Manager にシークレット登録 ==="
echo "各シークレットを入力してください（入力はターミナルに表示されません）"

for SECRET in DISCORD_WEBHOOK_URL GROQ_API_KEY TAVILY_API_KEY EXA_API_KEY ACCOUNT_BALANCE; do
  echo -n "${SECRET}: "
  read -rs VALUE
  echo
  echo -n "${VALUE}" | gcloud secrets create ${SECRET} --data-file=- 2>/dev/null \
    || echo -n "${VALUE}" | gcloud secrets versions add ${SECRET} --data-file=-
done

echo "=== Docker イメージをビルド & プッシュ ==="
gcloud auth configure-docker gcr.io
gcloud builds submit --tag ${IMAGE} .

echo "=== Cloud Run デプロイ ==="
# サービスアカウント作成
SA_NAME="kabu-runner"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
gcloud iam service-accounts create ${SA_NAME} --display-name="株レポート実行"

# Secret Manager アクセス権付与
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/secretmanager.secretAccessor"

# Cloud Run デプロイ
SECRET_ENV="DISCORD_WEBHOOK_URL=projects/${PROJECT_ID}/secrets/DISCORD_WEBHOOK_URL/versions/latest"
SECRET_ENV="${SECRET_ENV},GROQ_API_KEY=projects/${PROJECT_ID}/secrets/GROQ_API_KEY/versions/latest"
SECRET_ENV="${SECRET_ENV},TAVILY_API_KEY=projects/${PROJECT_ID}/secrets/TAVILY_API_KEY/versions/latest"
SECRET_ENV="${SECRET_ENV},EXA_API_KEY=projects/${PROJECT_ID}/secrets/EXA_API_KEY/versions/latest"
SECRET_ENV="${SECRET_ENV},ACCOUNT_BALANCE=projects/${PROJECT_ID}/secrets/ACCOUNT_BALANCE/versions/latest"

gcloud run deploy kabu-report \
  --image=${IMAGE} \
  --region=${REGION} \
  --platform=managed \
  --no-allow-unauthenticated \
  --service-account=${SA_EMAIL} \
  --update-secrets=${SECRET_ENV} \
  --memory=512Mi \
  --cpu=1 \
  --timeout=600 \
  --min-instances=0 \
  --max-instances=1

SERVICE_URL=$(gcloud run services describe kabu-report --region=${REGION} --format="value(status.url)")
echo "Cloud Run URL: ${SERVICE_URL}"

echo "=== Cloud Scheduler 設定（JST）==="
# Scheduler が Cloud Run を叩くための権限
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/run.invoker"

SCHEDULER_SA="--oidc-service-account-email=${SA_EMAIL} --oidc-token-audience=${SERVICE_URL}"

gcloud scheduler jobs create http kabu-morning \
  --location=${REGION} \
  --schedule="0 7 * * 1-5" \
  --time-zone="Asia/Tokyo" \
  --uri="${SERVICE_URL}/morning" \
  --http-method=POST \
  ${SCHEDULER_SA}

gcloud scheduler jobs create http kabu-morning-close \
  --location=${REGION} \
  --schedule="30 11 * * 1-5" \
  --time-zone="Asia/Tokyo" \
  --uri="${SERVICE_URL}/morning-close" \
  --http-method=POST \
  ${SCHEDULER_SA}

gcloud scheduler jobs create http kabu-midday \
  --location=${REGION} \
  --schedule="0 12 * * 1-5" \
  --time-zone="Asia/Tokyo" \
  --uri="${SERVICE_URL}/midday" \
  --http-method=POST \
  ${SCHEDULER_SA}

gcloud scheduler jobs create http kabu-close \
  --location=${REGION} \
  --schedule="30 15 * * 1-5" \
  --time-zone="Asia/Tokyo" \
  --uri="${SERVICE_URL}/close" \
  --http-method=POST \
  ${SCHEDULER_SA}

echo "=== 予算アラート設定 ==="
# Pub/Sub トピック作成
gcloud pubsub topics create billing-alerts

# 予算 Cloud Function デプロイ
gcloud functions deploy budget-guard \
  --gen2 \
  --region=${REGION} \
  --runtime=python312 \
  --source=./budget_guard \
  --entry-point=budget_alert \
  --trigger-topic=billing-alerts \
  --set-env-vars="GCP_PROJECT_ID=${PROJECT_ID},GCP_LOCATION=${REGION}" \
  --update-secrets="DISCORD_WEBHOOK_URL=projects/${PROJECT_ID}/secrets/DISCORD_WEBHOOK_URL/versions/latest" \
  --service-account=${SA_EMAIL}

# Cloud Scheduler 停止権限を付与
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/cloudscheduler.admin"

# 予算作成（billing API経由 - コンソールでも設定可能）
BILLING_ACCOUNT=$(gcloud billing projects describe ${PROJECT_ID} --format="value(billingAccountName)" | sed 's/billingAccounts\///')

gcloud billing budgets create \
  --billing-account=${BILLING_ACCOUNT} \
  --display-name="株レポート上限" \
  --budget-amount="${BUDGET_AMOUNT}USD" \
  --threshold-rule=percent=0.8,basis=CURRENT_SPEND \
  --threshold-rule=percent=1.0,basis=CURRENT_SPEND \
  --notifications-rule-pubsub-topic="projects/${PROJECT_ID}/topics/billing-alerts" \
  --notifications-rule-schema-version=1.0

echo ""
echo "======================================"
echo "✅ セットアップ完了！"
echo "======================================"
echo "Cloud Run URL: ${SERVICE_URL}"
echo "予算上限: \$${BUDGET_AMOUNT} USD"
echo "  80%で警告 → 100%で全ジョブ自動停止"
echo ""
echo "スケジュール（JST）:"
echo "  朝レポート      : 平日 07:00"
echo "  前場終了レポート: 平日 11:30"
echo "  昼レポート      : 平日 12:00"
echo "  終了レポート    : 平日 15:30"
