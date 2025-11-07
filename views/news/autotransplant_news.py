from __future__ import annotations
import base64, json, time, logging, traceback
from flask import render_template, request, current_app
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from urllib.parse import quote_plus
import feedparser
from hashlib import sha256 as _sha
from . import bp
from flask import render_template, request, current_app, jsonify

logger = logging.getLogger(__name__)

# ========= 共通ユーティリティ =========
def _d(msg: str):
    """DEBUG出力（Flask DEBUG時は必ず出す）"""
    try:
        if current_app and current_app.debug:
            print(msg)
            logger.info(msg)
        else:
            # 本番でも最低限は残したい場合はlogger側に委譲
            logger.info(msg)
    except Exception:
        # app コンテキスト外でも落ちないように
        print(msg)

# ========= DynamoDB I/O =========
def _table():
    return current_app.config["DENTAL_TABLE"]

def _hash_url(url: str) -> str:
    return _sha(url.encode()).hexdigest()

def put_unique_dental(item: dict) -> bool:
    pk = f"URL#{_hash_url(item['url'])}"
    try:
        _table().put_item(
            Item={
                "pk": pk, "sk": "METADATA",
                "url": item["url"], "title": item.get("title"),
                "source": item.get("source"), "kind": item.get("kind"),
                "lang": item.get("lang"), "published_at": item.get("published_at"),
                "summary": item.get("summary"), "image_url": item.get("image_url"),
                "author": item.get("author"),
                "gsi1pk": f"KIND#{item.get('kind')}#LANG#{item.get('lang')}",
                "gsi1sk": item.get("published_at") or "0001-01-01T00:00:00Z",
            },
            ConditionExpression="attribute_not_exists(pk)"
        )
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise

def dental_query_items(kind="research", lang="ja", limit=40, last_evaluated_key=None):
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

# ========= 関連度フィルタ（自家歯牙移植に特化） =========
JA_POS = [
    "自家歯牙移植", "自家歯移植", "歯牙移植", "歯の移植", "移植歯",
    "ドナーレプリカ", "デジタルドナーレプリカ", "レプリカ", "3d レプリカ", "3Ｄ レプリカ",
    "レシピエント窩", "移植窩", "受容窩",
    "歯根膜", "pd l", "口腔外科", "歯科", "口腔"
]
EN_POS = [
    "tooth autotransplantation", "autogenous tooth transplantation",
    "tooth transplantation", "dental replica", "donor replica",
    "replica-assisted", "recipient socket", "periodontal ligament", "pdl",
    "oral", "dentistry", "dental"
]
# 明確にノイズな領域
JA_NEG = ["眼科", "緑内障", "白内障", "眼", "角膜", "股関節", "膝関節", "整形外科",
          "ペースメーカー", "乳房", "美容", "形成外科"]
EN_NEG = ["ophthalmology", "glaucoma", "cataract", "eye", "cornea",
          "hip", "knee", "orthopedic", "pacemaker", "breast", "cosmetic", "aesthetic"]

def _lc(s: str | None) -> str:
    return (s or "").lower()

def is_relevant(title: str | None, summary: str | None, lang: str) -> bool:
    if not title:
        return False
    t = (title or "").lower()
    s = (summary or "").lower()
    text = f"{t} {s}"

    if lang == "ja":
        allow = [
            "自家歯牙移植","自家歯移植","歯牙移植","歯の移植","歯の自家移植",
            "ドナーレプリカ","レプリカ 手術","移植窩","移植窩形成","cbct",
            "3d プリンタ","デジタル レプリカ","歯科","口腔","口腔外科"
        ]
        # 非歯科 or 広告/医院紹介ワードを弾く
        deny = [
            "乳房インプラント","インプラント医院","おすすめ","ランキング","費用","名医","口コミ","広告",
            "腎","腎移植","肝","肝移植","角膜","骨移植","皮膚移植","臓器","移植片"
        ]
    else:
        allow = [
            "tooth autotransplantation","autogenous tooth transplantation","autotransplanted tooth",
            "tooth transplantation","donor tooth replica","recipient site","alveolar socket",
            "cbct","3d print","3d-printed","dental","dentistry","oral","maxillofacial"
        ]
        deny = [
            "kidney","renal","liver","hepatic","corneal","bone graft","skin graft","organ","allograft","xenograft",
            "implant clinic","best clinic","cost","pricing","cosmetic","whitening","aligner","ad"
        ]

    if any(x in text for x in (d.lower() for d in deny)):
        return False
    return any(x in text for x in (a.lower() for a in allow))


def classify_kind(title: str) -> str:
    t = (title or "").lower()
    if any(w in t for w in ["症例", "case report", "clinical case"]):
        return "case"
    if any(w in t for w in ["動画", "video", "tutorial", "technique"]):
        return "video"
    return "research"

