import os
import sys
import json
import requests

def send_line_push_notification():
    # ==========================================
    # 0. 判斷是否有新標案資料 (有新案才推播)
    # ==========================================
    json_file = "new_tenders.json"

    # 檢查檔案是否存在
    if not os.path.exists(json_file):
        print("ℹ️ 未檢測到 new_tenders.json 檔案，今日無新標案，自動結束流程。")
        sys.exit(0)  # 正常結束，讓 GitHub Actions 顯示綠色成功

    # 讀取標案 JSON 資料
    try:
        with open(json_file, "r", encoding="utf-8") as f:
            tenders = json.load(f)
    except Exception as e:
        print(f"❌ 讀取 {json_file} 時發生錯誤: {e}")
        sys.exit(1)

    # 檢查標案列表是否為空
    if not tenders or not isinstance(tenders, list) or len(tenders) == 0:
        print("✅ 今日無新增標案，不發送 LINE 通知。")
        sys.exit(0)  # 正常結束

    print(f"🎉 偵測到 {len(tenders)} 筆新標案，開始準備發送 LINE 推播訊息...")

    # ==========================================
    # 1. 從環境變數讀取 GitHub Secrets 金鑰與資訊
    # ==========================================
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    user_id = os.environ.get("LINE_USER_ID")
    system_url = os.environ.get("SYSTEM_URL", "https://google.com")

    # 簡單的防呆檢查
    if not token or not user_id:
        print("❌ 錯誤：未設定 LINE_CHANNEL_ACCESS_TOKEN 或 LINE_USER_ID 環境變數。")
        sys.exit(1)

    # ==========================================
    # 2. 構建動態推播訊息內容
    # ==========================================
    count = len(tenders)
    
    # 組合新標案摘要清單 (最多列出前 5 筆，避免訊息過長)
    details_list = []
    for idx, item in enumerate(tenders[:5], 1):
        title = item.get("title", "無標案名稱")
        budget = item.get("budget", "未公開/詳內文")
        unit = item.get("unit", "")
        
        entry = f"{idx}. {title}\n   💰 預算: {budget}"
        if unit:
            entry += f"\n   🏢 招標單位: {unit}"
        details_list.append(entry)

    details_text = "\n\n".join(details_list)
    
    if count > 5:
        details_text += f"\n\n...等共 {count} 筆新標案"

    message_text = (
        f"🚨 發現 {count} 筆符合條件的新標案！\n\n"
        f"{details_text}\n\n"
        f"🔗 點擊查看完整系統試算表：\n{system_url}"
    )

    # ==========================================
    # 3. 設定 LINE Messaging API Push Message
    # ==========================================
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }

    payload = {
        "to": user_id,
        "messages": [
            {
                "type": "text",
                "text": message_text
            }
        ]
    }

    # ==========================================
    # 4. 發送 HTTP POST 請求
    # ==========================================
    print("🚀 正在發送 LINE 推播訊息...")
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        
        # 輸出 HTTP 回應狀態碼與結果（方便在 Actions 日誌中除錯）
        print(f"📡 Status Code: {response.status_code}")
        print(f"📩 Response Body: {response.text}")

        # 如果 HTTP Code 不是 200，拋出例外以讓 GitHub Actions 標示為 Failure
        response.raise_for_status()
        print("✅ 推播訊息發送成功！")

    except requests.exceptions.HTTPError as err:
        print(f"❌ LINE API 發送失敗: {err}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 發生未預期的錯誤: {e}")
        sys.exit(1)

if __name__ == "__main__":
    send_line_push_notification()
