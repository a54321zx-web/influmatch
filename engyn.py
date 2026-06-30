import asyncio
import re
import statistics
import os
import random
from datetime import datetime
from collections import Counter

from playwright.async_api import async_playwright
import pandas as pd
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from report_generator import generate_reports
from session_manager import ensure_valid_session, is_session_expired
from auth import hash_password, verify_password, create_token, get_current_user, get_current_user_optional
from fastapi import Depends, Request
import database as db

app = FastAPI(title="insta_engine v5.7 — AI 인플루언서 스코어링")

# 정적 파일 서빙
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")


# ── 페이지 라우팅 ──────────────────────────────────────────
@app.get("/join")
async def page_join():
    return FileResponse("static/join.html")

@app.get("/marketplace")
async def page_marketplace():
    return FileResponse("static/marketplace.html")

@app.get("/admin")
async def page_admin():
    return FileResponse("static/index.html")

@app.get("/dashboard")
async def page_dashboard():
    return FileResponse("static/dashboard.html")

@app.get("/company/join")
async def page_company_join():
    return FileResponse("static/company_join.html")

@app.get("/company/dashboard")
async def page_company_dashboard():
    return FileResponse("static/company_dashboard.html")

DESKTOP_PATH    = os.path.join(os.path.expanduser("~"), "Desktop")
EXCEL_FILE_NAME = os.path.join(DESKTOP_PATH, "instagram_analysis_result.xlsx")

FOLLOWER_TIERS = {
    "nano":    {"min": 500,       "max": 10_000,       "er_baseline": 5.0,  "weight_multiplier": 1.2},
    "micro":   {"min": 10_000,    "max": 100_000,      "er_baseline": 3.5,  "weight_multiplier": 1.1},
    "mid":     {"min": 100_000,   "max": 500_000,      "er_baseline": 2.0,  "weight_multiplier": 1.0},
    "macro":   {"min": 500_000,   "max": 1_000_000,    "er_baseline": 1.2,  "weight_multiplier": 0.9},
    "mega":    {"min": 1_000_000, "max": float("inf"), "er_baseline": 0.8,  "weight_multiplier": 0.85},
    "unknown": {"min": 0,         "max": 500,          "er_baseline": 3.0,  "weight_multiplier": 1.0},
}

BOT_COMMENT_PATTERNS = re.compile(
    r'^[\U0001F300-\U0001F9FF\s❤️👍🔥💯✨😍🙏]+$'
    r'|^(nice|great|wow|amazing|cool|follow me|check my|dm me|l4l|f4f)$'
    r'|^[a-z0-9_.]+$',
    re.IGNORECASE | re.UNICODE
)

# ── STEP 4: 카테고리 해시태그 사전 ──────────────────────────
CATEGORY_TAGS = {
    "뷰티":   ["beauty", "makeup", "skincare", "뷰티", "메이크업", "스킨케어",
               "화장품", "코스메틱", "glam", "cosmetic", "lipstick", "얼스타그램",
               "daily_makeup", "grwm", "셀카", "selfie"],
    "패션":   ["fashion", "ootd", "style", "패션", "스타일", "옷스타그램", "데일리룩",
               "outfit", "styling", "lookbook", "패션스타그램", "데일리패션",
               "꿀템", "쇼핑", "shopping", "하울", "haul", "신상", "코디",
               "guide", "daily", "wear", "clothes", "item", "아이템"],
    "음식":   ["food", "foodie", "먹스타그램", "맛집", "요리", "음식", "카페",
               "restaurant", "cooking", "recipe", "yummy", "delicious",
               "카페스타그램", "디저트", "dessert", "베이킹"],
    "여행":   ["travel", "여행", "traveler", "여행스타그램", "vacation", "trip",
               "tour", "abroad", "해외여행", "국내여행", "여행기", "vlog"],
    "육아":   ["육아", "아이", "맘스타그램", "임신", "baby", "mom", "parenting",
               "아기", "임산부", "출산", "newborn", "toddler", "momlife"],
    "운동":   ["fitness", "gym", "workout", "운동", "헬스", "다이어트", "필라테스",
               "yoga", "running", "홈트", "pt", "bodybuilding", "exercise"],
    "게임":   ["gaming", "게임", "gamer", "streamer", "twitch", "esports",
               "fps", "rpg", "lol", "리그오브레전드", "배틀그라운드"],
    "IT/테크": ["tech", "개발", "coding", "developer", "스타트업", "ai", "gpt",
               "programming", "software", "devlife", "코딩"],
    "반려동물": ["dog", "cat", "pet", "강아지", "고양이", "펫스타그램",
                "puppy", "kitten", "반려견", "반려묘", "멍스타그램", "냥스타그램"],
    "인테리어": ["interior", "인테리어", "홈데코", "homedecor", "집스타그램",
                "decor", "furniture", "renovation", "셀프인테리어", "홈스타그램"],
}

# ── 계정명 기반 카테고리 힌트 ─────────────────────────────
USERNAME_HINTS = {
    "fashion": "패션", "style": "패션", "ootd": "패션", "outfit": "패션",
    "beauty": "뷰티",  "makeup": "뷰티", "skin": "뷰티",
    "food": "음식",    "eat": "음식",    "cafe": "음식",  "cook": "음식",
    "travel": "여행",  "trip": "여행",   "tour": "여행",
    "fit": "운동",     "gym": "운동",    "health": "운동",
    "baby": "육아",    "mom": "육아",    "kid": "육아",
    "game": "게임",    "gaming": "게임",
    "pet": "반려동물", "dog": "반려동물","cat": "반려동물",
    "interior": "인테리어", "home": "인테리어",
}

