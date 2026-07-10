"""
第10回〜第11回 Webアプリケーションの設計・実装（株価分析）
株価分析アプリ（Streamlit + yfinance）

画面構成:
  - メインダッシュボード（サイドバーで銘柄・期間選択、株価チャート、RSI・現在価格・シグナルバッジを表示）
  - タブ1: テクニカル指標（RSI, 移動平均線）
  - タブ2: シグナル・仮想売買（5段階シグナル、シグナル変化履歴、仮想売買）
  - タブ3: ポートフォリオ（全保有銘柄の実勢価格で評価、資金配分の進捗バー）
"""

import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import altair as alt
from streamlit_searchbox import st_searchbox
from datetime import datetime, timedelta

# apps フォルダから実行した場合でもルートのモジュールを参照できるようにする
import sys
from pathlib import Path

# プロジェクトルートは apps/ の一つ上にある想定
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from local_stock_catalog import get_local_stock_name, search_local_stock_options

# ------------------------------------------------------------
# 基本設定
# ------------------------------------------------------------
st.set_page_config(page_title="株価分析アプリ", layout="wide")

INITIAL_CASH = 1_000_000  # 仮想資金の初期値（円）

TICKER_OPTIONS = {
    "トヨタ自動車 (7203.T)": "7203.T",
    "ソニーグループ (6758.T)": "6758.T",
    "任天堂 (7974.T)": "7974.T",
    "ソフトバンクグループ (9984.T)": "9984.T",
    "Apple (AAPL)": "AAPL",
    "Microsoft (MSFT)": "MSFT",
    "その他（コードを直接入力）": None,
}

# ------------------------------------------------------------
# セッションステートの初期化（仮想ポートフォリオ・取引履歴）
# ------------------------------------------------------------
if "initial_cash" not in st.session_state:
    st.session_state.initial_cash = INITIAL_CASH
if "cash" not in st.session_state:
    st.session_state.cash = st.session_state.initial_cash
if "holdings" not in st.session_state:
    # {ticker: {"shares": int, "avg_price": float}}
    st.session_state.holdings = {}
if "trade_history" not in st.session_state:
    # list of dict: date, ticker, action, shares, price
    st.session_state.trade_history = []
if "signal_history" not in st.session_state:
    # list of dict: date, ticker, signal, rsi, ma5, ma25
    st.session_state.signal_history = []
if "last_signal" not in st.session_state:
    # {ticker: 直近に記録したシグナル}　変化検知用
    st.session_state.last_signal = {}

def reset_portfolio(initial_cash: int) -> None:
    """仮想資金と売買履歴を指定金額で初期化する。"""
    st.session_state.initial_cash = initial_cash
    st.session_state.cash = initial_cash
    st.session_state.holdings = {}
    st.session_state.trade_history = []
    st.session_state.signal_history = []
    st.session_state.last_signal = {}


# ------------------------------------------------------------
# データ取得・計算処理
# ------------------------------------------------------------
@st.cache_data(ttl=600, show_spinner=False)
def fetch_stock_data(ticker: str, period_days: int) -> pd.DataFrame:
    """Yahoo Finance APIから株価データを取得する"""
    end = datetime.now()
    start = end - timedelta(days=period_days)
    data = yf.download(ticker, start=start, end=end, progress=False)
    return data


@st.cache_data(ttl=600, show_spinner=False)
def fetch_latest_price(ticker: str):
    """指定銘柄の直近終値のみを取得する（ポートフォリオの評価額計算用）。取得できない場合はNoneを返す"""
    try:
        hist = yf.download(ticker, period="5d", progress=False)
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = hist.columns.get_level_values(0)
        if hist is None or hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception:
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def search_yahoo_finance(query: str, max_results: int = 8):
    """
    証券コード・企業名どちらの入力からも候補を検索する（Yahoo Financeの検索APIを利用）。
    戻り値: [{"symbol": ..., "name": ..., "exchange": ...}, ...]
    """
    if not query:
        return []
    try:
        results = yf.Search(query, max_results=max_results).quotes
    except Exception:
        return []

    candidates = []
    for r in results:
        symbol = r.get("symbol")
        if not symbol:
            continue
        name = r.get("longname") or r.get("shortname") or ""
        exchange = r.get("exchange", "")
        candidates.append({"symbol": symbol, "name": name, "exchange": exchange})
    return candidates


