from __future__ import annotations
import base64, json, time, logging, traceback, os
from flask import render_template, request, current_app, jsonify
from botocore.exceptions import ClientError
from urllib.parse import quote_plus
import feedparser
from hashlib import sha256 as _sha
from . import bp
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from boto3.dynamodb.conditions import Attr
from flask_login import current_user, login_required
from urllib.parse import quote


@bp.route('/admin/delete_article')
@login_required
def admin_delete_article():
    """特定記事を削除（管理者のみ）"""
    if not current_user.is_administrator:
        return "権限がありません", 403
    
    url = request.args.get('url')
    
    if not url:
        return "URLパラメータが必要です", 400
    
    confirm = request.args.get('confirm')
    
    table = _table()
    pk = f"URL#{_hash_url(url)}"
    
    try:
        response = table.get_item(Key={"pk": pk, "sk": "METADATA"})
        item = response.get('Item')
        
        if not item:
            return f"記事が見つかりません: {url}", 404
        
        # 確認画面
        if not confirm:
            # ★ URLをエンコードして渡す
            encoded_url = quote(url, safe='')
            
            html = f"""
            <h1>記事削除の確認</h1>
            <div style="border: 2px solid red; padding: 20px; margin: 20px 0;">
                <h2>以下の記事を削除しますか？</h2>
                <p><strong>Title:</strong> {item.get('title')}</p>
                <p><strong>URL:</strong> {item.get('url')}</p>
                <p><strong>Kind:</strong> {item.get('kind')} | <strong>Lang:</strong> {item.get('lang')}</p>
                <p><strong>Published:</strong> {item.get('published_at')}</p>
            </div>
            <p>
                <a href="/news/admin/delete_article?url={encoded_url}&confirm=yes" 
                   style="background: red; color: white; padding: 10px 20px; text-decoration: none;">
                   削除する
                </a>
                <a href="/news/autotransplant_news" 
                   style="background: gray; color: white; padding: 10px 20px; text-decoration: none; margin-left: 10px;">
                   キャンセル
                </a>
            </p>
            """
            return html
        
        # 実際に削除
        table.delete_item(Key={"pk": pk, "sk": "METADATA"})
        
        return f"""
        <h1>削除完了</h1>
        <p>記事を削除しました: {item.get('title')}</p>
        <p><a href="/news/autotransplant_news">一覧に戻る</a></p>
        """
        
    except Exception as e:
        import traceback
        return f"<pre>{traceback.format_exc()}</pre>", 500
    

logger = logging.getLogger(__name__)
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

# ========= 共通ユーティリティ =========
def _d(msg: str):
    """DEBUG出力（Flask DEBUG時は必ず出す）"""
    try:
        if current_app and current_app.debug:
            print(msg)
            logger.info(msg)
        else:
            logger.info(msg)
    except Exception:
        print(msg)

def _iso_now_utc():
    """現在時刻をISO形式で取得"""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _ensure_iso(v):
    """DynamoDB が datetime を受け取れないため ISO 文字列に揃える"""
    from datetime import datetime, date, timezone
    if v is None:
        return None
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        else:
            v = v.astimezone(timezone.utc)
        return v.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day, tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(v)

def _dynamodb_sanitize(v):
    """DynamoDB に渡す辞書を安全化（datetime→ISO 文字列 など）"""
    from datetime import datetime, date, timezone
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        else:
            v = v.astimezone(timezone.utc)
        return v.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day, tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(v, dict):
        return {k: _dynamodb_sanitize(v2) for k, v2 in v.items()}
    if isinstance(v, (list, tuple)):
        return type(v)(_dynamodb_sanitize(x) for x in v)
    if isinstance(v, set):
        return list(_dynamodb_sanitize(x) for x in v)
    return v

# ========= DynamoDB I/O =========
def _table():
    return current_app.config["DENTAL_TABLE"]

def _hash_url(url: str) -> str:
    return _sha(url.encode()).hexdigest()

def ai_filter_and_classify(title: str, summary: str = None, lang: str = "ja", url: str = None):
    """AIを使って記事をフィルタリング＆分類し、サマリーと見出しを生成"""
    
    prompt = f"""
以下の記事が「自家歯牙移植（tooth autotransplantation）」に関連するかどうかを判定し、
関連する場合は魅力的な見出しと要約を生成してください。

タイトル: {title}
要約: {summary or "なし"}
言語: {lang}
URL: {url or "なし"}

【判定基準】
✅ 関連する（relevant: true）：
- 自家歯牙移植の手術、技術、症例
- 移植歯の予後、成功率、生存率
- 移植に使用する歯（親知らず、小臼歯など）
- 移植時の歯根膜（PDL）保存技術
- 移植後の骨・歯周組織再生
- 3Dプリンティング、CADを使った移植用レプリカ
- 移植歯の固定方法、リグロスなどの併用療法

❌ 関連しない（relevant: false）：
- **自家歯牙移植が主題として明確に含まれていない一般的な歯科研究**
- 肉芽組織、創傷治癒、骨再生などが主題だが移植との関連が不明確
- インプラント、ブリッジ、義歯などの他の治療法のみ
- 研究者プロフィール、大学のデータベース
- 歯科医院の料金表、診療案内
- アーカイブページ（/archives/tag/、/archives/category/）
- タグページ、カテゴリページ
- 論文メタデータのみのページ（CiNii、researchmap等

【重要】
- タイトルや要約に「autotransplantation」「移植」「transplant」などが含まれていても、
  それが**歯の移植**ではなく他の医療分野の移植である可能性があります
- **自家歯牙移植との直接的な関連性**を慎重に確認してください
- 疑わしい場合は relevant: false としてください

【分類基準】（relevantがtrueの場合のみ）
- research: 学術論文、研究報告
- case: 症例報告、治療例
- news: ニュース記事、一般向け情報
- video: 動画コンテンツ

【見出しと要約の生成】（relevantがtrueの場合のみ）
- ai_headline: 魅力的で簡潔な見出し（30文字以内、{'日本語' if lang == 'ja' else '英語'}で）
- ai_summary: 記事の要点をまとめた要約（100-150文字、{'日本語' if lang == 'ja' else '英語'}で）

JSON形式で回答してください（relevant が false の場合、ai_headline と ai_summary は空文字列で構いません）：
{{
  "relevant": true/false,
  "kind": "research/case/news/video",
  "reason": "判定理由",
  "ai_headline": "魅力的な見出し",
  "ai_summary": "記事の要約"
}}

DO NOT OUTPUT ANYTHING OTHER THAN VALID JSON.
"""

    try:
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {OPENAI_API_KEY}"
            },
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1500,  # サマリー生成のため増やす
                "temperature": 0.3
            },
            timeout=30
        )
        
        if response.status_code != 200:
            _d(f"[AI] API error: {response.status_code} - {response.text}")
            return {
                "relevant": False,
                "kind": "research",
                "ai_summary": "",
                "ai_headline": "",
                "reason": "API error",
            }
        
        data = response.json()
        
        if "choices" not in data or len(data["choices"]) == 0:
            _d(f"[AI] Unexpected response: {json.dumps(data, indent=2)}")
            return {
                "relevant": False,
                "kind": "research",
                "ai_summary": "",
                "ai_headline": "",
                "reason": "Unexpected API response",
            }
        
        result_text = data["choices"][0]["message"]["content"].strip()
        result_text = result_text.replace("```json", "").replace("```", "").strip()
        
        try:
            result = json.loads(result_text)
        except json.JSONDecodeError as e:
            _d(f"[AI] JSON parse error: {e}")
            _d(f"[AI] Raw response: {result_text}")
            return {
                "relevant": False,
                "kind": "research",
                "ai_summary": "",
                "ai_headline": "",
                "reason": f"JSON parse error: {e}",
            }
        
        return {
            "relevant": result.get("relevant", False),
            "kind": result.get("kind", "research"),
            "ai_summary": result.get("ai_summary", ""),
            "ai_headline": result.get("ai_headline", ""),
            "reason": result.get("reason", "")
        }
        
    except Exception as e:
        _d(f"[AI] Filter error: {e}")
        traceback.print_exc()
        return {
            "relevant": False,
            "kind": "research",
            "ai_summary": "",
            "ai_headline": "",
            "reason": f"Error: {e}",
        }

