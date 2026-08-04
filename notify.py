import os
import sys
import requests

def send_line_push_notification():
    # 1. 從環境變數讀取 GitHub Secrets 傳進來的金鑰與資訊
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    user_id = os.environ.get("LINE_USER_ID")
    system_url = os.environ.get("SYSTEM_URL", "https://google.com")

    # 簡單的防呆檢查
    if not token or not user_id:
        print("❌ 錯誤：未設定 LINE_CHANNEL_ACCESS_TOKEN 或 LINE_USER_ID 環境變數。")
        sys.exit(1)

    # 2. 設定 LINE Messaging API 的 Push Message 端點與請求標頭
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }

    # 3. 構建推播訊息內容
    message_text = (
        "🔔 每日標案系統監控通知\n\n"
        "最新的標案檢索資料已更新完成！\n"
        f"🔗 點擊查看系統試算表：\n{system_url}"
    )

    payload = {
        "to": user_id,
        "messages": [
            {
                "type": "text",
                "text": message_text
            }
        ]
    }

    # 4. 發送 HTTP POST 請求
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
