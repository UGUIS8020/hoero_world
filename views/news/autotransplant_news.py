from __future__ import annotations
import base64, json, time, logging, traceback, os
from flask import render_template, request, current_app, jsonify
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from urllib.parse import quote_plus
import feedparser
from hashlib import sha256 as _sha
from . import bp
import requests
import xml.etree.ElementTree as ET
from datetime import datetime

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
                # AI判定結果を保存
                "ai_relevant": item.get("ai_relevant"),
                "ai_kind": item.get("ai_kind"),
                "ai_summary": item.get("ai_summary"),
                "ai_reason": item.get("ai_reason"),
                "ai_search_query": item.get("ai_search_query"),
                "ai_headline": item.get("ai_headline"),
            }),
            ConditionExpression="attribute_not_exists(pk)"
        )
        _d(f"[DB] ✅ Saved: {item.get('title', '')[:60]}")  # ★ 成功ログ
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            _d(f"[DB] ⚠️ Already exists: {item.get('title', '')[:60]}")  # ★ 重複ログ
            return False
        _d(f"[DB] ❌ Error saving: {e}")  # ★ エラーログ
        raise
    except Exception as e:
        _d(f"[DB] ❌ Unexpected error: {e}")  # ★ その他のエラー
        traceback.print_exc()
        raise

def dental_query_items(kind="research", lang="ja", limit=40, last_evaluated_key=None):
    """歯科ニュース用クエリ関数"""
    kwargs = {
        "IndexName": "gsi1",
        "KeyConditionExpression": Key("gsi1pk").eq(f"KIND#{kind}#LANG#{lang}"),
        "ScanIndexForward": False,
        "Limit": limit,
    }
    if last_evaluated_key:
        kwargs["ExclusiveStartKey"] = last_evaluated_key
    resp = _table().query(**kwargs)
    return resp.get("Items", []), resp.get("LastEvaluatedKey")