def ai_collect_news(lang="ja", max_iterations=5):
    """AIエージェントが自律的にニュース・論文を収集（Google News + PubMed）"""

    # ★ 除外するURLパターン（ここに追加）
    EXCLUDED_PATTERNS = [
        '/archives/tag/',           # 確実に不要
        '/archives/category/',      # 確実に不要
        '/author/',                 # 確実に不要（著者ページ）
        '/feed',                    # 確実に不要（RSSフィード）
        '?share=',                  # 確実に不要（シェアリンク）
        '/wp-admin',               # 確実に不要（管理画面）
        '/wp-login',               # 確実に不要（ログイン）
        '/archives/tag/',
        '/archives/category/',
        '/department/',
        '/about/',
    ]
    
    # ★ 最初にDynamoDBから既存URLを読み込んでキャッシュ
    collected_urls = _load_existing_urls_from_db()
    _d(f"[CACHE] Starting with {len(collected_urls)} existing URLs in cache")
    
    all_items = []
    search_history = []
    
    # ★ Google Search API呼び出しカウンター
    google_api_call_count = 0
    MAX_GOOGLE_API_CALLS = 10
    
    # ★ Google Search API呼び出しカウンター
    google_api_call_count = 0
    MAX_GOOGLE_API_CALLS = 10  # 1回の収集で最大10回まで
    
    # 共通コンテキスト
    base_context = """あなたは自家歯牙移植（tooth autotransplantation）に関する
最新情報を収集する専門エージェントです。

以下の観点で幅広く情報を収集してください：
- 技術革新（3Dプリント、デジタルワークフロー、CAD/CAM）
- 新製品・医療機器（アルベオシェーバー、レプリカシステムなど）
- 臨床症例（特に前歯への移植、上顎中切歯、親知らずの活用など）
- 研究論文（成功率、長期予後、PDL保存など）
- 市場動向・統計データ
- 比較記事（インプラント vs 自家歯牙移植など）
- **海外ニュース（中国、韓国、欧米などの日本語記事）**  # ← 追加
"""

    # ★日本語だけクエリを「ゆるく」する追加指示
    if lang == "ja":
        context = base_context + """

【重要：日本語検索用の注意】
- 日本語記事はヒットが少ないので、クエリは 2〜3 語程度にしてください。
- 必ず「自家歯牙移植」「歯牙自家移植」「歯の自家移植」いずれかの基本語を含め、
  それに 1 語だけキーワードを足す程度にしてください。
  例: "自家歯牙移植 症例", "自家歯牙移植 予後", "歯の自家移植 研究"
- 「3Dプリント」「CAD/CAM」「アルベオシェーバー」などニッチな語は、
  全体の 1〜2 クエリにとどめてください。
"""
    else:
        context = base_context

    # ===== メインの自律検索ループ =====
    for iteration in range(max_iterations):
        query_prompt = f"""{context}

【これまでの検索履歴】
{json.dumps(search_history, ensure_ascii=False, indent=2) if search_history else "まだ検索していません"}

【収集済み記事数】{len(all_items)}件

次に実行すべき検索クエリを3つ提案してください。
- 既存の検索と重複しない新しい切り口で探してください
- {lang}言語（{'日本語' if lang == 'ja' else '英語'}）での検索クエリを生成してください
- 具体的な製品名、技術名、症例タイプなどを含めてください
- **検索クエリは「文章」ではなく検索エンジン向けのキーワード列にしてください**
  （例: 日本語なら "自家歯牙移植 症例",
       英語なら "tooth autotransplantation 3D printed replica"）
- これらのクエリはニュースサイトや論文データベース（Google News / PubMed など）で利用されます

以下のJSON形式で回答してください：
{{
  "queries": [
    {{"query": "検索クエリ1", "reason": "なぜこの検索が必要か"}},
    {{"query": "検索クエリ2", "reason": "なぜこの検索が必要か"}},
    {{"query": "検索クエリ3", "reason": "なぜこの検索が必要か"}}
  ],
  "strategy": "今回の検索戦略の説明"
}}

DO NOT OUTPUT ANYTHING OTHER THAN VALID JSON."""
        
        try:
            # OpenAI API を呼び出し
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {OPENAI_API_KEY}"
                },
                json={
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": query_prompt}],
                    "max_tokens": 2000,
                    "temperature": 0.7
                },
                timeout=30
            )
            
            _d(f"[AI AGENT] API status code: {response.status_code}")
            
            if response.status_code != 200:
                _d(f"[AI AGENT] API error response: {response.text}")
                continue
            
            data = response.json()
            
            if "choices" not in data or len(data["choices"]) == 0:
                _d(f"[AI AGENT] Unexpected response format: {json.dumps(data, indent=2)}")
                continue
                
            result_text = data["choices"][0]["message"]["content"].strip()
            result_text = result_text.replace("```json", "").replace("```", "").strip()
            query_plan = json.loads(result_text)
            
            _d(f"[AI AGENT] Iteration {iteration+1}: {query_plan['strategy']}")
            
            for q_item in query_plan["queries"]:
                query = q_item["query"]
                reason = q_item["reason"]
                
                _d(f"[AI AGENT] Searching: {query}")
                
                search_results = []

                # ① Google News RSS（10-15件程度）
                google_news_results = _execute_google_search(query, lang)
                search_results.extend(google_news_results)

                # ② Google Custom Search API（★ 制限付き）
                if os.getenv("GOOGLE_API_KEY") and os.getenv("GOOGLE_CX_ID"):
                    if google_api_call_count < MAX_GOOGLE_API_CALLS:
                        google_api_results = _execute_google_search_api(query, lang, max_results=30)
                        search_results.extend(google_api_results)
                        google_api_call_count += 1
                    else:
                        _d(f"[Google Search API] Skipped - reached limit ({MAX_GOOGLE_API_CALLS} calls)")

                # ③ PubMed（英語のみ、最大30件）
                if lang == "en":
                    pubmed_results = _execute_pubmed_search(query, max_results=30)
                    search_results.extend(pubmed_results)

                # ④ YouTube RSS版（最大30件）
                yt_rss_results = _execute_youtube_search(query, lang, max_results=30)
                search_results.extend(yt_rss_results)
                
                # ⑤ YouTube Data API版（最大30件）
                if os.getenv("YOUTUBE_API_KEY"):
                    yt_api_results = _execute_youtube_search_api(query, lang, max_results=30)
                    search_results.extend(yt_api_results)
                
                # ★ ここから検索結果の処理（インデントに注意！）
                for result_item in search_results:
                    if not result_item.get("url"):
                        continue
                    
                    # ★ 除外パターンチェック（追加）
                    url = result_item["url"]
                    if any(pattern in url for pattern in EXCLUDED_PATTERNS):
                        _d(f"[FILTER] Skipped excluded URL: {url[:80]}...")
                        continue
                    
                    if url in collected_urls:
                        continue
                    
                    # ★ Google検索結果の場合は本文を取得してAI判定
                    summary_for_ai = result_item.get("summary")
                    
                    if result_item.get("source") == "google_search_api":
                        _d(f"[AI] Google search result - fetching full content")
                        full_content = _fetch_content_for_ai(result_item["url"], max_chars=800)
                        if full_content:
                            _d(f"[AI] Fetched content ({len(full_content)} chars)")
                            summary_for_ai = full_content
                        else:
                            _d(f"[AI] Failed to fetch, using snippet")
                    
                    ai_result = ai_filter_and_classify(
                        result_item["title"], 
                        summary_for_ai,  # ← 本文またはスニペット
                        lang,
                        result_item.get("url")
                    )
                    
                    if not ai_result["relevant"]:
                        continue

                    # 基本は AI の kind
                    kind = ai_result.get("kind", "research")

                    # YouTube から来たものは必ず video 扱い
                    if result_item.get("source") in ["youtube", "youtube_api"]:
                        kind = "video"
                    
                    result_item["lang"] = lang
                    result_item["kind"] = kind
                    result_item["ai_relevant"] = ai_result["relevant"]
                    result_item["ai_kind"] = kind
                    result_item["ai_summary"] = ai_result["ai_summary"]
                    result_item["ai_reason"] = ai_result["reason"]
                    result_item["ai_search_query"] = query
                    result_item["ai_headline"] = ai_result.get("ai_headline")
                    
                    all_items.append(result_item)
                    collected_urls.add(result_item["url"])
                    
                    _d(
                        f"[AI AGENT] ✓ Found: {result_item['title'][:60]}..."
                        f" (kind={kind}, lang={lang}, source={result_item.get('source')})"
                    )
                
                search_history.append({
                    "iteration": iteration + 1,
                    "query": query,
                    "reason": reason,
                    "found": len(search_results)
                })
                
                time.sleep(1)
                
        except Exception as e:
            _d(f"[AI AGENT] Error in iteration {iteration+1}: {e}")
            traceback.print_exc()

    # ===== フォールバック：日本語で1件も拾えていない場合 =====
    if lang == "ja" and not all_items:
        fallback_queries = [
            "自家歯牙移植 症例",
            "自家歯牙移植 予後 調査",
            "歯の自家移植 研究"
        ]
        for query in fallback_queries:
            _d(f"[AI AGENT] Fallback searching (ja): {query}")
            search_results = _execute_google_search(query, "ja")
            
            # Google Search API版を追加（★ 制限なし - フォールバックなので）
            if os.getenv("GOOGLE_API_KEY") and os.getenv("GOOGLE_CX_ID"):
                google_api = _execute_google_search_api(query, "ja", max_results=30)
                search_results.extend(google_api)
            
            # YouTube RSS版を追加
            yt_rss = _execute_youtube_search(query, "ja", max_results=30)
            search_results.extend(yt_rss)
            
            # YouTube API版を追加
            if os.getenv("YOUTUBE_API_KEY"):
                yt_api = _execute_youtube_search_api(query, "ja", max_results=30)
                search_results.extend(yt_api)

            for result_item in search_results:
                if not result_item.get("url"):
                    continue
                
                # ★ 除外パターンチェック（追加）
                url = result_item["url"]
                if any(pattern in url for pattern in EXCLUDED_PATTERNS):
                    _d(f"[FILTER] Skipped excluded URL: {url[:80]}...")
                    continue
                
                if result_item["url"] in collected_urls:
                    continue
                
                # ★ Google検索結果の場合は本文を取得してAI判定
                summary_for_ai = result_item.get("summary")
                
                if result_item.get("source") == "google_search_api":
                    _d(f"[AI] Google search result - fetching full content")
                    full_content = _fetch_content_for_ai(result_item["url"], max_chars=800)
                    if full_content:
                        _d(f"[AI] Fetched content ({len(full_content)} chars)")
                        summary_for_ai = full_content
                    else:
                        _d(f"[AI] Failed to fetch, using snippet")
                
                ai_result = ai_filter_and_classify(
                    result_item["title"], 
                    summary_for_ai,  # ← 本文またはスニペット
                    lang,
                    result_item.get("url")
                )
                
                if not ai_result["relevant"]:
                    continue

                # 基本は AI の kind
                kind = ai_result.get("kind", "research")

                # YouTube（RSS版/API版）から来たものは必ず video 扱いに上書き
                if result_item.get("source") in ["youtube", "youtube_api"]:
                    kind = "video"
                
                result_item["lang"] = "ja"
                result_item["kind"] = kind
                result_item["ai_relevant"] = ai_result["relevant"]
                result_item["ai_kind"] = kind
                result_item["ai_summary"] = ai_result["ai_summary"]
                result_item["ai_reason"] = ai_result["reason"]
                result_item["ai_search_query"] = query
                result_item["ai_headline"] = ai_result.get("ai_headline")
                
                all_items.append(result_item)
                collected_urls.add(result_item["url"])
                
                _d(
                    f"[AI AGENT] ✓ Found: {result_item['title'][:60]}..."
                    f" (kind={kind}, lang=ja, source={result_item.get('source')})"
                )

        # ログ用に履歴も追加しておく
        search_history.append({
            "iteration": "fallback",
            "query": " / ".join(fallback_queries),
            "reason": "日本語モードで0件だったため固定クエリで再検索",
            "found": len(all_items)
        })
    
    # ===== DynamoDB へ保存 =====
    saved = 0
    for item in all_items:
        if put_unique_dental(item):
            saved += 1
            _d(f"[AI AGENT] 💾 Saved: {item['title'][:60]}...")
    
    _d(f"[AI AGENT] ✅ Complete: total_found={len(all_items)}, saved={saved}")
    
    return {
        "total_found": len(all_items),
        "saved": saved,
        "search_history": search_history
    }


