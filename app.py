# **導入函式庫（Import Libraries）**
import os
import re
import gspread
import json
import base64
import time
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
def chat_with_deepseek(prompt, retry_count=2):
    for attempt in range(retry_count + 1):
        try:
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "你是一個語言篩檢助手，負責回答家長的問題與記錄兒童的語言發展情況，請提供幫助。請使用繁體中文回答。"},
                    {"role": "user", "content": prompt}
                ]
            )
            return response.choices[0].message.content
        except Exception as e:
            error_type = type(e).__name__
            print(f"DeepSeek API 錯誤 (嘗試 {attempt+1}/{retry_count+1}): {error_type} - {str(e)}")
            
            # 最後一次嘗試失敗時
            if attempt == retry_count:
                # 判斷錯誤類型
                if "Unauthorized" in str(e) or "Invalid" in str(e):
                    print("API 金鑰錯誤或授權問題")
                    return "系統暫時無法處理您的回應，請稍後再試。"
                elif "Timeout" in str(e) or "Connection" in str(e):
                    print("網路連線問題")
                    return "系統回應緩慢，請稍後再試。"
                elif "Rate" in str(e) or "Too many" in str(e):
                    print("速率限制問題")
                    return "系統暫時繁忙，請稍後再試。"
                else:
                    print("其他 API 錯誤")
                    return "系統處理您的回應時出現問題，請稍後再試。"
            
            # 非最後一次嘗試，等待後重試
            time.sleep(1)  # 添加延遲再重試

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
    
#獲取當前日期
def get_formatted_today():
    return datetime.now().strftime("%Y-%m-%d")

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

        for row in sheet_data[1:]:  # 跳過標題列
            age_range = row[1]  # 年齡區間（例如 "0-4個月"）
            group_number = int(row[0])  # 組別欄
            question_number = row[2]  # 題號（第三欄）
            question_text = row[3]  # 題目內容（第四欄）
            question_type = row[4]  # 題目類別R/E (第五欄)
            hint = row[5]  # 提示 (第六欄)
            pass_criteria = row[6]  # 通過標準 (第七欄)

            # **解析 "X-Y個月" 這種類型**
            match = re.findall(r'\d+', age_range)
            if len(match) == 2:  # 只考慮 "X-Y個月" 這種類型
                min_age, max_age = map(int, match)
                if min_age <= months <= max_age:
                    questions.append({"組別": group_number, "題號": question_number, "題目": question_text, "類別": question_type, "提示": hint, "通過標準": pass_criteria})

        return questions if questions else None
    except Exception as e:
        print("讀取 Google Sheets 失敗，錯誤訊息：", e)
        return None

#  根據組別與總分判斷結果
def evaluate_development(score_all_final, original_group):
    standards = {
        1: [2, 4, 7, 8, 9],
        2: [8, 9, 9, 11, 13],
        3: [11, 13, 14, 18, 19],
        4: [17, 19, 21, 25, 28],
        5: [22, 24, 25, 33, 38],
        6: [25, 30, 31, 42, 45],
        7: [33, 36, 44, 48, 50],
        8: [37, 43, 48, 50, 50],
        9: [44, 48, 50, 50, 50]
    }
    threshold = standards[original_group]

    if score_all_final < threshold[0]:  # <5%
        return "疑似遲緩"
    elif score_all_final < threshold[1]:  # 5-25%
        return "可能落後"
    elif score_all_final >= threshold[1] and score_all_final < threshold[3]:
        return "平均水準"
    elif score_all_final < threshold[4]:  # 75-90%
        return "稍微超前"
    else:  # >90%
        return "超前"

def get_min_age_for_group(group): # 記住每組最小年齡
    group_age_mapping = {1: 0, 2: 5, 3: 9, 4: 13, 5: 17, 6: 21, 7: 25, 8: 29, 9: 33}
    return group_age_mapping.get(group, None)  # 若組別無效，回傳 None

def get_group_all_score(group): # 記住每組別與其之前組別總分
    group_all_score_mapping = {1: 5, 2: 10, 3: 15, 4: 20, 5: 26, 6: 32, 7: 38, 8: 44, 9: 50}
    return group_all_score_mapping.get(group, None)

