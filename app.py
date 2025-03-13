import os
from flask import Flask, request
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FollowEvent

from openai import OpenAI  # 確保 import 最新的 OpenAI 函式庫

# 使用環境變數來存 API Key
LINE_ACCESS_TOKEN = os.getenv("LINE_ACCESS_TOKEN")
LINE_SECRET = os.getenv("LINE_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

line_bot_api = LineBotApi(LINE_ACCESS_TOKEN)
handler = WebhookHandler(LINE_SECRET)
client = OpenAI(api_key=OPENAI_API_KEY)

app = Flask(__name__)

@app.route("/", methods=["GET"])
def home():
    return "LINE Bot is Running!"

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        return "Invalid signature", 400

    return "OK"

# 新增 FollowEvent 事件（使用者加入時觸發）
@handler.add(FollowEvent)
def handle_follow(event):
    welcome_message = """你好，這是一個語言篩檢 AI。  
本 AI 測驗不代表最終測驗結果，仍需專業人員解釋。  
如果有進一步檢查需求，請聯絡周圍的語言治療師。"""
    
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=welcome_message)
    )

def chat_with_gpt(prompt):
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "你是一個專門用於語言篩檢的 AI 助理，你的唯一任務是按照標準化流程詢問家長語言評估的問題，並收集回應。如果使用者詢問其他問題，例如『如何提升兒童語言能力』或『我的孩子應該怎麼學習語言』，請回應『抱歉，我只提供語言篩檢問題的服務』，若使用者並非詢問問題而是打招呼等仍提供招呼回應。請使用繁體中文回答。"},
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content  # ✅ 這樣才會正確回傳訊息

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text
    reply = chat_with_gpt(user_message)  # ✅ 呼叫新版 OpenAI API
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
