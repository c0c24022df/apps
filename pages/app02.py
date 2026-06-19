import streamlit as st

# タイトル
st.title("社会情報プロジェクト実習I")

# 見出し
st.subheader("データ分析関連")

# CSVファイルの読み込み
import pandas as pd
df = pd.read_csv("data/iris.csv",encoding="utf-8")
# データフレームを表示（ブラウザでスクロール可能）
st.subheader("データフレーム（ブラウザでスクロール可能）") # 見出し 
st.dataframe(df)

# データフレームをテーブルで表示（ブラウザでスクロール不可）
st.subheader("テーブル（スクロール不可）") # 見出し 
st.table(df)

# Streamlitを使ってグラフ表示（散布図）
st.subheader("散布図") # 見出し 
st.scatter_chart(df, x="petal_length", y="petal_width")

# matplotlibを使ってグラフ表示(1個)
import matplotlib.pyplot as plt 
import matplotlib_fontja # 日本語化

st.subheader("matplotlibを使ってグラフ表示(1)") # 見出し

fig, ax = plt.subplots() # figureオブジェクトとaxesオブジェクトの作成
ax.scatter(df["petal_length"], df["petal_width"])
ax.set_title("散布図", fontsize=20)
ax.set_xlabel("petal_length", fontsize=15)
ax.set_ylabel("petal_width", fontsize=15)
st.pyplot(fig) # figureオブジェクトをStreamlitに表示

# matplotlibを使ってグラフ表示(2)
st.subheader("matplotlibを使ってグラフ表示(2個)") # 見出し

fig, axes = plt.subplots(1,2,figsize=(10,5),tight_layout=True,squeeze=False) # figureオブジェクトとaxesオブジェクトの作成
axes[0,0].scatter(df["petal_length"], df["petal_width"])
axes[0,0].set_title("散布図", fontsize=20)
axes[0,0].set_xlabel("petal_length", fontsize=15)
axes[0,0].set_ylabel("petal_width", fontsize=15) 
axes[0,1].scatter(df["sepal_length"], df["sepal_width"])
axes[0,1].set_title("散布図", fontsize=20)
axes[0,1].set_xlabel("sepal_length", fontsize=15)
axes[0,1].set_ylabel("sepal_width", fontsize=15)
st.pyplot(fig) # figureオブジェクトをStreamlitに表示