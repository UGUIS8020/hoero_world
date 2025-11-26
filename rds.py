import os
import pymysql
from dotenv import load_dotenv

# .envファイルから環境変数を読み込む
load_dotenv()

# データベース接続設定
connection = pymysql.connect(
    host='127.0.0.1',
    port=3307,
    user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASSWORD'),
    database=os.getenv('DB_NAME')
)

try:
    with connection.cursor() as cursor:
        # テーブル一覧の取得
        cursor.execute("SHOW TABLES")
        tables = cursor.fetchall()
        
        print("データベース内のテーブル:")
        for table in tables:
            table_name = table[0]
            print(f"\n=== テーブル: {table_name} ===")

            # ★ レコード件数の取得（ここを追加）
            cursor.execute(f"SELECT COUNT(*) FROM `{table_name}`")
            count = cursor.fetchone()[0]
            print(f"レコード数: {count}")

            # テーブル構造の取得
            cursor.execute(f"DESCRIBE `{table_name}`")
            columns = cursor.fetchall()
                    
            print("カラム構造:")
            for column in columns:
                field = column[0]
                type = column[1]
                null = column[2]
                key = column[3]
                default = column[4]
                extra = column[5]
                print(f"  - {field}: {type}, Null: {null}, Key: {key}, Default: {default}, Extra: {extra}")
            
            # インデックスの取得
            cursor.execute(f"SHOW INDEX FROM {table_name}")
            indexes = cursor.fetchall()
            
            if indexes:
                print("\nインデックス:")
                for index in indexes:
                    index_name = index[2]
                    column_name = index[4]
                    print(f"  - {index_name}: {column_name}")
            
            # 外部キーの取得（必要に応じて）
            try:
                cursor.execute(f"""
                    SELECT 
                        CONSTRAINT_NAME, 
                        COLUMN_NAME, 
                        REFERENCED_TABLE_NAME, 
                        REFERENCED_COLUMN_NAME 
                    FROM 
                        INFORMATION_SCHEMA.KEY_COLUMN_USAGE 
                    WHERE 
                        TABLE_NAME = '{table_name}' 
                        AND REFERENCED_TABLE_NAME IS NOT NULL
                """)
                foreign_keys = cursor.fetchall()
                
                if foreign_keys:
                    print("\n外部キー:")
                    for fk in foreign_keys:
                        constraint = fk[0]
                        column = fk[1]
                        ref_table = fk[2]
                        ref_column = fk[3]
                        print(f"  - {constraint}: {column} -> {ref_table}({ref_column})")
            except:
                pass  # 外部キー情報の取得に失敗した場合は無視
            
finally:
    connection.close()