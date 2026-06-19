import streamlit as st
import pandas as pd
import plotly.express as px

st.title("社会情報プロジェクト実習I") # タイトル

st.subheader("plotlyの使い方") # 見出し

# CSVファイルの読み込み
df = pd.read_csv("data/iris.csv", encoding="utf-8")

# plotlyによるグラフ作成
fig = px.scatter(
    df,  # 描画に使うDataFrame
    x="sepal_length",  # x軸に使う列名
    y="sepal_width",  # y軸に使う列名
    color="species",  # 点の色を種別で分ける
    size="petal_length",  # 点の大きさを花弁長さに応じて変える
    hover_data=["petal_width"],  # ホバー時に表示する追加データ
    title="Irisデータの Plotly 散布図"  # グラフタイトル
)

# Streamlit上にグラフを表示
st.plotly_chart(fig, use_container_width=True)  # PlotlyグラフをStreamlitに表示
