import os
import schedule
import time
import logging
import subprocess
import sys
from run_report import main as run_report
from midday_report import main as run_midday

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday"]


def morning_job():
    logging.info("【07:00】朝レポート開始...")
    try:
        run_report()
        logging.info("朝レポート完了")
    except Exception as e:
        logging.error(f"朝レポートエラー: {e}")


def morning_close_job():
    logging.info("【11:30】前場終了レポート開始...")
    try:
        subprocess.run([sys.executable, "close_report.py", "morning-close"], check=True)
        logging.info("前場終了レポート完了")
    except Exception as e:
        logging.error(f"前場終了レポートエラー: {e}")


def midday_job():
    logging.info("【12:00】昼レポート開始...")
    try:
        run_midday()
        logging.info("昼レポート完了")
    except Exception as e:
        logging.error(f"昼レポートエラー: {e}")


def close_job():
    logging.info("【15:30】後場終了レポート開始...")
    try:
        subprocess.run([sys.executable, "close_report.py"], check=True)
        logging.info("後場終了レポート完了")
    except Exception as e:
        logging.error(f"後場終了レポートエラー: {e}")


for day in WEEKDAYS:
    getattr(schedule.every(), day).at("07:00").do(morning_job)
    getattr(schedule.every(), day).at("11:30").do(morning_close_job)
    getattr(schedule.every(), day).at("12:00").do(midday_job)
    getattr(schedule.every(), day).at("15:30").do(close_job)

if __name__ == "__main__":
    logging.info("スケジューラー起動")
    logging.info("  平日 07:00 → 朝レポート（Tavily/Exa/Groq/yfinance）")
    logging.info("  平日 11:30 → 前場終了レポート（yfinanceのみ）")
    logging.info("  平日 12:00 → 昼レポート（DDG/Groq/yfinance）")
    logging.info("  平日 15:30 → 後場終了レポート（yfinance/Groq+予測分析）")
    logging.info("Ctrl+C で停止")
    while True:
        schedule.run_pending()
        time.sleep(30)
