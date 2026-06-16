"""
iTero (Align Technology) の通知メールを Gmail IMAP で取得し、
DynamoDB の prescriptions テーブルに指示書として登録する。
"""
import imaplib
import email
import os
import re
import logging
from datetime import datetime, timezone, timedelta, date as date_type
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
import pytz

from bs4 import BeautifulSoup

_JST = pytz.timezone("Asia/Tokyo")
log = logging.getLogger(__name__)

ITERO_FROM = "notifications-myiTero@aligntech.com"
ITERO_LOOKBACK_DAYS = 30  # 安定後は7に変更可

# iTero 英語医院名 → 日本語 sender_name マッピング
# 新しい医院が増えたらここに追加する
ITERO_CLINIC_NAME_MAP = {
    "Ichikawa Dental Clinic":           "いちかわ歯科",
    "Sakuragicho Hiro Dental Clinic":   "桜木町ヒロ歯科クリニック",
}


def _decode_subject(raw):
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return raw or ""


def parse_itero_email(msg):
    """
    iTero 通知メールから指示書フィールドを抽出して dict を返す。失敗時は None。
    """
    subject = _decode_subject(msg.get("Subject", ""))

    # 件名からオーダー番号: "オーダー番号305160181"
    order_id = ""
    m = re.search(r'オーダー番号\s*(\d+)', subject)
    if m:
        order_id = m.group(1)

    # メール受信日時
    email_date_str = ""
    try:
        dt = parsedate_to_datetime(msg.get("Date", ""))
        email_date_str = dt.astimezone(_JST).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass

    # HTML 本文取得
    html_body = text_body = ""
    for part in msg.walk():
        ct = part.get_content_type()
        charset = part.get_content_charset() or "utf-8"
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        decoded = payload.decode(charset, errors="replace")
        if ct == "text/html":
            html_body = decoded
        elif ct == "text/plain":
            text_body = decoded

    body = html_body or text_body
    if not body:
        return None

    soup = BeautifulSoup(body, "html.parser")
    text = soup.get_text(separator=" ")

    # 医院名: "新しい症例が{Clinic Name}から現在の症例に入りました"
    clinic_en = ""
    m = re.search(r'新しい症例が(.+?)から現在の症例に', text)
    if m:
        clinic_en = m.group(1).strip()

    # 本文からもオーダー番号を補完
    if not order_id:
        m = re.search(r'(\d{6,})\s*が追加されました', text)
        if m:
            order_id = m.group(1)

    # 英語医院名を日本語に変換
    clinic_jp = ITERO_CLINIC_NAME_MAP.get(clinic_en, "")

    log.debug("iTero parse: order=%s clinic_en=[%s] clinic_jp=[%s]",
              order_id, clinic_en, clinic_jp)

    return {
        "itero_order_id": order_id,
        "clinic_en":      clinic_en,
        "clinic_jp":      clinic_jp,
        "email_date":     email_date_str,
    }


def fetch_itero_emails():
    """
    過去 ITERO_LOOKBACK_DAYS 日分の iTero 通知メールを取得して返す。
    """
    gmail_user = os.getenv("GMAIL_USER", "")
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD", "").replace("-", "").replace(" ", "")
    if not gmail_user or not gmail_pass or "xxxx" in gmail_pass:
        log.warning("GMAIL_APP_PASSWORD が未設定のため iTero インポートをスキップ")
        return []

    messages = []
    try:
        imap = imaplib.IMAP4_SSL("imap.gmail.com")
        imap.login(gmail_user, gmail_pass)
        imap.select("INBOX")

        since_date = (date_type.today() - timedelta(days=ITERO_LOOKBACK_DAYS)).strftime("%d-%b-%Y")
        log.info("iTero メール検索範囲: SINCE %s", since_date)

        status, data = imap.search(None, f'FROM "{ITERO_FROM}" SINCE {since_date}')
        if status == "OK" and data[0]:
            nums = data[0].split()
            log.info("iTero メール %d 件を取得", len(nums))
            for num in nums:
                _, msg_data = imap.fetch(num, "(RFC822)")
                msg = email.message_from_bytes(msg_data[0][1])
                subject = _decode_subject(msg.get("Subject", ""))
                # 新規症例通知のみ（他の通知は除外）
                if "新しい症例" not in subject:
                    log.debug("スキップ（対象外件名）: %s", subject)
                    continue
                messages.append(msg)

        imap.logout()
    except Exception as e:
        log.error("Gmail IMAP 接続エラー (iTero): %s", e)

    return messages


def import_itero_emails(app):
    """
    Flask app コンテキスト内で呼び出す。
    戻り値: (取得件数, 登録件数, スキップ件数)
    """
    from utils.common_utils import get_next_sequence_number
    from boto3.dynamodb.conditions import Attr

    messages = fetch_itero_emails()
    found = len(messages)
    if not found:
        return 0, 0, 0

    with app.app_context():
        prescriptions_table = app.config["PRESCRIPTIONS_TABLE"]
        users_table = app.config["HOERO_USERS_TABLE"]
        imported = 0
        skipped = 0
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        # sender_name → user_id キャッシュ構築
        sender_to_user = {}
        try:
            resp = users_table.scan(ProjectionExpression="user_id, sender_name")
            for u in resp.get("Items", []):
                sname = u.get("sender_name", "").strip()
                if sname:
                    sender_to_user[sname] = u["user_id"]
        except Exception as e:
            log.warning("ユーザーテーブル読み込みエラー: %s", e)

        for msg in messages:
            data = parse_itero_email(msg)
            if not data or not data["itero_order_id"]:
                skipped += 1
                continue

            # 重複チェック
            resp = prescriptions_table.scan(
                FilterExpression=Attr("itero_order_id").eq(data["itero_order_id"]),
                Select="COUNT",
            )
            if resp.get("Count", 0) > 0:
                log.info("iTero オーダー %s は登録済みのためスキップ", data["itero_order_id"])
                skipped += 1
                continue

            # 医院名でユーザー紐づけ
            matched_user_id = sender_to_user.get(data["clinic_jp"], "itero")
            log.info("iTero 医院=[%s]→[%s] user_id=%s",
                     data["clinic_en"], data["clinic_jp"], matched_user_id)

            session_id, _ = get_next_sequence_number()
            id_str = f"{session_id:05d}"

            item = {
                "prescription_id":   id_str,
                "user_id":           matched_user_id,
                "business_name":     data["clinic_jp"] or data["clinic_en"],
                "user_name":         "",
                "patient_name":      data["itero_order_id"],
                "chart_number":      "",
                "appointment_date":  "",
                "appointment_hour":  "",
                "project_type":      "",
                "crown_type":        "",
                "shade":             "",
                "teeth":             [],
                "teeth_abutment":    [],
                "teeth_missing":     [],
                "teeth_fabrication": [],
                "message":           f"[iTero オーダー番号: {data['itero_order_id']}]",
                "s3_keys":           [],
                "image_keys":        [],
                "status":            "受付中",
                "source":            "itero",
                "itero_order_id":    data["itero_order_id"],
                "created_at":        data["email_date"] or now_str,
                "updated_at":        now_str,
            }

            prescriptions_table.put_item(Item=item)
            log.info("iTero 指示書を登録: No.%s オーダー=%s", id_str, data["itero_order_id"])
            imported += 1

    return found, imported, skipped