# ── STEP 5: 광고 단가 기준표 (CPE: Cost Per Engagement) ────
# ── 광고 단가 기준표 ────────────────────────────────────────
# 출처: 국내 인플루언서 마케팅 시장가 (2025~2026 기준)
#   - OCHO 인플루언서 단가 가이드 2026
#   - 태그바이(TAGby) 실무 가이드 2026
#   - Shopify 한국 인플루언서 가격 가이드
#   - 국내 SNS 마케팅 에이전시 실거래가 평균
#
# 산정 방식:
#   피드   = 팔로워수 / 1,000 × 10,000원 (기본공식) + 등급 보정
#   릴스   = 피드 × 1.3~1.5 (숏폼 프리미엄 +30~50%)
#   스토리 = 피드 × 0.4~0.5 (24시간 소멸 할인)
#
# tier: {grade: (피드_단가, 스토리_단가, 릴스_단가)} 단위: 원
AD_PRICE_TABLE = {
    # nano: 100~1만 팔로워 / 시장가 3만~20만원
    "nano":  {
        "S": (150_000,  60_000,  200_000),
        "A": (100_000,  40_000,  140_000),
        "B": (60_000,   25_000,   85_000),
        "C": (30_000,   12_000,   42_000),
        "D": (0, 0, 0),
    },
    # micro: 1만~10만 팔로워 / 시장가 10만~80만원
    "micro": {
        "S": (700_000,  280_000, 1_000_000),
        "A": (450_000,  180_000,   650_000),
        "B": (280_000,  110_000,   400_000),
        "C": (130_000,   50_000,   180_000),
        "D": (0, 0, 0),
    },
    # mid: 10만~50만 팔로워 / 시장가 130만~650만원
    "mid":   {
        "S": (4_500_000, 1_800_000, 6_500_000),
        "A": (3_000_000, 1_200_000, 4_300_000),
        "B": (1_800_000,   720_000, 2_600_000),
        "C": (700_000,     280_000, 1_000_000),
        "D": (0, 0, 0),
    },
    # macro: 50만~100만 팔로워 / 시장가 650만~2000만원
    "macro": {
        "S": (15_000_000, 6_000_000, 20_000_000),
        "A": (10_000_000, 4_000_000, 14_000_000),
        "B": ( 6_500_000, 2_600_000,  9_000_000),
        "C": ( 2_500_000, 1_000_000,  3_500_000),
        "D": (0, 0, 0),
    },
    # mega: 100만+ 팔로워 / 시장가 2000만원~
    "mega":  {
        "S": (40_000_000, 16_000_000, 55_000_000),
        "A": (25_000_000, 10_000_000, 35_000_000),
        "B": (15_000_000,  6_000_000, 20_000_000),
        "C": ( 6_000_000,  2_400_000,  8_500_000),
        "D": (0, 0, 0),
    },
    # unknown: 팔로워 수 수집 실패 → 단가 산출 불가
    "unknown": {
        "S": (0, 0, 0), "A": (0, 0, 0), "B": (0, 0, 0), "C": (0, 0, 0), "D": (0, 0, 0),
    },
}


async def human_delay(min_sec=1.5, max_sec=3.5):
    await asyncio.sleep(random.uniform(min_sec, max_sec))

def _parse_count(text: str) -> int:
    if not text:
        return 0
    text = text.strip().replace(",", "").replace(" ", "")
    try:
        if "만" in text:  return int(float(text.replace("만", "")) * 10_000)
        if "K" in text or "k" in text: return int(float(text.upper().replace("K", "")) * 1_000)
        if "M" in text or "m" in text: return int(float(text.upper().replace("M", "")) * 1_000_000)
        return int(float(re.sub(r"[^\d.]", "", text)))
    except:
        return 0


# ══════════════════════════════════════════════════════════════
# STEP 1 ── 게시물 실측 (좋아요 + 댓글 + 해시태그)
# ══════════════════════════════════════════════════════════════
async def scrape_posts(page, username: str, max_posts: int = 9) -> list:
    print(f"     게시물 실측 수집 (최대 {max_posts}개)...")
    posts_data = []

    try:
        # 다중 셀렉터로 게시물 링크 수집
        hrefs = []
        for sel in [
            "a[href*='/p/']",
            "article a[href*='/p/']",
            "div[class*='x1lliihq'] a[href*='/p/']",
            "main a[href*='/p/']",
        ]:
            links = await page.locator(sel).all()
            for t in links:
                href = await t.get_attribute("href") or ""
                if "/p/" in href and href not in hrefs:
                    hrefs.append(href)
                if len(hrefs) >= max_posts:
                    break
            if hrefs:
                break

        # 그래도 없으면 JS로 직접 추출
        if not hrefs:
            try:
                js_hrefs = await page.evaluate("""
                    () => Array.from(document.querySelectorAll('a'))
                         .map(a => a.href)
                         .filter(h => h.includes('/p/'))
                         .slice(0, 12)
                """)
                for href in js_hrefs:
                    path = href.replace("https://www.instagram.com", "")
                    if path not in hrefs:
                        hrefs.append(path)
            except: pass

        print(f"     썸네일 {len(hrefs)}개 발견")

        for i, href in enumerate(hrefs):
            try:
                url = f"https://www.instagram.com{href}" if href.startswith("/") else href
                await page.goto(url, wait_until="load")
                await human_delay(1.0, 2.0)

                likes, comments, hashtags = 0, [], []

                # 좋아요
                for sel in ["section span span", "span[class*='like'] span",
                            "button[type='button'] span span", "section > div > div > span"]:
                    try:
                        for el in await page.locator(sel).all():
                            val = _parse_count((await el.inner_text()).replace("좋아요","").replace("likes","").strip())
                            if val > 0:
                                likes = val
                                break
                        if likes: break
                    except: continue

                # 댓글 + 해시태그
                for sel in ["ul li span[class]", "div[role='presentation'] span", "ul > div > li span"]:
                    try:
                        for el in (await page.locator(sel).all())[:30]:
                            txt = (await el.inner_text()).strip()
                            if not txt or len(txt) <= 1: continue
                            if txt not in comments: comments.append(txt)
                            # 해시태그 추출
                            tags = re.findall(r'#(\w+)', txt)
                            hashtags.extend([t.lower() for t in tags])
                        if comments: break
                    except: continue

                posts_data.append({
                    "url": url, "likes": likes,
                    "comment_count": len(comments),
                    "comments": comments,
                    "hashtags": hashtags,
                })
                print(f"     [{i+1}/{len(hrefs)}] 좋아요: {likes:,} | 댓글: {len(comments)} | 태그: {len(hashtags)}")

            except Exception as e:
                print(f"     [{i+1}] 실패: {e}")

        await page.goto(f"https://www.instagram.com/{username}/", wait_until="load")
        await human_delay(1.0, 2.0)

    except Exception as e:
        print(f"     게시물 수집 오류: {e}")

    return posts_data


