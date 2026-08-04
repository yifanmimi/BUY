import os
import requests
import zoneinfo
from datetime import datetime

def send_line_notification():
    """獨立發送每日提醒通知至 LINE"""
    channel_access_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    user_id = os.environ.get("LINE_USER_ID")
    
    # 填入你的 Web App / 試算表網址
    system_url = os.environ.get("SYSTEM_URL", "https://your-app-url.com")
    
    if not channel_access_token or not user_id:
        print("ℹ️ 未設定 LINE 憑證，跳過推播。")
        return

    taipei_tz = zoneinfo.ZoneInfo("Asia/Taipei")
    today_str = datetime.now(taipei_tz).strftime("%Y-%m-%d")
    
    message_text = (
        f"🎯 【每日標案 AI 篩選通知 - {today_str}】\n\n"
        f"今日標案資料已更新完畢！\n\n"
        f"👉 點擊前往查看最新結果：\n{system_url}"
    )

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {channel_access_token}"
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
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code == 200:
            print("🚀 已成功發送 LINE 提醒通知！")
        else:
            print(f"⚠️ LINE 推播失敗，狀態碼：{response.status_code}, 回應：{response.text}")
    except Exception as e:
        print(f"❌ 發送 LINE 通知時發生異常: {e}")

if __name__ == "__main__":
    send_line_notification()
