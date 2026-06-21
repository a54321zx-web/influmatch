"""
server.py — 클라우드 배포 전용
Playwright 없이 웹사이트 + API만 운영
분석은 로컬 engyn.py에서, 결과는 여기서 서빙
"""

import os
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import database as db
from auth import (
    hash_password, verify_password,
    create_token, get_current_user, get_current_user_optional
)

app = FastAPI(title="InfluMatch — AI 인플루언서 마케팅 플랫폼")

# 정적 파일
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")


# ══════════════════════════════════════════════════════════════
# 페이지 라우팅
# ══════════════════════════════════════════════════════════════
@app.get("/")
async def page_landing():
    return FileResponse("static/landing.html")

@app.get("/join")
async def page_join():
    return FileResponse("static/join.html")

@app.get("/dashboard")
async def page_dashboard():
    return FileResponse("static/dashboard.html")

@app.get("/marketplace")
async def page_marketplace():
    return FileResponse("static/marketplace.html")

@app.get("/company/join")
async def page_company_join():
    return FileResponse("static/company_join.html")

@app.get("/company/dashboard")
async def page_company_dashboard():
    return FileResponse("static/company_dashboard.html")

@app.get("/admin")
async def page_admin():
    return FileResponse("static/index.html")


# ══════════════════════════════════════════════════════════════
# 인플루언서 API
# ══════════════════════════════════════════════════════════════
@app.post("/api/join")
async def api_join(data: dict):
    """인플루언서 회원가입 — 분석은 로컬에서 별도 실행"""
    required = ["name", "email", "insta_handle", "password"]
    for field in required:
        if not data.get(field):
            return {"error": f"{field} 필드가 필요합니다"}
    if len(data["password"]) < 6:
        return {"error": "비밀번호는 6자 이상이어야 합니다"}

    handle = data["insta_handle"].replace("@", "").strip()

    if db.get_influencer_by_handle(handle):
        return {"error": "이미 등록된 계정입니다"}
    if db.get_influencer_by_email(data["email"]):
        return {"error": "이미 등록된 이메일입니다"}

    hashed_pw = hash_password(data["password"])
    row_id = db.create_influencer({
        "name":         data["name"],
        "email":        data["email"],
        "phone":        data.get("phone", ""),
        "insta_handle": handle,
        "category":     data.get("category", ""),
    })
    db.set_influencer_password(handle, hashed_pw)

    token = create_token({"sub": handle, "type": "influencer", "email": data["email"]})
    return {
        "success":  True,
        "id":       row_id,
        "token":    token,
        "message":  "가입 완료! AI 분석은 최대 24시간 내 완료됩니다.",
        "grade":    "분석 중",
        "final_score": 0,
        "tier":     "분석 중",
        "follower_count": 0,
        "fake_risk": "분석 중",
        "category": data.get("category", "일반"),
        "feed_fmt": "분석 후 산출",
        "reels_fmt": "분석 후 산출",
    }


@app.post("/api/login")
async def api_influencer_login(data: dict):
    handle   = (data.get("insta_handle") or "").replace("@","").strip()
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


@app.get("/api/influencer/{handle}")
async def api_influencer(handle: str):
    inf = db.get_influencer_by_handle(handle)
    if not inf:
        return {"error": "인플루언서를 찾을 수 없습니다"}
    return inf


@app.post("/api/reanalyze/{handle}")
async def api_reanalyze(handle: str):
    """재분석 요청 — 로컬 engyn.py에서 처리 후 DB 업데이트"""
    inf = db.get_influencer_by_handle(handle)
    if not inf:
        return {"error": "등록된 인플루언서가 없습니다"}
    return {
        "success": True,
        "message": "재분석 요청이 접수됐습니다. 최대 24시간 내 업데이트됩니다."
    }


# ══════════════════════════════════════════════════════════════
# 알림 API
# ══════════════════════════════════════════════════════════════
@app.get("/api/notifications/{handle}")
async def api_get_notifications(handle: str):
    notifs = db.get_notifications(handle)
    unread = db.get_unread_count(handle)
    return {"notifications": notifs, "unread": unread}

@app.post("/api/notifications/{notif_id}/read")
async def api_mark_read(notif_id: int):
    db.mark_read(notif_id)
    return {"success": True}


# ══════════════════════════════════════════════════════════════
# 마켓플레이스 API
# ══════════════════════════════════════════════════════════════
@app.get("/api/marketplace")
async def api_marketplace(
    category: str = None,
    tier: str = None,
    grade_min: str = None,
    limit: int = 50
):
    influencers = db.get_marketplace(category, tier, grade_min, limit)
    return {"influencers": influencers, "total": len(influencers)}


@app.get("/api/stats")
async def api_stats():
    return db.get_stats()


# ══════════════════════════════════════════════════════════════
# 기업 API
# ══════════════════════════════════════════════════════════════
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
    match_count = db.create_match_notifications(row_id, data)
    return {"success": True, "id": row_id, "matched_influencers": match_count}


@app.get("/api/company/requests")
async def api_company_requests(email: str):
    campaigns = db.get_company_campaigns(email)
    open_cnt  = sum(1 for c in campaigns if c.get("status") == "open")
    return {"requests": campaigns, "total": len(campaigns), "open": open_cnt}


@app.get("/session/status")
async def session_status():
    return {"status": "정상", "reason": "정상", "auth_file_exists": True}


@app.get("/history")
async def get_history():
    return {"records": [], "message": "히스토리는 로컬 엑셀 파일에서 확인하세요"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    print(f"🌐 InfluMatch 서버 구동 중... (포트: {port})")
    uvicorn.run(app, host="0.0.0.0", port=port)