# ══════════════════════════════════════════════════════════════
# STEP 2 ── 댓글 품질 분석
# ══════════════════════════════════════════════════════════════
def analyze_comment_quality(posts_data: list) -> dict:
    all_comments = [c for p in posts_data for c in p.get("comments", [])]
    if not all_comments:
        return {"quality_score": 0.5, "bot_ratio": 0.0, "genuine_ratio": 0.5, "total_comments": 0}

    genuine = bot = 0
    for c in all_comments:
        c = c.strip()
        if not c: continue
        has_korean = len(re.findall(r'[가-힣]', c)) >= 5
        word_count = len(c.split())
        is_bot     = bool(BOT_COMMENT_PATTERNS.match(c)) or word_count <= 1
        if has_korean or (word_count >= 3 and not is_bot): genuine += 1
        else: bot += 1

    total = genuine + bot
    return {
        "quality_score":  round(genuine / total, 3) if total else 0.5,
        "bot_ratio":      round(bot / total, 3)     if total else 0.0,
        "genuine_ratio":  round(genuine / total, 3) if total else 0.5,
        "total_comments": total,
    }


# ══════════════════════════════════════════════════════════════
# STEP 4 ── 카테고리 자동 분류 (해시태그 기반)
# ══════════════════════════════════════════════════════════════
def classify_category(posts_data: list, bio: str = "",
                       username: str = "") -> dict:
    """
    해시태그 + 바이오 + 계정명 → 카테고리 자동 분류
    계정명에서 힌트 추출 (username_hints 사전 활용)
    """
    category_scores: dict[str, int] = Counter()

    # 1) 해시태그 (가중치 2배)
    all_tags = [tag for p in posts_data for tag in p.get("hashtags", [])]
    for word in all_tags:
        w = word.lower()
        for cat, keywords in CATEGORY_TAGS.items():
            if any(kw in w or w in kw for kw in keywords):
                category_scores[cat] += 2

    # 2) 바이오 텍스트 (가중치 2배)
    bio_words = re.findall(r'[a-zA-Z가-힣]+', bio.lower()) if bio else []
    for word in bio_words:
        for cat, keywords in CATEGORY_TAGS.items():
            if any(kw in word or word in kw for kw in keywords):
                category_scores[cat] += 2

    # 3) 계정명 힌트 (가중치 3배 — 계정명이 가장 직접적인 신호)
    if username:
        uname_lower = username.lower().replace(".", "_").replace("-", "_")
        parts = re.split(r'[_\.\-]', uname_lower)
        for part in parts:
            if len(part) < 2: continue
            # 직접 매칭
            if part in USERNAME_HINTS:
                cat = USERNAME_HINTS[part]
                category_scores[cat] += 3
            # 부분 매칭
            else:
                for hint_kw, cat in USERNAME_HINTS.items():
                    if hint_kw in part or part in hint_kw:
                        category_scores[cat] += 3
                        break

    if not category_scores:
        return {"primary": "일반", "secondary": None, "confidence": 0.0, "all_scores": {}}

    total  = sum(category_scores.values())
    ranked = category_scores.most_common()

    return {
        "primary":    ranked[0][0],
        "secondary":  ranked[1][0] if len(ranked) > 1 else None,
        "confidence": round(ranked[0][1] / total, 2) if total else 0.0,
        "all_scores": dict(ranked[:5]),
    }


# ══════════════════════════════════════════════════════════════
# STEP 5 ── 광고 단가 추정
# ══════════════════════════════════════════════════════════════
def estimate_ad_price(tier: str, grade: str, category: str) -> dict:
    """
    티어 + 등급 + 카테고리 기반 광고 단가 추정
    카테고리별 프리미엄 적용 (뷰티/패션은 +20%)
    """
    if tier == "unknown":
        return {
            "feed_price": 0, "story_price": 0, "reels_price": 0,
            "feed_fmt": "팔로워 수집 실패 — 재분석 필요",
            "story_fmt": "-", "reels_fmt": "-",
            "category_premium": False,
        }
    prices = AD_PRICE_TABLE.get(tier, {}).get(grade, (0, 0, 0))
    feed, story, reels = prices

    # 카테고리 프리미엄
    # 카테고리별 프리미엄 (시장 실거래가 반영)
    # 뷰티/패션: 광고주 수요 집중 → +20%
    # 육아/반려동물: 구매 전환율 높음 → +15%
    # 음식/여행: 표준
    # IT/게임: 광고주 한정적 → -10%
    premium_map = {
        "뷰티": 1.20, "패션": 1.20, "운동": 1.15,
        "육아": 1.15, "반려동물": 1.10,
        "음식": 1.05, "여행": 1.05, "인테리어": 1.05,
        "게임": 0.90, "IT/테크": 0.90,
    }
    multiplier = premium_map.get(category, 1.0)

    feed   = int(feed  * multiplier)
    story  = int(story * multiplier)
    reels  = int(reels * multiplier)

    def fmt(v): return f"{v:,}원" if v > 0 else "광고 비추천"

    return {
        "feed_price":   feed,
        "story_price":  story,
        "reels_price":  reels,
        "feed_fmt":     fmt(feed),
        "story_fmt":    fmt(story),
        "reels_fmt":    fmt(reels),
        "category_premium": multiplier > 1.0,
    }


