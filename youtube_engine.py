"""
youtube_engine.py
YouTube Data API v3 기반 채널 분석 엔진
인스타 engyn.py와 동일한 스코어링 구조
"""

import os
import re
import httpx
from datetime import datetime, timezone

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
BASE_URL = "https://www.googleapis.com/youtube/v3"


# ══════════════════════════════════════════════════════════════
# 채널 정보 수집
# ══════════════════════════════════════════════════════════════
async def get_channel_info(channel_input: str) -> dict:
    """
    채널명 또는 URL로 채널 정보 수집
    예: @channelname, channel_id, https://youtube.com/@channelname
    """
    if not YOUTUBE_API_KEY:
        return {"error": "YouTube API 키가 설정되지 않았습니다"}

    # 채널 핸들 추출
    handle = channel_input.strip()
    handle = re.sub(r'https?://(www\.)?youtube\.com/', '', handle)
    handle = handle.lstrip('@').strip('/')

    async with httpx.AsyncClient() as client:
        # 1. 핸들로 채널 검색
        res = await client.get(f"{BASE_URL}/channels", params={
            "key":  YOUTUBE_API_KEY,
            "forHandle": handle,
            "part": "snippet,statistics,brandingSettings",
        })
        data = res.json()

        if not data.get("items"):
            # 2. 검색으로 재시도
            res2 = await client.get(f"{BASE_URL}/search", params={
                "key":  YOUTUBE_API_KEY,
                "q":    handle,
                "type": "channel",
                "part": "snippet",
                "maxResults": 1,
            })
            data2 = res2.json()
            if not data2.get("items"):
                return {"error": f"채널을 찾을 수 없습니다: {handle}"}

            channel_id = data2["items"][0]["id"]["channelId"]
            res3 = await client.get(f"{BASE_URL}/channels", params={
                "key":  YOUTUBE_API_KEY,
                "id":   channel_id,
                "part": "snippet,statistics,brandingSettings",
            })
            data = res3.json()

        if not data.get("items"):
            return {"error": "채널 정보를 가져올 수 없습니다"}

        ch = data["items"][0]
        snippet    = ch.get("snippet", {})
        stats      = ch.get("statistics", {})
        channel_id = ch["id"]

        subscriber_count = int(stats.get("subscriberCount", 0))
        video_count      = int(stats.get("videoCount", 0))
        view_count       = int(stats.get("viewCount", 0))

        return {
            "channel_id":       channel_id,
            "channel_name":     snippet.get("title", ""),
            "handle":           snippet.get("customUrl", handle),
            "description":      snippet.get("description", ""),
            "subscriber_count": subscriber_count,
            "video_count":      video_count,
            "total_views":      view_count,
            "published_at":     snippet.get("publishedAt", ""),
            "country":          snippet.get("country", ""),
        }


# ══════════════════════════════════════════════════════════════
# 최근 동영상 수집
# ══════════════════════════════════════════════════════════════
async def get_recent_videos(channel_id: str, max_results: int = 15) -> list:
    """최근 동영상 목록 + 통계"""
    async with httpx.AsyncClient() as client:
        # 최근 동영상 ID 수집
        res = await client.get(f"{BASE_URL}/search", params={
            "key":       YOUTUBE_API_KEY,
            "channelId": channel_id,
            "part":      "id",
            "order":     "date",
            "type":      "video",
            "maxResults": max_results,
        })
        data = res.json()
        if not data.get("items"):
            return []

        video_ids = [item["id"]["videoId"] for item in data["items"]]

        # 동영상 통계 수집
        res2 = await client.get(f"{BASE_URL}/videos", params={
            "key":  YOUTUBE_API_KEY,
            "id":   ",".join(video_ids),
            "part": "snippet,statistics,contentDetails",
        })
        data2 = res2.json()

        videos = []
        for v in data2.get("items", []):
            s = v.get("statistics", {})
            snippet = v.get("snippet", {})
            videos.append({
                "video_id":     v["id"],
                "title":        snippet.get("title", ""),
                "published_at": snippet.get("publishedAt", ""),
                "view_count":   int(s.get("viewCount", 0)),
                "like_count":   int(s.get("likeCount", 0)),
                "comment_count":int(s.get("commentCount", 0)),
                "duration":     v.get("contentDetails", {}).get("duration", ""),
                "tags":         snippet.get("tags", []),
                "category_id":  snippet.get("categoryId", ""),
            })
        return videos