def _load_existing_urls_from_db():
    """DynamoDBから既存のURLをすべて取得してセットで返す（2回目以降のコスト削減）"""
    table = _table()
    existing_urls = set()
    
    scan_kwargs = {
        'ProjectionExpression': '#url',
        'FilterExpression': 'attribute_exists(#url)',
        'ExpressionAttributeNames': {
            '#url': 'url'
        }
    }
    
    try:
        while True:
            response = table.scan(**scan_kwargs)
            
            for item in response.get('Items', []):
                if 'url' in item:
                    existing_urls.add(item['url'])
            
            if 'LastEvaluatedKey' not in response:
                break
            scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
        
        _d(f"[CACHE] Loaded {len(existing_urls)} existing URLs from DynamoDB")
        
    except Exception as e:
        _d(f"[CACHE] Error loading existing URLs: {e}")
        traceback.print_exc()
        # エラーが起きても空のセットを返して処理を続行
    
    return existing_urls


def _execute_google_search(query, lang="ja"):
    """実際のGoogle News検索を実行"""
    if lang == "ja":
        hl, gl, ceid = "ja", "JP", "JP:ja"
    else:
        hl, gl, ceid = "en", "US", "US:en"
    
    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl={hl}&gl={gl}&ceid={ceid}"
    
    feed = feedparser.parse(url)
    items = []
    
    for e in feed.entries:
        link = getattr(e, "link", None)
        if not link:
            continue
            
        title = (getattr(e, "title", "") or "").strip()
        summary = getattr(e, "summary", None)
        
        pub = getattr(e, "published", None) or getattr(e, "updated", None)
        published_at = _iso_now_utc()
        if pub and getattr(e, "published_parsed", None):
            try:
                import datetime
                import time as _time
                tm = e.published_parsed
                published_at = datetime.datetime.utcfromtimestamp(
                    _time.mktime(tm)
                ).strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                pass
        
        items.append({
            "source": "google_news",  # ✅ 修正
            "title": title,
            "url": link,
            "published_at": published_at,
            "summary": summary,
            "author": getattr(getattr(e, "source", None) or {}, "title", None),
            "image_url": None,
            "lang": lang,
        })
    
    _d(f"[Google News RSS] Found {len(items)} articles for query: {query}")  # ✅ ログ追加
    return items

