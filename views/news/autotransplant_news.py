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
import re 

logger = logging.getLogger(__name__)

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
                # 追加フィールド（存在すれば保存、無ければスキップでOK）
                "ai_relevant": item.get("ai_relevant"),         # bool
                "ai_kind": item.get("ai_kind"),                 # str
                "ai_summary": item.get("ai_summary"),           # 140字など短要約
                "ai_reason": item.get("ai_reason"),             # 採否の理由（管理用）
                "ai_prompt_id": item.get("ai_prompt_id"),       # プロンプトのハッシュなど
                "ai_score_semantic": item.get("ai_score_semantic"),  # 任意：前段スコア
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

# ========= 関連度フィルタ（自家歯牙移植に特化・強化版） =========
JA_POS = [
    "自家歯牙移植", "自家歯移植", "歯牙移植", "歯の移植", "移植歯",
    "ドナーレプリカ", "デジタルドナーレプリカ", "レプリカ", "3d レプリカ", "3Ｄ レプリカ",
    "レシピエント窩", "移植窩", "受容窩",
    "歯根膜", "pd l", "口腔外科", "歯科", "口腔",
    # 製品関連（会話から追加）
    "アルベオシェーバー", "アルベオ・シェーバー", "sk シリーズ", "sk-スピンドル",
    # 技術関連
    "3dプリント", "3dプリンター", "デジタル歯科", "cad/cam",
    # 症例関連
    "前歯 移植", "上顎中切歯", "親知らず 前歯", "中切歯 移植",
]
EN_POS = [
    "tooth autotransplantation", "autogenous tooth transplantation",
    "tooth transplantation", "dental replica", "donor replica",
    "replica-assisted", "recipient socket", "periodontal ligament", "pdl",
    "oral", "dentistry", "dental",
    # 製品・技術関連
    "alveo shaver", "3d printed replica", "digital dentistry",
    "cad/cam", "digital workflow",
    # 症例関連
    "anterior tooth", "central incisor", "maxillary incisor", "wisdom tooth anterior",
]

# 明確にノイズな領域（インプラントは除外リストから削除 - 比較記事は有用）
JA_NEG = ["眼科", "緑内障", "白内障", "眼", "角膜", "股関節", "膝関節", "整形外科",
          "ペースメーカー", "乳房", "美容外科", "豊胸"]
EN_NEG = ["ophthalmology", "glaucoma", "cataract", "eye", "cornea",
          "hip", "knee", "orthopedic", "pacemaker", "breast augmentation"]

def _lc(s: str | None) -> str:
    return (s or "").lower()

# 主題判定に使う語（強化版）
_CORE_JA = [
    r"自家?歯牙?移植", r"歯牙移植", r"歯の移植", r"自家移植",
    r"智歯.*移植", r"余剰歯.*移植", r"ドナー歯",
    r"親知らず.*移植", r"第三大臼歯.*移植",
]
_SUPP_JA = [
    r"レプリカ.*(移植|移動|窩|窩形成)", r"移植窩", r"歯根膜.*(温存|保存|再生)",
    r"3D.?プリンタ?.*(移植|レプリカ|シミュレーション)",
    r"アルベオ.?シェーバー", r"デジタル.*(ドナー|レプリカ|移植)",
    r"(前歯|中切歯|上顎).*(移植|親知らず)", r"口腔外科.*(移植|再植)",
]
_PRODUCT_JA = [
    r"アルベオ.?シェーバー", r"SK.?シリーズ", r"歯牙移植.*(器具|製品|バー)",
    r"移植.*(3D|デジタル).*(プリント|レプリカ)",
]

_CORE_EN = [
    r"tooth\s+autotransplant", r"autogenous\s+tooth\s+transplant",
    r"tooth\s+transplantation", r"donor\s+tooth",
    r"wisdom\s+tooth.*transplant", r"third\s+molar.*transplant",
]
_SUPP_EN = [
    r"digital\s+replica.*(socket|site|graft|transplant)",
    r"periodontal.*(ligament|PDL).*(preserv|healing|regenerat)",
    r"supernumerary.*tooth.*transplant",
    r"(anterior|incisor).*autotransplant",
    r"3D.?(print|replica).*(transplant|donor)",
]
_PRODUCT_EN = [
    r"alveo.?shaver", r"transplant.*(instrument|device|tool)",
    r"digital.*replica.*system", r"3D.*print.*dental.*transplant",
]

# 参照語（主題判定の補助）
_IMPLANT_JA = [r"インプラント"]
_IMPLANT_EN = [r"\bimplant(s)?\b"]

