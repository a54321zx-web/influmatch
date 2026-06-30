"""
cloud_sync.py
로컬 engyn.py 분석 결과를 클라우드(server.py / Railway)와 동기화
"""

import os
import httpx

CLOUD_URL   = os.environ.get("CLOUD_URL", "https://railway-up-production-c373.up.railway.app")
SYNC_SECRET = os.environ.get("SYNC_SECRET", "")


async def fetch_pending_handles() -> list[dict]:
    """클라우드에서 '분석 대기 중' 계정 목록 가져오기"""
    if not SYNC_SECRET:
        print("⚠️  SYNC_SECRET 환경변수가 없습니다. .env 파일을 확인하세요.")
        return []
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.get(f"{CLOUD_URL}/api/sync/pending", params={"secret": SYNC_SECRET})
            data = res.json()
            if data.get("error"):
                print(f"⚠️  클라우드 인증 실패: {data['error']}")
                return []
            return data.get("pending", [])
    except Exception as e:
        print(f"⚠️  클라우드 연결 실패: {e}")
        return []


async def push_result(insta_handle: str, result: dict, account_data: dict) -> bool:
    """분석 결과를 클라우드 DB에 업로드"""
    if not SYNC_SECRET:
        print("⚠️  SYNC_SECRET 환경변수가 없습니다. 동기화를 건너뜁니다.")
        return False
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.post(f"{CLOUD_URL}/api/sync/result", json={
                "secret":        SYNC_SECRET,
                "insta_handle":  insta_handle,
                "result":        result,
                "account_data":  account_data,
            })
            data = res.json()
            if data.get("success"):
                print(f"   ☁️  클라우드 동기화 완료: @{insta_handle}")
                return True
            else:
                print(f"   ⚠️  클라우드 동기화 실패: {data.get('error')}")
                return False
    except Exception as e:
        print(f"   ⚠️  클라우드 연결 실패: {e}")
        return False
