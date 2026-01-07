"""
PubMed論文の全文をセクションごとに分割してQdrant (raiden-main) に保存するモジュール

特徴:
- PMCから全文を取得（Open Access論文のみ）
- セクションごとに分割（Abstract, Introduction, Methods, Results, Discussion, Conclusions）
- 英語・日本語の両方で保存
- PMCで全文が取得できない場合はアブストラクトのみ保存
- IDベースの重複チェック（インデックス不要）

使用方法:
    from pubmed_fulltext_vector_store import save_pubmed_items_to_qdrant
    
    # ニュース収集後に呼び出し
    save_pubmed_items_to_qdrant(all_items)
"""

import os
import re
import uuid
import time
import requests
import xml.etree.ElementTree as ET
import openai
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct
from dotenv import load_dotenv
from typing import Dict, List, Optional

load_dotenv()

QDRANT_COLLECTION = "raiden-main"

# セクション検出用のキーワード
SECTION_KEYWORDS = {
    "introduction": ["introduction", "background"],
    "methods": ["methods", "materials and methods", "methodology", "experimental"],
    "results": ["results", "findings"],
    "discussion": ["discussion"],
    "conclusions": ["conclusion", "conclusions", "summary"]
}


class PubMedFullTextVectorStore:
    def __init__(self):
        self.openai_client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.qdrant_client = QdrantClient(
            url=os.getenv("QDRANT_URL"),
            api_key=os.getenv("QDRANT_API_KEY")
        )
    
    def get_embedding(self, text: str) -> list:
        """テキストのembeddingを生成"""
        max_chars = 8000
        if len(text) > max_chars:
            text = text[:max_chars]
        
        response = self.openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=text
        )
        return response.data[0].embedding
    
    def translate_to_japanese(self, text: str, section: str) -> str:
        """テキストを日本語に翻訳"""
        if not text or len(text.strip()) < 10:
            return ""
        
        max_chars = 6000
        if len(text) > max_chars:
            text = text[:max_chars]
        
        section_names = {
            "abstract": "アブストラクト",
            "introduction": "序論",
            "methods": "材料と方法",
            "results": "結果",
            "discussion": "考察",
            "conclusions": "結論",
            "title": "タイトル"
        }
        section_ja = section_names.get(section, section)
        
        prompt = f"""以下の学術論文の{section_ja}を日本語に翻訳してください。
専門用語は適切な日本語訳を使用してください。

{text}"""

        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "歯科学の学術論文を翻訳する専門家です。自然で読みやすい日本語に翻訳してください。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"[ERROR] 翻訳エラー: {e}")
            return ""
    
    def get_pmcid_from_pmid(self, pmid: str) -> Optional[str]:
        """PMIDからPMCIDを取得"""
        try:
            url = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
            params = {"ids": pmid, "format": "json"}
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            records = data.get("records", [])
            if records and "pmcid" in records[0]:
                return records[0]["pmcid"]
            return None
        except Exception as e:
            print(f"[WARN] PMCID取得エラー (PMID {pmid}): {e}")
            return None
    
    def fetch_fulltext_from_pmc(self, pmcid: str) -> Optional[Dict[str, str]]:
        """PMCから全文XMLを取得してセクションごとにパース"""
        try:
            url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
            params = {
                "db": "pmc",
                "id": pmcid.replace("PMC", ""),
                "rettype": "xml"
            }
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            return self._parse_pmc_xml(response.text)
        except Exception as e:
            print(f"[WARN] PMC全文取得エラー ({pmcid}): {e}")
            return None
    
    def _parse_pmc_xml(self, xml_text: str) -> Dict[str, str]:
        """PMC XMLをパースしてセクションごとのテキストを抽出"""
        sections = {
            "abstract": "",
            "introduction": "",
            "methods": "",
            "results": "",
            "discussion": "",
            "conclusions": ""
        }
        
        try:
            root = ET.fromstring(xml_text)
            
            # アブストラクト
            abstract_elem = root.find(".//abstract")
            if abstract_elem is not None:
                sections["abstract"] = self._extract_text(abstract_elem)
            
            # 本文セクション
            body = root.find(".//body")
            if body is not None:
                for sec in body.findall(".//sec"):
                    title_elem = sec.find("title")
                    if title_elem is not None:
                        title = self._extract_text(title_elem).lower()
                        section_type = self._identify_section(title)
                        if section_type:
                            text = self._extract_text(sec)
                            title_text = self._extract_text(title_elem)
                            text = text.replace(title_text, "", 1).strip()
                            sections[section_type] += " " + text
            
            # テキストのクリーンアップ
            for key in sections:
                sections[key] = self._clean_text(sections[key])
            
            return sections
        except Exception as e:
            print(f"[ERROR] XMLパースエラー: {e}")
            return sections
    
    def _extract_text(self, element) -> str:
        """XML要素からテキストを抽出"""
        if element is None:
            return ""
        return "".join(element.itertext()).strip()
    
    def _identify_section(self, title: str) -> Optional[str]:
        """タイトルからセクションタイプを識別"""
        title_lower = title.lower()
        for section, keywords in SECTION_KEYWORDS.items():
            for keyword in keywords:
                if keyword in title_lower:
                    return section
        return None
    
    def _clean_text(self, text: str) -> str:
        """テキストをクリーンアップ"""
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        return text
    
    def _generate_point_id(self, pmid: str, section: str, lang: str) -> str:
        """一意のポイントIDを生成"""
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"pubmed_{pmid}_{section}_{lang}"))
    
    def check_exists(self, pmid: str, section: str, lang: str) -> bool:
        """IDベースで重複チェック（インデックス不要）"""
        point_id = self._generate_point_id(pmid, section, lang)
        try:
            result = self.qdrant_client.retrieve(
                collection_name=QDRANT_COLLECTION,
                ids=[point_id],
                with_payload=False,
                with_vectors=False
            )
            return len(result) > 0
        except Exception:
            return False
    
    def save_paper(self, item: dict) -> dict:
        """PubMed論文を全文・セクションごとにraiden-mainに保存"""
        pmid = item.get("pmid", "")
        if not pmid:
            url = item.get("url", "")
            if "pubmed.ncbi.nlm.nih.gov" in url:
                pmid = url.rstrip("/").split("/")[-1]
        
        if not pmid:
            print(f"[ERROR] PMIDが取得できません: {item.get('title', '')[:30]}")
            return {"saved": 0, "skipped": 0}
        
        title = item.get("title", "")
        abstract = item.get("summary", "")
        
        # PMCから全文取得を試行
        sections = {
            "abstract": abstract,
            "introduction": "",
            "methods": "",
            "results": "",
            "discussion": "",
            "conclusions": ""
        }
        
        pmcid = self.get_pmcid_from_pmid(pmid)
        fulltext_available = False
        
        if pmcid:
            print(f"[PMC] PMCID取得: {pmcid}")
            fulltext = self.fetch_fulltext_from_pmc(pmcid)
            if fulltext:
                for key, value in fulltext.items():
                    if value:
                        sections[key] = value
                fulltext_available = True
                print(f"[PMC] 全文取得成功")
            else:
                print(f"[PMC] 全文取得失敗、アブストラクトのみ使用")
        else:
            print(f"[PMC] PMCIDなし、アブストラクトのみ使用")
        
        stats = {"saved": 0, "skipped": 0}
        points = []
        
        # タイトルの日本語訳（一度だけ）
        title_ja = None
        
        # 各セクションを処理
        for section, text in sections.items():
            if not text or len(text.strip()) < 50:
                continue
            
            # === 英語版 ===
            if not self.check_exists(pmid, section, "en"):
                full_text = f"{title}\n\n[{section.upper()}]\n{text}"
                vector = self.get_embedding(full_text)
                
                points.append(PointStruct(
                    id=self._generate_point_id(pmid, section, "en"),
                    vector=vector,
                    payload={
                        "text": full_text,
                        "category": "dental",
                        "title": title,
                        "topic": "autotransplantation",
                        "items": [],
                        "type": "pubmed_paper",
                        "weight": 1.0 if section == "abstract" else 0.8,
                        "vector_id": f"pubmed_{pmid}_{section}_en",
                        "original_id": f"pubmed_{pmid}",
                        "pmid": pmid,
                        "pmcid": pmcid or "",
                        "section": section,
                        "section_text": text,
                        "journal": item.get("author", ""),
                        "published_date": item.get("published_at", ""),
                        "url": item.get("url", ""),
                        "source": "pubmed",
                        "lang": "en",
                        "fulltext_available": fulltext_available
                    }
                ))
                stats["saved"] += 1
                print(f"  [EN] {section}: 準備完了")
            else:
                stats["skipped"] += 1
                print(f"  [EN] {section}: スキップ（既存）")
            
            # === 日本語版 ===
            if not self.check_exists(pmid, section, "ja"):
                # 翻訳
                text_ja = self.translate_to_japanese(text, section)
                if text_ja:
                    # タイトル翻訳（初回のみ）
                    if title_ja is None:
                        title_ja = self.translate_to_japanese(title, "title")
                    display_title = title_ja if title_ja else title
                    
                    section_names_ja = {
                        "abstract": "アブストラクト",
                        "introduction": "序論",
                        "methods": "材料と方法",
                        "results": "結果",
                        "discussion": "考察",
                        "conclusions": "結論"
                    }
                    section_ja = section_names_ja.get(section, section)
                    
                    full_text_ja = f"{display_title}\n\n[{section_ja}]\n{text_ja}"
                    vector_ja = self.get_embedding(full_text_ja)
                    
                    points.append(PointStruct(
                        id=self._generate_point_id(pmid, section, "ja"),
                        vector=vector_ja,
                        payload={
                            "text": full_text_ja,
                            "category": "dental",
                            "title": display_title,
                            "title_original": title,
                            "topic": "autotransplantation",
                            "items": [],
                            "type": "pubmed_paper",
                            "weight": 1.0 if section == "abstract" else 0.8,
                            "vector_id": f"pubmed_{pmid}_{section}_ja",
                            "original_id": f"pubmed_{pmid}",
                            "pmid": pmid,
                            "pmcid": pmcid or "",
                            "section": section,
                            "section_text": text_ja,
                            "section_text_original": text,
                            "journal": item.get("author", ""),
                            "published_date": item.get("published_at", ""),
                            "url": item.get("url", ""),
                            "source": "pubmed",
                            "lang": "ja",
                            "fulltext_available": fulltext_available
                        }
                    ))
                    stats["saved"] += 1
                    print(f"  [JA] {section}: 準備完了")
                else:
                    print(f"  [JA] {section}: 翻訳失敗")
            else:
                stats["skipped"] += 1
                print(f"  [JA] {section}: スキップ（既存）")
            
            # API rate limit対策
            time.sleep(0.5)
        
        # Qdrantに保存
        if points:
            self.qdrant_client.upsert(
                collection_name=QDRANT_COLLECTION,
                points=points
            )
            print(f"[QDRANT] 保存完了: PMID {pmid} ({len(points)}ポイント)")
        
        return stats


