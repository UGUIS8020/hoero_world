import os
import streamlit as st
from typing import Annotated, TypedDict, Any, cast
from pathlib import Path
from dotenv import load_dotenv

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage

from PIL import Image
import io
import base64

# .envファイルを読み込む
load_dotenv(dotenv_path=Path(__file__).with_name(".env"))

# ============================================================
# 1. 定数・設定の一元管理 (プロンプトを構造化・短文化)
# ============================================================
AGENT_CONFIG = {
    "GPT": {
        "label": "【高橋：熱血起業家】",
        "system_prompt": (
            "あなたは『高橋』という熱血起業家です。過去にいくつかの事業を立ち上げ、成功も失敗も経験してきました。\n\n"
            "【最重要ルール】\n"
            "- 質問には必ず最初に直接答える。株価の話なら株価について、製品の話なら製品について、自分の意見を先に言う。\n"
            "- 『難しい』『本質は別にある』『予測はナンセンス』で話をそらすことは絶対禁止。\n"
            "- まず答えを出してから、自分ならではの視点を付け加える。順番を守る。\n\n"
            "【あなたの思考スタイル】\n"
            "- 直感と現場感覚が武器。数字よりも『人がどう動くか』で物事を判断する。\n"
            "- 他者の意見を聞いて触発されたとき『それを聞いて思ったんですが』と自分の経験を絡めて展開する。\n"
            "- 自分の失敗談・現場のリアルな話を根拠として使う。\n\n"
            "【絶対にやらないこと】\n"
            "- 中立・バランス・まとめ。常に自分の立場で断言する。\n"
            "- 箇条書きの羅列。体温のある言葉で話す。\n"
            "- 哲学的・抽象的な話だけで終わること。必ず具体的な意見を述べる。"
        ),
        "round_inputs": [
            "このテーマで、あなたが現場で感じた『これは絶対おかしい』という体験や直感を話してください。断言でいい。",
            "直前の発言で最も引っかかった点を1つ取り上げ、『逆に考えると』で展開してください。",
            "全員が見落としているチャンスか盲点を1つ指摘してください。根拠は直感でも経験でも可。",
            "この議論で一番面白いと感じた発見を1つ挙げ、それをさらに大胆に発展させてください。"
        ]
    },
    "Claude": {
        "label": "【佐藤：懐疑的研究者】",
        "system_prompt": (
            "あなたは『佐藤』という研究者です。楽観的な話に何度も裏切られてきたので、前提を疑うのが癖になっています。\n\n"
            "【最重要ルール】\n"
            "- 質問には必ず最初に直接答える。株価の話なら株価について、技術の話なら技術について自分の見解を先に言う。\n"
            "- 『不確実性が高い』『一概には言えない』で逃げることは禁止。不確実でも自分なりの結論を出す。\n"
            "- まず答えを出してから、前提の疑問や反証を付け加える。順番を守る。\n\n"
            "【あなたの思考スタイル】\n"
            "- 『でも、そこで1つ疑問なんですが』と必ず前提を掘り下げる。\n"
            "- 『この条件が変わると、まったく逆の結論になる』と反証で展開する。\n"
            "- 本当に面白い発見には素直に反応する：『あ、それは考えたことなかった』\n"
            "- データがないときは『実験するとしたら』の形で検証可能な問いに変換する。\n"
            "- 議論に隠れている暗黙の前提・見えていない変数を可視化する。\n\n"
            "【絶対にやらないこと】\n"
            "- 否定だけで終わること。必ず『こういう条件なら可能性がある』と展開する。\n"
            "- 全員の意見に同意すること・話をまとめること。"
        ),
        "round_inputs": [
            "この議論で誰も疑っていない『当たり前の前提』を1つ特定し、それをひっくり返してください。",
            "直前の意見の中で最も証拠が薄い主張を1つ取り上げ、反証と代替仮説を示してください。",
            "見落とされている重要な変数（時間軸・対象・規模・文化など）を1つ持ち込んでください。",
            "この議論全体で最も検証する価値がある仮説を1つ選び、最小限の実験を設計してください。"
        ]
    },
    "Gemini": {
        "label": "【中村：異分野の発想家】",
        "system_prompt": (
            "あなたは『中村』という異分野横断の発想家です。生物学・ゲーム設計・都市計画・料理・音楽など、"
            "全く別の領域からアナロジーを持ち込んで議論を突破するのが得意です。\n\n"
            "【最重要ルール】\n"
            "- 質問には必ず最初に直接答える。株価の話なら株価について自分の見方を先に述べてから、別視点を展開する。\n"
            "- 議題から逃げるためにアナロジーを使うことは禁止。アナロジーは議題をより深く理解するためだけに使う。\n"
            "- まず答えを出してから、面白い切り口を付け加える。順番を守る。\n\n"
            "【あなたの思考スタイル】\n"
            "- 『これって〇〇（全く別の分野）と同じ構造じゃないですか？』が口癖。\n"
            "- 2人が対立しているとき『そもそもその問い自体が違うかも』と第3の枠組みを出す。\n"
            "- ユーザーや現場の人が持つ素朴な疑問を代弁して、専門家の議論のズレを指摘する。\n"
            "- 最後は答えではなく、次の探索を誘う問いで締める。\n\n"
            "【絶対にやらないこと】\n"
            "- 2人の意見をまとめること・折衷案を出すこと。\n"
            "- 抽象論で終わること。必ず具体的なシーン・場面・事例を使う。"
        ),
        "round_inputs": [
            "全く別の業界や分野で、これと同じ問題が解決された事例を1つ挙げ、アナロジーで展開してください。",
            "ユーザーや現場の人がこの議論を聞いたら、どんな素朴な疑問を持つと思いますか？その視点で切り込んでください。",
            "2人の議論が共通して前提にしていることを1つ特定し、それを疑うと見えてくる第3の選択肢を出してください。",
            "この議論全体を全く別の枠組みで見たとき、次に探索すべき最も面白い問いを1つ出してください。"
        ]
    }
}