@st.cache_data(ttl=3600, show_spinner=False)
def get_stock_name(ticker: str) -> str:
    """証券コードから銘柄名を取得する。取得できない場合は空文字を返す"""
    if not ticker:
        return ""
    local_name = get_local_stock_name(ticker)
    if local_name:
        return local_name
    try:
        results = yf.Search(ticker, max_results=5).quotes
        for r in results:
            if r.get("symbol", "").upper() == ticker.upper():
                return r.get("shortname") or r.get("longname") or ""
    except Exception:
        pass
    return ""


def search_ticker_options(searchterm: str):
    """
    st_searchbox に渡す検索関数。
    入力されるたびに呼び出され、(表示ラベル, 証券コード) のタプルのリストを返す。
    """
    if not searchterm:
        return []
    candidates = list(search_local_stock_options(searchterm))
    seen = {ticker for _, ticker in candidates}

    if len(candidates) < 8:
        for candidate in search_yahoo_finance(searchterm, max_results=8):
            ticker = candidate["symbol"]
            if ticker in seen:
                continue
            label = f"{ticker} － {candidate['name']}" + (f"（{candidate['exchange']}）" if candidate["exchange"] else "")
            candidates.append((label, ticker))
            seen.add(ticker)
            if len(candidates) >= 8:
                break

    return candidates


def calc_rsi(close: pd.Series, window: int = 14) -> pd.Series:
    """RSI（Relative Strength Index）を計算する"""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=window, min_periods=window).mean()
    avg_loss = loss.rolling(window=window, min_periods=window).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """移動平均線・RSIを付加する"""
    df = df.copy()
    df["MA5"] = df["Close"].rolling(window=5).mean()
    df["MA25"] = df["Close"].rolling(window=25).mean()
    df["RSI"] = calc_rsi(df["Close"], window=14)
    return df


SIGNAL_LABELS = ["強い買い", "買い", "売り", "強い売り", "様子見"]

# シグナルごとの表示記号・バッジ色（Component Galleryの「Badge」を参考にした簡易バッジ表現）
SIGNAL_SYMBOLS = {
    "強い買い": "▲",
    "買い": "△",
    "売り": "▽",
    "強い売り": "▼",
    "様子見": "―",
}
SIGNAL_COLORS = {
    "強い買い": "#0f7b0f",
    "買い": "#4caf50",
    "売り": "#ef9a9a",
    "強い売り": "#c62828",
    "様子見": "#9e9e9e",
}


def judge_signal(latest_rsi: float, latest_ma5: float, latest_ma25: float):
    """RSI・移動平均線をもとに売買シグナルを判定する（強弱つき5段階）"""
    if pd.isna(latest_rsi) or pd.isna(latest_ma5) or pd.isna(latest_ma25):
        return "様子見", "指標を計算するにはデータが不足しています。"

    golden_cross = latest_ma5 > latest_ma25  # ゴールデンクロス寄り
    dead_cross = latest_ma5 < latest_ma25    # デッドクロス寄り

    if latest_rsi <= 30 and golden_cross:
        return "強い買い", f"RSI={latest_rsi:.1f}（売られすぎ）かつMA5がMA25を上回っています。"
    elif latest_rsi <= 40 and golden_cross:
        return "買い", f"RSI={latest_rsi:.1f}（やや売られすぎ）で、MA5がMA25を上回っています。"
    elif latest_rsi >= 70 and dead_cross:
        return "強い売り", f"RSI={latest_rsi:.1f}（買われすぎ）かつMA5がMA25を下回っています。"
    elif latest_rsi >= 60 and dead_cross:
        return "売り", f"RSI={latest_rsi:.1f}（やや買われすぎ）で、MA5がMA25を下回っています。"
    else:
        return "様子見", f"RSI={latest_rsi:.1f}。明確なシグナルは出ていません。"


