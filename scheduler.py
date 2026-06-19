import os
import schedule
import time
import logging
from run_report import main as run_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def job():
    logging.info("予測レポート開始...")
    try:
        run_report()
        logging.info("予測レポート完了")
    except Exception as e:
        logging.error(f"エラー発生: {e}")


schedule.every().monday.at("07:00").do(job)
schedule.every().tuesday.at("07:00").do(job)
schedule.every().wednesday.at("07:00").do(job)
schedule.every().thursday.at("07:00").do(job)
schedule.every().friday.at("07:00").do(job)

if __name__ == "__main__":
    logging.info("スケジューラー起動（平日毎朝7:00に実行）")
    logging.info("Ctrl+C で停止")
    while True:
        schedule.run_pending()
        time.sleep(30)
