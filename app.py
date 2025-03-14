# **導入函式庫（Import Libraries）**
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
from openai import OpenAI  # 使用 OpenAI SDK 兼容格式
from datetime import datetime, timedelta

# **初始化 Flask 與 API 相關變數**
app = Flask(__name__)
LINE_ACCESS_TOKEN = os.getenv("LINE_ACCESS_TOKEN")
LINE_SECRET = os.getenv("LINE_SECRET")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")  # 環境變數名稱更改

# **初始化 LINE Bot API**
line_bot_api = LineBotApi(LINE_ACCESS_TOKEN)
handler = WebhookHandler(LINE_SECRET)

# **初始化 DeepSeek API（使用 OpenAI SDK 兼容格式）**
client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com"  # 設定 DeepSeek API 端點
)

# **連接 Google Sheets API（代碼保持不變）**
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
service_account_json_base64 = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
if service_account_json_base64:
    service_account_info = json.loads(base64.b64decode(service_account_json_base64))
    creds = Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
    gspread_client = gspread.authorize(creds)
    SPREADSHEET_ID = "1twgKpgWZIzzy7XoMg08jQfweJ2lP4S2LEcGGq-txMVk"
    sheet = gspread_client.open_by_key(SPREADSHEET_ID).sheet1
    print("成功連接 Google Sheets！")
else:
    print("無法獲取 GOOGLE_SERVICE_ACCOUNT_JSON，請確認環境變數是否正確設定！")

