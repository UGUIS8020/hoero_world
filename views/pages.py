from flask import Blueprint, render_template, current_app
from flask import request, current_app
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
import feedparser
from urllib.parse import quote_plus
from hashlib import sha256
from datetime import datetime
import time
import json
import base64
import requests
from bs4 import BeautifulSoup   
from dateutil.parser import parse as iso
from dateutil import tz



bp = Blueprint('pages', __name__, url_prefix='/pages', template_folder='hoero_world/templates', static_folder='hoero_world/static')

@bp.route('/root_replica')
def root_replica():
    
    return render_template('pages/root_replica.html')

@bp.route('/root_replica_case')
def root_replica_case():
    
    return render_template('pages/root_replica_case.html')

@bp.route('/root_replica_info')
def root_replica_info():
    
    return render_template('pages/root_replica_info.html')

@bp.route('/root_replica_qa')
def root_replica_qa():
    
    return render_template('pages/root_replica_qa.html')

@bp.route('/zirconia')
def zirconia():
    
    return render_template('pages/zirconia.html')

@bp.route('/combination_checker')
def combination_checker():
    
    return render_template('pages/combination_checker.html')

@bp.route('/missing_teeth_nation')
def missing_teeth_nation():
    
    return render_template('pages/missing_teeth_nation.html')

@bp.route('/news')
def news():
    
    return render_template('pages/news.html')




# ---- 自家歯牙移植ニュース収集関数 ----
def fetch_google_news_dental(query="自家歯牙移植", lang="ja"):
    """Google Newsから歯科ニュースを取得"""
    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=ja&gl=JP&ceid=JP:ja"
    feed = feedparser.parse(url)
    
    count = 0
    for e in feed.entries:
        link = getattr(e, "link", None)
        if not link:
            continue
            
        item = {
            "source": "google_news",
            "kind": "research",  # デフォルトは研究論文
            "title": (getattr(e, "title", "") or "").strip(),
            "url": link,
            "published_at": iso(getattr(e, "published", None)),
            "summary": getattr(e, "summary", None),
            "author": getattr(e, "source", {}).get("title") if hasattr(e, "source") else None,
            "image_url": None,
            "lang": lang,
        }
        
        # タイトルから記事の種類を判定
        title_lower = item["title"].lower()
        if any(word in title_lower for word in ["症例", "case report", "clinical case"]):
            item["kind"] = "case"
        elif any(word in title_lower for word in ["研究", "study", "research", "journal"]):
            item["kind"] = "research"
        elif any(word in title_lower for word in ["動画", "video", "tutorial", "technique"]):
            item["kind"] = "video"
            
        # OG画像を取得（研究論文・症例報告では不要だが一応）
        if item["kind"] == "video" and not item["image_url"]:
            item["image_url"] = extract_og_image(item["url"])
            
        if put_unique_dental(item):
            count += 1
            
    print(f"Google News (Dental): {count}件の新しい記事を追加 (クエリ: {query})")
    return count

def fetch_pubmed_articles(query="autotransplantation"):
    """PubMedから研究論文を取得（簡易版）"""
    # 実際にはPubMed APIを使用
    # ここでは概念的な実装を示す
    
    count = 0
    try:
        # PubMed E-utilities API
        search_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        params = {
            "db": "pubmed",
            "term": query,
            "retmax": "10",
            "sort": "pub date",
            "format": "json"
        }
        
        # 実際のAPI呼び出しは省略し、サンプルデータで代用
        sample_articles = [
            {
                "title": "Digital replica-assisted autotransplantation: A systematic review",
                "url": f"https://pubmed.ncbi.nlm.nih.gov/sample1",
                "author": "Journal of Oral Surgery",
                "published_at": "2025-01-10T00:00:00Z",
                "summary": "A comprehensive review of digital replica techniques in tooth autotransplantation.",
                "pmid": "sample1"
            }
        ]
        
        for article in sample_articles:
            item = {
                "source": "pubmed",
                "kind": "research",
                "title": article["title"],
                "url": article["url"],
                "published_at": article["published_at"],
                "summary": article["summary"],
                "author": article["author"],
                "image_url": None,
                "lang": "en",
            }
            
            if put_unique_dental(item):
                count += 1
                
    except Exception as e:
        print(f"PubMed取得エラー: {e}")
    
    print(f"PubMed: {count}件の新しい論文を追加")
    return count

