"""
debug_follower.py
팔로워 수 수집 디버깅 스크립트
headless=False로 실제 페이지 구조 확인
"""
import asyncio
import re
import os
import sys

from playwright.async_api import async_playwright

TARGET = "miwoon.bubu"   # 테스트 계정

async def debug():
    if not os.path.exists("auth.json"):
        print("❌ auth.json 없음")
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)   # 눈으로 확인
        context = await browser.new_context(
            storage_state="auth.json",
            ignore_https_errors=True,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()
        await page.set_viewport_size({"width": 1280, "height": 800})

        print(f"\n🔍 [{TARGET}] 페이지 로드 중...")
        await page.goto(f"https://www.instagram.com/{TARGET}/", wait_until="load")
        await asyncio.sleep(3)

        print("\n── 방법 1: meta description ──────────────────────")
        try:
            meta = await page.locator("meta[name='description']").get_attribute("content")
            print(f"  meta content: {meta}")
        except Exception as e:
            print(f"  실패: {e}")

        print("\n── 방법 2: 팔로워 링크 span ─────────────────────")
        for sel in [
            f"a[href='/{TARGET}/followers/'] span[title]",
            f"a[href='/{TARGET}/followers/'] span",
            "a[href*='followers/'] span[title]",
            "a[href*='followers/'] span",
        ]:
            try:
                els = await page.locator(sel).all()
                if els:
                    for el in els[:3]:
                        title = await el.get_attribute("title") or ""
                        txt   = await el.inner_text()
                        print(f"  [{sel}] title={title!r} text={txt!r}")
                else:
                    print(f"  [{sel}] 없음")
            except Exception as e:
                print(f"  [{sel}] 오류: {e}")

        print("\n── 방법 3: body 전체 텍스트 패턴 ───────────────")
        try:
            body = await page.inner_text("body")
            patterns = [
                r'([\d.]+)만\s*팔로워',
                r'팔로워\s*([\d,.]+[KMkm만]?)',
                r'([\d,.]+[KMkm만]?)\s*followers',
                r'([\d,.]+[KMkm만]?)\s*Followers',
            ]
            found = False
            for pat in patterns:
                m = re.search(pat, body, re.IGNORECASE)
                if m:
                    print(f"  패턴 [{pat}] → {m.group(0)!r}")
                    found = True
            if not found:
                print("  패턴 없음 — body 일부 출력:")
                # 팔로워 관련 줄만 출력
                for line in body.split('\n'):
                    if any(kw in line.lower() for kw in ['follower', '팔로워', '742']):
                        print(f"    {line.strip()!r}")
        except Exception as e:
            print(f"  오류: {e}")

        print("\n── 방법 4: JSON-LD ──────────────────────────────")
        try:
            scripts = await page.locator("script[type='application/ld+json']").all()
            for s in scripts:
                txt = await s.inner_text()
                if 'follower' in txt.lower():
                    print(f"  JSON-LD: {txt[:200]}")
        except Exception as e:
            print(f"  오류: {e}")

        print("\n── 방법 5: 페이지 HTML 저장 ─────────────────────")
        html = await page.content()
        with open("debug_profile.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("  debug_profile.html 저장 완료")

        # 742 숫자가 HTML 어디에 있는지 찾기
        if "742" in html:
            idx = html.index("742")
            print(f"\n  ✅ '742' 발견! 주변 컨텍스트:")
            print(f"  ...{html[max(0,idx-100):idx+100]}...")
        else:
            print("\n  ❌ HTML에서 '742' 숫자를 찾을 수 없음")
            print("     → 로그인 세션 만료 or 인스타 봇 탐지 가능성")

        input("\n브라우저 확인 후 Enter 누르면 종료...")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(debug())