# **與 DeepSeek 互動的函式**
def chat_with_deepseek(prompt):
    response = client.chat.completions.create(
        model="deepseek-chat",  # 使用 DeepSeek 模型名稱
        messages=[
            {"role": "system", "content": "你是一個語言篩檢助手，負責回答家長的問題與記錄兒童的語言發展情況，請提供幫助。請使用繁體中文回答。"},
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content  # 解析響應格式與 OpenAI 相同

# **Flask 路由（API 入口點）**
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
        return f"成功讀取試算表內容：\n{formatted_data}"
    except Exception as e:
        return f"無法讀取 Google Sheets，錯誤訊息：{e}"
    
# **計算年齡函式（用於判斷兒童月齡）**
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

# **讀取 Google Sheets 並篩選符合年齡的題目
def get_questions_by_age(months):
    """從 Google Sheets 讀取符合年齡的篩檢題目"""
    try:
        sheet_data = sheet.get_all_values()  # 讀取試算表
        questions = []  # 存放符合條件的題目
        current_group = None  # 用於存儲當前組別

        for row in sheet_data[1:]:  # 跳過標題列
            group_number = int(row[0])  # 組別欄
            age_range = row[1]  # 年齡區間（例如 "0-4個月"）
            question_number = row[2]  # 題號（第二欄）
            question_text = row[3]  # 題目內容（第三欄）

            # **解析 "X-Y個月" 這種類型**
            match = re.findall(r'\d+', age_range)
            if len(match) == 2:  # 只考慮 "X-Y個月" 這種類型
                min_age, max_age = map(int, match)
                if min_age <= months <= max_age:
                    questions.append({"組別": group_number, "題號": question_number, "題目": question_text})

        return questions if questions else None
    except Exception as e:
        print("讀取 Google Sheets 失敗，錯誤訊息：", e)
        return None

def get_min_age_for_group(group):
    group_age_mapping = {1: 0, 2: 5, 3: 9, 4: 13, 5: 17, 6: 21, 7: 25, 8: 29, 9: 33}
    return group_age_mapping.get(group, None)  # 若組別無效，回傳 None

# **處理使用者加入 Bot 時的回應**
@handler.add(FollowEvent)
def handle_follow(event):
    """使用者加入時，發送歡迎訊息並請求輸入孩子出生年月日"""
    welcome_message = """🎉 歡迎來到 **兒童語言篩檢 BOT**！
請選擇您需要的功能，輸入對應的關鍵字開始：
🔹 **篩檢** → 進行兒童語言發展篩檢
🔹 **提升** → 獲取語言發展建議
🔹 **我想治療** → 查找附近語言治療服務

⚠️ 若要進行篩檢，請輸入「篩檢」開始測驗。
⚠️ 若輸入其他內容，BOT會重複此訊息。"""
    
    line_bot_api.reply_message(event.reply_token,TextSendMessage(text=welcome_message))

# **追蹤使用者狀態（模式），這裡用字典模擬（正式可用資料庫）
user_states = {}

# **定義不同模式
MODE_MAIN_MENU = "主選單"
MODE_SCREENING = "篩檢模式"
MODE_TIPS = "語言發展建議模式"
MODE_TREATMENT = "語言治療資訊模式"
MODE_TESTING_FIRST = "首組篩檢"
MODE_TESTING_FORWARD = "順向施測"
MODE_TESTING_BACKWARD = "逆向施測"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    """處理使用者輸入的文字訊息"""
    user_id = event.source.user_id  # 取得使用者 ID
    user_message = event.message.text.strip()  # 去除空格

    # **檢查使用者狀態，預設為「主選單」
    if user_id not in user_states:
        user_states[user_id] = {"mode": MODE_MAIN_MENU}

    user_mode = user_states[user_id]["mode"]  # 取得使用者目前模式

    # **返回主選單
    if user_message == "返回":
        user_states[user_id] = {"mode": MODE_MAIN_MENU}
        response_text = "✅ 已返回主選單。\n\n請選擇功能：\n- 「篩檢」開始語言篩檢\n- 「提升」獲取語言發展建議\n- 「我想治療」獲取語言治療資源"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
        return

    # **主選單模式
    if user_mode == MODE_MAIN_MENU:
        if user_message == "篩檢":
            user_states[user_id] = {"mode": MODE_SCREENING}
            response_text = "請提供孩子的西元出生年月日（格式：YYYY-MM-DD），以便開始語言篩檢。\n\n輸入「返回」回到主選單。"
        elif user_message == "提升":
            user_states[user_id] = {"mode": MODE_TIPS}
            response_text = "幼兒語言發展建議：\n- 與孩子多對話，描述日常事物。\n- 用簡單但完整的句子與孩子交流。\n- 讀繪本、唱童謠、玩互動遊戲來促進語言學習。\n\n輸入「返回」回到主選單。"
        elif user_message == "我想治療":
            user_states[user_id] = {"mode": MODE_TREATMENT}
            response_text = "語言治療機構資訊：請搜尋官方語言治療機構網站，或聯絡當地醫療院所。\n\n輸入「返回」回到主選單。"
        else:
            response_text = "❌無效指令，請輸入：\n- 「篩檢」開始語言篩檢\n- 「提升」獲取語言發展建議\n- 「我想治療」獲取語言治療資源"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
        return

    # **語言發展建議 & 治療模式
    if user_mode in [MODE_TIPS, MODE_TREATMENT]:
        if user_message == "返回":
            user_states[user_id] = {"mode": MODE_MAIN_MENU}
            response_text = "✅已返回主選單。\n\n請選擇功能：\n- 「篩檢」開始語言篩檢\n- 「提升」獲取語言發展建議\n- 「我想治療」獲取語言治療資源"
        else:
            response_text = "輸入「返回」回到主選單。"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
        return

    # **篩檢模式（計算年齡）
    if user_mode == MODE_SCREENING:
        match = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", user_message)
        if match:
            birth_date = datetime.strptime(match.group(0), "%Y-%m-%d").date()
            total_months = calculate_age(str(birth_date))

            if total_months > 36:
                response_text = "本篩檢僅適用於三歲以下兒童，若您的孩子超過 36 個月，建議聯絡語言治療師進行進一步評估。\n\n輸入「返回」回到主選單。"
                user_states[user_id] = {"mode": MODE_MAIN_MENU}
            else:
                questions = get_questions_by_age(total_months)
                if questions:
                    group = questions[0]["組別"]  # 取得題目所屬的組別
                    min_age_in_group = get_min_age_for_group(group)

                    user_states[user_id] = {
                        "mode": MODE_TESTING_FIRST,
                        "questions": questions,
                        "current_index": 0,
                        "score": 0,
                        "group": group,
                        "min_age_in_group": min_age_in_group
                    }
                    response_text = f"""
                    您的孩子目前 {total_months} 個月大，現在開始篩檢。
                    注意：bot需要時間回應，請在回答完每個問題後稍加等待並盡量避免錯別字，謝謝。
                    
                    題目：{questions[0]['題目']}\n\n輸入「返回」可中途退出篩檢。"""

                else:
                    response_text = "無法找到適合此年齡的篩檢題目，請確認 Google Sheets 設定是否正確。\n\n輸入「返回」回到主選單。"
                    user_states[user_id] = {"mode": MODE_MAIN_MENU}
        else:
            response_text = "若要進行語言篩檢，請提供有效的西元出生日期（YYYY-MM-DD），例如 2020-08-15。\n\n輸入「返回」回到主選單。"

        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
        return

    # **首組篩檢
    if user_mode == MODE_TESTING_FIRST:
        state = user_states[user_id]
        questions = state["questions"]
        current_index = state["current_index"]
        score_first = state["score"]
        min_age_in_group = state["min_age_in_group"]  # 該組最小月齡
        
        if questions:
            current_group = int(questions[0]['組別'])
        else:
            response_text = "無法找到符合年齡的題目，請確認資料是否正確。\n\n輸入「返回」回到主選單。"
            user_states[user_id] = {"mode": MODE_MAIN_MENU}
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
            return
        
        print("原始題組數量：", len(questions))###
        print("進行原月齡組題組", current_index, score_first)###

        # **取得目前這題的題號
        current_question = questions[current_index]
        question_number = current_question["題號"]

        # **遍歷 Google Sheets，根據「題號」找到正確的行號
        question_row_index = None
        for i, row in enumerate(sheet.get_all_values(), start=1):  # i 為試算表實際的行號（從 1 開始）
            if row[2] == question_number:  # 題號在第三欄
                question_row_index = i
                break

        # **確保找到對應的行號**
        if question_row_index is not None:
            pass_criteria = sheet.cell(question_row_index, 7).value  # 第7欄：通過標準
            hint = sheet.cell(question_row_index, 6).value  # 第6欄：提示
        else:
            pass_criteria = "未找到通過標準"
            hint = "未找到提示"

        # **讓 deepseek 根據題目、提示、通過標準來判斷使用者回應
        deepseek_prompt = f"""
        題目：{current_question['題目']}
        提示：{hint}
        通過標準：{pass_criteria}
        使用者回應：{user_message}

        這是兒童語言篩檢的一道測驗題，請根據「題目」、「提示」、「通過標準」來判斷使用者的回答是否符合「通過標準」：
        1. 不清楚：使用者的回答表示對題目疑惑，如使用者說「不知道」「不清楚」，或你認為使用者回答仍不足以判斷。請只回應「不清楚」。
        2. 符合：使用者的回答符合「通過標準」(不需字句相同)。請只回應「符合」。
        3. 不符合：使用者的回答並非不清楚且未達到「通過標準」。請只回應「不符合」。

        **請務必只回應「符合」、「不符合」或「不清楚」，不要任何額外文字、符號或解釋！**
        """

        print(questions[current_index], hint, pass_criteria, user_message, sep="\n")
        deepseek_response = chat_with_deepseek(deepseek_prompt).strip()
        print(f"deepseek 判斷：{deepseek_response}")  # Debug 記錄 deepseek 回應

        # **根據 deepseek 回應處理邏輯
        if deepseek_response.startswith("符合"):
            score_first += 1
            user_states[user_id]["score"] = score_first
            current_index += 1
            response_text = "了解，現在進入下一題。\n\n"
        elif deepseek_response.startswith("不符合"):
            current_index += 1
            response_text = "了解，現在進入下一題。\n\n"
        elif deepseek_response.startswith("不清楚"):
            # **若回答不清楚，提供簡單易懂的提示
            hint_prompt = f"""
            使用者因為回應模糊或不清楚題目意思而需提示，請基於以下題目與例子生成30字內的提示回應使用者，要簡單平易近人不要列點。
            題目：{current_question['題目']}，例子：{hint}
            """
            hint_response = chat_with_deepseek(hint_prompt).strip()
            response_text = f"{hint_response}\n請再回覆一次。"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
            return
        else:
            response_text = "❌無法判斷回應，請再試一次。"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
            return

        user_states[user_id]["current_index"] = current_index

        if current_index + 1 < len(questions):
            response_text += f"題目：{questions[current_index]['題目']}\n\n輸入「返回」可中途退出篩檢。"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
            return
        
        else:
            pass_percentage = score_first / len(questions)  # 計算通過比例

            if pass_percentage == 1.0 and current_group < 9:
                # 進入順向模式
                print("進入順向施測模式")
                user_states[user_id]["mode"] = MODE_TESTING_FORWARD
                user_states[user_id]["group"] = current_group + 1
                user_states[user_id]["min_age_in_group"] = get_min_age_for_group(current_group + 1)
                user_states[user_id]["questions"] = get_questions_by_age(get_min_age_for_group(current_group + 1))
                user_states[user_id]["current_index"] = 0
                user_states[user_id]["score"] = 0
                response_text = f"✅ 進入下一個題組（{current_group+1}），請準備。\n\n題目：{user_states[user_id]['questions'][0]['題目']}\n\n輸入「返回」可中途退出篩檢。"
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
                return

            elif pass_percentage < 1.0 and current_group > 1:
                # 進入逆向模式
                print("進入逆向施測模式")
                user_states[user_id]["mode"] = MODE_TESTING_BACKWARD
                user_states[user_id]["group"] = current_group - 1
                user_states[user_id]["min_age_in_group"] = get_min_age_for_group(current_group - 1)
                user_states[user_id]["questions"] = get_questions_by_age(get_min_age_for_group(current_group - 1))
                user_states[user_id]["current_index"] = 0
                user_states[user_id]["score"] = 0
                response_text = f"⏪ 逆向施測，回到上一個題組（{current_group-1}）。\n\n題目：{user_states[user_id]['questions'][0]['題目']}\n\n輸入「返回」可中途退出篩檢。"
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
                return

    ## **順向篩檢
    if user_mode == MODE_TESTING_FORWARD:
        state = user_states[user_id]
        questions = state["questions"]
        current_index = state["current_index"]
        score_forward = state["score"]
        min_age_in_group = state["min_age_in_group"]  # 該組最小月齡
        
        if questions:
            current_group = int(questions[0]['組別'])
        else:
            response_text = "無法找到符合年齡的題目，請確認資料是否正確。\n\n輸入「返回」回到主選單。"
            user_states[user_id] = {"mode": MODE_MAIN_MENU}
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
            return

        # **取得目前這題的題號
        current_question = questions[current_index]
        question_number = current_question["題號"]

        # **遍歷 Google Sheets，根據「題號」找到正確的行號
        question_row_index = None
        for i, row in enumerate(sheet.get_all_values(), start=1):  # i 為試算表實際的行號（從 1 開始）
            if row[2] == question_number:  # 題號在第三欄
                question_row_index = i
                break

        # **確保找到對應的行號**
        if question_row_index is not None:
            pass_criteria = sheet.cell(question_row_index, 7).value  # 第7欄：通過標準
            hint = sheet.cell(question_row_index, 6).value  # 第6欄：提示
        else:
            pass_criteria = "未找到通過標準"
            hint = "未找到提示"

        # **讓 deepseek 根據題目、提示、通過標準來判斷使用者回應
        deepseek_prompt = f"""
        題目：{current_question['題目']}
        提示：{hint}
        通過標準：{pass_criteria}
        使用者回應：{user_message}

        這是兒童語言篩檢的一道測驗題，請根據「題目」、「提示」、「通過標準」來判斷使用者的回答是否符合「通過標準」：
        1. 不清楚：使用者的回答表示對題目疑惑，如使用者說「不知道」「不清楚」，或你認為使用者回答仍不足以判斷。請只回應「不清楚」。
        2. 符合：使用者的回答符合「通過標準」(不需字句相同)。請只回應「符合」。
        3. 不符合：使用者的回答並非不清楚且未達到「通過標準」。請只回應「不符合」。

        **請務必只回應「符合」、「不符合」或「不清楚」，不要任何額外文字、符號或解釋！**
        """

        print(questions[current_index], hint, pass_criteria, user_message, sep="\n")
        deepseek_response = chat_with_deepseek(deepseek_prompt).strip()
        print(f"deepseek 判斷：{deepseek_response}")  # Debug 記錄 deepseek 回應

        # **根據 deepseek 回應處理邏輯
        if deepseek_response.startswith("符合"):
            score_forward += 1
            user_states[user_id]["score"] = score_forward
            current_index += 1
            response_text = "了解，現在進入下一題。\n\n"
        elif deepseek_response.startswith("不符合"):
            current_index += 1
            response_text = "了解，現在進入下一題。\n\n"
        elif deepseek_response.startswith("不清楚"):
            # **若回答不清楚，提供簡單易懂的提示
            hint_prompt = f"""
            使用者因為回應模糊或不清楚題目意思而需提示，請基於以下題目與例子生成30字內的提示回應使用者，要簡單平易近人不要列點。
            題目：{current_question['題目']}，例子：{hint}
            """
            hint_response = chat_with_deepseek(hint_prompt).strip()
            response_text = f"{hint_response}\n請再回覆一次。"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
            return
        else:
            response_text = "❌無法判斷回應，請再試一次。"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
            return

        user_states[user_id]["current_index"] = current_index

        if current_index < len(questions):
            response_text += f"題目：{questions[current_index]['題目']}\n\n輸入「返回」可中途退出篩檢。"
        else:
            pass_percentage = score_forward / len(questions)  # 計算通過比例

            if pass_percentage == 1.0 and current_group < 9:  
                # 順向施測（進入下一組）
                print("繼續順向")
                next_group = current_group + 1
                min_age_in_group = get_min_age_for_group(next_group)
                new_questions = get_questions_by_age(min_age_in_group)

                if new_questions:
                    user_states[user_id].update({
                        "group": next_group,
                        "min_age_in_group": min_age_in_group,
                        "questions": new_questions,
                        "current_index": 0,
                        "score": score_forward
                    })
                    response_text = f"進入下一個題組（{next_group}），請準備。\n\n題目：{new_questions[0]['題目']}\n\n輸入「返回」可中途退出篩檢。"
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
                    return
                else:
                    response_text = f"""篩檢結束！\n您的孩子在測驗中的總得分為：{score_forward} 分。
                    
                    請記住，測驗結果僅供參考，若有疑問請聯絡語言治療師。\n\n輸入「返回」回到主選單。
                    """
                    user_states[user_id] = {"mode": MODE_MAIN_MENU}
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
                    return
            else:
                    response_text = f"""篩檢結束！\n您的孩子在測驗中的總得分為：{score_forward} 分。
                    
                    請記住，測驗結果僅供參考，若有疑問請聯絡語言治療師。\n\n輸入「返回」回到主選單。
                    """
                    user_states[user_id] = {"mode": MODE_MAIN_MENU}
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
                    return

    ##逆向篩檢     
    if user_mode == MODE_TESTING_BACKWARD:
        state = user_states[user_id]
        questions = state["questions"]
        current_index = state["current_index"]
        score_backward = state["score"]
        min_age_in_group = state["min_age_in_group"]  # 該組最小月齡
        
        if questions:
            current_group = int(questions[0]['組別'])
        else:
            response_text = "無法找到符合年齡的題目，請確認資料是否正確。\n\n輸入「返回」回到主選單。"
            user_states[user_id] = {"mode": MODE_MAIN_MENU}
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
            return

        # **取得目前這題的題號
        current_question = questions[current_index]
        question_number = current_question["題號"]

        # **遍歷 Google Sheets，根據「題號」找到正確的行號
        question_row_index = None
        for i, row in enumerate(sheet.get_all_values(), start=1):  # i 為試算表實際的行號（從 1 開始）
            if row[2] == question_number:  # 題號在第三欄
                question_row_index = i
                break

        # **確保找到對應的行號**
        if question_row_index is not None:
            pass_criteria = sheet.cell(question_row_index, 7).value  # 第7欄：通過標準
            hint = sheet.cell(question_row_index, 6).value  # 第6欄：提示
        else:
            pass_criteria = "未找到通過標準"
            hint = "未找到提示"

        # **讓 deepseek 根據題目、提示、通過標準來判斷使用者回應
        deepseek_prompt = f"""
        題目：{current_question['題目']}
        提示：{hint}
        通過標準：{pass_criteria}
        使用者回應：{user_message}

        這是兒童語言篩檢的一道測驗題，請根據「題目」、「提示」、「通過標準」來判斷使用者的回答是否符合「通過標準」：
        1. 不清楚：使用者的回答表示對題目疑惑，如使用者說「不知道」「不清楚」，或你認為使用者回答仍不足以判斷。請只回應「不清楚」。
        2. 符合：使用者的回答符合「通過標準」(不需字句相同)。請只回應「符合」。
        3. 不符合：使用者的回答並非不清楚且未達到「通過標準」。請只回應「不符合」。

        **請務必只回應「符合」、「不符合」或「不清楚」，不要任何額外文字、符號或解釋！**
        """

        print(questions[current_index], hint, pass_criteria, user_message, sep="\n")
        deepseek_response = chat_with_deepseek(deepseek_prompt).strip()
        print(f"deepseek 判斷：{deepseek_response}")  # Debug 記錄 deepseek 回應

        # **根據 deepseek 回應處理邏輯
        if deepseek_response.startswith("符合"):
            score_backward += 1
            user_states[user_id]["score"] = score_backward
            current_index += 1
            response_text = "了解，現在進入下一題。\n\n"
        elif deepseek_response.startswith("不符合"):
            current_index += 1
            response_text = "了解，現在進入下一題。\n\n"
        elif deepseek_response.startswith("不清楚"):
            # **若回答不清楚，提供簡單易懂的提示
            hint_prompt = f"""
            使用者因為回應模糊或不清楚題目意思而需提示，請基於以下題目與例子生成30字內的提示回應使用者，要簡單平易近人不要列點。
            題目：{current_question['題目']}，例子：{hint}
            """
            hint_response = chat_with_deepseek(hint_prompt).strip()
            response_text = f"{hint_response}\n請再回覆一次。"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
            return
        else:
            response_text = "❌無法判斷回應，請再試一次。"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
            return

        user_states[user_id]["current_index"] = current_index

        if current_index < len(questions):
            response_text += f"第 {current_index + 1} 題：{questions[current_index]['題目']}\n\n輸入「返回」可中途退出篩檢。"
        else:
            pass_percentage = score_backward / len(questions)  # 計算通過比例

            if pass_percentage < 1.0 and current_group > 1:  
                # ✅ 逆向施測（進入下一組）
                print(" 繼續逆向")
                next_group = current_group + 1
                min_age_in_group = get_min_age_for_group(next_group)
                new_questions = get_questions_by_age(min_age_in_group)

                if new_questions:
                    user_states[user_id].update({
                        "group": next_group,
                        "min_age_in_group": min_age_in_group,
                        "questions": new_questions,
                        "current_index": 0,
                        "score": score_backward
                    })
                    response_text = f"✅ 進入下一個題組（{next_group}），請準備。\n\n題目：{new_questions[0]['題目']}\n\n輸入「返回」可中途退出篩檢。"
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
                    return
                else:
                    response_text = f"""✅篩檢結束！\n您的孩子在測驗中的總得分為：{score_backward} 分。
                    
                    請記住，測驗結果僅供參考，若有疑問請聯絡語言治療師。\n\n輸入「返回」回到主選單。
                    """
                    user_states[user_id] = {"mode": MODE_MAIN_MENU}
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
                    return
            else:
                    response_text = f"""篩檢結束！\n您的孩子在測驗中的總得分為：{score_forward} 分。
                    
                    請記住，測驗結果僅供參考，若有疑問請聯絡語言治療師。\n\n輸入「返回」回到主選單。
                    """
                    user_states[user_id] = {"mode": MODE_MAIN_MENU}
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
                    return

# **啟動 Flask 應用**
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)