def _execute_google_search_api(query, lang="ja", max_results=30):
    """Google Custom Search API実行（エラーハンドリング付き）"""
    api_key = os.getenv("GOOGLE_API_KEY")
    cx_id = os.getenv("GOOGLE_CX_ID")
    
    if not api_key or not cx_id:
        return []
    
    try:
        url = "https://www.googleapis.com/customsearch/v1"
        params = {
            "key": api_key,
            "cx": cx_id,
            "q": query,
            "num": min(max_results, 10),
            "lr": f"lang_{lang}",
        }
        
        response = requests.get(url, params=params, timeout=10)
        
        # ★ 429エラー（レート制限）の処理
        if response.status_code == 429:
            _d(f"[Google Search API] Rate limit reached - skipping this query")
            return []
        
        if response.status_code != 200:
            _d(f"[Google Search API] Error: {response.status_code}")
            return []
        
        data = response.json()
        items = []
        
        for item in data.get("items", []):
            items.append({
                "source": "google_search_api",
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "published_at": _iso_now_utc(),
                "summary": item.get("snippet", ""),
                "author": None,
                "image_url": item.get("pagemap", {}).get("cse_image", [{}])[0].get("src"),
                "lang": lang,
            })
        
        _d(f"[Google Search API] Found {len(items)} articles")
        return items
        
    except Exception as e:
        _d(f"[Google Search API] Error: {e}")
        return []

