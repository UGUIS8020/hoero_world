import os
import pymysql
from dotenv import load_dotenv
import uuid
from datetime import datetime
from decimal import Decimal
import boto3
from boto3.dynamodb.conditions import Attr

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

# テーブル名（Flaskのconfig から取得している値を直接指定）
POSTS_TABLE_NAME = os.getenv('STL_POSTS_TABLE', 'hoero_stl_posts')
COMMENTS_TABLE_NAME = os.getenv('STL_COMMENTS_TABLE', 'hoero_stl_comments')
LIKES_TABLE_NAME = os.getenv('STL_LIKES_TABLE', 'hoero_stl_likes')

posts_table = dynamodb.Table(POSTS_TABLE_NAME)
comments_table = dynamodb.Table(COMMENTS_TABLE_NAME)
likes_table = dynamodb.Table(LIKES_TABLE_NAME)

# RDSのIDとDynamoDBのUUIDをマッピング
post_id_mapping = {}  # {rds_id: dynamodb_uuid}
comment_id_mapping = {}  # {rds_id: dynamodb_uuid}


def migrate_stl_posts():
    """stl_postsテーブルをDynamoDBに移行"""
    print("\n" + "="*50)
    print("STL Posts 移行開始")
    print("="*50)
    
    with rds_connection.cursor(pymysql.cursors.DictCursor) as cursor:
        cursor.execute("SELECT * FROM stl_posts ORDER BY created_at")
        posts = cursor.fetchall()
        
        print(f"移行対象: {len(posts)}件")
        
        for i, post in enumerate(posts, 1):
            try:
                new_post_id = str(uuid.uuid4())
                post_id_mapping[post['id']] = new_post_id
                
                created_at = post['created_at'] if post['created_at'] else datetime.utcnow()
                
                item = {
                    "post_id": new_post_id,
                    "title": post['title'] or "Untitled",
                    "content": post['content'] or "",
                    "user_id": str(post['user_id']),
                    "stl_filename": post['stl_filename'] or "",
                    "stl_file_path": post['gltf_file_path'] or "",  # gltf_file_pathを使用
                    "gltf_file_path": post['gltf_file_path'] or "",
                    "created_at": created_at.isoformat(),
                    "created_at_ts": Decimal(str(created_at.timestamp())),
                }
                
                posts_table.put_item(Item=item)
                print(f"  [{i}/{len(posts)}] ✓ RDS ID {post['id']} → DynamoDB {new_post_id[:8]}... ('{post['title']}')")
                
            except Exception as e:
                print(f"  [{i}/{len(posts)}] ✗ RDS ID {post['id']} 失敗: {e}")
    
    print(f"\nSTL Posts 移行完了: {len(posts)}件")
    return post_id_mapping


def migrate_stl_comments():
    """stl_commentsテーブルをDynamoDBに移行"""
    print("\n" + "="*50)
    print("STL Comments 移行開始")
    print("="*50)
    
    with rds_connection.cursor(pymysql.cursors.DictCursor) as cursor:
        cursor.execute("SELECT * FROM stl_comments ORDER BY created_at")
        comments = cursor.fetchall()
        
        print(f"移行対象: {len(comments)}件")
        
        for i, comment in enumerate(comments, 1):
            try:
                new_comment_id = str(uuid.uuid4())
                comment_id_mapping[comment['id']] = new_comment_id
                
                # RDSのpost_idをDynamoDBのUUIDに変換
                rds_post_id = comment['post_id']
                dynamodb_post_id = post_id_mapping.get(rds_post_id)
                
                if not dynamodb_post_id:
                    print(f"  [{i}/{len(comments)}] ✗ Comment ID {comment['id']}: 対応するpost_idが見つかりません (RDS post_id: {rds_post_id})")
                    continue
                
                # parent_comment_idも変換
                parent_comment_id = ""
                if comment['parent_comment_id']:
                    parent_comment_id = comment_id_mapping.get(comment['parent_comment_id'], "")
                
                created_at = comment['created_at'] if comment['created_at'] else datetime.utcnow()
                
                item = {
                    "comment_id": new_comment_id,
                    "post_id": dynamodb_post_id,
                    "user_id": str(comment['user_id']),
                    "content": comment['content'],
                    "parent_comment_id": parent_comment_id,
                    "created_at": created_at.isoformat(),
                    "created_at_ts": Decimal(str(created_at.timestamp())),
                }
                
                comments_table.put_item(Item=item)
                print(f"  [{i}/{len(comments)}] ✓ RDS ID {comment['id']} → DynamoDB {new_comment_id[:8]}...")
                
            except Exception as e:
                print(f"  [{i}/{len(comments)}] ✗ Comment ID {comment['id']} 失敗: {e}")
    
    print(f"\nSTL Comments 移行完了: {len(comments)}件")


