import json
import os
import sys
from pathlib import Path
import httpx

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://fmjggxjjaitsuddkkwxr.supabase.co")
SUPABASE_KEY = os.getenv(
    "SUPABASE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZtamdneGpqYWl0c3VkZGtrd3hyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTI3MjgyMjUsImV4cCI6MjEwODMwNDIyNX0.yPBWELCtjo954RaeiRUA4_svSCSaRiFzFzUStamGM8A"
)

LOCAL_PROFILE_FILE = Path("user_profile.json")


def _get_headers() -> dict:
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def fetch_profile() -> dict | None:
    """Fetches user profile from Supabase with local fallback."""
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            url = f"{SUPABASE_URL}/rest/v1/user_profiles?id=eq.default_user"
            with httpx.Client(timeout=4.0) as client:
                res = client.get(url, headers=_get_headers())
                if res.status_code == 200:
                    rows = res.json()
                    if rows:
                        row = rows[0]
                        return {
                            "current_level": row.get("current_level", "N4"),
                            "total_calls": row.get("total_calls", 0),
                            "level_stats": row.get("level_stats", {}),
                            "history": []
                        }
        except Exception as e:
            print(f"[Supabase 조회 오류, 로컬 캐시 사용] {e}", file=sys.stderr)

    # Local fallback
    if LOCAL_PROFILE_FILE.exists():
        try:
            with open(LOCAL_PROFILE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def sync_profile(profile_data: dict):
    """Saves profile to local file and syncs to Supabase."""
    # Always save local copy
    try:
        with open(LOCAL_PROFILE_FILE, "w", encoding="utf-8") as f:
            json.dump(profile_data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    # Sync to Supabase
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            url = f"{SUPABASE_URL}/rest/v1/user_profiles?id=eq.default_user"
            payload = {
                "current_level": profile_data.get("current_level", "N4"),
                "total_calls": profile_data.get("total_calls", 0),
                "level_stats": profile_data.get("level_stats", {}),
            }
            with httpx.Client(timeout=5.0) as client:
                client.patch(url, headers=_get_headers(), json=payload)
        except Exception as e:
            print(f"[Supabase 프로필 동기화 오류] {e}", file=sys.stderr)


def record_conversation_to_supabase(
    duration_seconds: int,
    target_level: str,
    score: int,
    passed: bool,
    transcript: list[dict],
    feedback_markdown: str = ""
):
    """Inserts a completed conversation session into Supabase."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return

    try:
        url = f"{SUPABASE_URL}/rest/v1/conversations"
        payload = {
            "duration_seconds": duration_seconds,
            "target_level": target_level,
            "score": score,
            "passed": passed,
            "transcript": transcript,
            "feedback_markdown": feedback_markdown,
        }
        with httpx.Client(timeout=6.0) as client:
            res = client.post(url, headers=_get_headers(), json=payload)
            if res.status_code in (200, 201):
                print("☁️ [Supabase 동기화] 오늘 통화 및 복습 리포트가 클라우드에 영구 저장되었습니다!")
            else:
                print(f"[Supabase 통화 저장 실패: {res.status_code}] {res.text}", file=sys.stderr)
    except Exception as e:
        print(f"[Supabase 통화 기록 오류] {e}", file=sys.stderr)


def get_past_conversations(limit: int = 15) -> list[dict]:
    """Fetches past conversation records and feedback reports from Supabase."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return []

    try:
        url = f"{SUPABASE_URL}/rest/v1/conversations?select=*&order=created_at.desc&limit={limit}"
        with httpx.Client(timeout=5.0) as client:
            res = client.get(url, headers=_get_headers())
            if res.status_code == 200:
                return res.json()
    except Exception as e:
        print(f"[Supabase 과거 기록 조회 오류] {e}", file=sys.stderr)
    return []