def _execute_youtube_search(query, lang="ja", max_results=20):
    """
    YouTube 検索（RSS）から動画一覧を取得
    返り値は他のニュースと同じフォーマット：
    {source, title, url, published_at, summary, author, image_url, lang}
    """
    # YouTube 検索用 RSS フィード
    # 例: https://www.youtube.com/feeds/videos.xml?search_query=%E8%87%AA%E5%AE%B6%E6%AD%AF%E7%89%99%E7%A7%BB%E6%A4%8D
    url = f"https://www.youtube.com/feeds/videos.xml?search_query={quote_plus(query)}"

    feed = feedparser.parse(url)
    items = []

    for e in feed.entries[:max_results]:
        link = getattr(e, "link", None)
        if not link:
            continue

        title = (getattr(e, "title", "") or "").strip()
        summary = getattr(e, "summary", None)

        # 投稿日
        pub = getattr(e, "published", None) or getattr(e, "updated", None)
        published_at = _iso_now_utc()
        if pub and getattr(e, "published_parsed", None):
            try:
                import datetime
                import time as _time
                tm = e.published_parsed
                published_at = datetime.datetime.utcfromtimestamp(
                    _time.mktime(tm)
                ).strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                pass

        # チャンネル名
        author = getattr(e, "author", None)

        # サムネイル（あれば）
        thumb = None
        if "media_thumbnail" in e:
            try:
                thumb = e.media_thumbnail[0]["url"]
            except Exception:
                pass

        items.append({
            "source": "youtube",
            "title": title,
            "url": link,
            "published_at": published_at,
            "summary": summary,
            "author": author,
            "image_url": thumb,
            "lang": lang,
            # kind は後で強制的に "video" にする
        })

    return items

def _execute_youtube_search_api(query: str, lang: str = "ja", max_results: int = 10) -> list:
    """YouTube Data API版（より詳細な検索・APIキー必要）"""
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        _d("[YouTube API] API key not found, skipping")
        return []
    
    try:
        url = "https://www.googleapis.com/youtube/v3/search"
        params = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": max_results,
            "key": api_key,
            "relevanceLanguage": lang,
            "order": "date",  # 最新順
            "regionCode": "JP" if lang == "ja" else "US"
        }
        
        response = requests.get(url, params=params, timeout=15)
        
        if response.status_code != 200:
            _d(f"[YouTube API] Error: {response.status_code} - {response.text}")
            return []
        
        data = response.json()
        items = []
        
        for item in data.get("items", []):
            video_id = item["id"].get("videoId")
            if not video_id:
                continue
            
            snippet = item["snippet"]
            
            # 公開日時をISO形式に変換
            published_at = snippet.get("publishedAt", "")
            
            items.append({
                "source": "youtube_api",
                "title": snippet.get("title", ""),
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "published_at": published_at,
                "summary": snippet.get("description", "")[:200],
                "author": snippet.get("channelTitle", ""),
                "image_url": snippet.get("thumbnails", {}).get("high", {}).get("url", ""),
                "lang": lang,
            })
        
        _d(f"[YouTube API] Found {len(items)} videos for query: {query}")
        return items
        
    except Exception as e:
        _d(f"[YouTube API] Error: {e}")
        traceback.print_exc()
        return []


def _execute_pubmed_search(query: str, max_results: int = 20):
    """PubMed から論文情報を取得して、ニュースと同じフォーマットで返す"""
    try:
        # 1. ID リストを取得
        r = requests.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            params={
                "db": "pubmed",
                "term": query,
                "retmode": "json",
                "retmax": max_results,
                "sort": "pub+date",   # 発行日の新しい順
            },
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        ids = data.get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []

        id_str = ",".join(ids)

        # 2. 詳細情報（タイトル・アブストラクトなど）を XML で取得
        r2 = requests.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            params={
                "db": "pubmed",
                "id": id_str,
                "retmode": "xml",
            },
            timeout=20,
        )
        r2.raise_for_status()
        root = ET.fromstring(r2.text)

        def _parse_pubdate(pubdate_elem):
            """PubDate 要素から ISO 文字列をできる範囲で作る"""
            if pubdate_elem is None:
                return _iso_now_utc()

            year = pubdate_elem.findtext("Year")
            month = pubdate_elem.findtext("Month") or "01"
            day = pubdate_elem.findtext("Day") or "01"

            # 月が "Jan" などの省略表記の場合に対応
            month_map = {
                "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
                "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
                "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
            }
            month = month_map.get(month, month)

            try:
                dt = datetime(int(year), int(month), int(day))
                return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                return _iso_now_utc()

        items = []

        for art in root.findall(".//PubmedArticle"):
            pmid_el = art.find(".//PMID")
            pmid = pmid_el.text if pmid_el is not None else None

            article = art.find(".//Article")
            title = ""
            if article is not None:
                title_el = article.find("ArticleTitle")
                if title_el is not None:
                    # タグを含むことがあるので itertext で結合
                    title = "".join(title_el.itertext()).strip()

            abstract = ""
            abstr_el = article.find("Abstract") if article is not None else None
            if abstr_el is not None:
                parts = []
                for t in abstr_el.findall("AbstractText"):
                    parts.append("".join(t.itertext()).strip())
                abstract = " ".join(parts)

            journal = ""
            journal_el = article.find("Journal/Title") if article is not None else None
            if journal_el is not None:
                journal = journal_el.text

            pubdate_el = art.find(".//PubDate")
            published_at = _parse_pubdate(pubdate_elem=pubdate_el)

            url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else None

            items.append({
                "source": "pubmed",
                "pmid": pmid,
                "title": title,
                "url": url,
                "published_at": published_at,
                "summary": abstract,
                "author": journal,   # or first author でもOK
                "image_url": None,
                "lang": "en",        # PubMed は基本英語扱い
            })

        return items

    except Exception as e:
        _d(f"[PUBMED] Error: {e}")
        traceback.print_exc()
        return []

