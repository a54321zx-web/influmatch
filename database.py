"""
database.py
SQLite 기반 플랫폼 DB
인플루언서 회원 + 분석 결과 저장
"""

import sqlite3
import os
from datetime import datetime

DB_FILE = "platform.db"


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