def save_pubmed_items_to_qdrant(items: list) -> dict:
    """収集したアイテムのうちPubMed論文のみQdrantに保存（全文・セクション分割版）"""
    store = PubMedFullTextVectorStore()
    
    pubmed_items = [i for i in items if i.get("source") == "pubmed"]
    
    if not pubmed_items:
        print("[INFO] PubMed論文がありません")
        return {"total_saved": 0, "total_skipped": 0}
    
    print(f"\n{'='*50}")
    print(f"PubMed論文をQdrantに保存（全文・セクション分割）")
    print(f"対象: {len(pubmed_items)}件")
    print(f"{'='*50}\n")
    
    total_saved = 0
    total_skipped = 0
    
    for i, item in enumerate(pubmed_items, 1):
        print(f"\n--- [{i}/{len(pubmed_items)}] {item.get('title', '')[:50]}... ---")
        
        stats = store.save_paper(item)
        total_saved += stats["saved"]
        total_skipped += stats["skipped"]
        
        time.sleep(1)
    
    print(f"\n{'='*50}")
    print(f"Qdrant保存結果")
    print(f"{'='*50}")
    print(f"保存: {total_saved}ポイント")
    print(f"スキップ: {total_skipped}ポイント")
    print(f"{'='*50}\n")
    
    return {"total_saved": total_saved, "total_skipped": total_skipped}


# テスト用
if __name__ == "__main__":
    test_items = [
        {
            "source": "pubmed",
            "pmid": "36363473",
            "title": "Long-Term Survival Rate of Autogenous Tooth Transplantation: Up to 162 Months",
            "url": "https://pubmed.ncbi.nlm.nih.gov/36363473/",
            "published_at": "2022-10-25T00:00:00Z",
            "summary": "Background and Objectives: The purpose of this study is to observe the usefulness of autogenous tooth transplantation by examining the cumulative survival rate according to the period of auto-transplanted teeth as pre-implant treatment.",
            "author": "Medicina (Kaunas)",
            "lang": "en"
        }
    ]
    
    print("テスト実行: 全文取得・セクション分割")
    save_pubmed_items_to_qdrant(test_items)