# ========= サービス =========
def _enc_tok(lek: dict | None) -> str | None:
    if not lek: return None
    return base64.urlsafe_b64encode(json.dumps(lek).encode()).decode()

def _dec_tok(tok: str | None):
    if not tok: return None
    try:
        return json.loads(base64.urlsafe_b64decode(tok.encode()).decode())
    except Exception:
        return None

def list_news(kind="research", lang="ja", limit=40, tok=None):
    lek = _dec_tok(tok)
    items, next_lek = dental_query_items(kind=kind, lang=lang, limit=limit, last_evaluated_key=lek)
    return items, _enc_tok(next_lek)

# ========= ルート =========
@bp.route("/news")
def news():
    return render_template("pages/news.html")

@bp.route("/autotransplant_news")
def autotransplant_news():
    kind = request.args.get("kind", "research")
    lang = request.args.get("lang", "ja")
    tok  = request.args.get("tok")
    rows, next_tok = list_news(kind=kind, lang=lang, limit=40, tok=tok)
    return render_template("pages/autotransplant_news.html",
                           rows=rows, kind=kind, lang=lang, page=1, next_tok=next_tok)

@bp.route("/api/latest")
def news_api_latest():
    kind = request.args.get("kind", "research")
    lang = request.args.get("lang", "ja")
    limit = min(int(request.args.get("limit", 5)), 20)

    # ★ lang=all のときは ja + en をまとめて返す
    if lang == "all":
        combined = []
        for lg in ["ja", "en"]:
            items, _ = dental_query_items(kind=kind, lang=lg, limit=limit)
            combined.extend(items)

        # published_at の新しい順にソート
        combined.sort(key=lambda x: x.get("published_at", ""), reverse=True)

        # URLで重複排除しつつ、最大 limit 件まで
        seen = set()
        payload = []
        for it in combined:
            url = it.get("url")
            if not url or url in seen:
                continue
            seen.add(url)

            # ★ 見出しの優先順位: ai_headline > title
            headline = it.get("ai_headline") or it.get("title")

            payload.append({
                "title": headline,
                "url": url,
                "published_at": (it.get("published_at") or "")[:10],
                "kind": it.get("kind"),
                "lang": it.get("lang"),
                "source": it.get("source"),
                "ai_headline": it.get("ai_headline"),  # ← 追加
                "ai_summary": it.get("ai_summary"),    # ← 追加
            })

            if len(payload) >= limit:
                break

        return jsonify({
            "kind": kind, "lang": "all",
            "count": len(payload),
            "updated_at": _iso_now_utc(),
            "items": payload,
        })

    # ★ lang が ja / en のとき（修正版）
    items, _ = dental_query_items(kind=kind, lang=lang, limit=limit, last_evaluated_key=None)
    
    payload = []
    for it in items:
        if not it.get("title") or not it.get("url"):
            continue
            
        # ★ 見出しの優先順位: ai_headline > title
        headline = it.get("ai_headline") or it.get("title")
        
        payload.append({
            "title": headline,
            "url": it.get("url"),
            "published_at": (it.get("published_at") or "")[:10],
            "kind": it.get("kind"),
            "ai_headline": it.get("ai_headline"),  # ← 追加
            "ai_summary": it.get("ai_summary"),    # ← 追加
        })
    
    return jsonify({
        "kind": kind, "lang": lang,
        "count": len(payload),
        "updated_at": _iso_now_utc(),
        "items": payload
    })


@bp.route("/api/all")
def news_api_all():
    """全ての記事を取得（全種類・全言語）"""
    all_items = []
    
    # 全種類・全言語を取得
    kinds = ["research", "case", "news", "video", "product", "market"]  # ← "news" を追加
    langs = ["ja", "en"]
    
    for kind in kinds:
        for lang in langs:
            items, _ = dental_query_items(kind=kind, lang=lang, limit=100)
            all_items.extend(items)
    
    # 日付順にソート（新しい順）
    all_items.sort(key=lambda x: x.get("published_at", ""), reverse=True)
    
    # 重複削除（URLベース）
    seen_urls = set()
    unique_items = []
    for item in all_items:
        if item["url"] not in seen_urls:
            seen_urls.add(item["url"])
            unique_items.append({
                "title": item.get("title"),
                "url": item.get("url"),
                "published_at": (item.get("published_at") or "")[:10],
                "kind": item.get("kind"),
                "lang": item.get("lang"),
                "ai_summary": item.get("ai_summary"),
                "author": item.get("author"),
                "image_url": item.get("image_url"),
            })
    
    return jsonify({
        "count": len(unique_items),
        "updated_at": _iso_now_utc(),
        "items": unique_items
    })


@bp.route("/admin/inspect")
def news_admin_inspect():
    kinds = ["research", "case", "video", "product", "market"]
    langs = ["ja", "en"]
    lines = []
    for k in kinds:
        for lg in langs:
            items, _ = dental_query_items(kind=k, lang=lg, limit=5)
            titles = [i.get("title") for i in items]
            lines.append(f"{k}/{lg}: count~{len(items)} sample={titles}")
    _d("[INSPECT] " + " | ".join(lines))
    return "<br>".join(lines)

@bp.route("/admin/debug_dump")
def news_admin_debug_dump():
    items, _ = dental_query_items(kind="research", lang="ja", limit=20)
    html = ["<h3>research/ja (top 20)</h3><ol>"]
    for it in items:
        html.append(f"<li>{it.get('published_at','')} — {it.get('title','')}<br>"
                    f"<small>{it.get('url','')}</small></li>")
    html.append("</ol>")
    return "".join(html)