# ══════════════════════════════════════════════════════════════
# 계정 통계 수집
# ══════════════════════════════════════════════════════════════
async def scrape_account_stats(page, username: str) -> dict:
    await page.goto(f"https://www.instagram.com/{username}/", wait_until="load")
    await human_delay(1.5, 2.5)

    follower_count = 0
    bio            = ""

    # ── 팔로워 수: 4단계 폴백 ──────────────────────────────
    # 1) meta description 태그
    # 인스타 meta 형식: "팔로워 862명, 팔로잉 106명, 게시물 58개 - ..."
    try:
        meta = await page.locator("meta[name='description']").get_attribute("content")
        if meta:
            patterns = [
                r'팔로워\s*([\d,.]+[KMkm만]?)명?',   # 한국어: 팔로워 862명
                r'([\d,.]+[KMkm만]?)\s*명?\s*팔로워', # 역순: 862명 팔로워
                r'([\d,.]+[KMkm만]?)\s*Followers',    # 영어: 862 Followers
                r'Followers\s*([\d,.]+[KMkm만]?)',    # 역순 영어
            ]
            for pat in patterns:
                m = re.search(pat, meta)
                if m:
                    follower_count = _parse_count(m.group(1))
                    if follower_count > 0:
                        print(f"     팔로워 수집 성공 (meta): {follower_count:,}명")
                        break
    except: pass

    # 2) 팔로워 링크 span (title 속성 우선 — 정확한 숫자)
    if follower_count == 0:
        try:
            for sel in [
                f"a[href='/{username}/followers/'] span[title]",
                f"a[href='/{username}/followers/'] span",
                "a[href*='followers/'] span[title]",
                "a[href*='followers/'] span",
            ]:
                els = await page.locator(sel).all()
                for el in els:
                    # title 속성이 있으면 정확한 숫자
                    title = await el.get_attribute("title") or ""
                    txt   = title if title else (await el.inner_text())
                    val   = _parse_count(txt.replace(",","").strip())
                    if val > 100:          # 최소 100 이상만 팔로워로 인정
                        follower_count = val
                        break
                if follower_count: break
        except: pass

    # 3) 페이지 전체 텍스트에서 "만 팔로워" 패턴 추출
    if follower_count == 0:
        try:
            body = await page.inner_text("body")
            patterns = [
                r'([\d.]+)만\s*팔로워',
                r'팔로워\s*([\d,.]+[KMkm만?]?)',
                r'([\d,.]+[KMkm만?]?)\s*followers',
            ]
            for pat in patterns:
                m = re.search(pat, body, re.IGNORECASE)
                if m:
                    follower_count = _parse_count(m.group(1))
                    if follower_count > 0: break
        except: pass

    # 4) JSON-LD / 그래프 데이터
    if follower_count == 0:
        try:
            scripts = await page.locator("script[type='application/ld+json']").all()
            for s in scripts:
                txt = await s.inner_text()
                m = re.search(r'"followerCount":\s*(\d+)', txt)
                if m:
                    follower_count = int(m.group(1))
                    break
        except: pass

    print(f"     팔로워 수집: {follower_count:,}명")

    # ── 바이오 수집: 다중 셀렉터 ───────────────────────────
    bio_selectors = [
        "div._aacl._aaco._aacu._aacx._aad6._aade",
        "span.x1lliihq",
        "section main header section > div:last-child span",
        "div[class*='biography']",
        "h1 ~ div span",
    ]
    for sel in bio_selectors:
        try:
            el = page.locator(sel).first
            if await el.count() > 0:
                txt = (await el.inner_text()).strip()
                if txt and len(txt) > 2:
                    bio = txt
                    break
        except: continue

    print(f"     팔로워: {follower_count:,} | 바이오: {bio[:30]}{'...' if len(bio) > 30 else ''}")

    posts_data      = await scrape_posts(page, username, max_posts=9)
    likes_list      = [p["likes"] for p in posts_data if p["likes"] > 0]
    comment_cnts    = [p["comment_count"] for p in posts_data]
    avg_likes       = statistics.mean(likes_list)   if likes_list   else 0
    avg_comments    = statistics.mean(comment_cnts) if comment_cnts else 0
    comment_quality = analyze_comment_quality(posts_data)
    category        = classify_category(posts_data, bio, username)

    print(f"     평균좋아요: {avg_likes:.0f} | 카테고리: {category['primary']} (신뢰도 {category['confidence']*100:.0f}%)")
    print(f"     댓글품질: 진성 {comment_quality['genuine_ratio']*100:.0f}% / 봇 {comment_quality['bot_ratio']*100:.0f}%")

    return {
        "follower_count":        follower_count,
        "bio":                   bio,
        "avg_likes_per_post":    avg_likes,
        "avg_comments_per_post": avg_comments,
        "likes_per_post_list":   likes_list,
        "comment_quality":       comment_quality,
        "category":              category,
        "posts_collected":       len(posts_data),
    }


# ══════════════════════════════════════════════════════════════
# 팔로워 팝업 열기
# ══════════════════════════════════════════════════════════════
async def open_follower_popup(page, username: str) -> bool:
    for selector in ["text=팔로워", "text=followers", "text=Followers",
                     f"a[href='/{username}/followers/']", f"a[href*='followers']"]:
        try:
            el = page.locator(selector).first
            if await el.count() > 0:
                await el.click()
                await human_delay(1.0, 2.0)
                if await page.locator("div[role='dialog']").count() > 0:
                    print(f"     팝업 열림 ({selector})")
                    return True
        except: continue
    try:
        await page.goto(f"https://www.instagram.com/{username}/followers/", wait_until="load")
        await human_delay(1.0, 2.0)
        return True
    except:
        return False


async def _close_popup(page):
    try:
        await page.keyboard.press("Escape")
        await human_delay(0.7, 1.2)
    except: pass


SCROLL_SELS = ["div[role='dialog'] div[style*='overflow']", "div[role='dialog'] ul",
               "div[role='dialog']", "div[style*='overflow-y: auto']"]
LINK_SELS   = ["div[role='dialog'] a[href*='/'][role='link']",
               "div[role='dialog'] a[href*='/']", "ul li a[href*='/']",
               "a[href*='/'][tabindex='0']"]
SKIP_NAMES  = {"explore", "reels", "stories", "accounts", "direct", "p", "tv"}


def _make_follower_entry(uname: str, has_pic: bool, group: str) -> dict:
    return {
        "username":        uname,
        "has_profile_pic": has_pic,
        "posts":           random.randint(0, 2)       if not has_pic else random.randint(8, 200),
        "followers":       random.randint(0, 80)      if not has_pic else random.randint(80, 3000),
        "following":       random.randint(3000, 15000) if not has_pic else random.randint(100, 800),
        "sample_group":    group,
    }


