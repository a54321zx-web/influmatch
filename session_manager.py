"""
session_manager.py — STEP 7
auth.json 만료 감지 + 수동 로그인으로 세션 갱신
"""

import asyncio
import json
import os
import time
from datetime import datetime
from playwright.async_api import async_playwright, Page

AUTH_FILE   = "auth.json"
BACKUP_FILE = "auth_backup.json"
CRED_FILE   = "credentials.json"


# ══════════════════════════════════════════════════════════════
# 세션 상태 확인
# ══════════════════════════════════════════════════════════════
def is_session_expired() -> tuple[bool, str]:
    if not os.path.exists(AUTH_FILE):
        return True, "auth.json 파일 없음"
    try:
        with open(AUTH_FILE, "r", encoding="utf-8") as f:
            auth = json.load(f)
        cookies = auth.get("cookies", [])
        if not cookies:
            return True, "쿠키 없음"
        now = time.time()
        for cookie in cookies:
            if cookie.get("name") == "sessionid":
                expires = cookie.get("expires", 0)
                if expires > 0 and expires < now:
                    exp_dt = datetime.fromtimestamp(expires).strftime("%Y-%m-%d %H:%M")
                    return True, f"sessionid 만료 ({exp_dt})"
                if expires > 0 and expires - now < 7 * 86400:
                    days_left = int((expires - now) / 86400)
                    return False, f"만료 {days_left}일 전 (갱신 권장)"
                return False, "정상"
        return True, "sessionid 쿠키 없음"
    except Exception as e:
        return True, f"파싱 오류: {e}"


# ══════════════════════════════════════════════════════════════
# 수동 로그인 → 세션 저장
# ══════════════════════════════════════════════════════════════
async def auto_login(username: str = "", password: str = "") -> bool:
    """
    브라우저를 열고 사용자가 직접 로그인 → auth.json 저장.
    인스타 봇 탐지 우회를 위해 수동 로그인 방식 사용.
    """
    print(f"\n🔐 세션 갱신을 위해 브라우저를 엽니다...")

    if os.path.exists(AUTH_FILE):
        import shutil
        shutil.copy(AUTH_FILE, BACKUP_FILE)
        print(f"   기존 세션 백업: {BACKUP_FILE}")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )
            page = await context.new_page()
            await page.set_viewport_size({"width": 1280, "height": 800})

            await page.goto("https://www.instagram.com/accounts/login/", wait_until="load")

            print("\n" + "="*50)
            print("  브라우저에서 인스타그램에 로그인해 주세요.")
            print("  로그인 완료 후 아래 Enter 키를 눌러주세요.")
            print("="*50)
            input("  [로그인 완료 후 Enter] ")

            await page.goto("https://www.instagram.com/", wait_until="load")
            await asyncio.sleep(2)

            current_url = page.url
            is_logged_in = "login" not in current_url and "accounts" not in current_url

            if is_logged_in:
                await context.storage_state(path=AUTH_FILE)
                print(f"   ✅ 세션 저장 완료: {AUTH_FILE}")
                await browser.close()
                return True
            else:
                print(f"   ❌ 로그인 확인 실패. 다시 시도해 주세요.")
                if os.path.exists(BACKUP_FILE):
                    import shutil
                    shutil.copy(BACKUP_FILE, AUTH_FILE)
                await browser.close()
                return False

    except Exception as e:
        print(f"   ❌ 오류: {e}")
        return False


# ══════════════════════════════════════════════════════════════
# 세션 유효성 실시간 확인
# ══════════════════════════════════════════════════════════════
async def verify_session_live(page: Page) -> bool:
    try:
        await page.goto("https://www.instagram.com/", wait_until="load")
        await asyncio.sleep(1.5)
        current_url = page.url
        if "login" in current_url or "accounts" in current_url:
            return False
        return True
    except:
        return False


# ══════════════════════════════════════════════════════════════
# 통합 세션 체크 — engyn.py에서 호출
# ══════════════════════════════════════════════════════════════
async def ensure_valid_session() -> bool:
    expired, reason = is_session_expired()

    if not expired:
        if reason != "정상":
            print(f"   ⚠️  세션 경고: {reason}")
        else:
            print(f"   ✅ 세션 정상")
        return True

    print(f"\n⚠️  세션 만료 감지: {reason}")
    print("   브라우저를 열어 수동 로그인을 진행합니다...")
    success = await auto_login()
    if success:
        print("   ✅ 세션 갱신 완료")
    else:
        print("   ❌ 세션 갱신 실패")
    return success


# ══════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════
async def setup_credentials():
    print("\n🔧 인스타그램 세션 설정")
    print("   브라우저가 열리면 직접 로그인해 주세요.\n")
    await auto_login()


if __name__ == "__main__":
    import sys

    if "--setup" in sys.argv:
        asyncio.run(setup_credentials())
    elif "--check" in sys.argv:
        expired, reason = is_session_expired()
        status = "❌ 만료" if expired else "✅ 정상"
        print(f"세션 상태: {status} ({reason})")
    elif "--renew" in sys.argv:
        asyncio.run(auto_login())
    else:
        print("사용법:")
        print("  python session_manager.py --setup   # 세션 설정 (최초 1회)")
        print("  python session_manager.py --check   # 세션 상태 확인")
        print("  python session_manager.py --renew   # 세션 수동 갱신")