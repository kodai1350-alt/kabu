"""
Cloud Run HTTP サーバー
Cloud Scheduler から POST リクエストを受けて各レポートを実行する
"""
import os
import threading
import subprocess
from flask import Flask, request, jsonify

app = Flask(__name__)

ALLOWED_TOKEN = os.getenv("CLOUD_SCHEDULER_TOKEN", "")


def _auth_ok() -> bool:
    """Cloud Scheduler からのリクエストか確認（簡易トークン認証）"""
    if not ALLOWED_TOKEN:
        return True  # トークン未設定時はスキップ（開発用）
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    return token == ALLOWED_TOKEN


def _run_async(cmd: list[str]) -> None:
    """バックグラウンドでスクリプトを実行（タイムアウト対策）"""
    subprocess.run(cmd, timeout=540)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/morning", methods=["POST"])
def morning():
    if not _auth_ok():
        return jsonify({"error": "unauthorized"}), 401
    t = threading.Thread(target=_run_async, args=(["python", "run_report.py"],))
    t.start()
    return jsonify({"status": "started", "job": "morning"}), 202


@app.route("/morning-close", methods=["POST"])
def morning_close():
    if not _auth_ok():
        return jsonify({"error": "unauthorized"}), 401
    t = threading.Thread(target=_run_async, args=(["python", "close_report.py", "morning-close"],))
    t.start()
    return jsonify({"status": "started", "job": "morning-close"}), 202


@app.route("/midday", methods=["POST"])
def midday():
    if not _auth_ok():
        return jsonify({"error": "unauthorized"}), 401
    t = threading.Thread(target=_run_async, args=(["python", "midday_report.py"],))
    t.start()
    return jsonify({"status": "started", "job": "midday"}), 202


@app.route("/close", methods=["POST"])
def close():
    if not _auth_ok():
        return jsonify({"error": "unauthorized"}), 401
    t = threading.Thread(target=_run_async, args=(["python", "close_report.py"],))
    t.start()
    return jsonify({"status": "started", "job": "close"}), 202


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
