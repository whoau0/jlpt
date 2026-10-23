import json
from pathlib import Path
from db import fetch_profile, sync_profile

PROFILE_FILE = Path("user_profile.json")

LEVELS = ["N4", "N3", "N2", "N1"]

LEVEL_DETAILS = {
    "N4": {
        "title": "JLPT N4 (초급 회화 완성)",
        "desc": "애니메이션/기초 어휘, 일상 루틴, 경험 이야기, 기본 가정법 (~たら)",
        "next_level": "N3",
        "required_pass_count": 3,  # 3회 성공적인 N4 회화 달성 시 N3로 자동 승급
        "aizuchi_style": "친절하고 쉬운 맞장구 (そうなんだ！、いいね！、わかる！)",
        "system_instruction_addon": """
【현재 목표 레벨: JLPT N4】
- 대화 상대는 초급자입니다.
- 말하는 속도를 약간 천천히 하고, 복잡한 한자어나 관용구 대신 일상적인 쉬운 단어를 사용하세요.
- N4 핵심 문형(〜たことがある, 〜てから, 〜たら, 〜と思う)을 자연스럽게 유도하세요.
- 한국어 SOS 요청 시 언제든 한국어로 친절히 도와주세요.
"""
    },
    "N3": {
        "title": "JLPT N3 (중급 일상 회화)",
        "desc": "감정 표현, 뉴스/화제, 자연스러운 일상 반말/존댓말 구분, 이유 설명 (~わけ, ~はず)",
        "next_level": "N2",
        "required_pass_count": 3,
        "aizuchi_style": "자연스러운 원어민 맞장구 (なるほどね、たしかに！、それめっちゃわかる！)",
        "system_instruction_addon": """
【현재 목표 레벨: JLPT N3】
- 대화 상대는 기초를 뗀 중급 학습자입니다.
- 일상적인 자연스러운 속도로 대화하며, 친구끼리 쓰는 캐주얼한 반말(タメ口)과 정중한 표현을 골고루 섞어주세요.
- N3 핵심 문법(〜ようにする, 〜はずだ, 〜わけにはいかない, 〜によって)을 대화 속에 자연스럽게 사용하고 유도하세요.
- 한국어 도움 요청 시 한국어로 설명하되, N3 수준의 조금 더 풍부한 일본어 표현을 제시하세요.
"""
    },
    "N2": {
        "title": "JLPT N2 (상급 실전 토론 & 비즈니스)",
        "desc": "사회적 이슈, 직장/진로 고민, 찬반 토론, 뉘앙스 차이 표현",
        "next_level": "N1",
        "required_pass_count": 4,
        "aizuchi_style": "원어민 수준의 리액션 (おっしゃる通りです、一理ありますね、なるほど)",
        "system_instruction_addon": """
【현재 목표 레벨: JLPT N2】
- 대화 상대는 상급 학습자입니다.
- 일본 현지 원어민 속도로 자연스럽게 말하세요.
- 사회 현상, 문화 비교, 개인의 가치관이나 진로 등 깊이 있는 주제를 다루고 N2 문형(〜に違いない, 〜をきっかけに, 〜にすぎない)을 활용하세요.
- 필요한 경우 적절한 비즈니스 경어(敬語)도 섞어서 연습을 유도하세요.
"""
    },
    "N1": {
        "title": "JLPT N1 (최상급 원어민 프리토킹)",
        "desc": "추상적 주제, 문화/철학, 관용구 및 사자성어, 완전한 원어민 억양과 티키타카",
        "next_level": None,
        "required_pass_count": 5,
        "aizuchi_style": "풍부하고 지적인 맞장구",
        "system_instruction_addon": """
【현재 목표 레벨: JLPT N1】
- 대화 상대는 최상급 목표자입니다.
- 고급 어휘, 관용구, 미묘한 어감 차이까지 다루며 자유롭고 지적인 프리토킹을 이끕니다.
- 추상적인 비유나 사회적 담론을 주제로 티키타카를 펼치세요.
"""
    }
}


class LevelManager:
    """Manages learner profile, current JLPT level, mastery scoring, and level-up checks."""

    def __init__(self):
        self.profile = self.load_profile()

    def load_profile(self) -> dict:
        remote_data = fetch_profile()
        if remote_data:
            return remote_data

        # Default initial profile (Starts at N4)
        default_profile = {
            "current_level": "N4",
            "total_calls": 0,
            "level_stats": {
                "N4": {"calls_completed": 0, "pass_count": 0, "mastery_score": 0},
                "N3": {"calls_completed": 0, "pass_count": 0, "mastery_score": 0},
                "N2": {"calls_completed": 0, "pass_count": 0, "mastery_score": 0},
                "N1": {"calls_completed": 0, "pass_count": 0, "mastery_score": 0},
            },
            "history": []
        }
        self.save_profile(default_profile)
        return default_profile

    def save_profile(self, data: dict = None):
        if data is None:
            data = self.profile
        sync_profile(data)

    def get_current_level(self) -> str:
        return self.profile.get("current_level", "N4")

    def set_current_level(self, level: str):
        if level in LEVELS:
            self.profile["current_level"] = level
            self.save_profile()

    def get_level_info(self, level: str = None) -> dict:
        if level is None:
            level = self.get_current_level()
        info = dict(LEVEL_DETAILS.get(level, LEVEL_DETAILS["N4"]))
        stats = self.profile.get("level_stats", {}).get(level, {"pass_count": 0, "mastery_score": 0})
        info["current_level"] = level
        info["pass_count"] = stats.get("pass_count", 0)
        info["mastery_score"] = stats.get("mastery_score", 0)
        req = info.get("required_pass_count", 3)
        info["progress_percent"] = min(100, int((info["pass_count"] / req) * 100))
        return info

    def record_call_result(self, level_passed: bool, score: int, call_summary: str = "") -> dict:
        """
        Updates stats after a call and checks if student qualifies for a level up!
        """
        curr = self.get_current_level()
        stats = self.profile["level_stats"].setdefault(curr, {"calls_completed": 0, "pass_count": 0, "mastery_score": 0})

        self.profile["total_calls"] += 1
        stats["calls_completed"] += 1
        stats["mastery_score"] = int((stats["mastery_score"] + score) / 2) if stats["mastery_score"] > 0 else score

        leveled_up = False
        new_level = curr

        if level_passed:
            stats["pass_count"] += 1
            req_count = LEVEL_DETAILS[curr].get("required_pass_count", 3)
            next_lvl = LEVEL_DETAILS[curr].get("next_level")

            # Check Level Up condition!
            if stats["pass_count"] >= req_count and next_lvl:
                leveled_up = True
                new_level = next_lvl
                self.profile["current_level"] = new_level
                try:
                    print(f"\n[레벨업 축하] JLPT {curr} 마스터! -> 다음 레벨 {new_level}로 승급했습니다!")
                except Exception:
                    pass

        self.profile["history"].append({
            "level": curr,
            "passed": level_passed,
            "score": score,
            "leveled_up": leveled_up,
            "summary": call_summary
        })

        self.save_profile()

        return {
            "leveled_up": leveled_up,
            "previous_level": curr,
            "current_level": self.get_current_level(),
            "pass_count": stats["pass_count"],
            "progress_percent": min(100, int((stats["pass_count"] / LEVEL_DETAILS[curr].get("required_pass_count", 3)) * 100)),
            "mastery_score": score,
        }
