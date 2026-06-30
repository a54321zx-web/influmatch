"""
list_users.py
DB의 전체 인플루언서 목록 출력
"""
import sqlite3

conn = sqlite3.connect("platform.db")
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT id, name, insta_handle, email, status, joined_at FROM influencers ORDER BY id").fetchall()

if not rows:
    print("❌ 등록된 인플루언서가 없습니다.")
else:
    print(f"\n📋 전체 인플루언서 {len(rows)}명:\n")
    for r in rows:
        print(f"   ID:{r['id']} | 이름:{r['name']} | 계정:@{r['insta_handle']} | 이메일:{r['email']} | 상태:{r['status']} | 가입일:{r['joined_at']}")

conn.close()
