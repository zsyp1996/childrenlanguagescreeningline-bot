# 📌 1️⃣ **導入函式庫（Import Libraries）**
import os
import re
import gspread
import json
import base64
from google.oauth2.service_account import Credentials
from flask import Flask, request
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FollowEvent
from openai import OpenAI  # 確保 import 最新的 OpenAI 函式庫
from datetime import datetime, timedelta  # 🆕 計算年齡所需

# 📌 2️⃣ **初始化 Flask 與 API 相關變數**
app = Flask(__name__)
LINE_ACCESS_TOKEN = os.getenv("LINE_ACCESS_TOKEN")
LINE_SECRET = os.getenv("LINE_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# 初始化 LINE Bot API
line_bot_api = LineBotApi(LINE_ACCESS_TOKEN)
handler = WebhookHandler(LINE_SECRET)

# 初始化 OpenAI API
client = OpenAI(api_key=OPENAI_API_KEY)

# 📌 3️⃣ **連接 Google Sheets API（使用 Base64 環境變數）**
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# **從環境變數讀取 Base64 JSON 並解碼**
service_account_json_base64 = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
if service_account_json_base64:
    service_account_info = json.loads(base64.b64decode(service_account_json_base64))
    creds = Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
    gspread_client = gspread.authorize(creds)

    # **設定試算表 ID**
    SPREADSHEET_ID = "1twgKpgWZIzzy7XoMg08jQfweJ2lP4S2LEcGGq-txMVk"
    sheet = gspread_client.open_by_key(SPREADSHEET_ID).sheet1  # 連接第一個工作表
    print("✅ 成功連接 Google Sheets！")
else:
    print("❌ 無法獲取 GOOGLE_SERVICE_ACCOUNT_JSON，請確認環境變數是否正確設定！")

# 📌 4️⃣ **測試是否成功讀取 Google Sheets**
try:
    sheet_data = sheet.get_all_values()
    print("✅ 成功連接 Google Sheets，內容如下：")
    for row in sheet_data:
        print(row)  # Debug：顯示試算表內容
except Exception as e:
    print("❌ 無法讀取 Google Sheets，錯誤訊息：", e)

# 📌 5️⃣ **計算年齡函式（用於判斷兒童月齡）**
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

# 📌 6️⃣ **與 OpenAI ChatGPT 互動的函式**
def chat_with_gpt(prompt):
    """與 OpenAI ChatGPT 互動，確保 Bot 只回答篩檢問題"""
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "你是一個語言篩檢助手，負責回答家長的問題與記錄兒童的語言發展情況，請提供幫助。請使用繁體中文回答。"},
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content  # ✅ 正確回傳 ChatGPT 回應

# 📌 7️⃣ **Flask 路由（API 入口點）**
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

@app.route("/test_sheets", methods=["GET"])
def test_sheets():
    """測試 Google Sheets API 讀取資料"""
    try:
        sheet_data = sheet.get_all_values()  # 讀取試算表的所有內容
        formatted_data = "\n".join([", ".join(row) for row in sheet_data])  # 轉換為可讀的字串格式
        return f"✅ 成功讀取試算表內容：\n{formatted_data}"
    except Exception as e:
        return f"❌ 無法讀取 Google Sheets，錯誤訊息：{e}"

# 📌 8️⃣ **處理使用者加入 Bot 時的回應**
@handler.add(FollowEvent)
def handle_follow(event):
    """使用者加入時，發送歡迎訊息並請求輸入孩子出生年月日"""
    welcome_message = """請提供孩子的西元出生年月日（YYYY-MM-DD），以便開始語言篩檢。
本測驗僅供參考，最終結果仍需專業人員評估。如有疑問，請諮詢語言治療師。"""
    
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=welcome_message)
    )

# 📌 9️⃣ **處理使用者訊息**
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    """處理使用者輸入的文字訊息"""
    user_message = event.message.text.strip()  # 去除空格

    # 🔹 讓 GPT 轉換日期格式
    gpt_prompt = f"將這個日期(無論西元或民國年)轉為西元 YYYY-MM-DD 格式，請只輸出日期不要有任何額外的解釋：{user_message}"
    gpt_response = chat_with_gpt(gpt_prompt)  # 呼叫 GPT
    
    print("GPT 回應:", gpt_response)  # 🛠️ Debug，檢查 GPT 真的回應什麼

    # 🔹 檢查 GPT 的回應是否符合 YYYY-MM-DD 格式
    match = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", gpt_response)  # 找到標準日期格式
    if match:
        birth_date = datetime.strptime(match.group(0), "%Y-%m-%d").date()
        today = datetime.today().date()

        # 計算實足月齡
        total_months = (today.year - birth_date.year) * 12 + (today.month - birth_date.month)

        # 🔹 如果天數不足，減去一個月
        if today.day < birth_date.day:
            total_months -= 1

        # 🔹 限制施測年齡（不超過 36 個月）
        if total_months > 36:
            response_text = "本篩檢僅適用於三歲以下兒童，若您的孩子超過 36 個月，建議聯絡語言治療師進行進一步評估。"
        else:
            response_text = f"你的孩子目前 {total_months} 個月大，現在開始篩檢。"

    else:
        # GPT 解析失敗，請使用者重新輸入
        response_text = "若要進行語言篩檢，請提供有效的西元出生日期（YYYY-MM-DD），例如 2020-08-15。"

    # 🔹 回應使用者
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=response_text)
    )

# 📌 🔟 **啟動 Flask 應用**
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
