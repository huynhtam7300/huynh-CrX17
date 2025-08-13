from .notify_telegram import send_telegram_message

def send_daily_report(text: str) -> None:
    send_telegram_message("📊 DAILY REPORT\n" + text)