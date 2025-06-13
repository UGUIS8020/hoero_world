import boto3

def create_user_table():
    dynamodb = boto3.resource('dynamodb', region_name='ap-northeast-1')
    
    table_name = 'hoero-users'
    existing_tables = [table.name for table in dynamodb.tables.all()]
    if table_name in existing_tables:
        print(f"テーブル '{table_name}' は既に存在します")
        return

    table = dynamodb.create_table(
        TableName=table_name,
        KeySchema=[
            {'AttributeName': 'user_id', 'KeyType': 'HASH'}
        ],
        AttributeDefinitions=[
            {'AttributeName': 'user_id', 'AttributeType': 'S'},
            {'AttributeName': 'email', 'AttributeType': 'S'},
            {'AttributeName': 'display_name', 'AttributeType': 'S'}
        ],
        GlobalSecondaryIndexes=[
            {
                'IndexName': 'email-index',
                'KeySchema': [{'AttributeName': 'email', 'KeyType': 'HASH'}],
                'Projection': {'ProjectionType': 'ALL'}
            },
            {
                'IndexName': 'display_name-index',
                'KeySchema': [{'AttributeName': 'display_name', 'KeyType': 'HASH'}],
                'Projection': {'ProjectionType': 'ALL'}
            }
        ],
        BillingMode='PAY_PER_REQUEST'
    )

    print("テーブル作成中。ステータス:", table.table_status)

    # 作成完了を待つ
    table.meta.client.get_waiter('table_exists').wait(TableName=table_name)
    print(f"テーブル '{table_name}' が作成されました")

if __name__ == "__main__":
    create_user_table()
