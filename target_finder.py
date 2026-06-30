"""
target_finder.py
해시태그 기반 DM 타겟 인플루언서 자동 수집
결과를 엑셀로 저장
"""

import asyncio
import re
import os
import random
import pandas as pd
from datetime import datetime
from playwright.async_api import async_playwright

DESKTOP = os.path.join(os.path.expanduser("~"), "Desktop")
OUTPUT_FILE = os.path.join(DESKTOP, "dm_targets.xlsx")

# 타겟 조건
MIN_FOLLOWERS = 500
MAX_FOLLOWERS = 10_000
MIN_POSTS     = 10

async def human_delay(a=1.0, b=2.5):
    await asyncio.sleep(random.uniform(a, b))

def _parse_count(text: str) -> int:
    if not text: return 0
    text = text.strip().replace(",", "").replace(" ", "")
    try:
        if "만" in text: return int(float(text.replace("만","")) * 10_000)
        if "K" in text or "k" in text: return int(float(text.upper().replace("K","")) * 1_000)
        if "M" in text or "m" in text: return int(float(text.upper().replace("M","")) * 1_000_000)
        return int(float(re.sub(r"[^\d.]", "", text)))
    except: return 0


async def collect_hashtag_accounts(page, hashtag: str, max_accounts: int = 50) -> list:
    """해시태그 페이지에서 게시물 작성자 수집"""
    print(f"\n🔍 #{hashtag} 검색 중...")
    results = []
    seen = set()

    await page.goto(f"https://www.instagram.com/explore/tags/{hashtag}/", wait_until="load")
    await human_delay(2, 3)

    # 게시물 링크 수집
    hrefs = []
    for sel in ["a[href*='/p/']", "article a[href*='/p/']"]:
        links = await page.locator(sel).all()
        for lnk in links:
            href = await lnk.get_attribute("href") or ""
            if "/p/" in href and href not in hrefs:
                hrefs.append(href)
        if hrefs: break

    print(f"   게시물 {len(hrefs)}개 발견")

    for i, href in enumerate(hrefs[:max_accounts]):
        try:
            url = f"https://www.instagram.com{href}" if href.startswith("/") else href
            await page.goto(url, wait_until="load")
            await human_delay(1.5, 2.5)

            # 작성자 계정 추출
            username = ""
            for sel in ["a[href*='/'][role='link'] span", "header a span", "a[href*='/'] span.x1lliihq"]:
                try:
                    els = await page.locator(sel).all()
                    for el in els:
                        txt = (await el.inner_text()).strip()
                        if txt and re.match(r'^[a-zA-Z0-9_.]+$', txt) and len(txt) > 2:
                            username = txt
                            break
                    if username: break
                except: continue

            if not username or username in seen:
                continue

            # 프로필 페이지로 이동해서 팔로워 확인
            await page.goto(f"https://www.instagram.com/{username}/", wait_until="load")
            await human_delay(1.0, 2.0)

            # 팔로워 수 수집
            follower_count = 0
            try:
                meta = await page.locator("meta[name='description']").get_attribute("content")
                if meta:
                    m = re.search(r'팔로워\s*([\d,.]+[KMkm만]?)명?', meta)
                    if m: follower_count = _parse_count(m.group(1))
            except: pass

            # 게시물 수 수집
            post_count = 0
            try:
                meta = await page.locator("meta[name='description']").get_attribute("content")
                if meta:
                    m = re.search(r'게시물\s*([\d,.]+)', meta)
                    if m: post_count = _parse_count(m.group(1))
            except: pass

            # 바이오 수집
            bio = ""
            for sel in ["div._aacl._aaco._aacu._aacx._aad6._aade", "span.x1lliihq", "section main header section span"]:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        txt = (await el.inner_text()).strip()
                        if txt and len(txt) > 2:
                            bio = txt[:100]
                            break
                except: continue

            # 조건 필터링
            if follower_count < MIN_FOLLOWERS:
                print(f"   [{i+1}] @{username} 팔로워 {follower_count:,}명 — 제외 (너무 적음)")
                continue
            if follower_count > MAX_FOLLOWERS:
                print(f"   [{i+1}] @{username} 팔로워 {follower_count:,}명 — 제외 (너무 많음)")
                continue
            if post_count < MIN_POSTS:
                print(f"   [{i+1}] @{username} 게시물 {post_count}개 — 제외 (너무 적음)")
                continue

            seen.add(username)
            results.append({
                "계정명":    username,
                "팔로워":    follower_count,
                "게시물수":  post_count,
                "바이오":    bio,
                "URL":       f"https://www.instagram.com/{username}/",
                "해시태그":  f"#{hashtag}",
                "수집일":    datetime.now().strftime("%Y-%m-%d"),
                "DM발송":    "미발송",
                "반응":      "",
                "메모":      "",
            })
            print(f"   [{i+1}] ✅ @{username} | 팔로워 {follower_count:,}명 | 게시물 {post_count}개")

        except Exception as e:
            print(f"   [{i+1}] 오류: {e}")
            continue

        # 계정 제한 방지 딜레이
        if (i+1) % 5 == 0:
            wait = random.uniform(5, 10)
            print(f"   잠시 대기 ({wait:.0f}초)...")
            await asyncio.sleep(wait)

    return results


