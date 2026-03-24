import boto3
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash

# DynamoDB設定
dynamodb = boto3.resource('dynamodb', region_name='ap-northeast-1')
table = dynamodb.Table('hoero-users')

now = datetime.now(timezone.utc).isoformat()

clinic_user = {
    "user_id":      "fujita@test.com",
    "email":        "fujita@test.com",
    "display_name": "藤田歯科医院",
    "sender_name":  "藤田歯科医院",
    "full_name":    "藤田 融",
    "phone":        "0489708000",
    "postal_code":  "3430025",
    "prefecture":   "埼玉県",
    "address":      "越谷市大沢3-6-1",
    "building":     "パルテきたこし1F",
    "password_hash": generate_password_hash("00000000"),
    "administrator": 0,
    "clinic_id":    "D001",
    "dentists": [
        "藤田 融",
        "勝又 信明",
        "関根 誠",
        "小林 和磨",
        "近藤 健彦",
        "藤田 皇子",
    ],
    "created_at":   now,
    "updated_at":   now,
}

table.put_item(Item=clinic_user)
print(f"✅ アカウントを登録しました: {clinic_user['email']} (clinic_id: {clinic_user['clinic_id']})")
print(f"   所属歯科医師: {', '.join(clinic_user['dentists'])}")
