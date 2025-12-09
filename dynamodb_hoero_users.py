# view_hoero_users.py
import os
import boto3
from dotenv import load_dotenv
from pprint import pprint

# .env から AWS_REGION や認証情報を読む場合
load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "ap-northeast-1")
TABLE_NAME = "hoero-users"

def main():
    # DynamoDB リソース作成
    dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    table = dynamodb.Table(TABLE_NAME)

    print(f"=== Scan table: {TABLE_NAME} ===")

    # 全件取得（件数が多い場合は注意）
    items = []
    params = {}
    while True:
        response = table.scan(**params)
        items.extend(response.get("Items", []))

        # ページング（LastEvaluatedKey があれば続きあり）
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        params["ExclusiveStartKey"] = last_key

    print(f"Total items: {len(items)}")
    for i, item in enumerate(items, start=1):
        print(f"\n--- Item {i} ---")
        pprint(item)

if __name__ == "__main__":
    main()
