"""
メール定期取込スクリプト。Linux cron から毎時実行する。
  crontab: 0 * * * * /var/www/hoero_world/venv/bin/python /var/www/hoero_world/run_mail_import.py
"""
import sys
import os
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("/var/www/hoero_world/mail_import.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("mail_import")

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from app import flask_app

with flask_app.app_context():
    try:
        from utils.dscore_import import import_dscore_emails
        found, imported, skipped = import_dscore_emails(flask_app)
        log.info("D-score: %d件取得 / %d件登録 / %d件スキップ", found, imported, skipped)
    except Exception as e:
        log.error("D-score エラー: %s", e)

    try:
        from utils.itero_import import import_itero_emails
        found, imported, skipped = import_itero_emails(flask_app)
        log.info("iTero: %d件取得 / %d件登録 / %d件スキップ", found, imported, skipped)
    except Exception as e:
        log.error("iTero エラー: %s", e)

    try:
        from utils.shining3d_import import import_shining3d_emails
        found, imported, skipped = import_shining3d_emails(flask_app)
        log.info("Shining3D: %d件取得 / %d件登録 / %d件スキップ", found, imported, skipped)
    except Exception as e:
        log.error("Shining3D エラー: %s", e)

    try:
        from utils.threedshape_import import import_threedshape_emails
        found, imported, skipped = import_threedshape_emails(flask_app)
        log.info("3ds: %d件取得 / %d件登録 / %d件スキップ", found, imported, skipped)
    except Exception as e:
        log.error("3ds エラー: %s", e)