# ══════════════════════════════════════════════════════════════
# 카테고리 분류
# ══════════════════════════════════════════════════════════════
YOUTUBE_CATEGORY_MAP = {
    "1":  "영화/애니메이션", "2":  "자동차",
    "10": "음악",           "15": "반려동물",
    "17": "스포츠/운동",    "19": "여행",
    "20": "게임",           "22": "일상/브이로그",
    "23": "코미디",         "24": "엔터테인먼트",
    "25": "뉴스/정치",      "26": "스타일/뷰티",
    "27": "교육",           "28": "IT/과학",
    "29": "NGO/사회활동",
}

KEYWORD_CATEGORY = {
    "뷰티":    ["makeup","beauty","skincare","뷰티","메이크업","화장","스킨케어"],
    "패션":    ["fashion","ootd","style","패션","스타일","코디","옷"],
    "음식":    ["food","cook","recipe","먹방","요리","맛집","mukbang"],
    "여행":    ["travel","trip","vlog","여행","브이로그","투어"],
    "게임":    ["game","gaming","gameplay","게임","플레이","리뷰"],
    "IT/테크": ["tech","review","unboxing","테크","리뷰","언박싱","개발"],
    "운동":    ["fitness","workout","gym","운동","헬스","다이어트"],
    "육아":    ["baby","kids","mom","육아","아이","맘","임신"],
    "반려동물":["dog","cat","pet","강아지","고양이","펫"],
    "교육":    ["study","learn","education","공부","교육","강의"],
}

def classify_youtube_category(channel_info: dict, videos: list) -> dict:
    scores = {}
    desc   = (channel_info.get("description","") + " " + channel_info.get("handle","")).lower()
    all_tags = [t.lower() for v in videos for t in v.get("tags",[])]
    all_titles = " ".join(v.get("title","").lower() for v in videos)
    text = desc + " " + " ".join(all_tags) + " " + all_titles

    for cat, keywords in KEYWORD_CATEGORY.items():
        score = sum(text.count(kw) for kw in keywords)
        if score > 0:
            scores[cat] = score

    # YouTube 카테고리 ID 활용
    cat_ids = [v.get("category_id","") for v in videos if v.get("category_id")]
    if cat_ids:
        most_common = max(set(cat_ids), key=cat_ids.count)
        yt_cat = YOUTUBE_CATEGORY_MAP.get(most_common, "")
        if yt_cat:
            scores[yt_cat] = scores.get(yt_cat, 0) + 5

    if not scores:
        return {"primary":"일반","confidence":0.0}

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    total  = sum(scores.values())
    return {
        "primary":   ranked[0][0],
        "secondary": ranked[1][0] if len(ranked)>1 else None,
        "confidence": round(ranked[0][1]/total, 2),
        "all_scores": dict(ranked[:5]),
    }


# ══════════════════════════════════════════════════════════════
# 스코어링
# ══════════════════════════════════════════════════════════════
def classify_yt_tier(n: int) -> str:
    if n < 1000:       return "unknown"
    if n < 10000:      return "nano"
    if n < 100000:     return "micro"
    if n < 500000:     return "mid"
    if n < 1000000:    return "macro"
    return "mega"

YT_TIER_CONFIG = {
    "nano":    {"er_baseline": 8.0,  "weight": 1.2},
    "micro":   {"er_baseline": 5.0,  "weight": 1.1},
    "mid":     {"er_baseline": 3.0,  "weight": 1.0},
    "macro":   {"er_baseline": 1.5,  "weight": 0.9},
    "mega":    {"er_baseline": 0.8,  "weight": 0.85},
    "unknown": {"er_baseline": 3.0,  "weight": 1.0},
}

# 유튜브 광고 단가표 (협찬 영상 기준)
YT_AD_PRICE = {
    "nano":    {"S":(300_000,420_000),"A":(200_000,280_000),"B":(120_000,170_000),"C":(60_000,85_000),"D":(0,0)},
    "micro":   {"S":(1_500_000,2_100_000),"A":(1_000_000,1_400_000),"B":(600_000,850_000),"C":(280_000,400_000),"D":(0,0)},
    "mid":     {"S":(8_000_000,11_000_000),"A":(5_500_000,7_700_000),"B":(3_500_000,4_900_000),"C":(1_500_000,2_100_000),"D":(0,0)},
    "macro":   {"S":(20_000_000,28_000_000),"A":(14_000_000,20_000_000),"B":(9_000_000,12_600_000),"C":(4_000_000,5_600_000),"D":(0,0)},
    "mega":    {"S":(50_000_000,70_000_000),"A":(35_000_000,49_000_000),"B":(22_000_000,31_000_000),"C":(10_000_000,14_000_000),"D":(0,0)},
    "unknown": {"S":(0,0),"A":(0,0),"B":(0,0),"C":(0,0),"D":(0,0)},
}

