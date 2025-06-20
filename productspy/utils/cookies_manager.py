import os
import json
from typing import List, Optional
from playwright.sync_api import sync_playwright

COOKIES_DIR = os.path.join(os.getcwd(), "cookies")

def ensure_cookies_dir():
    if not os.path.exists(COOKIES_DIR):
        os.makedirs(COOKIES_DIR)

def get_cookies_path(platform_name: str) -> str:
    ensure_cookies_dir()
    filename = f"{platform_name.lower()}.json"
    return os.path.join(COOKIES_DIR, filename)

def load_cookies(platform_name: str) -> Optional[List[dict]]:
    path = get_cookies_path(platform_name)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        try:
            cookies = json.load(f)
            return cookies
        except json.JSONDecodeError:
            return None

def save_cookies(platform_name: str, cookies: List[dict]):
    path = get_cookies_path(platform_name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cookies, f, ensure_ascii=False, indent=2)

def update_cookies_interactively(url, platform_name):
    print(f"⏳ فتح المتصفح... الرجاء إتمام التحقق أو تسجيل الدخول على موقع {platform_name}.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=100)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
            locale="ar-SA"
        )
        page = context.new_page()
        page.goto(url, wait_until="load", timeout=60000)

        print("\n✅ المتصفح جاهز.\n🔐 قم بإكمال التحقق، ثم تسجيل الدخول إذا طُلب منك.")
        print("🔒 بعد الانتهاء، **لا تغلق هذه النافذة**، فقط أغلق المتصفح يدويًا.")
        input("🟢 اضغط Enter بعد إغلاق المتصفح يدويًا...")

        # نحاول حفظ الكوكيز بعد ما يخلص المستخدم
        try:
            cookies = context.cookies()
            save_cookies(platform_name, cookies)
            print(f"✅ تم حفظ الكوكيز لـ {platform_name} بنجاح.")
        except Exception as e:
            print(f"❌ فشل في حفظ الكوكيز: {e}")

        # نحاول نغلق كل شيء بأمان
        try:
            context.close()
        except:
            pass
        try:
            browser.close()
        except:
            pass
