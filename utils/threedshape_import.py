"""
3ds (OralScan Data) の通知メールを Gmail IMAP で取得し、
DynamoDB の prescriptions テーブルに指示書として登録する。
"""
import imaplib
import email
import os
import logging
from datetime import datetime, timezone, timedelta, date as date_type
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
import pytz

_JST = pytz.timezone("Asia/Tokyo")
log = logging.getLogger(__name__)

THREEDSHAPE_FROM = "support@oralscandata.com"
THREEDSHAPE_SUBJECT_KEYWORD = "New order for"
THREEDSHAPE_LOOKBACK_DAYS = 30


def _decode_subject(raw):
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return raw or ""


def parse_threedshape_email(msg):
    """
    3ds 通知メールから指示書フィールドを抽出して dict を返す。失敗時は None。
    """
    subject = _decode_subject(msg.get("Subject", ""))

    # 件名から医院名を抽出: "New order for 東浦和" → "東浦和"
    clinic_name = ""
    if THREEDSHAPE_SUBJECT_KEYWORD in subject:
        clinic_name = subject.split(THREEDSHAPE_SUBJECT_KEYWORD, 1)[-1].strip()

    if not clinic_name:
        return None

    # メール受信日時
    email_date_str = ""
    try:
        dt = parsedate_to_datetime(msg.get("Date", ""))
        email_date_str = dt.astimezone(_JST).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass

    # Message-ID（重複チェック用）
    message_id = msg.get("Message-ID", "").strip()

    return {
        "clinic_name":  clinic_name,
        "email_date":   email_date_str,
        "message_id":   message_id,
    }


def fetch_threedshape_emails():
    gmail_user = os.getenv("GMAIL_USER", "")
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD", "").replace("-", "").replace(" ", "")
    if not gmail_user or not gmail_pass or "xxxx" in gmail_pass:
        log.warning("GMAIL_APP_PASSWORD が未設定のため 3ds インポートをスキップ")
        return []

    messages = []
    try:
        imap = imaplib.IMAP4_SSL("imap.gmail.com")
        imap.login(gmail_user, gmail_pass)
        imap.select("INBOX")

        since_date = (date_type.today() - timedelta(days=THREEDSHAPE_LOOKBACK_DAYS)).strftime("%d-%b-%Y")
        log.info("3ds メール検索範囲: SINCE %s", since_date)

        status, data = imap.search(None, f'FROM "{THREEDSHAPE_FROM}" SINCE {since_date}')
        if status == "OK" and data[0]:
            nums = data[0].split()
            log.info("3ds メール %d 件を取得", len(nums))
            for num in nums:
                _, msg_data = imap.fetch(num, "(RFC822)")
                msg = email.message_from_bytes(msg_data[0][1])
                subject = _decode_subject(msg.get("Subject", ""))
                if THREEDSHAPE_SUBJECT_KEYWORD not in subject:
                    log.debug("スキップ（対象外件名）: %s", subject)
                    continue
                messages.append(msg)

        imap.logout()
    except Exception as e:
        log.error("Gmail IMAP 接続エラー (3ds): %s", e)

    return messages


def import_threedshape_emails(app):
    """
    Flask app コンテキスト内で呼び出す。
    戻り値: (取得件数, 登録件数, スキップ件数)
    """
    from utils.common_utils import get_next_sequence_number

    messages = fetch_threedshape_emails()
    found = len(messages)
    if not found:
        return 0, 0, 0

    with app.app_context():
        prescriptions_table = app.config["PRESCRIPTIONS_TABLE"]
        users_table = app.config["HOERO_USERS_TABLE"]
        imported = 0
        skipped = 0
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        # threedshape_clinic_name → user_id キャッシュ構築
        clinic_to_user = {}
        try:
            resp = users_table.scan(ProjectionExpression="user_id, sender_name, threedshape_clinic_name")
            for u in resp.get("Items", []):
                cname = u.get("threedshape_clinic_name", "").strip()
                if cname:
                    clinic_to_user[cname] = u["user_id"]
        except Exception as e:
            log.warning("ユーザーテーブル読み込みエラー: %s", e)

        for msg in messages:
            data = parse_threedshape_email(msg)
            if not data or not data["clinic_name"]:
                skipped += 1
                continue

            # 重複チェック（Message-IDでスキャン）
            if data["message_id"]:
                from boto3.dynamodb.conditions import Attr
                resp = prescriptions_table.scan(
                    FilterExpression=Attr("threedshape_message_id").eq(data["message_id"]),
                    Select="COUNT",
                )
                if resp.get("Count", 0) > 0:
                    log.info("3ds メッセージ %s は登録済みのためスキップ", data["message_id"])
                    skipped += 1
                    continue

            matched_user_id = clinic_to_user.get(data["clinic_name"].strip(), "3ds")
            matched_business_name = data["clinic_name"]
            log.info("3ds 医院=[%s] user_id=%s", data["clinic_name"], matched_user_id)

            session_id, _ = get_next_sequence_number()
            id_str = f"{session_id:05d}"

            item = {
                "prescription_id":        id_str,
                "user_id":                matched_user_id,
                "business_name":          matched_business_name,
                "user_name":              "",
                "patient_name":           "",
                "patient_name_kana":      "",
                "chart_number":           "",
                "appointment_date":       "",
                "appointment_hour":       "",
                "project_type":           "",
                "crown_type":             "",
                "shade":                  "",
                "teeth":                  [],
                "teeth_abutment":         [],
                "teeth_missing":          [],
                "teeth_fabrication":      [],
                "message":                "3ds経由の注文。詳細はOralScan Dataでご確認ください。",
                "s3_keys":                [],
                "image_keys":             [],
                "status":                 "受付中",
                "source":                 "3ds",
                "created_at":             data["email_date"] or now_str,
                "updated_at":             now_str,
            }
            if data["message_id"]:
                item["threedshape_message_id"] = data["message_id"]

            prescriptions_table.put_item(Item=item)
            log.info("3ds 指示書を登録: No.%s clinic=%s", id_str, data["clinic_name"])
            imported += 1

    return found, imported, skipped