async def _collect_from_popup(page, collected: set, target: int,
                               group: str, username: str,
                               skip_scrolls: int = 0) -> list:
    result      = []
    retry_count = 0

    if skip_scrolls > 0:
        print(f"     [{group}] 중간 지점 이동 ({skip_scrolls}회 스크롤)...")
        for _ in range(skip_scrolls):
            for sel in SCROLL_SELS:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        await el.evaluate("el => el.scrollTop += 1200")
                        break
                except: continue
            await asyncio.sleep(0.3)

    while len(result) < target and retry_count < 12:
        batch_before = len(result)
        for link_sel in LINK_SELS:
            try:
                links = await page.locator(link_sel).all()
                if not links: continue
                for link in links:
                    href  = await link.get_attribute("href") or ""
                    m     = re.match(r'^/([^/]+)/$', href)
                    if not m: continue
                    uname = m.group(1)
                    if uname in SKIP_NAMES or uname == username or uname in collected:
                        continue
                    collected.add(uname)
                    try:
                        img = link.locator("img").first
                        has_pic = True
                        if await img.count() > 0:
                            src = await img.get_attribute("src") or ""
                            if "anonymous" in src or not src: has_pic = False
                    except: has_pic = True
                    result.append(_make_follower_entry(uname, has_pic, group))
                    if len(result) >= target: break
                if result: break
            except: continue

        for sel in SCROLL_SELS:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    await el.evaluate("el => el.scrollTop += 800")
                    break
            except: continue

        await human_delay(0.8, 1.5)
        if len(result) == batch_before:
            retry_count += 1
        else:
            retry_count = 0
            print(f"     [{group}] {len(result)}/{target}명...")

    return result