def score_youtube_channel(channel_info: dict, videos: list) -> dict:
    subs    = max(channel_info.get("subscriber_count", 1), 1)
    tier    = classify_yt_tier(subs)
    cfg     = YT_TIER_CONFIG[tier]

    # 1. 평균 조회수 기반 ER
    if videos:
        avg_views    = sum(v["view_count"] for v in videos) / len(videos)
        avg_likes    = sum(v["like_count"] for v in videos) / len(videos)
        avg_comments = sum(v["comment_count"] for v in videos) / len(videos)
    else:
        avg_views = avg_likes = avg_comments = 0

    # 조회율 (조회수/구독자)
    view_rate = avg_views / subs * 100
    norm_view = min(view_rate / cfg["er_baseline"] / 3.0, 1.0)

    # 좋아요율
    like_rate = avg_likes / max(avg_views, 1) * 100
    norm_like = min(like_rate / 3.0, 1.0)

    # 댓글율
    comment_rate = avg_comments / max(avg_views, 1) * 100
    norm_comment = min(comment_rate / 0.5, 1.0)

    # 업로드 일관성 (최근 영상 날짜 간격)
    if len(videos) >= 3:
        dates = []
        for v in videos[:10]:
            try:
                dt = datetime.fromisoformat(v["published_at"].replace("Z","+00:00"))
                dates.append(dt)
            except: pass
        if len(dates) >= 2:
            gaps = [(dates[i]-dates[i+1]).days for i in range(len(dates)-1)]
            avg_gap = sum(gaps)/len(gaps)
            norm_consistency = max(0, 1 - (avg_gap-7)/30) if avg_gap > 7 else 1.0
        else:
            norm_consistency = 0.5
    else:
        norm_consistency = 0.5

    # 최종 점수
    weighted    = norm_view*0.35 + norm_like*0.25 + norm_comment*0.20 + norm_consistency*0.20
    final_score = min(weighted * cfg["weight"] * 100, 100)

    grade = "S" if final_score>=80 else "A" if final_score>=65 else \
            "B" if final_score>=50 else "C" if final_score>=35 else "D"

    # 광고 단가
    prices  = YT_AD_PRICE.get(tier, {}).get(grade, (0,0))
    feed_lo, feed_hi = prices

    def fmt(v): return f"{v:,}원" if v>0 else "광고 비추천"

    # 카테고리 프리미엄
    category = classify_youtube_category(channel_info, videos)
    cat_premium = {"뷰티":1.2,"패션":1.2,"운동":1.15,"IT/테크":1.1,"게임":1.1}
    multiplier = cat_premium.get(category["primary"], 1.0)
    feed_lo = int(feed_lo * multiplier)
    feed_hi = int(feed_hi * multiplier)

    return {
        "final_score":     round(final_score, 1),
        "grade":           grade,
        "tier":            tier,
        "platform":        "youtube",
        "subscriber_count": subs,
        "avg_views":       round(avg_views),
        "avg_likes":       round(avg_likes),
        "avg_comments":    round(avg_comments),
        "view_rate":       round(view_rate, 2),
        "like_rate":       round(like_rate, 2),
        "category":        category,
        "ad_price": {
            "sponsorship_low":  feed_lo,
            "sponsorship_high": feed_hi,
            "sponsorship_fmt":  f"{fmt(feed_lo)} ~ {fmt(feed_hi)}" if feed_lo>0 else "광고 비추천",
        },
        "score_breakdown": {
            "view_rate":    round(norm_view, 3),
            "like_rate":    round(norm_like, 3),
            "comment_rate": round(norm_comment, 3),
            "consistency":  round(norm_consistency, 3),
        },
        "videos_analyzed": len(videos),
        "recent_videos":   videos[:5],
    }


# ══════════════════════════════════════════════════════════════
# 통합 분석 함수
# ══════════════════════════════════════════════════════════════
async def analyze_youtube_channel(channel_input: str) -> dict:
    """유튜브 채널 전체 분석"""
    print(f"\n📺 [YouTube] @{channel_input} 분석 시작...")

    channel_info = await get_channel_info(channel_input)
    if channel_info.get("error"):
        return channel_info

    print(f"   채널: {channel_info['channel_name']} | 구독자: {channel_info['subscriber_count']:,}명")

    videos = await get_recent_videos(channel_info["channel_id"], max_results=15)
    print(f"   최근 영상 {len(videos)}개 수집 완료")

    result = score_youtube_channel(channel_info, videos)
    result["channel_info"] = channel_info

    print(f"   ✅ {result['grade']}등급 {result['final_score']}점 | "
          f"카테고리: {result['category']['primary']} | "
          f"협찬단가: {result['ad_price']['sponsorship_fmt']}")

    return {"status": "success", **result}