# ========= 収集器 =========
def _iso_now_utc():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def fetch_google_news_dental(query="自家歯牙移植", lang="ja"):
    # クエリを OR/括弧 で強化（Google News RSS 検索）
    if lang == "ja":
        q = (
            '('
            '"自家歯牙移植" OR "自家歯移植" OR "歯牙移植" '
            'OR "ドナー歯" OR "レプリカ 移植" OR "移植窩 形成"'
            ') '
            '("歯" OR "歯科" OR "口腔")'
        )
        hl, gl, ceid = "ja", "JP", "JP:ja"
    else:
        q = (
            '('
            '"tooth autotransplantation" OR "autogenous tooth transplantation" '
            'OR "tooth transplantation" OR "donor tooth" OR "digital replica"'
            ') '
            '(dental OR dentistry OR oral)'
        )
        hl, gl, ceid = "en", "US", "US:en"

    # 追加の seed query を受け取ったら含める（backward compatibility）
    if query:
        q = f'({q}) OR ("{query}")'

    url = f"https://news.google.com/rss/search?q={quote_plus(q)}&hl={hl}&gl={gl}&ceid={ceid}"

    start = time.time()
    feed = feedparser.parse(url)
    saved = 0
    for e in feed.entries:
        link = getattr(e, "link", None)
        if not link:
            continue
        title = (getattr(e, "title", "") or "").strip()
        summary = getattr(e, "summary", None)

        # フィルタ：自家歯牙移植関連以外は除外
        if not is_relevant(title, summary, lang):
            continue

        kind = classify_kind(title)

        # 可能なら RSS の published/updated を使う（無ければ now）
        pub = getattr(e, "published", None) or getattr(e, "updated", None)
        published_at = _iso_now_utc()
        if pub:
            try:
                # feedparser は parsed も提供する場合あり
                if getattr(e, "published_parsed", None):
                    import datetime, time as _time
                    tm = e.published_parsed
                    published_at = datetime.datetime.utcfromtimestamp(_time.mktime(tm)).strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                pass

        item = {
            "source": "google_news",
            "kind": kind,
            "title": title,
            "url": link,
            "published_at": published_at,
            "summary": summary,
            "author": getattr(getattr(e, "source", None) or {}, "title", None),
            "image_url": None,
            "lang": lang,
        }
        if put_unique_dental(item):
            saved += 1
    _d(f"[COLLECT] GN {lang} saved={saved} (took {time.time()-start:.2f}s) url={url}")
    return saved

def fetch_pubmed_articles(query="autotransplantation"):
    """現状はダミー1件（将来正式APIに差し替え）"""
    sample = [{
        "source": "pubmed", "kind": "research",
        "title": "Digital replica-assisted autotransplantation: A systematic review",
        "url": "https://pubmed.ncbi.nlm.nih.gov/sample1",
        "published_at": "2025-01-10T00:00:00Z",
        "summary": "A comprehensive review ...",
        "author": "Journal of Oral Surgery",
        "image_url": None, "lang": "en",
    }]
    count = 0
    for item in sample:
        if put_unique_dental(item):
            count += 1
            _d(f"[PUT][PubMed] saved title={item['title']!r}")
    return count

def fetch_youtube_dental(query="tooth autotransplantation", lang="en"):
    if lang == "ja":
        q = '自家歯牙移植|自家歯移植|歯牙移植|ドナー歯|レプリカ 移植'
    else:
        q = 'tooth autotransplantation|autogenous tooth transplantation|tooth transplantation|donor tooth|digital replica'
    url = f"https://www.youtube.com/feeds/videos.xml?search_query={quote_plus(q)}"

    feed = feedparser.parse(url)
    count = 0
    for e in feed.entries:
        link = getattr(e, "link", None)
        if not link:
            continue
        title = (getattr(e, "title", "") or "").strip()
        if not is_relevant(title, None, lang):
            continue
        thumb = None
        media = getattr(e, "media_thumbnail", None)
        if media and len(media) > 0:
            thumb = media[0].get("url")
        item = {
            "source": "youtube_rss", "kind": "video",
            "title": title, "url": link, "published_at": _iso_now_utc(),
            "summary": None, "author": getattr(e, "author", None),
            "image_url": thumb, "lang": lang,
        }
        if put_unique_dental(item):
            count += 1
    _d(f"[COLLECT] YT {lang} saved={count} url={url}")
    return count

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

