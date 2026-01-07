"""
PubMed論文 全文取得・セクション分割 テストスクリプト

使用方法:
    python test_pubmed_fulltext.py

必要な環境変数（.envファイルまたは環境変数で設定）:
    OPENAI_API_KEY=sk-...
    QDRANT_URL=https://xxx.qdrant.io
    QDRANT_API_KEY=...
"""

from pubmed_vector_store import save_pubmed_items_to_qdrant

# テスト用データ（PMC全文公開論文）
test_items = [
    {
        "source": "pubmed",
        "pmid": "36363473",
        "title": "Long-Term Survival Rate of Autogenous Tooth Transplantation: Up to 162 Months",
        "url": "https://pubmed.ncbi.nlm.nih.gov/36363473/",
        "published_at": "2022-10-25T00:00:00Z",
        "summary": "Background and Objectives: The purpose of this study is to observe the usefulness of autogenous tooth transplantation by examining the cumulative survival rate according to the period of auto-transplanted teeth as pre-implant treatment. Materials and Methods: This study was conducted on 111 patients who visited Kyungpook National University Dental Hospital and underwent autogenous tooth transplantation between November 2008 and January 2021 (about 13 years). The cumulative survival rate of autogenous tooth transplantation according to the causes of extraction of the recipient tooth (caries, periapical lesion, crack, crown fracture, periodontitis) and condition of opposing teeth (natural teeth vs. fixed prosthesis). The cumulative survival rate of autogenous tooth transplantation according to the age (under 30 vs. over 30) was also investigated and it was examined whether there were any differences in each factor. Results: The average follow-up period was 12 months, followed by a maximum of 162 months. The 24-month cumulative survival rate of all auto-transplanted teeth was 91.7%, 83.1% at 60 months and the 162-month cumulative survival rate was 30.1%. There were no statistical differences between the causes of extraction of the recipient's teeth, differences in the condition of the opposing teeth, and differences under and over the age of 30. Conclusions: The survival rate of autogenous tooth transplantation appears to be influenced by the conditions of the donor tooth rather than the conditions of the recipient tooth. Although autogenous tooth transplantation cannot completely replace implant treatment, it is meaningful in that it can slightly delay or at least earn the time until implant placement is possible.",
        "author": "Medicina (Kaunas)",
        "lang": "en"
    }
]

if __name__ == "__main__":
    print("=" * 60)
    print("PubMed論文 全文取得・セクション分割 テスト")
    print("=" * 60)
    print(f"対象論文: PMID {test_items[0]['pmid']}")
    print(f"タイトル: {test_items[0]['title']}")
    print("=" * 60)
    
    result = save_pubmed_items_to_qdrant(test_items)
    
    print("\n" + "=" * 60)
    print("テスト完了")
    print(f"保存: {result['total_saved']} ポイント")
    print(f"スキップ: {result['total_skipped']} ポイント")
    print("=" * 60)