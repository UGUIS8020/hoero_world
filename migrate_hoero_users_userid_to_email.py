# migrate_hoero_users_userid_to_email.py
import os
import boto3
from decimal import Decimal
from dotenv import load_dotenv
from pprint import pprint

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "ap-northeast-1")
TABLE_NAME = "hoero-users"

# さっき scan で出てきた UUID をここにコピペ
OLD_USER_ID = "7485d622-d25c-4416-a7f9-5324d597a2d9"

def convert_decimals(obj):
    """Decimal を float / int に変換（print しやすくするだけ）"""
    if isinstance(obj, list):
        return [convert_decimals(o) for o in obj]
    if isinstance(obj, dict):
        return {k: convert_decimals(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        # 今回は 0/1 だけなので int に
        return int(obj)
    return obj

def main():
    dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    table = dynamodb.Table(TABLE_NAME)

    # 1) 旧ユーザーを取得（UUID 指定）
    res = table.get_item(Key={"user_id": OLD_USER_ID})
    item = res.get("Item")
    if not item:
        print("OLD_USER_ID のユーザーが見つかりません。")
        return

    print("=== old item ===")
    pprint(convert_decimals(item))

    # 2) email を新しい user_id にする
    new_user_id = item["email"]

    new_item = dict(item)
    new_item["user_id"] = new_user_id  # ここを email に変更

    # 3) 新しいレコードとして Put
    table.put_item(Item=new_item)
    print("\n=== new item (user_id = email) を作成しました ===")
    pprint(convert_decimals(new_item))

    # 4) 古い UUID レコードを消したい場合はコメントを外す
    # table.delete_item(Key={"user_id": OLD_USER_ID})
    # print("\n古い UUID レコードを削除しました。")

if __name__ == "__main__":
    main()
