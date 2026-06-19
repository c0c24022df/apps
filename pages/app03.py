import streamlit as st

# タイトル
st.title("社会情報プロジェクト実習I")

# 見出し
st.subheader("画面設計")
# 画面分割(縦2分割)
col1, col2 =st.columns(2) # 分割数
with col1: # １列目の領域
    st.subheader("入力画面")

    # テキストボックス
    studentID = st.text_input("学籍番号") # テキストボックスの入力内容

    # セレクトボタン
    years = st.selectbox("学年", ("1年", "2年", "3年", "4年")) # 選択肢

with col2: # ２列目の領域
    st.subheader("画像表示")

    # 画像
    from PIL import Image 
    image = Image.open("data/画像.png")
    st.image(image)