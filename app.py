# 📌 1️⃣ **導入函式庫（Import Libraries）**
import os
from flask import Flask, request
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FollowEvent
from openai import OpenAI  # 確保 import 最新的 OpenAI 函式庫
from datetime import datetime, timedelta  # 🆕 計算年齡所需

# 📌 2️⃣ **初始化 Flask 與 API 相關變數**
# 使用環境變數來存 API Key
LINE_ACCESS_TOKEN = os.getenv("LINE_ACCESS_TOKEN")
LINE_SECRET = os.getenv("LINE_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# 初始化 LINE Bot API
line_bot_api = LineBotApi(LINE_ACCESS_TOKEN)
handler = WebhookHandler(LINE_SECRET)

# 初始化 OpenAI API
client = OpenAI(api_key=OPENAI_API_KEY)

# 啟動 Flask 應用
app = Flask(__name__)

# 📌 3️⃣ **計算年齡函式（用於判斷兒童月齡）**
def calculate_age(birthdate_str):
    """計算孩子的實足月齡（滿 30 天進位一個月）"""
    try:
        birthdate = datetime.strptime(birthdate_str, "%Y-%m-%d").date()
        today = datetime.today().date()

        years = today.year - birthdate.year
        months = today.month - birthdate.month
        days = today.day - birthdate.day

        if days < 0:
            months -= 1
            last_month_end = today.replace(day=1) - timedelta(days=1)
            days += last_month_end.day

        if months < 0:
            years -= 1
            months += 12

        total_months = years * 12 + months
        if days >= 30:
            total_months += 1

        return total_months
    except ValueError:
        return None

# 📌 4️⃣ **與 OpenAI ChatGPT 互動的函式**
def chat_with_gpt(prompt):
    """與 OpenAI ChatGPT 互動，確保 Bot 只回答篩檢問題"""
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "你是一個專門用於語言篩檢的 AI 助理，你的唯一任務是按照標準化流程詢問家長語言評估的問題，並收集回應。如果使用者詢問其他問題，例如『如何提升兒童語言能力』或『我的孩子應該怎麼學習語言』，請回應『抱歉，我只提供語言篩檢問題的服務』，若使用者並非詢問問題而是打招呼等仍提供招呼回應。請使用繁體中文回答。"},
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content  # ✅ 正確回傳 ChatGPT 回應

# 📌 5️⃣ **Flask 路由（API 入口點）**
@app.route("/", methods=["GET"])
def home():
    """首頁（測試用）"""
    return "LINE Bot is Running!"

@app.route("/callback", methods=["POST"])
def callback():
    """處理 LINE Webhook 請求"""
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        return "Invalid signature", 400

    return "OK"

# 📌 6️⃣ **處理使用者加入 Bot 時的回應**
@handler.add(FollowEvent)
def handle_follow(event):
    """使用者加入時，發送歡迎訊息並請求輸入孩子出生年月日"""
    welcome_message = """請提供孩子的西元出生年月日（YYYY-MM-DD），以便開始語言篩檢。
本測驗僅供參考，最終結果仍需專業人員評估。如有疑問，請諮詢語言治療師。"""
    
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=welcome_message)
    )

# 📌 7️⃣ **處理使用者訊息**
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    """處理使用者輸入的文字訊息"""
    user_message = event.message.text

    # **檢查是否為有效的出生日期**
    child_age = calculate_age(user_message)

    if child_age is not None:
        reply_text = f"你的孩子目前 {child_age} 個月大，請回答以下問題。"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return  # ✅ 確保篩檢流程執行後結束函式

    else:
        reply = "❌ 請輸入正確的出生日期格式：`YYYY-MM-DD`，例如 **2020-08-15**。且孩子須滿至少一個月。"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return  # ✅ 確保錯誤訊息發送後函式結束，不進入 ChatGPT

    # **若非日期，則傳送給 ChatGPT 處理**
    reply = chat_with_gpt(user_message)  # ✅ 呼叫新版 OpenAI API
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

# 📌 8️⃣ **啟動 Flask 應用**
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
