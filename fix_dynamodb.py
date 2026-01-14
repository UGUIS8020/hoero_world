import os
import pymysql
from dotenv import load_dotenv
import boto3

load_dotenv()

# RDS接続
rds_connection = pymysql.connect(
    host='127.0.0.1',
    port=3307,
    user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASSWORD'),
    database=os.getenv('DB_NAME')
)

# DynamoDB接続
dynamodb = boto3.resource(
    'dynamodb',
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    region_name=os.getenv('AWS_REGION')
)

posts_table = dynamodb.Table('hoero-stl-posts')

print("="*50)
print("DynamoDB ファイルパス修正ツール")
print("="*50)

# DynamoDBの全投稿を取得
dynamo_response = posts_table.scan()
dynamo_posts = dynamo_response.get('Items', [])

# titleでマッピング（簡易的な方法）
with rds_connection.cursor(pymysql.cursors.DictCursor) as cursor:
    cursor.execute("SELECT id, title, stl_filename, stl_file_path FROM stl_posts")
    rds_posts = cursor.fetchall()
    
    # titleをキーにした辞書を作成
    rds_dict = {post['title']: post for post in rds_posts}

updated_count = 0
failed_count = 0

for dynamo_post in dynamo_posts:
    title = dynamo_post.get('title', '')
    post_id = dynamo_post.get('post_id')
    
    # RDSから対応するデータを探す
    rds_post = rds_dict.get(title)
    
    if rds_post and rds_post['stl_file_path']:
        try:
            # DynamoDBを更新
            posts_table.update_item(
                Key={'post_id': post_id},
                UpdateExpression='SET stl_file_path = :path, gltf_file_path = :path, stl_filename = :filename',
                ExpressionAttributeValues={
                    ':path': rds_post['stl_file_path'],
                    ':filename': rds_post['stl_filename'] or ''
                }
            )
            print(f"✓ 更新: {title}")
            print(f"  → {rds_post['stl_file_path']}")
            updated_count += 1
        except Exception as e:
            print(f"✗ 失敗: {title} - {e}")
            failed_count += 1
    else:
        print(f"⚠ スキップ: {title} (RDSにファイルパスなし)")
        failed_count += 1

print("\n" + "="*50)
print(f"更新完了: {updated_count}件")
print(f"失敗/スキップ: {failed_count}件")
print("="*50)

rds_connection.close()