def add_signal_column(df: pd.DataFrame) -> pd.DataFrame:
    """全期間について、judge_signalと同じ条件でシグナルを一括計算する（グラフの△▽表示用）"""
    df = df.copy()
    golden = df["MA5"] > df["MA25"]
    dead = df["MA5"] < df["MA25"]
    conditions = [
        (df["RSI"] <= 30) & golden,
        (df["RSI"] <= 40) & golden,
        (df["RSI"] >= 70) & dead,
        (df["RSI"] >= 60) & dead,
    ]
    choices = ["強い買い", "買い", "強い売り", "売り"]
    df["Signal"] = np.select(conditions, choices, default="様子見")
    return df


def signal_badge_html(signal: str) -> str:
    """シグナルを色付きバッジ（HTML）として表示するための文字列を生成する"""
    color = SIGNAL_COLORS.get(signal, "#9e9e9e")
    symbol = SIGNAL_SYMBOLS.get(signal, "")
    return (
        f'<span style="background-color:{color};color:white;padding:4px 12px;'
        f'border-radius:12px;font-weight:bold;font-size:0.95rem;">{symbol} {signal}</span>'
    )


# ------------------------------------------------------------
# サイドバー（銘柄選択・期間指定）
# ------------------------------------------------------------
st.sidebar.header("銘柄・期間の設定")

with st.sidebar.form("initial_cash_form"):
    initial_cash_input = st.number_input(
        "仮想資金の初期額（円）",
        min_value=0,
        max_value=100_000_000,
        value=int(st.session_state.initial_cash),
        step=10_000,
    )
    submitted = st.form_submit_button("初期資金を反映")
    if submitted:
        reset_portfolio(int(initial_cash_input))
        st.rerun()

selected_label = st.sidebar.selectbox("銘柄を選択", list(TICKER_OPTIONS.keys()))
ticker = TICKER_OPTIONS[selected_label]

if ticker is None:
    st.sidebar.caption("証券コード（例: 6501.T）でも、銘柄名（例: 日立、ホットランド、Tesla）でも検索できます。")
    with st.sidebar:
        selected_option = st_searchbox(
            search_ticker_options,
            placeholder="証券コード または 銘柄名で検索...",
            label=None,
            key="ticker_searchbox",
            clear_on_submit=False,
        )
    ticker = selected_option if selected_option else None
    if ticker:
        selected_label = get_stock_name(ticker) or ticker

period_days = st.sidebar.slider("表示期間（日数）", min_value=7, max_value=730, value=180, step=1)

st.sidebar.caption("※ 移動平均線（25日）・RSI（14日）の計算のため、30日以上を推奨します。")

st.title("📈 株価分析アプリ")

if not ticker:
    st.info("サイドバーから銘柄コードを選択、または企業名で検索してください。")
    st.stop()

stock_name = get_stock_name(ticker)
if stock_name:
    st.caption(f"銘柄コード：**{ticker}** ／ 銘柄名：**{stock_name}**")
else:
    st.caption(f"銘柄コード：**{ticker}**")

# ------------------------------------------------------------
# データ取得（例外対応）
# ------------------------------------------------------------
try:
    with st.spinner(f"{ticker} の株価データを取得中..."):
        raw_data = fetch_stock_data(ticker, period_days)
except Exception:
    st.error("データを取得できませんでした。通信環境を確認してください。")
    st.stop()

if raw_data is None or raw_data.empty:
    st.error(f"証券コード「{ticker}」が見つかりません。コードを確認してください。")
    st.stop()