def _count_hits(patterns, text: str) -> int:
    return sum(1 for p in patterns if re.search(p, text, re.IGNORECASE))

def is_relevant(title: str | None, summary: str | None, lang: str = "ja") -> bool:
    """
    自家歯牙移植に関連するかを判定（強化版）
    - 製品情報も含める
    - 症例報告（前歯への移植など）も含める
    - 技術情報（3Dプリント、デジタルワークフロー）も含める
    """
    text = f"{(title or '')} {(summary or '')}"
    
    if lang == "ja":
        core = _count_hits(_CORE_JA, text)
        supp = _count_hits(_SUPP_JA, text)
        prod = _count_hits(_PRODUCT_JA, text)
        impl = _count_hits(_IMPLANT_JA, text)
        neg = _count_hits(JA_NEG, text)
    else:
        core = _count_hits(_CORE_EN, text)
        supp = _count_hits(_SUPP_EN, text)
        prod = _count_hits(_PRODUCT_EN, text)
        impl = _count_hits(_IMPLANT_EN, text)
        neg = _count_hits(EN_NEG, text)

    # 明確なノイズは除外
    if neg > 0:
        return False

    # ルール:
    # 1) コア語が1つでもあれば採用
    if core >= 1:
        return True

    # 2) 製品情報：製品語が1つ以上 + (補助語1つ以上 または タイトルに「移植」)
    if prod >= 1 and (supp >= 1 or re.search(r"移植|transplant", text, re.IGNORECASE)):
        return True

    # 3) コアが0でも、補助語が複数（>=2）で移植文脈が濃ければ採用
    if core == 0 and supp >= 2:
        return True

    # 4) インプラント比較記事：インプラント語があっても、補助語が1つ以上あれば採用
    if impl >= 1 and supp >= 1:
        return True

    return False


def classify_kind(title: str) -> str:
    """記事種類の分類（強化版）"""
    t = (title or "").lower()
    
    # 製品情報
    if any(w in t for w in ["製品", "product", "器具", "instrument", "device", 
                            "アルベオ", "alveo", "新発売", "release"]):
        return "product"
    
    # 症例報告
    if any(w in t for w in ["症例", "case report", "clinical case", "症例報告"]):
        return "case"
    
    # 動画・チュートリアル
    if any(w in t for w in ["動画", "video", "tutorial", "technique", "手術", "surgery"]):
        return "video"
    
    # 市場レポート
    if any(w in t for w in ["市場", "market", "動向", "trend", "統計", "statistics"]):
        return "market"
    
    # デフォルトは研究・一般記事
    return "research"

# ========= 収集器 =========
def _iso_now_utc():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def fetch_google_news_dental(query="自家歯牙移植", lang="ja"):
    """
    Google News RSS検索（強化版）
    製品情報、症例報告、技術情報も含める
    """
    if lang == "ja":
        q = (
            '('
            '"自家歯牙移植" OR "自家歯移植" OR "歯牙移植" '
            'OR "ドナー歯" OR "レプリカ 移植" OR "移植窩 形成" '
            'OR "アルベオシェーバー" OR "3Dプリント 移植" '
            'OR "前歯 移植" OR "上顎中切歯 移植"'
            ') '
            '("歯" OR "歯科" OR "口腔")'
        )
        hl, gl, ceid = "ja", "JP", "JP:ja"
    else:
        q = (
            '('
            '"tooth autotransplantation" OR "autogenous tooth transplantation" '
            'OR "tooth transplantation" OR "donor tooth" OR "digital replica" '
            'OR "alveo shaver" OR "3D printed replica" '
            'OR "anterior autotransplantation" OR "wisdom tooth anterior"'
            ') '
            '(dental OR dentistry OR oral)'
        )
        hl, gl, ceid = "en", "US", "US:en"

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

        if not is_relevant(title, summary, lang):
            continue

        kind = classify_kind(title)

        pub = getattr(e, "published", None) or getattr(e, "updated", None)
        published_at = _iso_now_utc()
        if pub:
            try:
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
    """PubMed記事の収集（サンプル拡張版）"""
    sample = [
        {
            "source": "pubmed", "kind": "research",
            "title": "Digital replica-assisted autotransplantation: A systematic review",
            "url": "https://pubmed.ncbi.nlm.nih.gov/sample1",
            "published_at": "2025-01-10T00:00:00Z",
            "summary": "A comprehensive review of digital replica use in tooth autotransplantation...",
            "author": "Journal of Oral Surgery",
            "image_url": None, "lang": "en",
        },
        {
            "source": "pubmed", "kind": "case",
            "title": "Wisdom Tooth Autotransplantation for Maxillary Central Incisors Using 3D-Printed Replica",
            "url": "https://pubmed.ncbi.nlm.nih.gov/38947626",
            "published_at": "2024-07-01T00:00:00Z",
            "summary": "Case report of wisdom tooth transplantation to anterior region...",
            "author": "Journal of Oral Surgery",
            "image_url": None, "lang": "en",
        },
    ]
    count = 0
    for item in sample:
        if put_unique_dental(item):
            count += 1
            _d(f"[PUT][PubMed] saved title={item['title']!r}")
    return count

