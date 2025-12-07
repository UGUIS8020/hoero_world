import boto3
from dotenv import load_dotenv
import os

load_dotenv()

dynamodb = boto3.client(
    'dynamodb',
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    region_name=os.getenv("AWS_REGION", "ap-northeast-1")
)

tables = [
    {
        'TableName': 'hoero-stl-posts',
        'KeySchema': [{'AttributeName': 'post_id', 'KeyType': 'HASH'}],
        'AttributeDefinitions': [{'AttributeName': 'post_id', 'AttributeType': 'S'}],
    },
    {
        'TableName': 'hoero-stl-comments',
        'KeySchema': [{'AttributeName': 'comment_id', 'KeyType': 'HASH'}],
        'AttributeDefinitions': [{'AttributeName': 'comment_id', 'AttributeType': 'S'}],
    },
    {
        'TableName': 'hoero-stl-likes',
        'KeySchema': [{'AttributeName': 'like_id', 'KeyType': 'HASH'}],
        'AttributeDefinitions': [{'AttributeName': 'like_id', 'AttributeType': 'S'}],
    },
]

for table in tables:
    try:
        response = dynamodb.create_table(
            TableName=table['TableName'],
            KeySchema=table['KeySchema'],
            AttributeDefinitions=table['AttributeDefinitions'],
            BillingMode='PAY_PER_REQUEST'
        )
        print(f"テーブル作成成功: {table['TableName']}")
    except dynamodb.exceptions.ResourceInUseException:
        print(f"テーブル既存: {table['TableName']}")
    except Exception as e:
        print(f"エラー: {table['TableName']} - {e}")

print("完了!")