# MultiIndexの列になる場合があるため平坦化しておく
if isinstance(raw_data.columns, pd.MultiIndex):
    raw_data.columns = raw_data.columns.get_level_values(0)

if len(raw_data) < 30:
    st.warning("取得データが少ないため、指標が正しく計算できない場合があります。期間を長くしてください（最低30日以上推奨）。")

data = add_indicators(raw_data)
data = add_signal_column(data)

latest_close = float(data["Close"].iloc[-1])
latest_rsi = float(data["RSI"].iloc[-1]) if not pd.isna(data["RSI"].iloc[-1]) else np.nan
latest_ma5 = float(data["MA5"].iloc[-1]) if not pd.isna(data["MA5"].iloc[-1]) else np.nan
latest_ma25 = float(data["MA25"].iloc[-1]) if not pd.isna(data["MA25"].iloc[-1]) else np.nan

prev_close = float(data["Close"].iloc[-2]) if len(data) > 1 else latest_close
delta_close = latest_close - prev_close

# シグナルを判定し、前回と異なる場合のみ履歴に記録する（銘柄ごとに管理）
current_signal, current_reason = judge_signal(latest_rsi, latest_ma5, latest_ma25)
if st.session_state.last_signal.get(ticker) != current_signal:
    st.session_state.signal_history.append(
        {
            "日時": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "銘柄": ticker,
            "シグナル": current_signal,
            "RSI": round(latest_rsi, 1) if not pd.isna(latest_rsi) else None,
            "MA5": round(latest_ma5, 2) if not pd.isna(latest_ma5) else None,
            "MA25": round(latest_ma25, 2) if not pd.isna(latest_ma25) else None,
        }
    )
    st.session_state.last_signal[ticker] = current_signal

# ------------------------------------------------------------
# メインダッシュボード
# ------------------------------------------------------------
col1, col2, col3, col4 = st.columns(4)
col1.metric("現在の株価", f"{latest_close:,.2f}", f"{delta_close:,.2f}",
            help="直近の終値と、前日終値からの変化幅です。")
col2.metric("RSI (14日)", f"{latest_rsi:.1f}" if not pd.isna(latest_rsi) else "計算中",
            help="Relative Strength Index。一般的に30以下は売られすぎ、70以上は買われすぎとされます。")
col3.metric("保有現金（仮想資金）", f"{st.session_state.cash:,.0f} 円",
            help="仮想売買で使える現金残高です。")
with col4:
    st.markdown("**現在のシグナル**", help="RSIと移動平均線（MA5・MA25）から自動判定した売買シグナルです。")
    st.markdown(signal_badge_html(current_signal), unsafe_allow_html=True)

st.subheader(f"{selected_label} 株価チャート（終値推移）")

chart_df = data.reset_index().rename(columns={"index": "Date"})
# yfinanceの取得結果はインデックス名が"Date"になっていることが多いが、念のため統一する
if "Date" not in chart_df.columns:
    chart_df = chart_df.rename(columns={chart_df.columns[0]: "Date"})

price_line = alt.Chart(chart_df).mark_line(color="#1f77b4").encode(
    x=alt.X("Date:T", title="日付"),
    y=alt.Y("Close:Q", title="終値"),
    tooltip=[alt.Tooltip("Date:T", title="日付"), alt.Tooltip("Close:Q", title="終値", format=",.2f")],
)

strong_buy_points = chart_df[chart_df["Signal"] == "強い買い"]
buy_points = chart_df[chart_df["Signal"] == "買い"]
sell_points = chart_df[chart_df["Signal"] == "売り"]
strong_sell_points = chart_df[chart_df["Signal"] == "強い売り"]

strong_buy_marks = alt.Chart(strong_buy_points).mark_point(
    shape="triangle-up", size=220, filled=True, color=SIGNAL_COLORS["強い買い"]
).encode(
    x="Date:T", y="Close:Q",
    tooltip=[alt.Tooltip("Date:T", title="日付"), alt.Tooltip("Close:Q", title="終値", format=",.2f"), alt.Tooltip("Signal:N", title="シグナル")],
)