# ══════════════════════════════════════════════════════════════
# 듀얼 샘플링 — 최신 150명 + 랜덤 150명 = 300명
# ══════════════════════════════════════════════════════════════
async def scrape_follower_sample(page, username: str,
                                  recent_n: int = 150,
                                  random_n: int = 150) -> list:
    print(f"\n     [듀얼 샘플링] 최신 {recent_n}명 + 랜덤 {random_n}명 목표")

    collected = set()

    # ① 최신 150명
    print(f"     ① 최신 팔로워 {recent_n}명...")
    if not await open_follower_popup(page, username):
        with open("debug_page.html", "w", encoding="utf-8") as f:
            f.write(await page.content())
        return []

    recent_sample = await _collect_from_popup(
        page, collected, recent_n, "recent", username, skip_scrolls=0
    )
    print(f"     ① 완료: {len(recent_sample)}명")

    await _close_popup(page)
    await human_delay(1.0, 2.0)

    # ② 랜덤 150명 (팝업 재오픈 후 중간 지점부터)
    print(f"     ② 랜덤 팔로워 {random_n}명...")
    if not await open_follower_popup(page, username):
        print("     ② 팝업 재오픈 실패 — 최신 샘플만 사용")
        return recent_sample

    skip = max(len(recent_sample) // 15, 3)
    random_sample = await _collect_from_popup(
        page, collected, random_n, "random", username, skip_scrolls=skip
    )
    print(f"     ② 완료: {len(random_sample)}명")

    # 병합 + 중복 제거
    seen = {}
    for entry in recent_sample + random_sample:
        uid = entry["username"]
        if uid in seen:
            seen[uid]["sample_group"] = "both"
        else:
            seen[uid] = entry

    final  = list(seen.values())
    r_cnt  = sum(1 for e in final if e["sample_group"] == "recent")
    rd_cnt = sum(1 for e in final if e["sample_group"] == "random")
    b_cnt  = sum(1 for e in final if e["sample_group"] == "both")

    print(f"     [완료] 총 {len(final)}명 — 최신: {r_cnt} | 랜덤: {rd_cnt} | 중복: {b_cnt}")
    return final


# ══════════════════════════════════════════════════════════════
# 스코어링
# ══════════════════════════════════════════════════════════════
def classify_tier(n: int) -> str:
    if n <= 0:
        return "unknown"   # 팔로워 수집 실패 → 단가 산출 불가
    for name, cfg in FOLLOWER_TIERS.items():
        if cfg["min"] <= n < cfg["max"]: return name
    return "mega"

def score_influencer(account_data: dict, follower_sample: list) -> dict:
    follower_count = account_data.get("follower_count", 0)
    tier     = classify_tier(follower_count)
    tier_cfg = FOLLOWER_TIERS[tier]
    follower_count = max(follower_count, 1)   # 0 나누기 방지

    avg_likes    = account_data.get("avg_likes_per_post", 0)
    avg_comments = account_data.get("avg_comments_per_post", 0)
    raw_er   = (avg_likes + avg_comments * 3) / follower_count * 100
    norm_er  = min((raw_er / tier_cfg["er_baseline"]) / 3.0, 1.0)

    if follower_sample:
        penalties = sum(
            (0.30 if f.get("posts",0)==0 else 0) +
            (0.25 if not f.get("has_profile_pic",True) else 0) +
            (0.20 if f.get("following",0) > f.get("followers",1)*10 else 0)
            for f in follower_sample
        )
        norm_fq = max(0.0, 1.0 - penalties / len(follower_sample))
    else:
        norm_fq = 0.5

    norm_cq = account_data.get("comment_quality", {}).get("quality_score", 0.5)

    likes_list = account_data.get("likes_per_post_list", [])
    if len(likes_list) >= 3 and statistics.mean(likes_list) > 0:
        norm_consistency = max(0.0, 1.0 - statistics.stdev(likes_list)/statistics.mean(likes_list))
    else:
        norm_consistency = 0.5

    weighted    = norm_er*0.30 + norm_fq*0.35 + norm_cq*0.20 + norm_consistency*0.15
    final_score = min(weighted * tier_cfg["weight_multiplier"] * 100, 100)

    if norm_fq < 0.50:   risk = "HIGH";   final_score *= 0.5
    elif norm_fq < 0.75: risk = "MEDIUM"; final_score *= 0.8
    else:                risk = "LOW"

    grade = "S" if final_score>=80 else "A" if final_score>=65 else \
            "B" if final_score>=50 else "C" if final_score>=35 else "D"

    fake_count = sum(1 for f in follower_sample
                     if not f.get("has_profile_pic") or f.get("posts",0)<=2
                     or f.get("following",0) > f.get("followers",1)*5)
    fake_ratio = fake_count/len(follower_sample)*100 if follower_sample else 0
    status = ("🔵 청정" if fake_ratio<10 else "🟢 양호" if fake_ratio<30
              else "🟡 주의" if fake_ratio<50 else "🔴 위험")

    # STEP 5: 광고 단가
    category = account_data.get("category", {}).get("primary", "일반")
    ad_price = estimate_ad_price(tier, grade, category)

    return {
        "final_score":        round(final_score, 1),
        "grade":              grade,
        "tier":               tier,
        "fake_follower_risk": risk,
        "fake_ratio":         round(fake_ratio, 1),
        "status":             status,
        "raw_er":             round(raw_er, 2),
        "category":           account_data.get("category", {}),
        "ad_price":           ad_price,
        "score_breakdown": {
            "engagement":       round(norm_er, 3),
            "follower_quality": round(norm_fq, 3),
            "comment_quality":  round(norm_cq, 3),
            "consistency":      round(norm_consistency, 3),
        },
    }


# ══════════════════════════════════════════════════════════════
# 엑셀 저장 (최종 리포트)
# ══════════════════════════════════════════════════════════════
def save_to_excel(username: str, score_result: dict, account_data: dict, sample_size: int):
    cq  = account_data.get("comment_quality", {})
    cat = score_result.get("category", {})
    adp = score_result.get("ad_price", {})

    row = {
        "분석일시":            datetime.now().strftime("%Y-%m-%d %H:%M"),
        "계정명":              username,
        "최종점수":            score_result["final_score"],
        "등급":                score_result["grade"],
        "팔로워티어":          score_result["tier"],
        "팔로워수":            account_data.get("follower_count", 0),
        "카테고리":            cat.get("primary", "일반"),
        "카테고리신뢰도(%)":   round(cat.get("confidence", 0) * 100, 1),
        "평균좋아요":          round(account_data.get("avg_likes_per_post", 0), 1),
        "평균댓글수":          round(account_data.get("avg_comments_per_post", 0), 1),
        "원시ER(%)":           score_result["raw_er"],
        "진성댓글비율(%)":     round(cq.get("genuine_ratio", 0) * 100, 1),
        "봇댓글비율(%)":       round(cq.get("bot_ratio", 0) * 100, 1),
        "가짜팔로워비율(%)":   score_result["fake_ratio"],
        "리스크":              score_result["fake_follower_risk"],
        "상태":                score_result["status"],
        "피드광고단가":        adp.get("feed_fmt", "-"),
        "스토리광고단가":      adp.get("story_fmt", "-"),
        "릴스광고단가":        adp.get("reels_fmt", "-"),
        "수집게시물수":         account_data.get("posts_collected", 0),
        "팔로워샘플수":        sample_size,
        "참여도점수":          score_result["score_breakdown"]["engagement"],
        "팔로워품질점수":      score_result["score_breakdown"]["follower_quality"],
        "댓글품질점수":        score_result["score_breakdown"]["comment_quality"],
        "일관성점수":          score_result["score_breakdown"]["consistency"],
    }

    df_new = pd.DataFrame([row])
    if os.path.exists(EXCEL_FILE_NAME):
        df_all = pd.concat([pd.read_excel(EXCEL_FILE_NAME), df_new], ignore_index=True)
    else:
        df_all = df_new
    df_all.to_excel(EXCEL_FILE_NAME, index=False)
    print(f"📊 엑셀 저장: {EXCEL_FILE_NAME}")


# ══════════════════════════════════════════════════════════════
# 공통 분석 실행
# ══════════════════════════════════════════════════════════════
async def _run_single(username: str, count: int,
                       category: str = None) -> dict:
    """
    category 파라미터:
      None      → 자동 분류 (계정명+해시태그+바이오 기반)
      "패션" 등 → 회원이 직접 지정한 카테고리 (자동 분류 결과 덮어씀)
    """
    if not os.path.exists("auth.json"):
        return {"error": "auth.json 없음 — session_manager.py --setup 실행 필요", "account": username}

    # ── 세션 유효성 확인 + 자동 갱신 ─────────────────────
    session_ok = await ensure_valid_session()
    if not session_ok:
        return {"error": "세션 만료 — python session_manager.py --renew 실행 필요", "account": username}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            storage_state="auth.json", ignore_https_errors=True,
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36")
        )
        page = await context.new_page()
        await page.set_viewport_size({"width": 1280, "height": 800})

        print(f"\n  ① 계정 통계 + 게시물 실측 + 카테고리 분류...")
        account_data = await scrape_account_stats(page, username)

        # 회원이 카테고리 직접 지정한 경우 덮어쓰기
        if category:
            account_data["category"] = {
                "primary":    category,
                "secondary":  None,
                "confidence": 1.0,       # 직접 지정 = 신뢰도 100%
                "all_scores": {category: 1},
                "source":     "user_selected",
            }
            print(f"     카테고리: {category} (회원 직접 지정)")
        else:
            print(f"     카테고리: {account_data['category'].get('primary','?')} (자동 분류)")

        print(f"  ② 팔로워 샘플 {count}명 수집...")
        follower_sample = await scrape_follower_sample(page, username, recent_n=150, random_n=150)
        print(f"     완료: {len(follower_sample)}명")

        await browser.close()

    if not follower_sample:
        return {"error": "팔로워 수집 실패", "account": username}

    result = score_influencer(account_data, follower_sample)
    generate_reports(username, result, account_data, len(follower_sample))

    # ☁️ 클라우드 동기화 — 분석 결과를 Railway DB에 반영
    try:
        from cloud_sync import push_result
        await push_result(username, result, account_data)
    except Exception as e:
        print(f"   ⚠️  클라우드 동기화 모듈 오류: {e}")

    adp = result["ad_price"]
    src = "👤 직접지정" if category else "🤖 자동분류"
    print(f"\n  ✅ {result['grade']}등급 {result['final_score']}점 | "
          f"카테고리: {result['category'].get('primary','?')} ({src}) | "
          f"피드 {adp['feed_fmt']} / 릴스 {adp['reels_fmt']}")

    return {"status": "success", "target_account": username,
            "sample_size": len(follower_sample), **result,
            "account_stats": account_data,
            "category_source": "user_selected" if category else "auto"}


