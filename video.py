# video.py
import os
import boto3
from boto3.dynamodb.conditions import Attr

TABLE_NAME = os.environ.get("DENTAL_TABLE_NAME", "dental-news")
AWS_REGION = os.environ.get("AWS_REGION", "ap-northeast-1")

# ★ ここでプロファイル名を指定（default か、普段使っている名前）
session = boto3.Session(profile_name=os.environ.get("AWS_PROFILE", "default"))
dynamodb = session.resource("dynamodb", region_name=AWS_REGION)
table = dynamodb.Table(TABLE_NAME)

print("TABLE_NAME =", TABLE_NAME)
print("AWS_REGION =", AWS_REGION)
print("PROFILE   =", session.profile_name)

resp = table.scan(
    FilterExpression=Attr("kind").contains("video")
)

items = resp.get("Items", [])
print("total hits:", len(items))

for it in items[:20]:
    print(
        "kind =", it.get("kind"),
        "| lang =", it.get("lang"),
        "| gsi1pk =", it.get("gsi1pk"),
        "| title =", (it.get("title") or "")[:40]
    )