def get_group_r_score(group): # 記住每組別與其之前組別R總分
    group_r_score_mapping = {1: 3, 2: 6, 3: 9, 4: 12, 5: 16, 6: 18, 7: 21, 8: 23, 9: 24}
    return group_r_score_mapping.get(group, None)

def get_group_e_score(group): # 記住每組別與其之前組別E總分
    group_e_score_mapping = {1: 2, 2: 5, 3: 9, 4: 13, 5: 16, 6: 21, 7: 27, 8: 33, 9: 39}
    return group_e_score_mapping.get(group, None)

# **追蹤使用者狀態（模式），這裡用字典模擬（正式可用資料庫）
user_states = {}

# **定義不同模式
MODE_MAIN_MENU = "主選單"
MODE_AGING = "篩檢模式"
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
        response_text = "已返回主選單。\n\n若想重新進行兒童語言篩檢，請輸入「篩檢」。"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
        return

    # **主選單模式
    if user_mode == MODE_MAIN_MENU:
        if user_message == "篩檢":
            user_states[user_id] = {"mode": MODE_AGING}
            response_text = "請提供孩子的西元出生年月日（格式：YYYY-MM-DD），以便開始語言篩檢。\n注意：需為西元出生年月日，且「-」必不可少。\n\n輸入「返回」回到主選單。"
        elif user_message == "提升":
            user_states[user_id] = {"mode": MODE_TIPS}
            response_text = "提升語言能力功能待開發，若造成不便敬請見諒。\n\n輸入「返回」回到主選單。"
        elif user_message == "治療":
            user_states[user_id] = {"mode": MODE_TREATMENT}
            response_text = "提供語言治療場所功能待開發，若造成不便敬請見諒。\n\n輸入「返回」回到主選單。"
        else:
            response_text = "無效指令。\n\n若想進行兒童語言篩檢，請輸入「篩檢」。"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
        return

    # **語言發展建議 & 治療模式
    if user_mode in [MODE_TIPS, MODE_TREATMENT]:
        if user_message == "返回":
            user_states[user_id] = {"mode": MODE_MAIN_MENU}
            response_text = "已返回主選單。\n\n若想進行兒童語言篩檢，請輸入「篩檢」。"
        else:
            response_text = "輸入「返回」回到主選單。"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
        return

    # **篩檢模式（計算年齡）
    if user_mode == MODE_AGING:
        print("計算月齡模式")
        match = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", user_message)
        if match:
            birth_date = datetime.strptime(match.group(0), "%Y-%m-%d").date()
            total_months = calculate_age(str(birth_date))

            if total_months > 36:
                response_text = "本篩檢僅適用於三歲以下兒童，若您的孩子月齡超過36個月，建議聯絡語言治療師進行進一步評估。\n\n輸入「返回」回到主選單。"
                user_states[user_id] = {"mode": MODE_MAIN_MENU}
            else:
                questions = get_questions_by_age(total_months)
                print("首組月齡組題目資訊為：", questions)
                if questions:
                    group = questions[0]["組別"]  # 取得題目所屬的組別
                    min_age_in_group = get_min_age_for_group(group)

                    user_states[user_id] = {
                        "mode": MODE_TESTING_FIRST,
                        "total_months": total_months,
                        "questions": questions,
                        "current_index": 0,
                        "score_all_current": 0,
                        "score_all": 0, "score_r": 0, "score_e": 0,
                        "original_group": group,
                        "group": group,
                        "min_age_in_group": min_age_in_group,
                        "right_questions" : [],
                        "wrong_questions" : []
                    }
                    print("進入首組篩檢模式")
                    response_text_1 = f"""您的孩子目前 {total_months} 個月大，請詳閱以下篩檢注意事項。

1.您可以使用「可以」、「不可以」回應，也能描述孩子狀況交由AI判斷。如：
題目：「當您對孩子說『不行』時，他會停下來嗎？」
回應示範：「他會看著我，但停不停下來要看他心情。」

2.若您不確定題目意思時，請回覆「不清楚」，AI會提供說明。

3.由於AI需要時間回應，請回答完後稍加等待並避免再次傳送訊息。

4.請盡量完成所有題目，如需中斷請輸入「返回」。

5.本測驗僅供參考，不代表正式診斷結果，如有疑慮請諮詢語言治療師。"""
                    response_text_2 = f"現在開始篩檢，請回答以下題目。\n題目：{questions[0]['題目']}\n\n輸入「返回」可中途退出篩檢。"
                    line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=response_text_1), TextSendMessage(text=response_text_2)])
                    return
                else:
                    response_text = "無法找到適合此年齡的篩檢題目，請確認 Google Sheets 設定是否正確。\n\n輸入「返回」回到主選單。"
                    user_states[user_id] = {"mode": MODE_MAIN_MENU}
        else:
            response_text = "請提供孩子的「西元」出生年月日（格式：YYYY-MM-DD），並且「-」不可省略，例如 2020-08-15。\n\n輸入「返回」回到主選單。"

        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
        return

    # **首組篩檢
    if user_mode == MODE_TESTING_FIRST:
        state = user_states[user_id]
        questions = state["questions"]
        current_index = state["current_index"]
        score_all_first = state["score_all"]
        score_r_first = state["score_r"]
        score_e_first = state["score_e"]
        original_group = state["original_group"]
        min_age_in_group = state["min_age_in_group"]  # 該組最小月齡
        
        # 回覆使用者收到訊息並等待
        response_text_wait = "已收到回覆，請等待AI回應，等待過程中請勿再發送訊息。"
        user_id = event.source.user_id  # 取得使用者 LINE ID
        line_bot_api.push_message(user_id, TextSendMessage(text=response_text_wait))

        # **取得目前這題的資料
        current_question = questions[current_index] # 取得該題所有資料包含組別、題號、題目、類別、提示、通過標準
        current_group = int(questions[0]["組別"]) # 取得組別
        question_number = current_question["題號"] # 取得題號
        question_type = current_question["類別"] # 取得類別
        hint = current_question["提示"] # 取得提示
        pass_criteria = current_question["通過標準"] # 取得通過標準

        print("第", current_group, "組數量：", len(questions))###

        # **讓 deepseek 根據題目、提示、通過標準來判斷使用者回應
        deepseek_prompt = f"""
        題目：{current_question["題目"]}
        通過標準：{pass_criteria}
        回應：{user_message}
        根據題目、回應判斷回應是否符合「通過標準」：
        1. 不清楚：回應表示對題目疑惑如不清楚，或回應仍不足以判斷符不符合。
        2. 符合：回應符合「通過標準」(不需字句相同)或明確肯定。
        3. 不符合：回應並非不清楚且未達「通過標準」或明確否定。
        只回應「符合」、「不符合」或「不清楚」，勿額外解釋或加入符號。
        """

        deepseek_response = chat_with_deepseek(deepseek_prompt).strip()
        print(f"現在題目：{current_question['題目']}\n提示：{hint}\n通過標準：{pass_criteria}\n使用者回覆：{user_message}\ndeepseek判斷：{deepseek_response}")  # Debug記錄deepseek回應

        # **根據 deepseek 回應處理邏輯
        if deepseek_response.startswith("符合"):
            score_all_first += 1
            user_states[user_id]["score_all"] = score_all_first
            user_states[user_id]["right_questions"].append(question_number) # 記錄對題題號
            current_index += 1
            if question_type == "R":
                score_r_first += 1
                user_states[user_id]["score_r"] = score_r_first

            elif question_type == "E":
                score_e_first += 1
                user_states[user_id]["score_e"] = score_e_first
                
            else:
                score_r_first += 1
                score_e_first += 1
                user_states[user_id]["score_r"] = score_r_first
                user_states[user_id]["score_e"] = score_e_first
            response_text = "了解，現在進入下一題。\n\n"
        elif deepseek_response.startswith("不符合"):
            current_index += 1
            user_states[user_id]["wrong_questions"].append(question_number) # 記錄錯題題號
            response_text = "了解，現在進入下一題。\n\n"
        elif deepseek_response.startswith("不清楚"):
            # 若回答不清楚，提供簡單易懂的提示
            hint_prompt = f"""
            題目：{current_question['題目']}，例子：{hint}
            使用者回應模糊或不理解題目需提示，請根據題目與例子生成30字內的簡單提示。
            """
            hint_response = chat_with_deepseek(hint_prompt).strip()
            response_text = f"{hint_response}\n請再次回應問題。"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
            return
        else:
            response_text = "程式出現錯誤無法判斷回應，請聯絡負責人。"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
            return
        print(f"首組第{current_index}題，現在總分：{score_all_first}，現在R分{score_r_first}，現在E分{score_e_first}")
        user_states[user_id]["current_index"] = current_index

        if current_index < len(questions):
            response_text += f"題目：{questions[current_index]['題目']}\n\n輸入「返回」可中途退出篩檢。"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
            return

        else:
            pass_percentage = score_all_first / len(questions)  # 計算通過比例

            if pass_percentage == 1.0:
                if current_group < 9:
                    # 進入順向模式
                    print("進入順向施測模式")
                    user_states[user_id]["mode"] = MODE_TESTING_FORWARD
                    user_states[user_id]["status"] = "Forward"
                    user_states[user_id]["group"] = current_group + 1
                    user_states[user_id]["min_age_in_group"] = get_min_age_for_group(current_group + 1)
                    user_states[user_id]["questions"] = get_questions_by_age(get_min_age_for_group(current_group + 1))
                    user_states[user_id]["current_index"] = 0
                    user_states[user_id]["score_all"] = 0
                    user_states[user_id]["score_r"] = 0
                    user_states[user_id]["score_e"] = 0
                    response_text = f"題目：{user_states[user_id]['questions'][0]['題目']}\n\n輸入「返回」可中途退出篩檢。"
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
                    return
                else:
                    # 位於最後一個月齡組
                    score_all_final = score_all_first + 44 # 第1-8組分數加總為44，加上第9組分數即為總分。
                    #score_r_final = score_r_first + 23 # 第1-8組R分數加總為23，加上第9組R分數即為總分。
                    #score_e_final = score_e_first + 33 # 第1-8組E分數加總為33，加上第9組E分數即為總分。
                    evaluate_result = evaluate_development(score_all_final, original_group)
                    today = datetime.now().strftime("%Y-%m-%d")
                    total_months = user_states[user_id]["total_months"]
                    right_questions = user_states[user_id]["right_questions"]
                    sorted_right_questions = sorted(right_questions, key=lambda x: int(x))
                    wrong_questions = user_states[user_id]["wrong_questions"]
                    sorted_wrong_questions = sorted(wrong_questions, key=lambda x: int(x))
                    response_text_1 = f"""篩檢結束，總分為{score_all_final}分。
評估結果為：{evaluate_result}。

請記住，本測驗結果僅供參考，不代表真實診斷結果，若有疑慮請聯絡語言治療師。
                    
輸入「返回」回到主選單。"""
                    response_text_2 = f"""若有需要請將此訊息給語言治療師看：
本次篩檢時間為：{today}。
該孩子於此篩檢時月齡為：{total_months}。
正確題目為：{', '.join(map(str, sorted_right_questions))}。
錯誤題目為：{', '.join(map(str, sorted_wrong_questions))}。
                    """
                    line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=response_text_1), TextSendMessage(text=response_text_2)])
                    user_states[user_id] = {"mode": MODE_MAIN_MENU}
                    return

            elif pass_percentage < 1.0:
                if current_group > 1:
                    # 進入逆向模式
                    print("進入逆向施測模式")
                    user_states[user_id]["mode"] = MODE_TESTING_BACKWARD
                    user_states[user_id]["status"] = "Backward"
                    user_states[user_id]["group"] = current_group - 1
                    user_states[user_id]["min_age_in_group"] = get_min_age_for_group(current_group - 1)
                    user_states[user_id]["questions"] = get_questions_by_age(get_min_age_for_group(current_group - 1))
                    user_states[user_id]["current_index"] = 0
                    user_states[user_id]["score_r"] = 0
                    user_states[user_id]["score_e"] = 0
                    response_text = f"題目：{user_states[user_id]['questions'][0]['題目']}\n\n輸入「返回」可中途退出篩檢。"
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
                    return
                else:
                    # 位於第一個月齡組
                    score_all_final = score_all_first # 第1組分數即為總分。
                    #score_r_final = score_r_first # 第1組R分數即為總分。
                    #score_e_final = score_e_first # 第1組E分數即為總分。
                    evaluate_result = evaluate_development(score_all_final, original_group)
                    today = datetime.now().strftime("%Y-%m-%d")
                    total_months = user_states[user_id]["total_months"]
                    right_questions = user_states[user_id]["right_questions"]
                    sorted_right_questions = sorted(right_questions, key=lambda x: int(x))
                    wrong_questions = user_states[user_id]["wrong_questions"]
                    sorted_wrong_questions = sorted(wrong_questions, key=lambda x: int(x))
                    response_text_1 = f"""篩檢結束，總分為{score_all_final}分。
評估結果為：{evaluate_result}。

請記住，本測驗結果僅供參考，不代表真實診斷結果，若有疑慮請聯絡語言治療師。
                    
輸入「返回」回到主選單。"""
                    response_text_2 = f"""若有需要請將此訊息給語言治療師看：
本次篩檢時間為：{today}。
該孩子於此篩檢時月齡為：{total_months}。
正確題目為：{', '.join(map(str, sorted_right_questions))}。
錯誤題目為：{', '.join(map(str, sorted_wrong_questions))}。
                    """
                    line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=response_text_1), TextSendMessage(text=response_text_2)])
                    user_states[user_id] = {"mode": MODE_MAIN_MENU}
                    return
                    

    ## **順向篩檢
    if user_mode == MODE_TESTING_FORWARD:
        state = user_states[user_id]
        questions = state["questions"]
        current_index = state["current_index"]
        score_all_forward_current = state["score_all_current"] # score_all_forward_current指當前題組的分數
        score_all_forward_whole = state["score_all"] # score_all_forward_whole指逆向施測總分
        score_r_forward = state["score_r"]
        score_e_forward = state["score_e"]
        original_group = state["original_group"]
        min_age_in_group = state["min_age_in_group"]  # 該組最小月齡

        # 回覆使用者收到訊息並等待
        response_text_wait = "已收到回覆，請等待AI回應，等待過程中請勿再發送訊息。"
        user_id = event.source.user_id  # 取得使用者 LINE ID
        line_bot_api.push_message(user_id, TextSendMessage(text=response_text_wait))


        # **取得目前這題的資料
        current_question = questions[current_index] # 取得該題所有資料包含組別、題號、題目、類別、提示、通過標準
        current_group = int(questions[0]['組別']) # 取得組別
        question_number = current_question["題號"] # 取得題號
        question_type = current_question["類別"] # 取得類別
        hint = current_question["提示"] # 取得提示
        pass_criteria = current_question["通過標準"] # 取得通過標準

        print("第", current_group, "組數量：", len(questions))###

        # **讓 deepseek 根據題目、提示、通過標準來判斷使用者回應
        deepseek_prompt = f"""
        題目：{current_question["題目"]}
        通過標準：{pass_criteria}
        回應：{user_message}
        根據題目、回應判斷回應是否符合「通過標準」：
        1. 不清楚：回應表示對題目疑惑如不清楚，或回應仍不足以判斷符不符合。
        2. 符合：回應符合「通過標準」(不需字句相同)或明確肯定。
        3. 不符合：回應並非不清楚且未達「通過標準」或明確否定。
        只回應「符合」、「不符合」或「不清楚」，勿額外解釋或加入符號。
        """

        deepseek_response = chat_with_deepseek(deepseek_prompt).strip()
        print(f"現在題目：{current_question['題目']}\n提示：{hint}\n通過標準：{pass_criteria}\n使用者回覆：{user_message}\ndeepseek判斷：{deepseek_response}")  # Debug記錄deepseek回應

        # **根據 deepseek 回應處理邏輯
        if deepseek_response.startswith("符合"):
            score_all_forward_current += 1
            score_all_forward_whole += 1
            user_states[user_id]["score_all_current"] = score_all_forward_current
            user_states[user_id]["score_all"] = score_all_forward_whole
            user_states[user_id]["right_questions"].append(question_number) # 記錄對題題號
            current_index += 1
            if question_type == "R":
                score_r_forward += 1
                user_states[user_id]["score_r"] = score_r_forward

            elif question_type == "E":
                score_e_forward += 1
                user_states[user_id]["score_e"] = score_e_forward
                
            else:
                score_r_forward += 1
                score_e_forward += 1
                user_states[user_id]["score_r"] = score_r_forward
                user_states[user_id]["score_e"] = score_e_forward
            response_text = "了解，現在進入下一題。\n\n"
        elif deepseek_response.startswith("不符合"):
            current_index += 1
            user_states[user_id]["wrong_questions"].append(question_number) # 記錄錯題題號
            response_text = "了解，現在進入下一題。\n\n"
        elif deepseek_response.startswith("不清楚"):
            # **若回答不清楚，提供簡單易懂的提示
            hint_prompt = f"""
            題目：{current_question['題目']}，例子：{hint}
            使用者回應模糊或不理解題目需提示，請根據題目與例子生成30字內的簡單提示。
            """
            hint_response = chat_with_deepseek(hint_prompt).strip()
            response_text = f"{hint_response}\n請再回覆一次。"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
            return
        else:
            response_text = "❌無法判斷回應，請再試一次。"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
            return
        print("第", current_group, "組第幾題：", current_index, "現在總分：", score_all_forward_whole, "現在R分：", score_r_forward, "現在E分：", score_e_forward)
        user_states[user_id]["current_index"] = current_index

        if current_index < len(questions):
            response_text += f"題目：{questions[current_index]['題目']}\n\n輸入「返回」可中途退出篩檢。"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
            return
        else:
            pass_percentage = score_all_forward_current / len(questions)  # 計算通過比例

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
                        "score_all_current":0,
                        "score_all": score_all_forward_whole, "score_r": score_r_forward, "score_e": score_e_forward,
                        "right_questions" :user_states[user_id]["right_questions"],
                        "wrong_questions": user_states[user_id]["wrong_questions"]
                    })
                    response_text = f"題目：{new_questions[0]['題目']}\n\n輸入「返回」可中途退出篩檢。"
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
                    return
                else:
                    response_text = "找不到新題組，系統出現錯誤。返回主選單。"
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
                    user_states[user_id] = {"mode": MODE_MAIN_MENU}
                    return

            else:
                score_all_final = get_group_all_score(original_group) + score_all_forward_whole # 總分=當前組數減一所有組數的總分加上當前組的分數
                #score_r_final = get_group_r_score(original_group) + score_r_forward
                #score_e_final = get_group_e_score(original_group) + score_e_forward
                evaluate_result = evaluate_development(score_all_final, original_group)
                today = datetime.now().strftime("%Y-%m-%d")
                total_months = user_states[user_id]["total_months"]
                right_questions = user_states[user_id]["right_questions"]
                sorted_right_questions = sorted(right_questions, key=lambda x: int(x))
                wrong_questions = user_states[user_id]["wrong_questions"]
                sorted_wrong_questions = sorted(wrong_questions, key=lambda x: int(x))
                response_text_1 = f"""篩檢結束，總分為{score_all_final}分。
評估結果為：{evaluate_result}。

請記住，本測驗結果僅供參考，不代表真實診斷結果，若有疑慮請聯絡語言治療師。
                    
輸入「返回」回到主選單。"""
                response_text_2 = f"""若有需要請將此訊息給語言治療師看：
本次篩檢時間為：{today}。
該孩子於此篩檢時月齡為：{total_months}。
正確題目為：{', '.join(map(str, sorted_right_questions))}。
錯誤題目為：{', '.join(map(str, sorted_wrong_questions))}。
                    """
                line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=response_text_1), TextSendMessage(text=response_text_2)])
                user_states[user_id] = {"mode": MODE_MAIN_MENU}
                return
                

    ##逆向篩檢     
    if user_mode == MODE_TESTING_BACKWARD:
        state = user_states[user_id]
        questions = state["questions"]
        current_index = state["current_index"]
        score_all_backward_current = state["score_all_current"]
        score_all_backward_whole = state["score_all"]
        score_r_backward = state["score_r"]
        score_e_backward = state["score_e"]
        original_group = state["original_group"]
        min_age_in_group = state["min_age_in_group"]  # 該組最小月齡

        # 回覆使用者收到訊息並等待
        response_text_wait = "已收到回覆，請等待AI回應，等待過程中請勿再發送訊息。"
        user_id = event.source.user_id  # 取得使用者 LINE ID
        line_bot_api.push_message(user_id, TextSendMessage(text=response_text_wait))

        # **取得目前這題的資料
        current_question = questions[current_index] # 取得該題所有資料包含組別、題號、題目、類別、提示、通過標準
        current_group = int(questions[0]['組別']) # 取得組別
        question_number = current_question["題號"] # 取得題號
        question_type = current_question["類別"] # 取得類別
        hint = current_question["提示"] # 取得提示
        pass_criteria = current_question["通過標準"] # 取得通過標準

        print("第", current_group, "組數量：", len(questions))###

        # **讓 deepseek 根據題目、提示、通過標準來判斷使用者回應
        deepseek_prompt = f"""
        題目：{current_question["題目"]}
        通過標準：{pass_criteria}
        回應：{user_message}
        根據題目、回應判斷回應是否符合「通過標準」：
        1. 不清楚：回應表示對題目疑惑如不清楚，或回應仍不足以判斷符不符合。
        2. 符合：回應符合「通過標準」(不需字句相同)或明確肯定。
        3. 不符合：回應並非不清楚且未達「通過標準」或明確否定。
        只回應「符合」、「不符合」或「不清楚」，勿額外解釋或加入符號。
        """

        deepseek_response = chat_with_deepseek(deepseek_prompt).strip()
        print(f"現在題目：{current_question['題目']}\n提示：{hint}\n通過標準{pass_criteria}\n使用者回覆{user_message}\ndeepseek判斷：{deepseek_response}")  # Debug記錄deepseek回應

        # **根據 deepseek 回應處理邏輯
        if deepseek_response.startswith("符合"):
            score_all_backward_current += 1
            score_all_backward_whole += 1
            user_states[user_id]["score_all_current"] = score_all_backward_current
            user_states[user_id]["score_all"] = score_all_backward_whole
            user_states[user_id]["right_questions"].append(question_number) # 記錄對題題號
            current_index += 1
            if question_type == "R":
                score_r_backward += 1
                user_states[user_id]["score_r"] = score_r_backward

            elif question_type == "E":
                score_e_backward += 1
                user_states[user_id]["score_e"] = score_e_backward
                
            else:
                score_r_backward += 1
                score_e_backward += 1
                user_states[user_id]["score_r"] = score_r_backward
                user_states[user_id]["score_e"] = score_e_backward
            response_text = "了解，現在進入下一題。\n\n"
        elif deepseek_response.startswith("不符合"):
            current_index += 1
            user_states[user_id]["wrong_questions"].append(question_number) # 紀錄錯題題號
            response_text = "了解，現在進入下一題。\n\n"
        elif deepseek_response.startswith("不清楚"):
            # **若回答不清楚，提供簡單易懂的提示
            hint_prompt = f"""
            題目：{current_question['題目']}，例子：{hint}
            使用者回應模糊或不理解題目需提示，請根據題目與例子生成30字內的簡單提示。
            """
            hint_response = chat_with_deepseek(hint_prompt).strip()
            response_text = f"{hint_response}\n請再回覆一次。"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
            return
        else:
            response_text = "❌無法判斷回應，請再試一次。"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
            return
        print("第", current_group, "組第幾題：", current_index, "現在總分：", score_all_backward_whole, "現在R分：", score_r_backward, "現在E分：", score_e_backward)
        user_states[user_id]["current_index"] = current_index

        if current_index < len(questions):
            response_text += f"題目：{questions[current_index]['題目']}\n\n輸入「返回」可中途退出篩檢。"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
            return
        else:
            pass_percentage = score_all_backward_current / len(questions)  # 計算通過比例

            if pass_percentage < 1.0 and current_group > 1:  
                # 逆向施測（進入上一組）
                print("繼續逆向")
                next_group = current_group - 1
                min_age_in_group = get_min_age_for_group(next_group)
                new_questions = get_questions_by_age(min_age_in_group)

                if new_questions:
                    user_states[user_id].update({
                        "group": next_group,
                        "min_age_in_group": min_age_in_group,
                        "questions": new_questions,
                        "current_index": 0,
                        "score_all_current": 0,
                        "score_all": score_all_backward_whole, "score_r": score_r_backward, "score_e": score_e_backward,
                        "right_questions" :user_states[user_id]["right_questions"],
                        "wrong_questions": user_states[user_id]["wrong_questions"]
                    })
                    response_text = f"題目：{new_questions[0]['題目']}\n\n輸入「返回」可中途退出篩檢。"
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
                    return
                
                else:
                    response_text = "找不到新題組，系統出現錯誤。返回主選單。"
                    user_states[user_id] = {"mode": MODE_MAIN_MENU}
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
                    return

            else:
                if current_group > 1: # 確保如果逆向到第一組current_group - 1不會等於零
                    score_all_final = get_group_all_score(current_group - 1) + score_all_backward_whole # 總分=當前組數減一所有組數的總分+逆向施測分數+首組分數
                    #score_r_final = get_group_r_score(current_group - 1) + score_r_backward
                    #score_e_final = get_group_e_score(current_group - 1) + score_e_backward
                    evaluate_result = evaluate_development(score_all_final, original_group)
                    today = datetime.now().strftime("%Y-%m-%d")
                    total_months = user_states[user_id]["total_months"]
                    right_questions = user_states[user_id]["right_questions"]
                    sorted_right_questions = sorted(right_questions, key=lambda x: int(x))
                    wrong_questions = user_states[user_id]["wrong_questions"]
                    sorted_wrong_questions = sorted(wrong_questions, key=lambda x: int(x))
                    response_text_1 = f"""篩檢結束，總分為{score_all_final}分。
評估結果為：{evaluate_result}。

請記住，本測驗結果僅供參考，不代表真實診斷結果，若有疑慮請聯絡語言治療師。
                    
輸入「返回」回到主選單。"""
                    response_text_2 = f"""若有需要請將此訊息給語言治療師看：
本次篩檢時間為：{today}。
該孩子於此篩檢時月齡為：{total_months}。
正確題目為：{', '.join(map(str, sorted_right_questions))}。
錯誤題目為：{', '.join(map(str, sorted_wrong_questions))}。
                    """
                    line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=response_text_1), TextSendMessage(text=response_text_2)])
                    user_states[user_id] = {"mode": MODE_MAIN_MENU}
                    return

                else: # 如果逆向到第一組則逆向施測分數加上首組分數等於總分
                    score_all_final = score_all_backward_whole
                    #score_r_final = score_r_backward
                    #score_e_final = score_e_backward
                    evaluate_result = evaluate_development(score_all_final, original_group)
                    today = datetime.now().strftime("%Y-%m-%d")
                    total_months = user_states[user_id]["total_months"]
                    right_questions = user_states[user_id]["right_questions"]
                    sorted_right_questions = sorted(right_questions, key=lambda x: int(x))
                    wrong_questions = user_states[user_id]["wrong_questions"]
                    sorted_wrong_questions = sorted(wrong_questions, key=lambda x: int(x))
                    response_text_1 = f"""篩檢結束，總分為{score_all_final}分。
評估結果為：{evaluate_result}。

請記住，本測驗結果僅供參考，不代表真實診斷結果，若有疑慮請聯絡語言治療師。
                    
輸入「返回」回到主選單。"""
                    response_text_2 = f"""若有需要請將此訊息給語言治療師看：
本次篩檢時間為：{today}。
該孩子於此篩檢時月齡為：{total_months}。
正確題目為：{', '.join(map(str, sorted_right_questions))}。
錯誤題目為：{', '.join(map(str, sorted_wrong_questions))}。
                    """
                    line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=response_text_1), TextSendMessage(text=response_text_2)])
                    user_states[user_id] = {"mode": MODE_MAIN_MENU}
                    return

# **啟動 Flask 應用**
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)