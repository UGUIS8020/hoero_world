import os
from dotenv import load_dotenv
import boto3

load_dotenv()  # ← これを追加（.env から環境変数を読み込む）

REGION = os.getenv("AWS_REGION", "ap-northeast-1")
profile = os.getenv("AWS_PROFILE")

if profile:
    session = boto3.Session(profile_name=profile, region_name=REGION)
else:
    session = boto3.Session(region_name=REGION)

dynamodb = session.resource("dynamodb")

def wait_table_active(client, table_name, timeout=300):
    """テーブルが ACTIVE になるまで待機"""
    client.get_waiter('table_exists').wait(TableName=table_name, WaiterConfig={"Delay": 2, "MaxAttempts": timeout // 2})
    # 念のため状態確認
    desc = client.describe_table(TableName=table_name)
    status = desc["Table"]["TableStatus"]
    print(f"[WAIT] Table {table_name} status = {status}")
    return desc

def wait_gsis_active(client, table_name, index_names, timeout=300):
    """指定のGSIがACTIVEになるまで待機"""
    deadline = time.time() + timeout
    index_names = set(index_names)
    while time.time() < deadline:
        desc = client.describe_table(TableName=table_name)
        gsis = {g["IndexName"]: g["IndexStatus"] for g in desc["Table"].get("GlobalSecondaryIndexes", [])}
        pending = [n for n in index_names if gsis.get(n) != "ACTIVE"]
        if not pending:
            print(f"[WAIT] GSIs ACTIVE on {table_name}: {sorted(index_names)}")
            return
        time.sleep(2)
    raise TimeoutError(f"GSI not ACTIVE within timeout on {table_name}: {pending}")

def ensure_table(dynamodb, spec: dict):
    client = dynamodb.meta.client
    name = spec["TableName"]

    def _wait_table_active():
        return wait_table_active(client, name)

    def _wait_gsis_active(index_names):
        return wait_gsis_active(client, name, index_names)

    try:
        desc = client.describe_table(TableName=name)
        print(f"[INFO] Table '{name}' already exists (status={desc['Table']['TableStatus']}).")
        existing_gsis = {g["IndexName"] for g in desc["Table"].get("GlobalSecondaryIndexes", [])}
    except client.exceptions.ResourceNotFoundException:
        create_args = {
            "TableName": name,
            "AttributeDefinitions": spec["AttributeDefinitions"],
            "KeySchema": spec["KeySchema"],
            "BillingMode": spec.get("BillingMode", "PAY_PER_REQUEST"),
        }
        if spec.get("GlobalSecondaryIndexes"):
            create_args["GlobalSecondaryIndexes"] = spec["GlobalSecondaryIndexes"]
        print(f"[CREATE] Creating table '{name}' ...")
        client.create_table(**create_args)
        desc = _wait_table_active()
        existing_gsis = {g["IndexName"] for g in desc["Table"].get("GlobalSecondaryIndexes", [])}

    desired_gsis = {g["IndexName"] for g in spec.get("GlobalSecondaryIndexes", [])}
    missing = [g for g in spec.get("GlobalSecondaryIndexes", []) if g["IndexName"] not in existing_gsis]

    if missing:
        # GSIキーに必要な AttributeDefinitions だけ整形
        type_by_name = {a["AttributeName"]: a["AttributeType"] for a in spec["AttributeDefinitions"]}
        needed_names = sorted({ks["AttributeName"] for g in missing for ks in g["KeySchema"]})
        attr_defs = [{"AttributeName": n, "AttributeType": type_by_name[n]} for n in needed_names]

        print(f"[UPDATE] Adding GSIs on '{name}': {[m['IndexName'] for m in missing]}")
        client.update_table(
            TableName=name,
            AttributeDefinitions=attr_defs,
            GlobalSecondaryIndexes=[{"Create": {
                "IndexName": g["IndexName"],
                "KeySchema": g["KeySchema"],
                "Projection": g["Projection"],
            }} for g in missing]
        )
        _wait_gsis_active([m["IndexName"] for m in missing])
    else:
        if desired_gsis:
            print(f"[INFO] All desired GSIs already present on '{name}': {sorted(desired_gsis)}")

    print(f"[OK] Table '{name}' is ready.")

def ensure_hoero_users(dynamodb):
    spec = {
        "TableName": "hoero-users",
        "AttributeDefinitions": [
            {"AttributeName": "user_id", "AttributeType": "S"},
            {"AttributeName": "email", "AttributeType": "S"},
            {"AttributeName": "display_name", "AttributeType": "S"},
        ],
        "KeySchema": [
            {"AttributeName": "user_id", "KeyType": "HASH"}
        ],
        "BillingMode": "PAY_PER_REQUEST",
        "GlobalSecondaryIndexes": [
            {
                "IndexName": "email-index",
                "KeySchema": [{"AttributeName": "email", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"}
            },
            {
                "IndexName": "display_name-index",
                "KeySchema": [{"AttributeName": "display_name", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"}
            }
        ]
    }
    ensure_table(dynamodb, spec)

def ensure_dental_news(dynamodb):
    spec = {
        "TableName": "dental-news",
        "AttributeDefinitions": [
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
            {"AttributeName": "gsi1pk", "AttributeType": "S"},
            {"AttributeName": "gsi1sk", "AttributeType": "S"},
        ],
        "KeySchema": [
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"}
        ],
        "BillingMode": "PAY_PER_REQUEST",
        "GlobalSecondaryIndexes": [
            {
                "IndexName": "gsi1",
                "KeySchema": [
                    {"AttributeName": "gsi1pk", "KeyType": "HASH"},
                    {"AttributeName": "gsi1sk", "KeyType": "RANGE"}
                ],
                "Projection": {"ProjectionType": "ALL"}
            }
        ]
    }
    ensure_table(dynamodb, spec)

if __name__ == "__main__":
    dynamodb = boto3.resource("dynamodb", region_name=REGION)
    # 必要な方だけ呼んでOK（両方作るなら両方呼ぶ）
    ensure_hoero_users(dynamodb)
    ensure_dental_news(dynamodb)