# ========= AI収集機能 =========
def ai_filter_and_classify(title: str, summary: str | None, lang: str = "ja") -> dict:
    """AIで記事の関連度判定と分類（OpenAI版）"""
    prompt = f"""以下の記事が「自家歯牙移植（tooth autotransplantation）」に関連するか判定してください。

【記事情報】
タイトル: {title}
要約: {summary or "なし"}

【判定基準】
関連する内容：
- 自家歯牙移植、歯牙移植、歯の移植に関する技術・研究・症例
- ドナーレプリカ、3Dプリント、デジタルワークフローなどの関連技術
- 移植用の製品・医療機器（アルベオシェーバーなど）
- 親知らずや余剰歯を使った移植症例
- 前歯への移植など具体的な症例報告
- インプラントとの比較記事

除外する内容：
- 眼科、整形外科、美容外科など明らかに無関係な分野
- 臓器移植など歯科以外の移植

【記事分類】
- research: 研究・一般記事
- case: 症例報告
- video: 動画・チュートリアル  
- product: 製品情報・医療機器
- market: 市場レポート・統計

【出力要件】
- ai_summary と headline_ja は必ず**日本語**で書いてください
- headline_ja はおおよそ20文字以内の短い見出しとし、体言止めを推奨します
  例: 「3Dレプリカを用いた移植術」「親知らず移植の長期予後」など

以下のJSON形式で回答してください：
{{
  "relevant": true/false,
  "kind": "research/case/video/product/market",
  "ai_summary": "記事の要点を40〜80字程度の日本語1文で要約。可能であれば『どのような患者・歯』『どんな方法（3Dプリントやガイド手術など）』『どんな結果・意義（長期予後や審美性の改善など）』が分かるようにしてください。タイトルの言い換えだけの短いフレーズにはしないでください。",
  "headline_ja": "30〜45文字程度の自然な日本語の見出し。名詞の羅列ではなく、『〜を報告』『〜が示された』『〜により改善した』『〜の症例』などの表現を含む文章調にしてください。原題の直訳ではなく、日本の歯科ニュースサイト風の読みやすい見出しにしてください。",
  "reason": "判定理由を簡潔に（日本語）"
}}

DO NOT OUTPUT ANYTHING OTHER THAN VALID JSON."""

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
                "max_tokens": 1000,
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
        result = json.loads(result_text)
        
        return {
            "relevant": result.get("relevant", False),
            "kind": result.get("kind", "research"),
            "ai_summary": result.get("ai_summary", ""),
            "ai_headline": result.get("headline_ja", ""),  # ★ ここで変換
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
    collected_urls = set()
    all_items = []
    search_history = []
    
    # 共通コンテキスト
    base_context = """あなたは自家歯牙移植（tooth autotransplantation）に関する
最新情報を収集する専門エージェントです。

以下の観点で幅広く情報を収集してください：
- 技術革新（3Dプリント、デジタルワークフロー、CAD/CAM）
- 新製品・医療機器（アルベオシェーバー、レプリカシステムなど）
- 臨床症例（特に前歯への移植、上顎中切歯、親知らずの活用など）
- 研究論文（成功率、長期予後、PDL保存など）
- 市場動向・統計データ
- 比較記事（インプラント vs 自家歯牙移植など）"""

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

                # ① Google News
                search_results.extend(_execute_google_search(query, lang))

                # ② PubMed（英語のみ）
                if lang == "en":
                    pubmed_results = _execute_pubmed_search(query, max_results=20)
                    search_results.extend(pubmed_results)
                
                for result_item in search_results:
                    if not result_item.get("url"):
                        continue
                    if result_item["url"] in collected_urls:
                        continue
                    
                    ai_result = ai_filter_and_classify(
                        result_item["title"], 
                        result_item.get("summary"), 
                        lang
                    )
                    
                    if ai_result["relevant"]:
                        result_item["lang"] = lang
                        result_item["kind"] = ai_result["kind"]
                        result_item["ai_relevant"] = ai_result["relevant"]
                        result_item["ai_kind"] = ai_result["kind"]
                        result_item["ai_summary"] = ai_result["ai_summary"]
                        result_item["ai_reason"] = ai_result["reason"]
                        result_item["ai_search_query"] = query
                        result_item["ai_headline"] = ai_result.get("ai_headline")
                        
                        all_items.append(result_item)
                        collected_urls.add(result_item["url"])
                        
                        _d(
                            f"[AI AGENT] ✓ Found: {result_item['title'][:60]}..."
                            f" (kind={ai_result['kind']}, lang={lang})"
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

            for result_item in search_results:
                if not result_item.get("url"):
                    continue
                if result_item["url"] in collected_urls:
                    continue

                ai_result = ai_filter_and_classify(
                    result_item["title"],
                    result_item.get("summary"),
                    "ja"
                )

                if not ai_result["relevant"]:
                    continue

                result_item["lang"] = "ja"
                result_item["kind"] = ai_result["kind"]
                result_item["ai_relevant"] = ai_result["relevant"]
                result_item["ai_kind"] = ai_result["kind"]
                result_item["ai_summary"] = ai_result["ai_summary"]
                result_item["ai_reason"] = ai_result["reason"]
                result_item["ai_search_query"] = query
                result_item["ai_headline"] = ai_result.get("ai_headline")

                all_items.append(result_item)
                collected_urls.add(result_item["url"])
                _d(
                    f"[AI AGENT] ✓ Fallback Found: {result_item['title'][:60]}..."
                    f" (kind={ai_result['kind']}, lang=ja)"
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
            "source": "google_news_ai",
            "title": title,
            "url": link,
            "published_at": published_at,
            "summary": summary,
            "author": getattr(getattr(e, "source", None) or {}, "title", None),
            "image_url": None,
            "lang": lang,
        })
    
    return items


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

    # ★ ここから追加：lang=all のときは ja + en をまとめて返す
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

            # ★ 見出しの優先順位: ai_headline > ai_summary > title
            headline = (
                it.get("ai_headline")
                or it.get("ai_summary")
                or it.get("title")
            )

            payload.append({
                "title": headline,
                "url": url,
                "published_at": (it.get("published_at") or "")[:10],
                "kind": it.get("kind"),
                "lang": it.get("lang"),
                "source": it.get("source"),
            })

            if len(payload) >= limit:
                break

        return jsonify({
            "kind": kind, "lang": "all",
            "count": len(payload),
            "updated_at": _iso_now_utc(),
            "items": payload,
        })

    # ★ ここから下は今までのまま（lang が ja / en のとき）
    items, _ = dental_query_items(kind=kind, lang=lang, limit=limit, last_evaluated_key=None)
    payload = [
        {
            "title": it.get("title"),
            "url": it.get("url"),
            "published_at": (it.get("published_at") or "")[:10],
            "kind": it.get("kind"),
        }
        for it in items
        if it.get("title") and it.get("url")
    ]
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
    kinds = ["research", "case", "video", "product", "market"]
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
    """全記事を削除（テスト用）"""
    try:
        # 全記事を取得して削除
        table = _table()
        deleted = 0
        
        # 全種類・全言語をスキャン
        for kind in ["research", "case", "video", "product", "market"]:
            for lang in ["ja", "en"]:
                lek = None
                while True:
                    items, next_lek = dental_query_items(kind=kind, lang=lang, limit=100, last_evaluated_key=lek)
                    
                    for item in items:
                        table.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
                        deleted += 1
                    
                    if not next_lek:
                        break
                    lek = next_lek
        
        return f"削除完了: {deleted}件の記事を削除しました"
    except Exception as e:
        return f"エラー: {e}"
    




