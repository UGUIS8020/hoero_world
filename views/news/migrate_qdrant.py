"""
DynamoDBに保存済みのPubMed論文をQdrantに移行するスクリプト

使用方法:
    python migrate_pubmed_to_qdrant.py
"""

import os
import boto3
from dotenv import load_dotenv
from pubmed_vector_store import save_pubmed_items_to_qdrant

load_dotenv()

TABLE_NAME = os.getenv("DENTAL_TABLE_NAME", "dental-news")


def get_pubmed_items_from_dynamodb():
    """DynamoDBからPubMed論文を取得"""
    dynamodb = boto3.resource('dynamodb', region_name='ap-northeast-1')
    table = dynamodb.Table(TABLE_NAME)
    
    print(f"📦 テーブル: {TABLE_NAME}")
    print("🔍 PubMed論文を検索中...")
    
    items = []
    last_evaluated_key = None
    
    while True:
        scan_kwargs = {
            'FilterExpression': '#src = :pubmed',
            'ExpressionAttributeNames': {'#src': 'source'},
            'ExpressionAttributeValues': {':pubmed': 'pubmed'}
        }
        
        if last_evaluated_key:
            scan_kwargs['ExclusiveStartKey'] = last_evaluated_key
        
        response = table.scan(**scan_kwargs)
        items.extend(response.get('Items', []))
        
        last_evaluated_key = response.get('LastEvaluatedKey')
        if not last_evaluated_key:
            break
    
    print(f"✅ {len(items)}件のPubMed論文を取得")
    return items


def convert_dynamodb_to_pubmed_format(dynamo_items):
    """DynamoDBのアイテムをpubmed_fulltext_vector_storeで使える形式に変換"""
    converted = []
    
    for item in dynamo_items:
        # URLからPMIDを抽出（pmidフィールドがない場合）
        pmid = item.get('pmid', '')
        if not pmid:
            url = item.get('url', '')
            if 'pubmed.ncbi.nlm.nih.gov' in url:
                pmid = url.rstrip('/').split('/')[-1]
        
        if not pmid:
            print(f"[SKIP] PMIDが取得できません: {item.get('title', '')[:30]}")
            continue
        
        converted.append({
            "source": "pubmed",
            "pmid": pmid,
            "title": item.get('title', ''),
            "url": item.get('url', ''),
            "published_at": item.get('published_at', ''),
            "summary": item.get('summary', ''),
            "author": item.get('author', ''),
            "lang": "en"
        })
    
    return converted


def main():
    print("=" * 60)
    print("DynamoDB → Qdrant 移行スクリプト")
    print("=" * 60)
    
    # 1. DynamoDBから取得
    dynamo_items = get_pubmed_items_from_dynamodb()
    
    if not dynamo_items:
        print("❌ PubMed論文が見つかりません")
        return
    
    # 2. 形式変換
    print("\n🔄 データ形式を変換中...")
    pubmed_items = convert_dynamodb_to_pubmed_format(dynamo_items)
    print(f"✅ {len(pubmed_items)}件を変換")
    
    # 3. 確認
    print("\n📋 移行対象:")
    for i, item in enumerate(pubmed_items[:5], 1):
        print(f"  {i}. PMID {item['pmid']}: {item['title'][:40]}...")
    if len(pubmed_items) > 5:
        print(f"  ... 他 {len(pubmed_items) - 5}件")
    
    confirm = input(f"\n{len(pubmed_items)}件をQdrantに移行しますか？ (y/n): ").strip().lower()
    if confirm != 'y':
        print("キャンセルしました")
        return
    
    # 4. Qdrantに保存
    print("\n" + "=" * 60)
    result = save_pubmed_items_to_qdrant(pubmed_items)
    
    print("\n" + "=" * 60)
    print("移行完了")
    print(f"  保存: {result['total_saved']}ポイント")
    print(f"  スキップ: {result['total_skipped']}ポイント")
    print("=" * 60)


if __name__ == "__main__":
    main()