import os
import schedule
import time
import logging
from run_report import main as run_report
from close_report import main as run_close_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday"]


def morning_job():
    logging.info("【07:00】朝の予測レポート開始...")
    try:
        run_report()
        logging.info("朝の予測レポート完了")
    except Exception as e:
        logging.error(f"朝レポートエラー: {e}")


def close_job():
    logging.info("【15:30】終了レポート開始...")
    try:
        run_close_report()
        logging.info("終了レポート完了")
    except Exception as e:
        logging.error(f"終了レポートエラー: {e}")


for day in WEEKDAYS:
    getattr(schedule.every(), day).at("07:00").do(morning_job)
    getattr(schedule.every(), day).at("15:30").do(close_job)

if __name__ == "__main__":
    logging.info("スケジューラー起動")
    logging.info("  平日 07:00 → 朝の予測レポート")
    logging.info("  平日 15:30 → 市場終了レポート")
    logging.info("Ctrl+C で停止")
    while True:
        schedule.run_pending()
        time.sleep(30)