buy_marks = alt.Chart(buy_points).mark_point(
    shape="triangle-up", size=100, filled=False, color=SIGNAL_COLORS["買い"], strokeWidth=2
).encode(
    x="Date:T", y="Close:Q",
    tooltip=[alt.Tooltip("Date:T", title="日付"), alt.Tooltip("Close:Q", title="終値", format=",.2f"), alt.Tooltip("Signal:N", title="シグナル")],
)

sell_marks = alt.Chart(sell_points).mark_point(
    shape="triangle-down", size=100, filled=False, color=SIGNAL_COLORS["売り"], strokeWidth=2
).encode(
    x="Date:T", y="Close:Q",
    tooltip=[alt.Tooltip("Date:T", title="日付"), alt.Tooltip("Close:Q", title="終値", format=",.2f"), alt.Tooltip("Signal:N", title="シグナル")],
)

strong_sell_marks = alt.Chart(strong_sell_points).mark_point(
    shape="triangle-down", size=220, filled=True, color=SIGNAL_COLORS["強い売り"]
).encode(
    x="Date:T", y="Close:Q",
    tooltip=[alt.Tooltip("Date:T", title="日付"), alt.Tooltip("Close:Q", title="終値", format=",.2f"), alt.Tooltip("Signal:N", title="シグナル")],
)

combined_chart = (price_line + strong_buy_marks + buy_marks + sell_marks + strong_sell_marks).properties(height=420).interactive()
st.altair_chart(combined_chart, use_container_width=True)
st.caption("▲（濃緑）＝強い買い　△（緑）＝買い　▽（赤）＝売り　▼（濃赤）＝強い売り")

# ------------------------------------------------------------
# タブ構成
# ------------------------------------------------------------
tab1, tab2, tab3 = st.tabs(["テクニカル指標", "シグナル・仮想売買", "ポートフォリオ"])

# --- タブ1: テクニカル指標 ---
with tab1:
    st.write("### 移動平均線（5日・25日）")
    st.line_chart(data[["Close", "MA5", "MA25"]])

    st.write("### RSI（相対力指数）")
    rsi_chart_df = data[["RSI"]].copy()
    rsi_chart_df["買われすぎライン(70)"] = 70
    rsi_chart_df["売られすぎライン(30)"] = 30
    st.line_chart(rsi_chart_df)

    c1, c2 = st.columns(2)
    c1.metric("MA5（5日移動平均）", f"{latest_ma5:,.2f}" if not pd.isna(latest_ma5) else "計算中")
    c2.metric("MA25（25日移動平均）", f"{latest_ma25:,.2f}" if not pd.isna(latest_ma25) else "計算中")

