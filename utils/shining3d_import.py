"""
Shining 3D の通知メールを Gmail IMAP で取得し、
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

SHINING3D_FROM = "service@mq.shining3d.com"
SHINING3D_SUBJECT_KEYWORD = "新しい注文をしました"
SHINING3D_LOOKBACK_DAYS = 30


def _decode_subject(raw):
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return raw or ""


def parse_shining3d_email(msg):
    """
    Shining 3D 通知メールから指示書フィールドを抽出して dict を返す。失敗時は None。
    """
    subject = _decode_subject(msg.get("Subject", ""))

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
    lines = [l.strip() for l in soup.get_text(separator="|").split("|") if l.strip()]

    def find_val(keyword):
        """keyword を含む行の次の値を返す"""
        for i, l in enumerate(lines):
            if keyword in l:
                # 同じ行に値が含まれる場合（"ソース: 藤田歯科医院" など）
                after = l.split(":", 1)[-1].strip() if ":" in l else ""
                if after:
                    return after
                # 次の行に値がある場合
                if i + 1 < len(lines):
                    return lines[i + 1]
        return ""

    business_name = find_val("ソース")
    patient_raw   = find_val("患者")

    # 患者フィールド: "2317 たかはしえつこ" → chart_number + patient_name
    chart_number = ""
    patient_name = ""
    if patient_raw:
        parts = patient_raw.split(None, 1)
        if len(parts) == 2 and parts[0].isdigit():
            chart_number = parts[0]
            patient_name = parts[1]
        else:
            patient_name = patient_raw

    # ケースIDはカルテ番号＋医院名で一意化（カルテ番号は医院内でのみ一意の可能性があるため）
    case_id = f"{business_name}_{chart_number}" if chart_number else ""

    log.debug("Shining3D parse: case_id=%s biz=[%s] chart=%s patient=[%s]",
              case_id, business_name, chart_number, patient_name)

    return {
        "shining3d_case_id": case_id,
        "business_name":     business_name,
        "chart_number":      chart_number,
        "patient_name":      patient_name,
        "email_date":        email_date_str,
    }


def fetch_shining3d_emails():
    gmail_user = os.getenv("GMAIL_USER", "")
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD", "").replace("-", "").replace(" ", "")
    if not gmail_user or not gmail_pass or "xxxx" in gmail_pass:
        log.warning("GMAIL_APP_PASSWORD が未設定のため Shining3D インポートをスキップ")
        return []

    messages = []
    try:
        imap = imaplib.IMAP4_SSL("imap.gmail.com")
        imap.login(gmail_user, gmail_pass)
        imap.select("INBOX")

        since_date = (date_type.today() - timedelta(days=SHINING3D_LOOKBACK_DAYS)).strftime("%d-%b-%Y")
        log.info("Shining3D メール検索範囲: SINCE %s", since_date)

        status, data = imap.search(None, f'FROM "{SHINING3D_FROM}" SINCE {since_date}')
        if status == "OK" and data[0]:
            nums = data[0].split()
            log.info("Shining3D メール %d 件を取得", len(nums))
            for num in nums:
                _, msg_data = imap.fetch(num, "(RFC822)")
                msg = email.message_from_bytes(msg_data[0][1])
                subject = _decode_subject(msg.get("Subject", ""))
                if SHINING3D_SUBJECT_KEYWORD not in subject:
                    log.debug("スキップ（対象外件名）: %s", subject)
                    continue
                messages.append(msg)

        imap.logout()
    except Exception as e:
        log.error("Gmail IMAP 接続エラー (Shining3D): %s", e)

    return messages


def import_shining3d_emails(app):
    """
    Flask app コンテキスト内で呼び出す。
    戻り値: (取得件数, 登録件数, スキップ件数)
    """
    from utils.common_utils import get_next_sequence_number

    messages = fetch_shining3d_emails()
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
            data = parse_shining3d_email(msg)
            if not data or not data["business_name"]:
                skipped += 1
                continue

            # 重複チェック（GSI クエリ）
            if data["shining3d_case_id"]:
                resp = prescriptions_table.query(
                    IndexName="shining3d_case_id-index",
                    KeyConditionExpression="shining3d_case_id = :v",
                    ExpressionAttributeValues={":v": data["shining3d_case_id"]},
                    Select="COUNT",
                )
                if resp.get("Count", 0) > 0:
                    log.info("Shining3D ケース %s は登録済みのためスキップ", data["shining3d_case_id"])
                    skipped += 1
                    continue

            # 医院名でユーザー紐づけ
            matched_user_id = sender_to_user.get(data["business_name"].strip(), "shining3d")
            log.info("Shining3D 医院=[%s] user_id=%s", data["business_name"], matched_user_id)

            session_id, _ = get_next_sequence_number()
            id_str = f"{session_id:05d}"

            item = {
                "prescription_id":   id_str,
                "user_id":           matched_user_id,
                "business_name":     data["business_name"],
                "user_name":         "",
                "patient_name":      data["patient_name"],
                "patient_name_kana": "",
                "chart_number":      data["chart_number"],
                "appointment_date":  "",
                "appointment_hour":  "",
                "project_type":      "",
                "crown_type":        "",
                "shade":             "",
                "teeth":             [],
                "teeth_abutment":    [],
                "teeth_missing":     [],
                "teeth_fabrication": [],
                "message":           "",
                "s3_keys":           [],
                "image_keys":        [],
                "status":            "受付中",
                "source":            "shining3d",
                "created_at":        data["email_date"] or now_str,
                "updated_at":        now_str,
            }
            if data["shining3d_case_id"]:
                item["shining3d_case_id"] = data["shining3d_case_id"]

            prescriptions_table.put_item(Item=item)
            log.info("Shining3D 指示書を登録: No.%s chart=%s", id_str, data["chart_number"])
            imported += 1

    return found, imported, skipped