MAX_HISTORY = 24  # 最大メッセージ保持数
MAX_TURNS = 4     # 何巡（サイクル）させるか（1サイクル = 3人の発言）

DEBATE_PHASES = [
    "前提を疑え: この問いの設定そのものが間違っているとしたら、何が正解になるか？",
    "時間軸を変えろ: 10年後から振り返ると、今の議論のどこが的外れだったか？",
    "素人の目で見ろ: 専門知識のない人が聞いたら、どんな素朴な疑問を持つか？",
    "真逆を試せ: 今全員が向いている方向と真逆のアプローチを取ったら何が見えるか？"
]

# ============================================================
# 2. APIキーの検証（変更なし）
# ============================================================
def validate_api_keys():
    required_keys = {
        "OPENAI_API_KEY": "OpenAI",
        "ANTHROPIC_API_KEY": "Anthropic",
        "GOOGLE_API_KEY": "Google"
    }
    missing = [
        name for env_var, name in required_keys.items()
        if not os.getenv(env_var)
    ]
    if missing:
        st.error(f"⚠️ APIキーが未設定です: {', '.join(missing)}")
        st.stop()

# ============================================================
# 3. LLMインスタンスのキャッシュ（変更なし）
# ============================================================
@st.cache_resource
def get_llm_instances():
    openai_key = os.getenv("OPENAI_API_KEY")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    google_key = os.getenv("GOOGLE_API_KEY")

    return {
        "openai": ChatOpenAI(model="gpt-4o", api_key=cast(Any, openai_key), temperature=0.9),  # type: ignore[call-arg]
        "anthropic": ChatAnthropic(model_name="claude-sonnet-4-6", api_key=cast(Any, anthropic_key), timeout=None, stop=None, temperature=0.7),  # type: ignore[call-arg]
        "google": ChatGoogleGenerativeAI(model="gemini-2.5-flash", google_api_key=cast(Any, google_key), temperature=1.0)  # type: ignore[call-arg]
    }

# ============================================================
# 4. State（状態）の定義 (ターン管理用変数を追加)
# ============================================================
class State(TypedDict):
    messages: Annotated[list, add_messages]
    iterations: int
    image_data: str