# --- タブ2: シグナル・仮想売買 ---
with tab2:
    st.write("### 現在の売買シグナル")
    st.markdown(signal_badge_html(current_signal), unsafe_allow_html=True)
    st.caption(current_reason)

    with st.expander("シグナル変化履歴を見る"):
        st.caption("シグナル（強い買い／買い／売り／強い売り／様子見）が切り替わるたびに自動で記録されます。")
        ticker_signal_history = [h for h in st.session_state.signal_history if h["銘柄"] == ticker]
        if ticker_signal_history:
            signal_history_df = pd.DataFrame(ticker_signal_history)
            st.dataframe(signal_history_df, use_container_width=True)
        else:
            st.info("まだシグナルの変化履歴がありません。")

    st.write("### 仮想売買")
    shares = st.number_input("株数", min_value=1, value=100, step=1, help="売買する株数を入力してください。")

    buy_col, sell_col = st.columns(2)

    with buy_col:
        if st.button("買う", help="現在の株価で仮想的に購入します。"):
            cost = latest_close * shares
            if cost > st.session_state.cash:
                st.error("残高が足りません。株数または保有現金を確認してください。")
            else:
                st.session_state.cash -= cost
                holding = st.session_state.holdings.get(ticker, {"shares": 0, "avg_price": 0.0})
                total_shares = holding["shares"] + shares
                holding["avg_price"] = (
                    (holding["avg_price"] * holding["shares"] + latest_close * shares) / total_shares
                )
                holding["shares"] = total_shares
                st.session_state.holdings[ticker] = holding
                st.session_state.trade_history.append(
                    {
                        "日時": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "銘柄": ticker,
                        "種別": "買い",
                        "株数": shares,
                        "価格": latest_close,
                    }
                )
                st.toast(f"{ticker} を {shares}株 購入しました。", icon="✅")
                st.rerun()

    with sell_col:
        if st.button("売る", help="保有中の株を現在の株価で仮想的に売却します。"):
            holding = st.session_state.holdings.get(ticker, {"shares": 0, "avg_price": 0.0})
            if holding["shares"] < shares:
                st.error("保有株数が不足しているため売却できません。")
            else:
                proceeds = latest_close * shares
                st.session_state.cash += proceeds
                holding["shares"] -= shares
                if holding["shares"] == 0:
                    st.session_state.holdings.pop(ticker, None)
                else:
                    st.session_state.holdings[ticker] = holding
                st.session_state.trade_history.append(
                    {
                        "日時": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "銘柄": ticker,
                        "種別": "売り",
                        "株数": shares,
                        "価格": latest_close,
                    }
                )
                st.toast(f"{ticker} を {shares}株 売却しました。", icon="✅")
                st.rerun()

# --- タブ3: ポートフォリオ ---
with tab3:
    st.write("### 保有銘柄")

    if st.session_state.holdings:
        rows = []
        total_pnl = 0.0
        total_value = 0.0
        with st.spinner("保有銘柄の最新価格を取得中..."):
            for tkr, h in st.session_state.holdings.items():
                if tkr == ticker:
                    current_price = latest_close  # 表示中の銘柄はすでに取得済みのデータを再利用
                else:
                    fetched = fetch_latest_price(tkr)
                    current_price = fetched if fetched is not None else h["avg_price"]
                    if fetched is None:
                        st.warning(f"{tkr} の最新価格を取得できなかったため、平均購入価格で暫定計算しています。")
                pnl = (current_price - h["avg_price"]) * h["shares"]
                total_pnl += pnl
                total_value += current_price * h["shares"]
                rows.append(
                    {
                        "銘柄": tkr,
                        "保有株数": h["shares"],
                        "平均購入価格": round(h["avg_price"], 2),
                        "現在価格": round(current_price, 2),
                        "含み損益": round(pnl, 2),
                    }
                )
        portfolio_df = pd.DataFrame(rows)
        st.dataframe(portfolio_df, use_container_width=True)

        total_assets = st.session_state.cash + total_value
        m1, m2 = st.columns(2)
        m1.metric("評価損益合計", f"{total_pnl:,.0f} 円", help="保有銘柄の含み損益の合計です。")
        m2.metric("総資産（現金＋評価額）", f"{total_assets:,.0f} 円",
                   help="仮想現金と保有銘柄の評価額の合計です。")

        cash_ratio = st.session_state.cash / total_assets if total_assets > 0 else 1.0
        st.write("#### 資金配分（現金比率）")
        st.progress(min(max(cash_ratio, 0.0), 1.0),
                    text=f"現金 {cash_ratio * 100:.1f}% ／ 株式 {(1 - cash_ratio) * 100:.1f}%")

        st.write("#### 銘柄別 含み損益")
        st.bar_chart(portfolio_df.set_index("銘柄")["含み損益"])
    else:
        st.info("現在保有している銘柄はありません。")

    st.write("### 取引履歴")
    if st.session_state.trade_history:
        history_df = pd.DataFrame(st.session_state.trade_history)
        st.dataframe(history_df, use_container_width=True)
    else:
        st.info("取引履歴はまだありません。")