def fetch_youtube_dental(query="tooth autotransplantation", lang="en"):
    """YouTubeから歯科技術動画を取得"""
    url = f"https://www.youtube.com/feeds/videos.xml?search_query={quote_plus(query)}"
    feed = feedparser.parse(url)
    
    count = 0
    for e in feed.entries:
        link = getattr(e, "link", None)
        if not link:
            continue
            
        thumb = None
        media = getattr(e, "media_thumbnail", None)
        if media and len(media) > 0:
            thumb = media[0].get("url")
            
        item = {
            "source": "youtube_rss",
            "kind": "video",
            "title": (getattr(e, "title", "") or "").strip(),
            "url": link,
            "published_at": iso(getattr(e, "published", None)),
            "summary": None,
            "author": getattr(e, "author", None),
            "image_url": thumb,
            "lang": lang,
        }
        
        if put_unique_dental(item):
            count += 1
            
    print(f"YouTube (Dental): {count}件の新しい動画を追加 (クエリ: {query})")
    return count

def put_unique_dental(item: dict):
    """歯科ニュース専用のDynamoDB保存関数"""
    table = current_app.config["DENTAL_TABLE"]  # 歯科ニュース専用テーブル
    pk = f"URL#{sha256(item['url'])}"
    try:
        table.put_item(
            Item={
                "pk": pk, "sk": "METADATA",
                "url": item["url"], "title": item.get("title"),
                "source": item.get("source"), "kind": item.get("kind"),
                "lang": item.get("lang"), "published_at": item.get("published_at"),
                "summary": item.get("summary"), "image_url": item.get("image_url"),
                "author": item.get("author"),
                "gsi1pk": f"KIND#{item.get('kind')}#LANG#{item.get('lang')}",
                "gsi1sk": item.get("published_at") or "0000-00-00T00:00:00"
            },
            ConditionExpression="attribute_not_exists(pk)"
        )
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise

# ---- 歯科ニュース用クエリ関数 ----
def dental_query_items(kind=None, lang=None, limit=40, last_evaluated_key=None):
    table = current_app.config["DENTAL_TABLE"]
    if not kind:
        kind = "research"
    if not lang:
        lang = "ja"

    kwargs = {
        "IndexName": "gsi1",
        "KeyConditionExpression": Key("gsi1pk").eq(f"KIND#{kind}#LANG#{lang}"),
        "ScanIndexForward": False,  # gsi1sk（published_at）で新しい順
        "Limit": limit,
    }
    if last_evaluated_key:
        kwargs["ExclusiveStartKey"] = last_evaluated_key

    resp = table.query(**kwargs)
    return resp.get("Items", []), resp.get("LastEvaluatedKey")



# ---- データ収集実行 ----
def collect_autotransplant_news():
    """自家歯牙移植ニュースを収集する"""
    print("自家歯牙移植ニュース収集を開始...")
    
    total = 0
    
    # 日本語研究論文・症例報告
    total += fetch_google_news_dental("自家歯牙移植", "ja")
    time.sleep(1)
    total += fetch_google_news_dental("デジタルドナーレプリカ", "ja")
    time.sleep(1)
    total += fetch_google_news_dental("歯牙移植 症例", "ja")
    time.sleep(1)
    
    # 英語研究論文
    total += fetch_google_news_dental("autotransplantation", "en")
    time.sleep(1)
    total += fetch_google_news_dental("tooth transplantation", "en")
    time.sleep(1)
    total += fetch_pubmed_articles("autotransplantation")
    time.sleep(1)
    
    # 技術動画
    total += fetch_youtube_dental("自家歯牙移植 手術", "ja")
    time.sleep(1)
    total += fetch_youtube_dental("tooth autotransplantation surgery", "en")
    time.sleep(1)
    total += fetch_youtube_dental("dental replica technique", "en")
    
    print(f"収集完了: 合計 {total}件の新しいコンテンツを追加")
    return total

@bp.route("/admin/auto_collect_dental", methods=["POST"])
def auto_collect_dental():
    """定期的に歯科ニュース収集を実行"""
    try:
        total = collect_autotransplant_news()
        return {"success": True, "total": total}
    except Exception as e:
        return {"success": False, "error": str(e)}, 500
