import os
import boto3
from dotenv import load_dotenv

load_dotenv()

# DynamoDB接続
dynamodb = boto3.client(
    'dynamodb',
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    region_name=os.getenv('AWS_REGION')
)

print("="*50)
print("DynamoDB テーブル一覧")
print("="*50)

try:
    response = dynamodb.list_tables()
    tables = response.get('TableNames', [])
    
    if tables:
        print(f"見つかったテーブル数: {len(tables)}")
        for table in tables:
            print(f"  - {table}")
    else:
        print("テーブルが見つかりませんでした")
    
    print("\n.envファイルの設定:")
    print(f"  STL_POSTS_TABLE: {os.getenv('STL_POSTS_TABLE', '未設定')}")
    print(f"  STL_COMMENTS_TABLE: {os.getenv('STL_COMMENTS_TABLE', '未設定')}")
    print(f"  STL_LIKES_TABLE: {os.getenv('STL_LIKES_TABLE', '未設定')}")
    print(f"  AWS_REGION: {os.getenv('AWS_REGION', '未設定')}")
    
except Exception as e:
    print(f"エラー: {e}")