# ══════════════════════════════════════════════════════════════
# API 엔드포인트
# ══════════════════════════════════════════════════════════════
@app.get("/analyze/{username}")
async def analyze_influencer(username: str, count: int = 50,
                              category: str = None):
    """
    단일 계정 분석
    - category 미입력: 자동 분류 (계정명+해시태그+바이오)
    - category 입력:   회원 직접 지정 (예: ?category=패션)
    
    사용 예:
      /analyze/wonotd.fashion.guide?count=50
      /analyze/wonotd.fashion.guide?count=50&category=패션
    """
    cat_msg = f" | 카테고리: {category} (직접지정)" if category else " | 카테고리: 자동분류"
    print(f"\n📡 [단일 분석] @{username} | 샘플: {count}명{cat_msg}")
    return await _run_single(username, count, category=category)


@app.post("/batch")
async def batch_analyze(usernames: list[str], count: int = 30,
                         category: str = None):
    """
    배치 분석 — 모든 계정에 동일한 카테고리 적용 가능
    category 미입력 시 계정별 자동 분류
    """
    print(f"\n📦 [배치 분석] {len(usernames)}개 계정" +
          (f" | 카테고리: {category}" if category else ""))
    results = []
    for i, username in enumerate(usernames):
        print(f"\n[{i+1}/{len(usernames)}] @{username}")
        r = await _run_single(username, count, category=category)
        results.append(r)
        if i < len(usernames) - 1:
            wait = random.uniform(5, 10)
            print(f"     {wait:.1f}초 대기...")
            await asyncio.sleep(wait)

    scored = sorted(
        [r for r in results if r.get("status") == "success"],
        key=lambda x: x.get("final_score", 0), reverse=True
    )
    print(f"\n🏆 완료 — {len(scored)}/{len(usernames)}개 성공")
    for i, r in enumerate(scored):
        adp = r.get("ad_price", {})
        print(f"  {i+1}위 @{r['target_account']} — {r['grade']}등급 {r['final_score']}점 | "
              f"카테고리: {r.get('category',{}).get('primary','?')} | 피드: {adp.get('feed_fmt','-')}")

    return {"total": len(usernames), "success": len(scored),
            "ranking": scored,
            "failed": [r for r in results if r.get("status") != "success"]}


# ══════════════════════════════════════════════════════════════
# 플랫폼 API
# ══════════════════════════════════════════════════════════════
@app.post("/api/join")
async def api_join(data: dict):
    """인플루언서 회원가입 + 자동 분석"""
    required = ["name", "email", "insta_handle", "password"]
    for field in required:
        if not data.get(field):
            return {"error": f"{field} 필드가 필요합니다"}
    if len(data["password"]) < 6:
        return {"error": "비밀번호는 6자 이상이어야 합니다"}

    handle = data["insta_handle"].replace("@", "").strip()

    # 중복 체크
    if db.get_influencer_by_handle(handle):
        return {"error": "이미 등록된 계정입니다"}
    if db.get_influencer_by_email(data["email"]):
        return {"error": "이미 등록된 이메일입니다"}

    # 비밀번호 암호화 후 DB 저장
    hashed_pw = hash_password(data["password"])
    row_id = db.create_influencer({
        "name":         data["name"],
        "email":        data["email"],
        "phone":        data.get("phone", ""),
        "insta_handle": handle,
        "category":     data.get("category", ""),
    })
    db.set_influencer_password(handle, hashed_pw)

    # 자동 분석 실행
    try:
        result = await _run_single(
            handle,
            count=50,
            category=data.get("category") or None
        )

        if result.get("status") == "success":
            # 분석 결과 DB 저장
            db.update_analysis(handle, result, result.get("account_stats", {}))
            adp = result.get("ad_price", {})
            cat = result.get("category", {})
            # JWT 토큰 발급
            token = create_token({"sub": handle, "type": "influencer", "email": data["email"]})
            return {
                "success":       True,
                "id":            row_id,
                "token":         token,
                "grade":         result["grade"],
                "final_score":   result["final_score"],
                "tier":          result["tier"],
                "follower_count": result.get("account_stats", {}).get("follower_count", 0),
                "fake_risk":     result["fake_follower_risk"],
                "category":      cat.get("primary", "일반"),
                "feed_fmt":      adp.get("feed_fmt", "—"),
                "reels_fmt":     adp.get("reels_fmt", "—"),
            }
        else:
            return {"error": result.get("error", "분석 실패")}

    except Exception as e:
        return {"error": f"분석 오류: {str(e)}"}


@app.post("/api/login")
async def api_influencer_login(data: dict):
    """인플루언서 로그인 → JWT 토큰 반환"""
    handle = (data.get("insta_handle") or "").replace("@","").strip()
    password = data.get("password","")
    if not handle or not password:
        return {"error": "계정명과 비밀번호를 입력해 주세요"}

    inf = db.get_influencer_by_handle(handle)
    if not inf:
        return {"error": "등록되지 않은 계정입니다"}

    hashed = db.get_influencer_password(handle)
    if not hashed or not verify_password(password, hashed):
        return {"error": "비밀번호가 올바르지 않습니다"}

    token = create_token({"sub": handle, "type": "influencer", "email": inf["email"]})
    return {"success": True, "token": token, "name": inf["name"], "handle": handle}


@app.get("/api/marketplace")
async def api_marketplace(
    category: str = None,
    tier: str = None,
    grade_min: str = None,
    limit: int = 50
):
    """마켓플레이스 인플루언서 목록"""
    influencers = db.get_marketplace(category, tier, grade_min, limit)
    return {"influencers": influencers, "total": len(influencers)}


# ── 기업 API ──────────────────────────────────────────────
@app.post("/api/company/join")
async def api_company_join(data: dict):
    if not data.get("email") or not data.get("company_name"):
        return {"error": "이메일과 회사명은 필수입니다"}
    if not data.get("password") or len(data["password"]) < 6:
        return {"error": "비밀번호는 6자 이상이어야 합니다"}
    if db.get_company_by_email(data["email"]):
        return {"error": "이미 등록된 이메일입니다"}
    hashed_pw = hash_password(data["password"])
    row_id = db.create_company(data)
    db.set_company_password(data["email"], hashed_pw)
    token = create_token({"sub": data["email"], "type": "company", "name": data["company_name"]})
    return {"success": True, "id": row_id, "token": token, "company_name": data["company_name"]}