@bp.route("/admin/run_autotransplant_news")
def run_autotransplant_news():
    """AI収集を実行（既存のルートから呼び出し）"""
    try:
        # AI収集を実行
        results_ja = ai_collect_news(lang="ja", max_iterations=5)
        time.sleep(2)
        results_en = ai_collect_news(lang="en", max_iterations=3)
        
        total = results_ja["saved"] + results_en["saved"]
        
        # 最初の記事を確認
        items, _ = dental_query_items(kind="research", lang="ja", limit=1)
        
        _d(f"[DEBUG] after collect: total={total}, ja={results_ja['saved']}, en={results_en['saved']}")
        
        return f"""
        <h1>AI収集完了！</h1>
        <p>合計: {total}件の記事を保存しました</p>
        <ul>
            <li>日本語: {results_ja['saved']}件（検索{len(results_ja['search_history'])}回）</li>
            <li>英語: {results_en['saved']}件（検索{len(results_en['search_history'])}回）</li>
        </ul>
        <p>最初の記事: {'あり' if items else 'なし'}</p>
        <h3>検索履歴（日本語）:</h3>
        <pre>{json.dumps(results_ja['search_history'], ensure_ascii=False, indent=2)}</pre>
        <h3>検索履歴（英語）:</h3>
        <pre>{json.dumps(results_en['search_history'], ensure_ascii=False, indent=2)}</pre>
        <p><a href="/news/autotransplant_news?kind=research&lang=ja">日本語記事を見る</a></p>
        <p><a href="/news/autotransplant_news?kind=research&lang=en">英語記事を見る</a></p>
        """
    except Exception as e:
        traceback.print_exc()
        return f"<h1>エラー</h1><pre>{traceback.format_exc()}</pre>"
    

@bp.route("/admin/clear_all_dental_news")
def clear_all_dental_news():
    """全記事を完全削除"""
    try:
        table = current_app.config["DENTAL_TABLE"]
        deleted = 0
        
        # テーブル全体をスキャン
        scan_kwargs = {
            'ProjectionExpression': 'pk, sk'
        }
        
        while True:
            response = table.scan(**scan_kwargs)
            items = response.get('Items', [])
            
            # バッチで削除
            with table.batch_writer() as batch:
                for item in items:
                    batch.delete_item(Key={
                        'pk': item['pk'],
                        'sk': item['sk']
                    })
                    deleted += 1
            
            if 'LastEvaluatedKey' not in response:
                break
            scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
        
        return jsonify({
            "status": "success",
            "message": f"削除完了: {deleted}件"
        })
        
    except Exception as e:
        import traceback
        return jsonify({
            "status": "error",
            "message": str(e),
            "traceback": traceback.format_exc()
        }), 500
    
@bp.route("/admin/count_dental_news")
def count_dental_news():
    """記事の総数を確認"""
    try:
        table = current_app.config["DENTAL_TABLE"]
        
        response = table.scan(Select='COUNT')
        count = response.get('Count', 0)
        
        while 'LastEvaluatedKey' in response:
            response = table.scan(
                Select='COUNT',
                ExclusiveStartKey=response['LastEvaluatedKey']
            )
            count += response.get('Count', 0)
        
        return jsonify({
            "status": "success",
            "table": os.getenv("DENTAL_TABLE_NAME", "dental-news"),
            "total_count": count
        })
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500
    

def dental_query_items(kind=None, lang=None, limit=40, last_evaluated_key=None):
    table = current_app.config["DENTAL_TABLE"]

    if not kind:
        kind = "research"
    if not lang:
        lang = "ja"

    pk = f"KIND#{kind}#LANG#{lang}"

    # ★ scan ではなく query を使う（GSI1を利用）
    query_kwargs = {
        "IndexName": "gsi1",  # GSIの名前を確認してください
        "KeyConditionExpression": "gsi1pk = :pk",
        "ExpressionAttributeValues": {
            ":pk": pk
        },
        "ScanIndexForward": False,  # 新しい順（gsi1skで降順）
        "Limit": limit,
    }

    if last_evaluated_key:
        query_kwargs["ExclusiveStartKey"] = last_evaluated_key

    resp = table.query(**query_kwargs)
    items = resp.get("Items", [])

    return items, resp.get("LastEvaluatedKey")


def put_unique_dental(item: dict) -> bool:
    """歯科ニュース専用のDynamoDB保存関数（AI対応版）"""
    pk = f"URL#{_hash_url(item['url'])}"
    try:
        _table().put_item(
            Item=_dynamodb_sanitize({
                "pk": pk, "sk": "METADATA",
                "url": item["url"],
                "title": item.get("title"),
                "source": item.get("source"),
                "kind": item.get("kind"),
                "lang": item.get("lang"),
                "published_at": (_ensure_iso(item.get("published_at")) or _iso_now_utc()),
                "summary": item.get("summary"),
                "image_url": item.get("image_url"),
                "author": item.get("author"),
                "gsi1pk": f"KIND#{item.get('kind')}#LANG#{item.get('lang')}",
                "gsi1sk": _ensure_iso(item.get("published_at")) or "0000-00-00T00:00:00",
                # AI 判定結果
                "ai_relevant": item.get("ai_relevant"),
                "ai_kind": item.get("ai_kind"),
                "ai_summary": item.get("ai_summary"),
                "ai_reason": item.get("ai_reason"),
                "ai_search_query": item.get("ai_search_query"),
                "ai_headline": item.get("ai_headline"),
            }),
            ConditionExpression="attribute_not_exists(pk)",
        )
        _d(f"[DB] ✅ Saved: {item.get('title','')[:50]}")
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            _d(f"[DB] Skipped (already exists): {item.get('title','')[:50]}")  # ← タイトル追加
            return False
        _d(f"[DB] Error in put_unique_dental: {e}")
        return False
    

def _fetch_content_for_ai(url: str, max_chars: int = 500):
    """
    URLから本文を取得してAI判定用のテキストを返す
    取得できない場合はNoneを返す
    """
    try:
        import requests
        from bs4 import BeautifulSoup
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 不要なタグを削除
        for tag in soup(['script', 'style', 'nav', 'header', 'footer']):
            tag.decompose()
        
        # 本文を抽出
        text = soup.get_text(separator=' ', strip=True)
        
        # 空白を正規化
        text = ' '.join(text.split())
        
        # 指定文字数まで切り取り
        return text[:max_chars] if text else None
        
    except Exception as e:
        _d(f"[FETCH CONTENT] Error fetching {url}: {e}")
        return None
    
# 2. 最近の日本語記事を全部表示
def list_recent_ja_articles(limit=50):
    table = _table()
    response = table.query(
        IndexName="gsi1",
        KeyConditionExpression="gsi1pk = :pk",
        ExpressionAttributeValues={
            ":pk": "KIND#case#LANG#ja"  # または "KIND#research#LANG#ja"
        },
        ScanIndexForward=False,  # 新しい順
        Limit=limit
    )
    
    for item in response['Items']:
        print(f"{item.get('published_at')} - {item.get('title')}")


