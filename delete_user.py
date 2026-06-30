"""
delete_user.py
DB에서 특정 인플루언서/기업 삭제
사용법: python delete_user.py 계정명_또는_이메일
"""

import sys
import sqlite3

DB_FILE = "platform.db"

def delete_influencer(keyword: str):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # 이름, 계정명, 이메일로 검색
    rows = c.execute(
        "SELECT * FROM influencers WHERE name LIKE ? OR insta_handle LIKE ? OR email LIKE ?",
        (f"%{keyword}%", f"%{keyword}%", f"%{keyword}%")
    ).fetchall()

    if not rows:
        print(f"❌ '{keyword}' 와 일치하는 인플루언서를 찾을 수 없습니다.")
        conn.close()
        return

    print(f"\n🔍 검색 결과 {len(rows)}건:")
    for r in rows:
        print(f"   ID:{r['id']} | 이름:{r['name']} | 계정:@{r['insta_handle']} | 이메일:{r['email']}")

    confirm = input(f"\n위 {len(rows)}건을 삭제하시겠습니까? (y/n): ").strip().lower()
    if confirm != 'y':
        print("취소되었습니다.")
        conn.close()
        return

    for r in rows:
        c.execute("DELETE FROM influencers WHERE id=?", (r['id'],))
        c.execute("DELETE FROM notifications WHERE insta_handle=?", (r['insta_handle'],))
        print(f"   ✅ 삭제 완료: @{r['insta_handle']}")

    conn.commit()
    conn.close()
    print(f"\n🎉 {len(rows)}건 삭제 완료")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: python delete_user.py 계정명_또는_이름_또는_이메일")
        sys.exit(1)
    keyword = sys.argv[1]
    delete_influencer(keyword)