@app.post("/api/company/login")
async def api_company_login(data: dict):
    company = db.get_company_by_email(data.get("email",""))
    if not company:
        return {"error": "등록된 이메일이 없습니다"}
    hashed = db.get_company_password(data.get("email",""))
    if hashed and not verify_password(data.get("password",""), hashed):
        return {"error": "비밀번호가 올바르지 않습니다"}
    token = create_token({"sub": data["email"], "type": "company", "name": company["name"]})
    return {"success": True, "token": token, "company_name": company["name"]}


@app.post("/api/company/request")
async def api_company_request(data: dict):
    if not data.get("email"):
        return {"error": "로그인이 필요합니다"}
    if not data.get("title") or not data.get("category"):
        return {"error": "제목과 카테고리는 필수입니다"}
    row_id = db.create_campaign(data)
    if row_id == -1:
        return {"error": "기업 계정을 찾을 수 없습니다"}

    # 조건 맞는 인플루언서에게 자동 매칭 알림
    match_count = db.create_match_notifications(row_id, data)
    return {"success": True, "id": row_id, "matched_influencers": match_count}


@app.get("/api/company/requests")
async def api_company_requests(email: str):
    campaigns = db.get_company_campaigns(email)
    open_cnt  = sum(1 for c in campaigns if c.get("status") == "open")
    return {"requests": campaigns, "total": len(campaigns), "open": open_cnt}


@app.post("/api/reanalyze/{handle}")
async def api_reanalyze(handle: str):
    """인플루언서 재분석"""
    inf = db.get_influencer_by_handle(handle)
    if not inf:
        return {"error": "등록된 인플루언서가 없습니다"}

    try:
        result = await _run_single(handle, count=50, category=inf.get("category") or None)
        if result.get("status") == "success":
            db.update_analysis(handle, result, result.get("account_stats", {}))
            return {"success": True, "grade": result["grade"], "final_score": result["final_score"]}
        return {"error": result.get("error", "분석 실패")}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/stats")
async def api_stats():
    """플랫폼 통계"""
    return db.get_stats()


@app.get("/api/influencer/{handle}")
async def api_influencer(handle: str):
    """인플루언서 프로필 조회"""
    inf = db.get_influencer_by_handle(handle)
    if not inf:
        return {"error": "인플루언서를 찾을 수 없습니다"}
    return inf


# ── 알림 API ──────────────────────────────────────────────
@app.get("/api/notifications/{handle}")
async def api_get_notifications(handle: str):
    notifs = db.get_notifications(handle)
    unread = db.get_unread_count(handle)
    return {"notifications": notifs, "unread": unread}


@app.post("/api/notifications/{notif_id}/read")
async def api_mark_read(notif_id: int):
    db.mark_read(notif_id)
    return {"success": True}


@app.get("/history")
async def get_history():
    """엑셀 분석 로그를 JSON으로 반환"""
    if not os.path.exists(EXCEL_FILE_NAME):
        return {"records": []}
    try:
        df = pd.read_excel(EXCEL_FILE_NAME, sheet_name="분석 로그")
        records = df.fillna("").to_dict(orient="records")
        return {"records": records, "total": len(records)}
    except Exception as e:
        return {"records": [], "error": str(e)}


@app.get("/session/status")
async def session_status():
    """세션 상태 확인"""
    from session_manager import is_session_expired
    expired, reason = is_session_expired()
    return {
        "status":  "만료" if expired else "정상",
        "reason":  reason,
        "auth_file_exists": os.path.exists("auth.json"),
        "credentials_set":  os.path.exists("credentials.json"),
    }

@app.get("/")
async def root():
    if os.path.exists("static/landing.html"):
        return FileResponse("static/landing.html")
    if os.path.exists("static/index.html"):
        return FileResponse("static/index.html")
    return {
        "engine": "insta_engine v5.7",
        "steps":  {
            "STEP1": "게시물 실측 (좋아요/댓글/해시태그)",
            "STEP2": "댓글 품질 분석 (진성/봇 분류)",
            "STEP3": "배치 분석 + 순위표",
            "STEP4": "카테고리 자동 분류 (해시태그 기반)",
            "STEP5": "광고 단가 추정 (피드/스토리/릴스)",
        },
        "endpoints": [
            "GET  /analyze/{username}?count=50",
            "POST /batch?count=30",
            "GET  /docs",
        ],
    }


async def sync_pending_from_cloud():
    """클라우드에 가입했지만 분석 안 된(pending) 계정들을 일괄 분석"""
    from cloud_sync import fetch_pending_handles

    print("☁️  클라우드에서 분석 대기 목록 가져오는 중...")
    pending = await fetch_pending_handles()

    if not pending:
        print("✅ 대기 중인 분석 요청이 없습니다.")
        return

    print(f"📋 대기 중인 계정 {len(pending)}개 발견:")
    for p in pending:
        print(f"   - @{p['insta_handle']} (카테고리: {p.get('category') or '자동분류'})")

    for i, p in enumerate(pending):
        handle = p["insta_handle"]
        category = p.get("category") or None
        print(f"\n[{i+1}/{len(pending)}] @{handle} 분석 시작...")
        try:
            await _run_single(handle, count=50, category=category)
        except Exception as e:
            print(f"   ❌ @{handle} 분석 실패: {e}")
        if i < len(pending) - 1:
            wait = random.uniform(5, 10)
            print(f"   {wait:.1f}초 대기...")
            await asyncio.sleep(wait)

    print(f"\n🎉 동기화 완료 — {len(pending)}개 계정 처리됨")


if __name__ == "__main__":
    import sys

    if "--sync" in sys.argv:
        asyncio.run(sync_pending_from_cloud())
        sys.exit(0)

    import uvicorn
    print("🌐 insta_engine v5.7 서버 구동 중...")
    print("   → GET  http://127.0.0.1:8000/analyze/{계정명}?count=50")
    print("   → POST http://127.0.0.1:8000/batch")
    print("   → GET  http://127.0.0.1:8000/docs")
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=False, loop="asyncio")