async def main(hashtags: list, max_per_tag: int = 30):
    if not os.path.exists("auth.json"):
        print("❌ auth.json 없음 — session_manager.py --setup 실행 필요")
        return

    print(f"\n🎯 DM 타겟 수집 시작")
    print(f"   해시태그: {', '.join(['#'+h for h in hashtags])}")
    print(f"   조건: 팔로워 {MIN_FOLLOWERS:,}~{MAX_FOLLOWERS:,}명 | 게시물 {MIN_POSTS}개+")
    print(f"   태그당 최대: {max_per_tag}개")

    all_results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            storage_state="auth.json",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        await page.set_viewport_size({"width": 1280, "height": 800})

        for tag in hashtags:
            results = await collect_hashtag_accounts(page, tag, max_per_tag)
            all_results.extend(results)
            print(f"   #{tag} 완료: {len(results)}개 수집")

            if tag != hashtags[-1]:
                wait = random.uniform(8, 15)
                print(f"\n   다음 태그 전 대기 ({wait:.0f}초)...")
                await asyncio.sleep(wait)

        await browser.close()

    # 중복 제거
    seen = set()
    unique = []
    for r in all_results:
        if r["계정명"] not in seen:
            seen.add(r["계정명"])
            unique.append(r)

    print(f"\n📊 총 {len(unique)}개 계정 수집 완료 (중복 제거)")

    if not unique:
        print("수집된 계정이 없습니다.")
        return

    # 팔로워 순 정렬
    unique.sort(key=lambda x: x["팔로워"], reverse=True)

    # 엑셀 저장
    df = pd.DataFrame(unique)

    with pd.ExcelWriter(OUTPUT_FILE, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="DM 타겟")

        ws = writer.sheets["DM 타겟"]
        ws.column_dimensions["A"].width = 20
        ws.column_dimensions["B"].width = 12
        ws.column_dimensions["C"].width = 10
        ws.column_dimensions["D"].width = 40
        ws.column_dimensions["E"].width = 40
        ws.column_dimensions["F"].width = 15
        ws.column_dimensions["G"].width = 12
        ws.column_dimensions["H"].width = 10
        ws.column_dimensions["I"].width = 10
        ws.column_dimensions["J"].width = 20

    print(f"\n✅ 엑셀 저장 완료: {OUTPUT_FILE}")
    print(f"\n🏆 상위 10개 타겟:")
    for i, r in enumerate(unique[:10]):
        print(f"   {i+1}위 @{r['계정명']} — 팔로워 {r['팔로워']:,}명 | {r['해시태그']}")

    print(f"\n📱 DM 발송 순서:")
    print(f"   1. 엑셀 파일 열기: {OUTPUT_FILE}")
    print(f"   2. 계정명 복사 → 인스타에서 검색 → DM 발송")
    print(f"   3. DM 발송 후 '발송' 체크 → 반응 여부 기록")


if __name__ == "__main__":
    import sys

    # 기본 해시태그 (뷰티 집중)
    DEFAULT_TAGS = [
        "뷰티스타그램",
        "스킨케어",
        "메이크업",
        "먹스타그램",
        "일상스타그램",
    ]

    tags = sys.argv[1:] if len(sys.argv) > 1 else DEFAULT_TAGS
    asyncio.run(main(tags, max_per_tag=20))