def collect_autotransplant_news():
    """全収集を回し、詳細なDEBUGログを出す"""
    results = {
        "google_news_ja": 0,
        "google_news_en": 0,
        "pubmed": 0,
        "youtube_ja": 0,
        "youtube_en": 0,
        "_errors": []
    }

    def _step(label, fn, *args, sleep_sec=1):
        try:
            before = time.time()
            cnt = fn(*args)
            _d(f"[COLLECT] {label}: saved={cnt} (took {time.time()-before:.2f}s)")
            return cnt
        except Exception as e:
            msg = f"{label} failed: {e}"
            results["_errors"].append(msg)
            print("[ERROR]", msg)
            traceback.print_exc()
            return 0
        finally:
            if sleep_sec:
                time.sleep(sleep_sec)

    # Google News (ja)
    results["google_news_ja"] += _step("GN ja 自家歯牙移植",       fetch_google_news_dental, "自家歯牙移植", "ja")
    results["google_news_ja"] += _step("GN ja 歯牙移植 症例",      fetch_google_news_dental, "歯牙移植 症例", "ja")
    results["google_news_ja"] += _step("GN ja ドナーレプリカ",     fetch_google_news_dental, "ドナーレプリカ", "ja")

    # Google News (en)
    results["google_news_en"] += _step("GN en autotransplantation",     fetch_google_news_dental, "autotransplantation", "en")
    results["google_news_en"] += _step("GN en tooth transplantation",   fetch_google_news_dental, "tooth transplantation", "en")

    # PubMed（ダミー）
    results["pubmed"] += _step("PubMed autotransplantation", fetch_pubmed_articles, "autotransplantation")

    # YouTube（必要なら有効）
    # results["youtube_ja"] += _step("YT ja 自家歯牙移植 手術", fetch_youtube_dental, "自家歯牙移植 手術", "ja")
    # results["youtube_en"] += _step("YT en tooth autotransplantation surgery", fetch_youtube_dental, "tooth autotransplantation surgery", "en")

    total = sum(v for k, v in results.items() if not k.startswith("_"))
    _d(f"[COLLECT] total_saved={total} breakdown={results}")
    return total, results

@bp.route("/admin/cleanup_irrelevant", endpoint="news_admin_cleanup_irrelevant", strict_slashes=False)
@bp.route("/admin/cleanup_irrelevant/", endpoint="news_admin_cleanup_irrelevant_slash", strict_slashes=False)
def news_admin_cleanup_irrelevant():
    """自家歯牙移植に関係ない記事を除去（タイトル/要約で is_relevant 判定）。"""
    target = [
        ("research", "ja"), ("case", "ja"), ("video", "ja"),
        ("research", "en"), ("case", "en"), ("video", "en"),
    ]
    removed = 0
    checked = 0

    for kind, lang in target:
        lek = None
        while True:
            items, next_lek = dental_query_items(kind=kind, lang=lang, limit=40, last_evaluated_key=lek)
            if not items and not next_lek:
                break

            for it in items or []:
                checked += 1
                title = it.get("title")
                summary = it.get("summary")

                if not is_relevant(title, summary, lang):
                    try:
                        pk, sk = it["pk"], it["sk"]
                        _table().delete_item(Key={"pk": pk, "sk": sk})
                        removed += 1
                    except Exception as e:
                        _d(f"[CLEANUP][WARN] delete failed pk={it.get('pk')} err={e}")

            if not next_lek:
                break
            lek = next_lek

    msg = f"[CLEANUP] checked={checked} removed={removed}"
    _d(msg)
    return msg

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

@bp.route("/admin/run_autotransplant_news")
def run_autotransplant_news():
    total = collect_autotransplant_news()
    # 直後に gsi1 で1件拾えるか確認
    items, _ = dental_query_items(kind="research", lang="ja", limit=1)
    _d(f"[DEBUG] after collect: total={total}, first={items[0] if items else 'NONE'}")
    return f"collect ok (total={total}, first_kind_ja={'HIT' if items else 'NONE'})"

@bp.route("/api/latest")  # ← url_prefix="/news" 前提。最終URLは /news/api/latest
def news_api_latest():
    kind = request.args.get("kind", "research")
    lang = request.args.get("lang", "ja")
    limit = min(int(request.args.get("limit", 5)), 20)

    items, _ = dental_query_items(kind=kind, lang=lang, limit=limit, last_evaluated_key=None)
    payload = [
        {
            "title": it.get("title"),
            "url": it.get("url"),
            "published_at": (it.get("published_at") or "")[:10],
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

# ========== テスト(1件投入) ==========
@bp.route("/news/admin/put_demo_one")
def put_demo_one():
    item = {
        "source": "demo", "kind": "research", "title": "デモ記事（表示テスト）",
        "url": "https://example.com/demo-unique-001",
        "published_at": "2025-01-01T00:00:00Z",
        "summary": "demo", "author": "Demo", "image_url": None, "lang": "ja",
    }
    ok = put_unique_dental(item)
    return f"demo put: {ok}"

@bp.route("/admin/inspect")
def news_admin_inspect():
    kinds = ["research", "case", "video"]
    langs = ["ja", "en"]
    lines = []
    for k in kinds:
        for lg in langs:
            items, _ = dental_query_items(kind=k, lang=lg, limit=5)
            titles = [i.get("title") for i in items]
            lines.append(f"{k}/{lg}: count~{len(items)} sample={titles}")
    _d("[INSPECT] " + " | ".join(lines))
    # 簡易にプレーン表示
    return "<br>".join(lines)

# --- 管理用：ダンプ（research/ja を20件一覧） ---
@bp.route("/admin/debug_dump")
def news_admin_debug_dump():
    items, _ = dental_query_items(kind="research", lang="ja", limit=20)
    html = ["<h3>research/ja (top 20)</h3><ol>"]
    for it in items:
        html.append(f"<li>{it.get('published_at','')} — {it.get('title','')}<br>"
                    f"<small>{it.get('url','')}</small></li>")
    html.append("</ol>")
    return "".join(html)