def fetch_youtube_dental(query="tooth autotransplantation", lang="en"):
    if lang == "ja":
        q = '自家歯牙移植|自家歯移植|歯牙移植|ドナー歯|レプリカ 移植|アルベオシェーバー'
    else:
        q = 'tooth autotransplantation|autogenous tooth transplantation|tooth transplantation|donor tooth|digital replica|alveo shaver'
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
    """
    全収集を実行（強化版）
    - 製品情報も収集
    - 症例報告（前歯への移植など）も収集
    - 技術情報（3Dプリント、デジタルワークフロー）も収集
    """
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

    # Google News (ja) - クエリを拡張
    results["google_news_ja"] += _step("GN ja 自家歯牙移植", fetch_google_news_dental, "自家歯牙移植", "ja")
    results["google_news_ja"] += _step("GN ja 歯牙移植 症例", fetch_google_news_dental, "歯牙移植 症例", "ja")
    results["google_news_ja"] += _step("GN ja ドナーレプリカ", fetch_google_news_dental, "ドナーレプリカ", "ja")
    results["google_news_ja"] += _step("GN ja アルベオシェーバー", fetch_google_news_dental, "アルベオシェーバー 歯牙移植", "ja")
    results["google_news_ja"] += _step("GN ja 前歯 移植", fetch_google_news_dental, "前歯 親知らず 移植", "ja")
    results["google_news_ja"] += _step("GN ja 3Dプリント 移植", fetch_google_news_dental, "3Dプリント 歯牙移植", "ja")

    # Google News (en) - クエリを拡張
    results["google_news_en"] += _step("GN en autotransplantation", fetch_google_news_dental, "autotransplantation", "en")
    results["google_news_en"] += _step("GN en tooth transplantation", fetch_google_news_dental, "tooth transplantation", "en")
    results["google_news_en"] += _step("GN en digital replica", fetch_google_news_dental, "digital replica transplant", "en")
    results["google_news_en"] += _step("GN en anterior autotransplant", fetch_google_news_dental, "anterior tooth autotransplantation", "en")

    # PubMed（拡張サンプル）
    results["pubmed"] += _step("PubMed autotransplantation", fetch_pubmed_articles, "autotransplantation")

    # YouTube（必要に応じて有効化）
    results["youtube_ja"] += _step("YT ja 自家歯牙移植", fetch_youtube_dental, "自家歯牙移植 手術", "ja")
    results["youtube_en"] += _step("YT en tooth autotransplantation", fetch_youtube_dental, "tooth autotransplantation surgery", "en")

    total = sum(v for k, v in results.items() if not k.startswith("_"))
    _d(f"[COLLECT] total_saved={total} breakdown={results}")
    return total, results

@bp.route("/admin/cleanup_irrelevant", endpoint="news_admin_cleanup_irrelevant", strict_slashes=False)
@bp.route("/admin/cleanup_irrelevant/", endpoint="news_admin_cleanup_irrelevant_slash", strict_slashes=False)
def news_admin_cleanup_irrelevant():
    """自家歯牙移植に関係ない記事を除去（強化版フィルタ適用）"""
    target = [
        ("research", "ja"), ("case", "ja"), ("video", "ja"), ("product", "ja"), ("market", "ja"),
        ("research", "en"), ("case", "en"), ("video", "en"), ("product", "en"), ("market", "en"),
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
                        _d(f"[CLEANUP] removed: {title}")
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
    total, results = collect_autotransplant_news()
    items, _ = dental_query_items(kind="research", lang="ja", limit=1)
    _d(f"[DEBUG] after collect: total={total}, first={items[0] if items else 'NONE'}")
    return f"collect ok (total={total}, breakdown={results}, first_kind_ja={'HIT' if items else 'NONE'})"

@bp.route("/api/latest")
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