"""
database.py
SQLite 기반 플랫폼 DB
인플루언서 회원 + 분석 결과 저장
"""

import sqlite3
import os
from datetime import datetime

import os as _os
_DATA_DIR = "/app/data" if _os.path.isdir("/app/data") else "."
DB_FILE = _os.path.join(_DATA_DIR, "platform.db")


def get_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """DB 초기화 — 최초 1회 실행"""
    conn = get_conn()
    c = conn.cursor()

    # 인플루언서 회원 테이블
    c.execute("""
        CREATE TABLE IF NOT EXISTS influencers (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT NOT NULL,
            email         TEXT UNIQUE NOT NULL,
            phone         TEXT,
            insta_handle  TEXT UNIQUE NOT NULL,
            category      TEXT,
            bio           TEXT,
            joined_at     TEXT DEFAULT (datetime('now','localtime')),
            status        TEXT DEFAULT 'pending',   -- pending/analyzed/active/inactive
            
            -- 분석 결과
            final_score       REAL DEFAULT 0,
            grade             TEXT DEFAULT '',
            tier              TEXT DEFAULT '',
            follower_count    INTEGER DEFAULT 0,
            fake_ratio        REAL DEFAULT 0,
            fake_risk         TEXT DEFAULT '',
            raw_er            REAL DEFAULT 0,
            engagement_score  REAL DEFAULT 0,
            follower_quality  REAL DEFAULT 0,
            comment_quality   REAL DEFAULT 0,
            consistency       REAL DEFAULT 0,
            
            -- 광고 단가
            feed_price    INTEGER DEFAULT 0,
            story_price   INTEGER DEFAULT 0,
            reels_price   INTEGER DEFAULT 0,
            feed_fmt      TEXT DEFAULT '',
            story_fmt     TEXT DEFAULT '',
            reels_fmt     TEXT DEFAULT '',
            
            last_analyzed TEXT
        )
    """)

    # 기업 회원 테이블 (나중에 확장)
    c.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            email       TEXT UNIQUE NOT NULL,
            industry    TEXT,
            joined_at   TEXT DEFAULT (datetime('now','localtime')),
            status      TEXT DEFAULT 'active'
        )
    """)

    # 광고 의뢰 테이블 (나중에 확장)
    c.execute("""
        CREATE TABLE IF NOT EXISTS campaigns (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id      INTEGER,
            title           TEXT,
            category        TEXT,
            budget          INTEGER,
            tier_min        TEXT,
            grade_min       TEXT,
            status          TEXT DEFAULT 'open',
            created_at      TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(company_id) REFERENCES companies(id)
        )
    """)

    conn.commit()
    conn.close()
    print("✅ DB 초기화 완료: platform.db")


# ── CRUD ──────────────────────────────────────────────────────
def create_influencer(data: dict) -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO influencers (name, email, phone, insta_handle, category)
        VALUES (:name, :email, :phone, :insta_handle, :category)
    """, data)
    conn.commit()
    row_id = c.lastrowid
    conn.close()
    return row_id


