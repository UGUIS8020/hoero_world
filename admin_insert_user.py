import boto3
import uuid
from datetime import datetime
from werkzeug.security import generate_password_hash

# DynamoDBテーブル指定
dynamodb = boto3.resource('dynamodb', region_name='ap-northeast-1')
table = dynamodb.Table('hoero-users')

# ISO形式のタイムスタンプ
now = datetime.utcnow().isoformat() + "Z"

# 管理者アカウントのデータ
admin_user = {
    "user_id": str(uuid.uuid4()),
    "display_name": "UGUIS(管理者)",
    "sender_name": "渋谷歯科技工所",
    "full_name": "渋谷正彦",
    "phone": "07066330363",
    "email": "shibuya8020@gmail.com",
    "password_hash": generate_password_hash("giko8020@Z"),  # 実運用ではより強力なパスワード推奨
    "administrator": 1,
    "postal_code": "3430845",
    "prefecture": "埼玉県",
    "address": "越谷市南越谷4-9-6",
    "building": "新越谷プラザビル203",
    "created_at": now,
    "updated_at": now
}

# 登録処理
table.put_item(Item=admin_user)

print("✅ 管理者アカウントを登録しました:", admin_user["email"])
