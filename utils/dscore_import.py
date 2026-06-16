"""
D-score (Dentsply Sirona) の通知メールを Gmail IMAP で取得し、
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

_JST = pytz.timezone("Asia/Tokyo")

from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

DSCORE_FROM = "order@dscore.com"
DSCORE_SUBJECT_KEYWORD = "DS Coreの新しい注文"
DSCORE_LOOKBACK_DAYS = 30  # 安定後は7に変更可


# ── 日付パース ────────────────────────────────────────────────────────────────
# 形式A: "2026年7月3日、17:00"（2026年以降の日本語形式）
_DATE_RE_JP = re.compile(r'(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日[、,]?\s*(\d{1,2}):\d{2}')
# 形式B: "03/03/2025"（2025年以前のDD/MM/YYYY形式）
_DATE_RE_EU = re.compile(r'(\d{1,2})/(\d{1,2})/(\d{4})')

def _parse_jp_date(text):
    m = _DATE_RE_JP.search(text)
    if m:
        y, mo, d, h = m.groups()
        return f"{y}-{int(mo):02d}-{int(d):02d}", str(int(h))
    m = _DATE_RE_EU.search(text)
    if m:
        d, mo, y = m.groups()
        return f"{y}-{int(mo):02d}-{int(d):02d}", ""
    return "", ""


# ── メール件名デコード ──────────────────────────────────────────────────────
def _decode_subject(raw):
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return raw or ""


# ── HTML メール本文からデータ抽出 ────────────────────────────────────────────
def parse_dscore_email(msg):
    """
    email.message.Message を受け取り指示書フィールドの dict を返す。失敗時は None。
    実際のメール構造（行単位）に合わせたパーサー。
    """
    subject = _decode_subject(msg.get("Subject", ""))

    # メール受信日時（Date ヘッダー → JST 変換）
    email_date_str = ""
    try:
        dt = parsedate_to_datetime(msg.get("Date", ""))
        email_date_str = dt.astimezone(_JST).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass

    # 件名から注文番号: "DS Coreの新しい注文5AABI3GR"
    order_id = ""
    m = re.search(r'注文\s*([A-Z0-9]{6,})', subject)
    if m:
        order_id = m.group(1)

    # HTML パート取得
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
    # "|" で区切ってリスト化し、空行除去
    lines = [l.strip() for l in soup.get_text(separator="|").split("|") if l.strip()]

    # 本文からも注文番号を補完
    if not order_id:
        for line in lines:
            m = re.search(r'注文番号\s*([A-Z0-9]{6,})', line)
            if m:
                order_id = m.group(1)
                break

    def next_val(keyword, skip=1):
        """lines の中で keyword の次の skip 番目の行を返す"""
        for i, l in enumerate(lines):
            if keyword in l:
                idx = i + skip
                while idx < len(lines):
                    val = lines[idx]
                    if val and val not in ('電話:', '·'):
                        return val
                    idx += 1
        return ""

    business_name     = next_val("送付人")
    delivery_raw      = next_val("ご希望納期")
    user_name         = next_val("担当者")

    appointment_date, appointment_hour = _parse_jp_date(delivery_raw)

    # ご注文の詳細：キーワード以降の行を収集
    project_type = ""
    teeth_str    = ""
    detail_start = None
    for i, l in enumerate(lines):
        if "ご注文の詳細" in l:
            detail_start = i + 1
            break
    if detail_start is not None:
        for line in lines[detail_start:detail_start + 5]:
            if "DS Core" in line or "弊社" in line or "©" in line:
                break
            # "ブリッジ — 13,12,21,22,11(FDI)" のような行
            if re.search(r'[—―–-]', line) and re.search(r'\d+', line):
                parts = re.split(r'[—―–]', line, maxsplit=1)
                project_type = parts[0].strip()
                teeth_str    = parts[1].strip() if len(parts) > 1 else ""
                break
            elif not project_type and line:
                project_type = line  # 「修復」「補綴」など

    # 歯番（FDI: 11–48）
    teeth = []
    if teeth_str:
        teeth = [int(n) for n in re.findall(r'\d+', teeth_str) if 11 <= int(n) <= 48]

    log.debug("D-score parse: order=%s biz=[%s] delivery_raw=[%s] date=%s hour=%s",
              order_id, business_name, delivery_raw, appointment_date, appointment_hour)

    return {
        "dscore_order_id":  order_id,
        "business_name":    business_name,
        "user_name":        user_name,
        "appointment_date": appointment_date,
        "appointment_hour": appointment_hour,
        "project_type":     project_type,
        "teeth":            teeth,
        "source":           "dscore",
        "email_date":       email_date_str,
    }


# ── Gmail IMAP でメール取得 ──────────────────────────────────────────────────
def fetch_dscore_emails():
    """
    未読の D-score 通知メールを取得して email.Message リストを返す。
    取得後は既読にする。
    """
    gmail_user = os.getenv("GMAIL_USER", "")
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD", "").replace("-", "").replace(" ", "")
    if not gmail_user or not gmail_pass or "xxxx" in gmail_pass:
        log.warning("GMAIL_APP_PASSWORD が未設定のため D-score インポートをスキップ")
        return []

    messages = []
    try:
        imap = imaplib.IMAP4_SSL("imap.gmail.com")
        imap.login(gmail_user, gmail_pass)
        imap.select("INBOX")

        # 過去 LOOKBACK_DAYS 日分のみ検索（IMAP SINCE で絞り込み）
        since_date = (date_type.today() - timedelta(days=DSCORE_LOOKBACK_DAYS)).strftime("%d-%b-%Y")
        log.info("D-score メール検索範囲: SINCE %s", since_date)
        status, data = imap.search(None, f'FROM "order@dscore.com" SINCE {since_date}')
        if status != "OK" or not data[0]:
            status, data = imap.search(None, f'SUBJECT "DS Core" SINCE {since_date}')

        if status == "OK" and data[0]:
            nums = data[0].split()
            log.info("D-score メール %d 件を検索結果として取得", len(nums))
            for num in nums:
                _, msg_data = imap.fetch(num, "(RFC822)")
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)
                # 日本語形式の新規注文メールのみ対象（英語・完了通知は除外）
                subject = _decode_subject(msg.get("Subject", ""))
                if "新しい注文" not in subject:
                    log.debug("スキップ（対象外件名）: %s", subject)
                    continue
                messages.append(msg)

        imap.logout()
    except Exception as e:
        log.error("Gmail IMAP 接続エラー: %s", e)

    return messages


# ── DynamoDB に保存 ────────────────────────────────────────────────────────
def import_dscore_emails(app):
    """
    Flask app コンテキスト内で呼び出す。
    新しい D-score メールを取得して指示書として登録する。
    戻り値: (取得件数, 登録件数, スキップ件数)
    """
    from utils.common_utils import get_next_sequence_number

    messages = fetch_dscore_emails()
    found = len(messages)
    log.info("D-score: %d 件のメールを取得", found)
    if not messages:
        return 0, 0, 0

    with app.app_context():
        prescriptions_table = app.config["PRESCRIPTIONS_TABLE"]
        users_table = app.config["HOERO_USERS_TABLE"]
        imported = 0
        skipped  = 0
        now_str  = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        # sender_name → user_id のキャッシュを事前構築
        sender_to_user = {}
        try:
            scan_resp = users_table.scan(ProjectionExpression="user_id, sender_name")
            for u in scan_resp.get("Items", []):
                sname = u.get("sender_name", "").strip()
                if sname:
                    sender_to_user[sname] = u["user_id"]
        except Exception as e:
            log.warning("ユーザーテーブル読み込みエラー: %s", e)

        for msg in messages:
            data = parse_dscore_email(msg)
            if not data:
                skipped += 1
                continue

            # 重複チェック（同じ注文番号がすでに存在するか）
            if data["dscore_order_id"]:
                resp = prescriptions_table.query(
                    IndexName="dscore_order_id-index",
                    KeyConditionExpression="dscore_order_id = :v",
                    ExpressionAttributeValues={":v": data["dscore_order_id"]},
                    Select="COUNT",
                )
                if resp.get("Count", 0) > 0:
                    log.info("D-score 注文 %s は登録済みのためスキップ", data["dscore_order_id"])
                    skipped += 1
                    continue

            # 医院名でユーザー紐づけ
            matched_user_id = sender_to_user.get(data["business_name"].strip(), "dscore")
            log.info("D-score 医院名=[%s] → user_id=%s", data["business_name"], matched_user_id)

            session_id, _ = get_next_sequence_number()
            id_str = f"{session_id:05d}"

            item = {
                "prescription_id":  id_str,
                "user_id":          matched_user_id,
                "business_name":    data["business_name"],
                "user_name":        data["user_name"],
                "patient_name":     data["dscore_order_id"],
                "chart_number":     "",
                "appointment_date": data["appointment_date"],
                "appointment_hour": data["appointment_hour"],
                "project_type":     data["project_type"],
                "crown_type":       "",
                "shade":            "",
                "teeth":            data["teeth"],
                "teeth_abutment":   [],
                "teeth_missing":    [],
                "teeth_fabrication": data["teeth"],
                "message":          f"[D-score 注文番号: {data['dscore_order_id']}]",
                "s3_keys":          [],
                "image_keys":       [],
                "status":           "受付中",
                "source":           "dscore",
                "created_at":       data["email_date"] or now_str,
                "updated_at":       now_str,
            }
            if data["dscore_order_id"]:
                item["dscore_order_id"] = data["dscore_order_id"]

            prescriptions_table.put_item(Item=item)
            log.info("D-score 指示書を登録: No.%s 注文番号=%s", id_str, data["dscore_order_id"])
            imported += 1

    return found, imported, skipped