@bp.route('/debug_china')
def debug_china():
    """dental-plazaの記事を確認"""
    table = _table()
    
    response = table.scan()
    
    dental_plaza_items = []
    for item in response['Items']:
        url = item.get('url', '')
        if 'dental-plaza' in url or '切歯骨' in item.get('title', ''):
            dental_plaza_items.append(item)
    
    html = f"<h1>Dental Plaza / 切歯骨 Articles ({len(dental_plaza_items)}件)</h1>"
    
    for item in dental_plaza_items:
        html += f"""
        <div style="margin-bottom: 20px; border: 1px solid #ccc; padding: 10px;">
            <h3>{item.get('title')}</h3>
            <p><strong>URL:</strong> <a href="{item.get('url')}" target="_blank">{item.get('url')}</a></p>
            <p><strong>Kind:</strong> {item.get('kind')} | <strong>Lang:</strong> {item.get('lang')}</p>
            <p><strong>Published:</strong> {item.get('published_at')}</p>
            <p><strong>Search Query:</strong> {item.get('ai_search_query')}</p>
            <p><strong>AI Reason:</strong> {item.get('ai_reason')}</p>
        </div>
        """
    
    if not dental_plaza_items:
        html += "<p>該当する記事が見つかりませんでした。</p>"
    
    return html
    
@bp.route('/debug_article')
def debug_article():
    """特定記事のAI判定を確認"""
    article_url = request.args.get('url')
    
    if not article_url:
        return "URLパラメータが必要です。例: /news/debug_article?url=https://...", 400
    
    table = _table()
    pk = f"URL#{_hash_url(article_url)}"
    
    try:
        response = table.get_item(Key={"pk": pk, "sk": "METADATA"})
        item = response.get('Item')
        
        if item:
            html = f"""
            <h1>AI判定結果</h1>
            <h2>基本情報</h2>
            <p><strong>Title:</strong> {item.get('title')}</p>
            <p><strong>URL:</strong> <a href="{item.get('url')}" target="_blank">{item.get('url')}</a></p>
            <p><strong>Source:</strong> {item.get('source')}</p>
            <p><strong>Kind:</strong> {item.get('kind')}</p>
            <p><strong>Lang:</strong> {item.get('lang')}</p>
            <p><strong>Published:</strong> {item.get('published_at')}</p>
            
            <h2>収集時の要約</h2>
            <p><strong>Summary:</strong> {item.get('summary')}</p>
            
            <h2>AI判定</h2>
            <p><strong>AI Relevant:</strong> {item.get('ai_relevant')}</p>
            <p><strong>AI Kind:</strong> {item.get('ai_kind')}</p>
            <p><strong>AI Reason:</strong> {item.get('ai_reason')}</p>
            <p><strong>AI Summary:</strong> {item.get('ai_summary')}</p>
            <p><strong>Search Query:</strong> {item.get('ai_search_query')}</p>
            """
            return html
        else:
            return f"記事が見つかりません: {article_url}", 404
            
    except Exception as e:
        import traceback
        return f"<pre>{traceback.format_exc()}</pre>", 500
    
@bp.route('/debug_dental_plaza')
def debug_dental_plaza():
    """dental-plazaの記事を全てリスト"""
    table = _table()
    
    response = table.scan()
    
    dental_plaza_items = []
    for item in response['Items']:
        url = item.get('url', '')
        if 'dental-plaza' in url:
            dental_plaza_items.append(item)
    
    html = f"<h1>Dental Plaza Articles ({len(dental_plaza_items)}件)</h1>"
    
    for item in dental_plaza_items:
        html += f"""
        <div style="margin-bottom: 20px; border: 1px solid #ccc; padding: 10px;">
            <h3>{item.get('title')}</h3>
            <p><strong>URL:</strong> <a href="{item.get('url')}" target="_blank">{item.get('url')}</a></p>
            <p><strong>Kind:</strong> {item.get('kind')} | <strong>Lang:</strong> {item.get('lang')}</p>
            <p><strong>Published:</strong> {item.get('published_at')}</p>
            <p><strong>Search Query:</strong> {item.get('ai_search_query')}</p>
            <p><strong>AI Reason:</strong> {item.get('ai_reason')}</p>
            <hr>
            <p><a href="/news/debug_article?url={item.get('url')}" target="_blank">詳細を見る</a></p>
        </div>
        """
    
    return html

@bp.route("/admin/check_chinese_article")
def check_chinese_article():
    """中国記事の存在確認"""
    table = current_app.config["DENTAL_TABLE"]
    
    # 全記事をスキャンして中国関連を検索
    response = table.scan(
        FilterExpression="contains(title, :keyword)",
        ExpressionAttributeValues={
            ':keyword': '中国'
        }
    )
    
    return jsonify({
        "found": len(response.get('Items', [])),
        "items": response.get('Items', [])
    })


@bp.route("/admin/count_by_kind")
def count_by_kind():
    """種類別の記事数を確認"""
    table = current_app.config["DENTAL_TABLE"]
    
    kind_counts = {}
    langs = ["ja", "en"]
    
    for lang in langs:
        for kind in ["research", "case", "news", "video", "product", "market"]:
            items, count = dental_query_items(kind=kind, lang=lang, limit=1000)
            key = f"{kind}_{lang}"
            kind_counts[key] = len(items)
    
    # 全体の統計
    total_ja = sum(v for k, v in kind_counts.items() if k.endswith('_ja'))
    total_en = sum(v for k, v in kind_counts.items() if k.endswith('_en'))
    
    return jsonify({
        "by_kind_and_lang": kind_counts,
        "summary": {
            "total_ja": total_ja,
            "total_en": total_en,
            "total": total_ja + total_en
        },
        "news_ja": kind_counts.get("news_ja", 0),
        "news_en": kind_counts.get("news_en", 0),
        "total_news": kind_counts.get("news_ja", 0) + kind_counts.get("news_en", 0)
    })
