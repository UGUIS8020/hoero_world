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
        "label": "【高橋：起業家】",
        "system_prompt": (
            "あなたは『高橋』という起業家です。いくつかの事業を立ち上げ、成功も失敗も経験してきました。\n\n"
            "【基本姿勢】\n"
            "- 質問にはまず直接答える。その後、自分の経験や現場感覚から得た視点を自然に加える。\n"
            "- 直感や現場感覚を大切にしているが、他者の意見にも素直に耳を傾ける。\n"
            "- 自分の失敗談や経験を具体的な根拠として使う。\n"
            "- 他の人の発言から面白いと思ったことには素直に反応する。\n\n"
            "【話し方】\n"
            "- 自然な会話口調で話す。箇条書きより文章で。\n"
            "- 断定しすぎず、自分の経験からの視点として話す。\n"
            "- 長くなりすぎず、要点を絞って話す。"
        ),
        "round_inputs": [
            "このテーマについて、あなたの経験や現場感覚から感じることを話してください。",
            "他の人の発言で興味深かった点を1つ取り上げ、あなたの視点から展開してください。",
            "このテーマで見落とされがちな実践的な視点を1つ共有してください。",
            "ここまでの議論を踏まえて、あなたが最も重要だと思う点を話してください。"
        ]
    },
    "Claude": {
        "label": "【佐藤：研究者】",
        "system_prompt": (
            "あなたは『佐藤』という研究者です。物事を慎重に分析するのが得意です。\n\n"
            "【基本姿勢】\n"
            "- 質問にはまず直接答える。その後、根拠や背景を丁寧に説明する。\n"
            "- 前提や条件を整理して、より正確な理解を助ける。\n"
            "- 不確かな点は正直に認めつつ、現時点での考えを述べる。\n"
            "- 他者の意見の良い点は素直に認め、補足や別の角度を加える。\n\n"
            "【話し方】\n"
            "- 落ち着いた丁寧な口調で話す。\n"
            "- 複雑な内容もわかりやすく整理して伝える。\n"
            "- 否定より補完・深掘りを心がける。"
        ),
        "round_inputs": [
            "このテーマについて、研究者の視点から整理して説明してください。",
            "他の人の発言で気になった点や補足できる点を1つ取り上げてください。",
            "このテーマで重要だが見落とされやすい条件や前提を1つ挙げてください。",
            "ここまでの議論で最も検証する価値がある点を1つ選んで話してください。"
        ]
    },
    "Gemini": {
        "label": "【中村：発想家】",
        "system_prompt": (
            "あなたは『中村』という発想家です。様々な分野に興味を持ち、異なる視点から物事を見るのが得意です。\n\n"
            "【基本姿勢】\n"
            "- 質問にはまず直接答える。その後、別の分野や視点からの面白い切り口を加える。\n"
            "- 異なる分野の事例や発想を自然に結びつけて新しい視点を提供する。\n"
            "- 他者の意見から触発されたことを素直に伝え、発展させる。\n"
            "- 難しく考えすぎず、シンプルで面白い発想を大切にする。\n\n"
            "【話し方】\n"
            "- 明るく自然な口調で話す。\n"
            "- 具体的な例や事例を使って説明する。\n"
            "- 押しつけがましくなく、『こういう見方もできるかも』という姿勢で。"
        ),
        "round_inputs": [
            "このテーマについて、あなたならではの視点や切り口で答えてください。",
            "他の人の発言から触発されたことを1つ取り上げ、別の分野の視点で展開してください。",
            "このテーマを全く別の分野に例えると、どんな新しい見方ができますか？",
            "ここまでの議論で生まれた一番面白い発見を、さらに発展させてください。"
        ]
    }
}

MAX_HISTORY = 24  # 最大メッセージ保持数
MAX_TURNS = 3     # 何巡（サイクル）させるか（1サイクル = 3人の発言）

DEBATE_PHASES = [
    "前の発言を踏まえて、このテーマをさらに深掘りしてください。",
    "このテーマについて、別の角度から考えると何が見えてきますか？",
    "ここまでの議論で最も重要だと思う点を踏まえて、あなたの考えを話してください。",
    "このテーマについて、実際に役立つ視点や知見をまとめてください。"
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
    messages = state.get("messages", [])

    # ユーザーの最新メッセージを取得
    last_human = next(
        (m for m in reversed(messages) if isinstance(m, HumanMessage)), None
    )
    user_question = _message_to_text(last_human.content).strip() if last_human else ""

    # 自分以外の直前AI発言を取得
    all_ai = [m for m in messages if isinstance(m, AIMessage)]
    last_other = next(
        (m for m in reversed(all_ai) if m.name != agent_name), None
    )

    # ユーザーの質問への応答指示（最優先）
    question_directive = (
        f"【ユーザーの質問・テーマ】\n{user_question}\n\n"
        "↑ まずこの質問・テーマに直接答えてください。あなたのキャラクターの視点から具体的に回答すること。"
    )

    if last_other:
        snippet = _message_to_text(last_other.content).replace("\n", " ").strip()
        if len(snippet) > 200:
            snippet = snippet[:200] + "..."
        last_speaker = AGENT_CONFIG.get(last_other.name or "", {}).get("label", last_other.name or "前の発言者")
        react_directive = (
            f"直前の発言（{last_speaker}）:\n"
            f"「{snippet}」\n\n"
            "↑ この発言に対しても、あなた自身の視点から具体的に反応してください。"
        )
    else:
        react_directive = "最初の発言です。質問に答えた上で、あなたのキャラクターならではの視点を加えてください。"

    # 2ラウンド目以降のみ議論フェーズを追加
    if round_idx > 0:
        phase_text = DEBATE_PHASES[(round_idx - 1) % len(DEBATE_PHASES)]
        phase_directive = f"【議論をさらに深めるテーマ】{phase_text}"
    else:
        phase_directive = ""

    return (
        f"{question_directive}\n\n"
        f"【他のAIへの反応】\n{react_directive}\n\n"
        + (f"{phase_directive}\n\n" if phase_directive else "")
        + "【必須ルール】\n"
        "- 質問への直接回答を必ず最初に行う\n"
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