def migrate_stl_likes():
    """stl_likesテーブルをDynamoDBに移行"""
    print("\n" + "="*50)
    print("STL Likes 移行開始")
    print("="*50)
    
    with rds_connection.cursor(pymysql.cursors.DictCursor) as cursor:
        cursor.execute("SELECT * FROM stl_likes ORDER BY created_at")
        likes = cursor.fetchall()
        
        print(f"移行対象: {len(likes)}件")
        
        for i, like in enumerate(likes, 1):
            try:
                new_like_id = str(uuid.uuid4())
                
                # RDSのpost_idをDynamoDBのUUIDに変換
                rds_post_id = like['post_id']
                dynamodb_post_id = post_id_mapping.get(rds_post_id)
                
                if not dynamodb_post_id:
                    print(f"  [{i}/{len(likes)}] ✗ Like ID {like['id']}: 対応するpost_idが見つかりません (RDS post_id: {rds_post_id})")
                    continue
                
                created_at = like['created_at'] if like['created_at'] else datetime.utcnow()
                
                item = {
                    "like_id": new_like_id,
                    "post_id": dynamodb_post_id,
                    "user_id": str(like['user_id']),
                    "created_at": created_at.isoformat(),
                }
                
                likes_table.put_item(Item=item)
                print(f"  [{i}/{len(likes)}] ✓ RDS ID {like['id']} → DynamoDB {new_like_id[:8]}...")
                
            except Exception as e:
                print(f"  [{i}/{len(likes)}] ✗ Like ID {like['id']} 失敗: {e}")
    
    print(f"\nSTL Likes 移行完了: {len(likes)}件")


def verify_migration():
    """移行結果の確認"""
    print("\n" + "="*50)
    print("移行結果の確認")
    print("="*50)
    
    # Posts
    response = posts_table.scan()
    print(f"DynamoDB Posts: {len(response['Items'])}件")
    
    # Comments
    response = comments_table.scan()
    print(f"DynamoDB Comments: {len(response['Items'])}件")
    
    # Likes
    response = likes_table.scan()
    print(f"DynamoDB Likes: {len(response['Items'])}件")


def main():
    print("="*50)
    print("RDS → DynamoDB データ移行ツール")
    print("="*50)
    print(f"Posts Table: {POSTS_TABLE_NAME}")
    print(f"Comments Table: {COMMENTS_TABLE_NAME}")
    print(f"Likes Table: {LIKES_TABLE_NAME}")
    
    try:
        # 1. Postsを移行（post_id_mappingを作成）
        migrate_stl_posts()
        
        # 2. Commentsを移行（post_id_mappingを使用）
        migrate_stl_comments()
        
        # 3. Likesを移行（post_id_mappingを使用）
        migrate_stl_likes()
        
        # 4. 移行結果の確認
        verify_migration()
        
        print("\n" + "="*50)
        print("✓ すべての移行が完了しました！")
        print("="*50)
        
    except Exception as e:
        print(f"\n✗ エラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
    finally:
        rds_connection.close()


if __name__ == "__main__":
    confirm = input("本当に移行を実行しますか？ (yes/no): ")
    if confirm.lower() == 'yes':
        main()
    else:
        print("移行をキャンセルしました")