def _message_to_text(content) -> str:
    """LangChainのメッセージcontentを表示可能な文字列へ正規化する。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content)


def _build_round_directive(agent_name: str, state: State) -> str:
    """ラウンドと直近文脈に応じた動的ディスカッション指示を生成する。"""
    round_idx = state.get("iterations", 0)
    phase_text = DEBATE_PHASES[round_idx % len(DEBATE_PHASES)]

    # 自分以外の直前発言を取得して引用する
    all_ai = [m for m in state.get("messages", []) if isinstance(m, AIMessage)]
    last_other = next(
        (m for m in reversed(all_ai) if m.name != agent_name), None
    )

    if last_other:
        snippet = _message_to_text(last_other.content).replace("\n", " ").strip()
        if len(snippet) > 200:
            snippet = snippet[:200] + "..."
        last_speaker = AGENT_CONFIG.get(last_other.name or "", {}).get("label", last_other.name or "前の発言者")
        react_directive = (
            f"直前の発言（{last_speaker}）:\n"
            f"「{snippet}」\n\n"
            "↑ この発言に対して、あなた自身の視点から具体的に反応してください。\n"
            "  賛成でも反論でも発展でも構いません。ただし必ず自分の意見の根拠（経験・事例・理由）を1つ添えること。"
        )
    else:
        react_directive = "最初の発言です。このテーマについて、あなたが最も強く感じていることを1つ断言してください。"

    return (
        f"【今回のテーマ】{phase_text}\n\n"
        f"【反応すべき発言】\n{react_directive}\n\n"
        "【必須ルール】\n"
        "- 新しい情報・視点・事例を最低1つ追加する\n"
        "- 話をまとめること・要約だけで終わることは禁止\n"
        f"- ラウンド {round_idx + 1} / 4"
    )

# ============================================================
# 5. 共通ノード処理関数 (文脈維持と履歴トリミングの最適化)
# ============================================================
def _invoke_agent(
    llm,
    agent_name: str,
    state: State,
    normalize_content: bool = False
) -> dict:
    config = AGENT_CONFIG[agent_name]

    # 1. システムプロンプトのテキストを準備
    dynamic_directive = _build_round_directive(agent_name, state)
    system_text = f"{config['system_prompt']}\n\n{dynamic_directive}"

    # 2. メッセージの組み立て
    all_messages = []

    # 画像がある場合、最初のメッセージ（HumanMessage）に画像を含めて視覚認識させる
    if state.get("image_data"):
        prompt_content = [
            {"type": "text", "text": f"【システム指示】\n{system_text}"},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{state['image_data']}"}
            }
        ]
        # 画像認識をトリガーするため、最初のプロンプトを HumanMessage として構成
        all_messages.append(HumanMessage(content=prompt_content))
    else:
        # 画像がない場合は、これまで通り SystemMessage として渡す
        all_messages.append(("system", system_text))

    # 3. 過去の会話履歴を結合
    all_messages.extend(list(state["messages"]))
    
    # 4. ラウンドに応じた追加指示を末尾に付与
    round_idx = state.get("iterations", 0)
    round_inputs = config.get("round_inputs", [])
    if round_inputs:
        additional = round_inputs[round_idx % len(round_inputs)]
        all_messages.append(HumanMessage(content=additional))

    try:
        # 実行
        response = llm.invoke(all_messages)

        # Geminiなどのリスト形式レスポンス対策
        if normalize_content and isinstance(response.content, list):
            response.content = "".join([
                c.get("text", "") if isinstance(c, dict) else str(c)
                for c in response.content
            ])

        response.name = agent_name
        return {"messages": [response]}

    except Exception as e:
        return {"messages": [AIMessage(content=f"⚠️ {agent_name}エラー: {str(e)}", name=agent_name)]}

# ============================================================
# 6. 各AIエージェントのノード関数
# ============================================================
def gpt_node(state: State):
    llm = get_llm_instances()["openai"]
    return _invoke_agent(llm, "GPT", state)

def claude_node(state: State):
    llm = get_llm_instances()["anthropic"]
    return _invoke_agent(llm, "Claude", state)

def gemini_node(state: State):
    llm = get_llm_instances()["google"]
    return _invoke_agent(llm, "Gemini", state, normalize_content=True)

# サイクル数をカウントアップするだけの管理用ノード
def increment_counter(state: State):
    current = state.get("iterations", 0)
    return {"iterations": current + 1}
# ============================================================
# 7. グラフの構築 (ループ制御ロジック)
# ============================================================
# --- 修正後のグラフ構築部分 ---
def get_compiled_graph():
    workflow = StateGraph(State)

    # 各ノードの登録
    workflow.add_node("GPT", gpt_node)
    workflow.add_node("Claude", claude_node)
    workflow.add_node("Gemini", gemini_node)
    workflow.add_node("counter", increment_counter)

    # 基本エッジ
    workflow.add_edge(START, "GPT")
    workflow.add_edge("GPT", "Claude")
    workflow.add_edge("Claude", "Gemini")
    workflow.add_edge("Gemini", "counter")

    # 条件付きエッジの判定関数
    def should_continue(state: State):
        # 設定したサイクル数(MAX_TURNS)に達したか判定
        if state.get("iterations", 0) < MAX_TURNS:
            return "GPT"
        return "END"  # 文字列で返す

    # マッピングで遷移先を明示する
    workflow.add_conditional_edges(
        "counter",
        should_continue,
        {
            "GPT": "GPT",
            "END": END  # ここ！文字列 "END" を LangGraph の END オブジェクトに紐付ける
        }
    )

    return workflow.compile()

# ============================================================
# 8. ユーティリティ関数
# ============================================================
def get_trimmed_history(history: list, max_messages: int = MAX_HISTORY) -> list:
    """トークン超過を防ぐため、メッセージ履歴を一定数に制限する"""
    if len(history) > max_messages:
        return [history[0]] + history[-(max_messages - 1):]
    return history

def export_chat_history(history: list) -> str:
    """会話履歴をMarkdown形式に変換してエクスポートする"""
    lines = ["# AI三者会談 議事録\n"]
    for msg in history:
        if isinstance(msg, HumanMessage):
            lines.append(f"## 👤 ユーザー\n{msg.content}\n")
        elif isinstance(msg, AIMessage):
            msg_key = msg.name or ""
            label = AGENT_CONFIG.get(msg_key, {}).get("label", "【AI】")
            lines.append(f"## {label}\n{msg.content}\n")
    return "\n".join(lines)

def display_message(msg):
    """メッセージを適切なラベルで表示する"""
    if isinstance(msg, HumanMessage):
        with st.chat_message("user"):
            st.write(msg.content)
    elif isinstance(msg, AIMessage):
        msg_key = msg.name or ""
        label = AGENT_CONFIG.get(msg_key, {}).get("label", "【AI】")
        with st.chat_message("assistant"):
            st.markdown(f"**{label}**")
            st.write(msg.content)

# ============================================================
# 9. Streamlit UI
# ============================================================

# APIキーの検証（起動時）
validate_api_keys()

# セッション状態の初期化
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

st.set_page_config(page_title="AI三者会談システム", layout="wide")
st.title("🤝 AIマルチエージェント・コラボレーター")

# --- サイドバー ---
with st.sidebar:
    st.header("⚙️ 会議室の設定")

    # 1. 画像アップローダー
    uploaded_file = st.file_uploader("📈 画像を分析させる（チャート・UI等）", type=["jpg", "jpeg", "png"])
    
    # 画像をリサイズしてBase64に変換
    encoded_image = ""
    if uploaded_file:
        # 一旦、画像を開く
        img = Image.open(uploaded_file)
        
        # --- リサイズロジック (最大1000px) ---
        max_size = (1000, 1000)
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        
        # バイトデータに書き出し
        buffered = io.BytesIO()
        # 元の形式を維持。不明な場合はJPEG
        img_format = img.format if img.format else "JPEG"
        img.save(buffered, format=img_format)
        img_bytes = buffered.getvalue()
        
        # Base64エンコード
        encoded_image = base64.b64encode(img_bytes).decode("utf-8")
        
        st.image(img_bytes, caption="分析対象（リサイズ済み）", use_container_width=True)
    
    # リセットボタン
    if st.button("🗑️ 会議をリセット（履歴消去）"):
        st.session_state.chat_history = []
        st.rerun()

    st.divider()

    # 会話エクスポートボタン
    if st.session_state.chat_history:
        st.download_button(
            label="📄 議事録をダウンロード",
            data=export_chat_history(st.session_state.chat_history),
            file_name="ai_meeting_notes.md",
            mime="text/markdown"
        )

    st.divider()
    st.caption(f"💬 現在のメッセージ数: {len(st.session_state.chat_history)}")

# --- 過去のメッセージを表示 ---
for msg in st.session_state.chat_history:
    display_message(msg)

#-- チャット入力欄 ---
if user_input := st.chat_input("AIたちに相談・追加質問をする..."):
    # 1. ユーザーメッセージの表示と保存
    new_user_msg = HumanMessage(content=user_input)
    display_message(new_user_msg) 
    st.session_state.chat_history.append(new_user_msg)

    # 2. グラフと状態の準備
    app = get_compiled_graph()
    trimmed_history = st.session_state.chat_history[-MAX_HISTORY:]
    
    # ✅ 修正：サイドバーで取得した encoded_image を initial_state に渡す
    initial_state: State = {
        "messages": trimmed_history,
        "iterations": 0,
        "image_data": encoded_image  # ← ここを追加！
    }

    label_dict = {k: v["label"] for k, v in AGENT_CONFIG.items()}

    # --- 3. リアルタイムに1人ずつ表示 ---
    status_bar = st.status("AIたちが画像とメッセージを分析中...", expanded=False)

    for event in app.stream(initial_state):
        for node_name, output in event.items():
            if "messages" not in output: 
                continue
            
            last_msg = output["messages"][-1]
            st.session_state.chat_history.append(last_msg)
            label = label_dict.get(last_msg.name, f"【{node_name}】")
            
            status_bar.update(label=f"💬 {label} が分析結果を回答中...")

            with st.chat_message("assistant"):
                st.markdown(f"### {label}")
                
                def stream_text(text):
                    import time
                    for char in text:
                        yield char
                        time.sleep(0.01)
                
                st.write_stream(stream_text(last_msg.content))

    status_bar.update(label="✅ 視覚情報に基づいた議論が完了しました！", state="complete")