import boto3

def create_message_table():
    # リージョンを直接指定
    dynamodb = boto3.resource('dynamodb', region_name='ap-northeast-1')
    
    # テーブルが存在するかチェック
    existing_tables = [table.name for table in dynamodb.tables.all()]
    if 'Meziro-message' in existing_tables:
        print("テーブル 'Meziro-message' は既に存在します")
        return
    
    # テーブル作成
    table = dynamodb.create_table(
        TableName='Meziro-message',
        KeySchema=[
            {
                'AttributeName': 'file_id',
                'KeyType': 'HASH'  # パーティションキー
            },
        ],
        AttributeDefinitions=[
            {
                'AttributeName': 'file_id',
                'AttributeType': 'S'
            },
        ],
        ProvisionedThroughput={
            'ReadCapacityUnits': 5,
            'WriteCapacityUnits': 5
        }
    )
    
    print("テーブル作成中。ステータス:", table.table_status)
    
    # テーブルが作成されるのを待つ
    table.meta.client.get_waiter('table_exists').wait(TableName='Meziro-message')
    print("テーブル 'Meziro-message' が作成されました")

if __name__ == "__main__":
    create_message_table()