def update_analysis(insta_handle: str, result: dict, account_data: dict):
    """분석 결과 저장"""
    sb  = result.get("score_breakdown", {})
    adp = result.get("ad_price", {})
    cat = result.get("category", {})

    conn = get_conn()
    conn.execute("""
        UPDATE influencers SET
            status          = 'active',
            final_score     = :final_score,
            grade           = :grade,
            tier            = :tier,
            follower_count  = :follower_count,
            fake_ratio      = :fake_ratio,
            fake_risk       = :fake_risk,
            raw_er          = :raw_er,
            engagement_score= :engagement,
            follower_quality= :follower_quality,
            comment_quality = :comment_quality,
            consistency     = :consistency,
            feed_price      = :feed_price,
            story_price     = :story_price,
            reels_price     = :reels_price,
            feed_fmt        = :feed_fmt,
            story_fmt       = :story_fmt,
            reels_fmt       = :reels_fmt,
            category        = :category,
            last_analyzed   = :last_analyzed
        WHERE insta_handle = :insta_handle
    """, {
        "insta_handle":   insta_handle,
        "final_score":    result.get("final_score", 0),
        "grade":          result.get("grade", ""),
        "tier":           result.get("tier", ""),
        "follower_count": account_data.get("follower_count", 0),
        "fake_ratio":     result.get("fake_ratio", 0),
        "fake_risk":      result.get("fake_follower_risk", ""),
        "raw_er":         result.get("raw_er", 0),
        "engagement":     sb.get("engagement", 0),
        "follower_quality": sb.get("follower_quality", 0),
        "comment_quality":  sb.get("comment_quality", 0),
        "consistency":      sb.get("consistency", 0),
        "feed_price":     adp.get("feed_price", 0),
        "story_price":    adp.get("story_price", 0),
        "reels_price":    adp.get("reels_price", 0),
        "feed_fmt":       adp.get("feed_fmt", ""),
        "story_fmt":      adp.get("story_fmt", ""),
        "reels_fmt":      adp.get("reels_fmt", ""),
        "category":       cat.get("primary", "일반"),
        "last_analyzed":  datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    conn.commit()
    conn.close()


def get_influencer_by_handle(handle: str) -> dict | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM influencers WHERE insta_handle = ?", (handle,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_influencer_by_email(email: str) -> dict | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM influencers WHERE email = ?", (email,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_marketplace(
    category: str = None,
    tier: str = None,
    grade_min: str = None,
    limit: int = 50
) -> list[dict]:
    """마켓플레이스 검색 — 활성 인플루언서만"""
    query  = "SELECT * FROM influencers WHERE status = 'active'"
    params = []

    if category:
        query += " AND category = ?"
        params.append(category)
    if tier:
        query += " AND tier = ?"
        params.append(tier)
    if grade_min:
        grades = ["S","A","B","C","D"]
        min_idx = grades.index(grade_min) if grade_min in grades else 4
        allowed = grades[:min_idx+1]
        placeholders = ",".join("?"*len(allowed))
        query += f" AND grade IN ({placeholders})"
        params.extend(allowed)

    query += " ORDER BY final_score DESC LIMIT ?"
    params.append(limit)

    conn = get_conn()
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_pending_influencers() -> list[dict]:
    """분석 대기 중인 인플루언서 목록 (status='pending')"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT insta_handle, category FROM influencers WHERE status='pending' ORDER BY joined_at"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_pending(insta_handle: str):
    """재분석을 위해 상태를 pending으로 되돌림"""
    conn = get_conn()
    conn.execute(
        "UPDATE influencers SET status='pending' WHERE insta_handle=?", (insta_handle,)
    )
    conn.commit()
    conn.close()


def get_stats() -> dict:
    """관리자용 통계"""
    conn = get_conn()
    total    = conn.execute("SELECT COUNT(*) FROM influencers").fetchone()[0]
    active   = conn.execute("SELECT COUNT(*) FROM influencers WHERE status='active'").fetchone()[0]
    pending  = conn.execute("SELECT COUNT(*) FROM influencers WHERE status='pending'").fetchone()[0]
    avg_score= conn.execute("SELECT AVG(final_score) FROM influencers WHERE status='active'").fetchone()[0] or 0
    conn.close()
    return {
        "total": total, "active": active,
        "pending": pending, "avg_score": round(avg_score, 1)
    }


# 최초 실행 시 DB 초기화
init_db()


# ══════════════════════════════════════════════════════════════
# 기업 회원 CRUD
# ══════════════════════════════════════════════════════════════
def create_company(data: dict) -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO companies (name, email, industry)
        VALUES (:company_name, :email, :industry)
    """, data)
    conn.commit()
    row_id = c.lastrowid
    conn.close()
    return row_id


def get_company_by_email(email: str) -> dict | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM companies WHERE email = ?", (email,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ══════════════════════════════════════════════════════════════
# 광고 의뢰 CRUD
# ══════════════════════════════════════════════════════════════
def create_campaign(data: dict) -> int:
    conn = get_conn()
    # 기업 ID 조회
    company = conn.execute(
        "SELECT id FROM companies WHERE email = ?", (data["email"],)
    ).fetchone()
    if not company:
        conn.close()
        return -1

    c = conn.cursor()
    c.execute("""
        INSERT INTO campaigns (company_id, title, category, budget, tier_min, grade_min)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (company["id"], data["title"], data["category"],
          data.get("budget", 0), data.get("tier_min", ""),
          data.get("grade_min", "")))
    conn.commit()
    row_id = c.lastrowid
    conn.close()
    return row_id


def get_company_campaigns(email: str) -> list[dict]:
    conn = get_conn()
    company = conn.execute(
        "SELECT id FROM companies WHERE email = ?", (email,)
    ).fetchone()
    if not company:
        conn.close()
        return []
    rows = conn.execute(
        "SELECT * FROM campaigns WHERE company_id = ? ORDER BY created_at DESC",
        (company["id"],)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ══════════════════════════════════════════════════════════════
# 알림 시스템
# ══════════════════════════════════════════════════════════════
def init_notifications():
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            insta_handle TEXT NOT NULL,
            type         TEXT NOT NULL,   -- 'campaign_match' | 'system'
            title        TEXT NOT NULL,
            body         TEXT,
            campaign_id  INTEGER,
            is_read      INTEGER DEFAULT 0,
            created_at   TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(campaign_id) REFERENCES campaigns(id)
        )
    """)
    conn.commit()
    conn.close()


def create_match_notifications(campaign_id: int, campaign: dict):
    """
    의뢰 등록 시 조건에 맞는 인플루언서에게 알림 생성
    조건: 카테고리 일치 + 티어/등급 조건 충족
    """
    conn = get_conn()

    query  = "SELECT * FROM influencers WHERE status = 'active'"
    params = []

    if campaign.get("category"):
        query += " AND category = ?"
        params.append(campaign["category"])

    if campaign.get("tier_min"):
        tier_order = {"nano":1,"micro":2,"mid":3,"macro":4,"mega":5}
        min_order  = tier_order.get(campaign["tier_min"], 1)
        allowed    = [t for t,o in tier_order.items() if o >= min_order]
        query += f" AND tier IN ({','.join('?'*len(allowed))})"
        params.extend(allowed)

    if campaign.get("grade_min"):
        grade_order = {"S":1,"A":2,"B":3,"C":4,"D":5}
        min_order   = grade_order.get(campaign["grade_min"], 5)
        allowed     = [g for g,o in grade_order.items() if o <= min_order]
        query += f" AND grade IN ({','.join('?'*len(allowed))})"
        params.extend(allowed)

    matches = conn.execute(query, params).fetchall()

    for inf in matches:
        conn.execute("""
            INSERT INTO notifications (insta_handle, type, title, body, campaign_id)
            VALUES (?, 'campaign_match', ?, ?, ?)
        """, (
            inf["insta_handle"],
            f"새 광고 의뢰가 있습니다: {campaign['title']}",
            f"카테고리: {campaign.get('category','—')} | 예산: {campaign.get('budget',0):,}만원",
            campaign_id
        ))

    conn.commit()
    match_count = len(matches)
    conn.close()
    return match_count


def get_notifications(insta_handle: str) -> list[dict]:
    conn = get_conn()
    rows = conn.execute("""
        SELECT n.*, c.title as campaign_title, c.budget, c.category as campaign_category
        FROM notifications n
        LEFT JOIN campaigns c ON n.campaign_id = c.id
        WHERE n.insta_handle = ?
        ORDER BY n.created_at DESC
        LIMIT 20
    """, (insta_handle,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_read(notification_id: int):
    conn = get_conn()
    conn.execute("UPDATE notifications SET is_read=1 WHERE id=?", (notification_id,))
    conn.commit()
    conn.close()


def get_unread_count(insta_handle: str) -> int:
    conn = get_conn()
    count = conn.execute(
        "SELECT COUNT(*) FROM notifications WHERE insta_handle=? AND is_read=0",
        (insta_handle,)
    ).fetchone()[0]
    conn.close()
    return count


init_notifications()


# ══════════════════════════════════════════════════════════════
# 비밀번호 컬럼 추가 마이그레이션
# ══════════════════════════════════════════════════════════════
def migrate_add_passwords():
    conn = get_conn()
    # influencers 테이블에 password 컬럼 추가
    try:
        conn.execute("ALTER TABLE influencers ADD COLUMN password TEXT DEFAULT ''")
        print("✅ influencers.password 컬럼 추가")
    except:
        pass
    # companies 테이블에 password 컬럼 추가
    try:
        conn.execute("ALTER TABLE companies ADD COLUMN password TEXT DEFAULT ''")
        print("✅ companies.password 컬럼 추가")
    except:
        pass
    conn.commit()
    conn.close()


def set_influencer_password(insta_handle: str, hashed_pw: str):
    conn = get_conn()
    conn.execute(
        "UPDATE influencers SET password=? WHERE insta_handle=?",
        (hashed_pw, insta_handle)
    )
    conn.commit()
    conn.close()


def set_company_password(email: str, hashed_pw: str):
    conn = get_conn()
    conn.execute(
        "UPDATE companies SET password=? WHERE email=?",
        (hashed_pw, email)
    )
    conn.commit()
    conn.close()


def get_influencer_password(insta_handle: str) -> str:
    conn = get_conn()
    row = conn.execute(
        "SELECT password FROM influencers WHERE insta_handle=?",
        (insta_handle,)
    ).fetchone()
    conn.close()
    return row["password"] if row else ""


def get_company_password(email: str) -> str:
    conn = get_conn()
    row = conn.execute(
        "SELECT password FROM companies WHERE email=?",
        (email,)
    ).fetchone()
    conn.close()
    return row["password"] if row else ""


migrate_add_passwords()


# ══════════════════════════════════════════════════════════════
# 멤버십 + 결제 시스템
# ══════════════════════════════════════════════════════════════
def init_membership():
    conn = get_conn()

    # 멤버십 플랜 테이블
    conn.execute("""
        CREATE TABLE IF NOT EXISTS membership_plans (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            type        TEXT NOT NULL,   -- 'influencer' | 'company'
            price       INTEGER NOT NULL, -- 월 가격 (원)
            features    TEXT,             -- JSON 형태 기능 목록
            is_active   INTEGER DEFAULT 1
        )
    """)

    # 구독 테이블
    conn.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     TEXT NOT NULL,   -- insta_handle or email
            user_type   TEXT NOT NULL,   -- 'influencer' | 'company'
            plan_id     INTEGER NOT NULL,
            plan_name   TEXT NOT NULL,
            price       INTEGER NOT NULL,
            status      TEXT DEFAULT 'active',  -- active | cancelled | expired
            started_at  TEXT DEFAULT (datetime('now','localtime')),
            expires_at  TEXT,
            FOREIGN KEY(plan_id) REFERENCES membership_plans(id)
        )
    """)

    # 결제 내역 테이블
    conn.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         TEXT NOT NULL,
            user_type       TEXT NOT NULL,
            payment_key     TEXT,         -- 토스페이먼츠 결제키
            order_id        TEXT UNIQUE,  -- 주문번호
            amount          INTEGER NOT NULL,
            product_name    TEXT,
            status          TEXT DEFAULT 'pending',  -- pending | success | failed | cancelled
            payment_method  TEXT,
            paid_at         TEXT,
            created_at      TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    # 매칭 수수료 테이블
    conn.execute("""
        CREATE TABLE IF NOT EXISTS commissions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id     INTEGER,
            influencer_handle TEXT,
            company_email   TEXT,
            ad_amount       INTEGER,      -- 광고 금액
            commission_rate REAL DEFAULT 0.10,  -- 수수료율 10%
            commission_amount INTEGER,    -- 수수료 금액
            status          TEXT DEFAULT 'pending',  -- pending | paid
            created_at      TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(campaign_id) REFERENCES campaigns(id)
        )
    """)

    # 기본 플랜 데이터 삽입
    plans = [
        # 인플루언서 플랜
        ("Free",  "influencer", 0,      '["분석 1회","기본 프로필 노출"]'),
        ("Basic", "influencer", 9900,   '["재분석 무제한","프리미엄 뱃지","알림 우선수신"]'),
        ("Pro",   "influencer", 29900,  '["상단 노출","포트폴리오 페이지","전담 매니저"]'),
        # 기업 플랜
        ("Free",  "company", 0,       '["월 5건 탐색","의뢰 1건"]'),
        ("Basic", "company", 49000,   '["무제한 탐색","의뢰 3건","상세 분석 리포트"]'),
        ("Pro",   "company", 149000,  '["무제한 의뢰","매칭 보장","전담 매니저"]'),
    ]
    for name, type_, price, features in plans:
        existing = conn.execute(
            "SELECT id FROM membership_plans WHERE name=? AND type=?",
            (name, type_)
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO membership_plans (name, type, price, features) VALUES (?,?,?,?)",
                (name, type_, price, features)
            )

    conn.commit()
    conn.close()
    print("✅ 멤버십 DB 초기화 완료")


def get_plans(user_type: str) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM membership_plans WHERE type=? AND is_active=1 ORDER BY price",
        (user_type,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_subscription(user_id: str) -> dict | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM subscriptions WHERE user_id=? AND status='active' ORDER BY id DESC LIMIT 1",
        (user_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def create_payment(data: dict) -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO payments (user_id, user_type, order_id, amount, product_name)
        VALUES (:user_id, :user_type, :order_id, :amount, :product_name)
    """, data)
    conn.commit()
    row_id = c.lastrowid
    conn.close()
    return row_id


def confirm_payment(order_id: str, payment_key: str, amount: int) -> bool:
    conn = get_conn()
    payment = conn.execute(
        "SELECT * FROM payments WHERE order_id=?", (order_id,)
    ).fetchone()
    if not payment or payment["amount"] != amount:
        conn.close()
        return False

    conn.execute("""
        UPDATE payments SET
            status='success', payment_key=?, paid_at=datetime('now','localtime')
        WHERE order_id=?
    """, (payment_key, order_id))

    # 구독 생성
    conn.execute("""
        INSERT INTO subscriptions (user_id, user_type, plan_id, plan_name, price, expires_at)
        VALUES (?, ?, ?, ?, ?, datetime('now', '+30 days', 'localtime'))
    """, (
        payment["user_id"], payment["user_type"],
        1, payment["product_name"], payment["amount"]
    ))

    conn.commit()
    conn.close()
    return True


def create_commission(data: dict) -> int:
    conn = get_conn()
    c = conn.cursor()
    ad_amount   = data.get("ad_amount", 0)
    rate        = data.get("commission_rate", 0.10)
    commission  = int(ad_amount * rate)
    c.execute("""
        INSERT INTO commissions
        (campaign_id, influencer_handle, company_email, ad_amount, commission_rate, commission_amount)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        data.get("campaign_id"), data.get("influencer_handle"),
        data.get("company_email"), ad_amount, rate, commission
    ))
    conn.commit()
    row_id = c.lastrowid
    conn.close()
    return row_id


def get_revenue_stats() -> dict:
    conn = get_conn()
    total_payments = conn.execute(
        "SELECT COALESCE(SUM(amount),0) FROM payments WHERE status='success'"
    ).fetchone()[0]
    total_commission = conn.execute(
        "SELECT COALESCE(SUM(commission_amount),0) FROM commissions WHERE status='paid'"
    ).fetchone()[0]
    active_subs = conn.execute(
        "SELECT COUNT(*) FROM subscriptions WHERE status='active'"
    ).fetchone()[0]
    monthly_mrr = conn.execute(
        "SELECT COALESCE(SUM(price),0) FROM subscriptions WHERE status='active'"
    ).fetchone()[0]
    conn.close()
    return {
        "total_revenue":    total_payments + total_commission,
        "subscription_revenue": total_payments,
        "commission_revenue":   total_commission,
        "active_subscribers":   active_subs,
        "mrr":                  monthly_mrr,
    }


init_membership()


# ══════════════════════════════════════════════════════════════
# 체험단/캠페인 공고 시스템
# ══════════════════════════════════════════════════════════════
def init_campaigns():
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS campaign_posts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name    TEXT,
            title           TEXT NOT NULL,
            category        TEXT,
            campaign_type   TEXT DEFAULT 'review',
            description     TEXT,
            requirements    TEXT,
            reward          TEXT,
            reward_amount   INTEGER DEFAULT 0,
            deadline        TEXT,
            slots           INTEGER DEFAULT 10,
            applied         INTEGER DEFAULT 0,
            status          TEXT DEFAULT 'open',
            thumbnail       TEXT DEFAULT '🎁',
            created_at      TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS campaign_applications (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id     INTEGER,
            insta_handle    TEXT,
            name            TEXT,
            email           TEXT,
            message         TEXT,
            status          TEXT DEFAULT 'pending',
            applied_at      TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(campaign_id) REFERENCES campaign_posts(id)
        )
    """)
    existing = conn.execute("SELECT COUNT(*) FROM campaign_posts").fetchone()[0]
    if existing == 0:
        samples = [
            ("뷰티풀스킨", "신제품 수분크림 체험단 모집", "뷰티", "review",
             "새로 출시한 수분크림을 직접 사용해보고 솔직한 후기를 인스타그램에 올려주실 분을 모집합니다.",
             "뷰티 카테고리 · 팔로워 500명 이상 · B등급 이상",
             "제품 무료 제공 + 원고료 30,000원", 30000, "2026-08-31", 20, "💄"),
            ("맛있는부엌", "홈쿠킹 밀키트 체험단", "음식", "experience",
             "다양한 밀키트를 직접 요리하고 리뷰해주실 푸드 인플루언서를 모집합니다.",
             "음식/요리 카테고리 · 팔로워 1,000명 이상",
             "밀키트 3종 무료 제공", 0, "2026-08-15", 15, "🍳"),
            ("트렌디패션", "여름 신상 스타일링 광고", "패션", "ad",
             "2026 여름 신상 의류 스타일링 콘텐츠를 제작해주실 패션 인플루언서를 찾습니다.",
             "패션 카테고리 · 팔로워 3,000명 이상 · A등급 이상",
             "의류 제공 + 광고비 협의", 0, "2026-07-31", 5, "👗"),
            ("헬스짐", "피트니스 용품 체험 후기", "운동", "review",
             "홈트레이닝 용품을 체험하고 운동 루틴과 함께 리뷰해주실 분을 모집합니다.",
             "운동/헬스 카테고리 · 팔로워 500명 이상",
             "용품 무료 제공 + 20,000원", 20000, "2026-08-20", 10, "💪"),
            ("펫라이프", "강아지 간식 체험단", "반려동물", "review",
             "반려견과 함께하는 간식 체험 후기를 올려주실 펫 인플루언서를 모집합니다.",
             "반려동물 카테고리 · 팔로워 500명 이상",
             "간식 3종 무료 제공 + 15,000원", 15000, "2026-09-01", 30, "🐾"),
        ]
        for s in samples:
            conn.execute("""
                INSERT INTO campaign_posts
                (company_name, title, category, campaign_type, description, requirements, reward, reward_amount, deadline, slots, thumbnail)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, s)
    conn.commit()
    conn.close()


def get_campaigns(category=None, campaign_type=None, status='open', limit=50) -> list[dict]:
    conn = get_conn()
    q = "SELECT * FROM campaign_posts WHERE status=?"
    params = [status]
    if category:
        q += " AND category=?"
        params.append(category)
    if campaign_type:
        q += " AND campaign_type=?"
        params.append(campaign_type)
    q += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_campaign_by_id(campaign_id: int) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM campaign_posts WHERE id=?", (campaign_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def apply_campaign(campaign_id: int, data: dict) -> int:
    conn = get_conn()
    existing = conn.execute(
        "SELECT id FROM campaign_applications WHERE campaign_id=? AND insta_handle=?",
        (campaign_id, data.get("insta_handle",""))
    ).fetchone()
    if existing:
        conn.close()
        return -1
    c = conn.cursor()
    c.execute("""
        INSERT INTO campaign_applications (campaign_id, insta_handle, name, email, message)
        VALUES (?,?,?,?,?)
    """, (campaign_id, data.get("insta_handle",""), data.get("name",""), data.get("email",""), data.get("message","")))
    conn.execute("UPDATE campaign_posts SET applied=applied+1 WHERE id=?", (campaign_id,))
    conn.commit()
    row_id = c.lastrowid
    conn.close()
    return row_id


def create_campaign_post(data: dict) -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO campaign_posts
        (company_name, title, category, campaign_type, description, requirements, reward, reward_amount, deadline, slots, thumbnail)
        VALUES (:company_name,:title,:category,:campaign_type,:description,:requirements,:reward,:reward_amount,:deadline,:slots,:thumbnail)
    """, {
        "company_name":  data.get("company_name",""),
        "title":         data.get("title",""),
        "category":      data.get("category",""),
        "campaign_type": data.get("campaign_type","review"),
        "description":   data.get("description",""),
        "requirements":  data.get("requirements",""),
        "reward":        data.get("reward",""),
        "reward_amount": data.get("reward_amount",0),
        "deadline":      data.get("deadline",""),
        "slots":         data.get("slots",10),
        "thumbnail":     data.get("thumbnail","🎁"),
    })
    conn.commit()
    row_id = c.lastrowid
    conn.close()
    return row_id


init_campaigns()


def get_campaign_applications(campaign_id: int = None) -> list[dict]:
    """지원자 목록 조회 (campaign_id 없으면 전체)"""
    conn = get_conn()
    if campaign_id:
        rows = conn.execute("""
            SELECT a.*, p.title as campaign_title, p.company_name, p.thumbnail
            FROM campaign_applications a
            LEFT JOIN campaign_posts p ON a.campaign_id = p.id
            WHERE a.campaign_id = ?
            ORDER BY a.applied_at DESC
        """, (campaign_id,)).fetchall()
    else:
        rows = conn.execute("""
            SELECT a.*, p.title as campaign_title, p.company_name, p.thumbnail
            FROM campaign_applications a
            LEFT JOIN campaign_posts p ON a.campaign_id = p.id
            ORDER BY a.applied_at DESC
        """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_application_status(app_id: int, status: str):
    """지원자 상태 변경 (pending/accepted/rejected)"""
    conn = get_conn()
    conn.execute("UPDATE campaign_applications SET status=? WHERE id=?", (status, app_id))
    conn.commit()
    conn.close()


def get_applications_by_company(company_email: str) -> list[dict]:
    """기업이 등록한 캠페인의 지원자 목록"""
    conn = get_conn()
    rows = conn.execute("""
        SELECT a.*, p.title as campaign_title, p.thumbnail
        FROM campaign_applications a
        LEFT JOIN campaign_posts p ON a.campaign_id = p.id
        WHERE p.company_id IN (
            SELECT id FROM companies WHERE email=?
        )
        ORDER BY a.applied_at DESC
    """, (company_email,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]