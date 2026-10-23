import datetime
import json
import os
import re
import sys
from pathlib import Path

from config import GEMINI_API_KEY
from level_manager import LevelManager


FEEDBACK_PROMPT_TEMPLATE = """
당신은 일본어 교육 전문가이자, 학생의 다정한 일본인 친구 '키라키라'입니다.
방금 학생과 나눈 실시간 음성 통화 녹취록을 바탕으로, **[JLPT {level} 맞춤형 복습 피드백 및 레벨 평가 리포트]**를 작성해주세요.

【학생 프로필】
- 현재 목표 레벨: JLPT {level}
- 평가 기준: JLPT {level} 수준의 어휘/문형 이해도 및 적극적인 발화 시도.

【통화 대화록 전문】
{transcript_text}

【출력 형식 요구사항】
반드시 아래와 같이 마크다운 리포트를 작성하고, **맨 마지막에 JSON 평가 블록**을 포함해주세요.

# 🌸 키라키라의 통화 복습 리포트 (JLPT {level})

## 1. 💌 키라키라의 한마디 응원
- 오늘 통화에서 좋았던 점, 적극적으로 말하려 했던 태도를 따뜻하게 칭찬해주세요. (한국어로 작성, 간단한 일본어 응원 문장 포함)

## 2. 💡 더 자연스러운 표현 제안 (Before & After)
- 통화 중 학생이 말했던 문장 중 2~3가지를 선정하여 {level} 수준의 자연스러운 원어민 표현으로 업그레이드해주세요.
- 각 표현마다:
  * ❌ 원래 표현: (학생 발화)
  * ✅ 추천 표현: ({level} 수준의 자연스러운 일본어 / 한자에는 후리가나 표기)
  * 📌 팁: 왜 이렇게 쓰면 더 자연스러운지 쉬운 한국어 설명

## 3. 📚 오늘 대화의 핵심 단어 & {level} 문형
- 오늘 통화에서 나온 유용한 단어 3~5개 (한자/후리가나/한국어 뜻)
- 오늘 대화에 쓰였거나 유도된 핵심 {level} 문법 1~2개 정리

## 4. 🎯 다음 통화 원포인트 미션!
- 다음번 통화에서 꼭 써먹어 볼 만한 {level} 핵심 문장 1개 추천

```json
{{
  "score": 75,
  "passed_level_check": true,
  "evaluation_summary": "기본 질문을 잘 이해하고 적극적으로 대답함"
}}
```
(참고: score는 0~100점 사이, 70점 이상이면 passed_level_check: true로 설정)
"""


def generate_post_call_feedback(transcript_records: list[dict], duration_seconds: int) -> tuple[Path | None, dict]:
    """
    Generates personalized review report, assesses JLPT level mastery, and handles level up!
    Returns (report_path, level_result).
    """
    level_mgr = LevelManager()
    curr_level = level_mgr.get_current_level()

    default_result = {
        "leveled_up": False,
        "current_level": curr_level,
        "progress_percent": level_mgr.get_level_info()["progress_percent"],
        "mastery_score": 0,
    }

    if not transcript_records or len(transcript_records) < 2:
        return None, default_result

    try:
        from google import genai
        client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"[안내] GenAI 클라이언트 초기화 실패: {e}", file=sys.stderr)
        return None, default_result

    # Format transcript
    formatted_lines = []
    for r in transcript_records:
        t = r.get("timestamp", "00:00")
        spk = r.get("speaker", "대화자")
        txt = r.get("text", "")
        formatted_lines.append(f"[{t}] {spk}: {txt}")

    transcript_text = "\n".join(formatted_lines)
    prompt = FEEDBACK_PROMPT_TEMPLATE.format(level=curr_level, transcript_text=transcript_text)

    print(f"\n📊 [피드백 & {curr_level} 평가 생성 중] 키라키라가 레벨 성취도를 분석하고 있습니다...")

    candidate_models = ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-flash-latest"]
    response = None

    for model_name in candidate_models:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            if response and response.text:
                break
        except Exception:
            continue

    if not response or not response.text:
        return None, default_result

    raw_text = response.text

    # Extract JSON evaluation block
    score = 70
    passed = True
    summary = "통화 완료"

    json_match = re.search(r"```json\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
    if json_match:
        try:
            eval_data = json.loads(json_match.group(1))
            score = int(eval_data.get("score", 70))
            passed = bool(eval_data.get("passed_level_check", score >= 70))
            summary = eval_data.get("evaluation_summary", "")
            # Remove json block from markdown body for clean display
            clean_md = raw_text[:json_match.start()].strip()
        except Exception:
            clean_md = raw_text
    else:
        clean_md = raw_text

    # Record result & check Level Up!
    level_result = level_mgr.record_call_result(passed, score, summary)

    # If leveled up, append celebratory banner to Markdown
    if level_result.get("leveled_up"):
        new_lvl = level_result["current_level"]
        banner = f"\n\n---\n## 🎊 축하합니다! JLPT {new_lvl}로 레벨업 하셨습니다!\n" \
                 f"JLPT {curr_level} 대화 기준을 훌륭히 마스터하셨습니다. 다음 통화부터는 **JLPT {new_lvl}** 맞춤 대화로 진행됩니다! ✨\n"
        clean_md += banner

    try:
        logs_dir = Path("logs")
        logs_dir.mkdir(exist_ok=True)
        now = datetime.datetime.now()
        report_path = logs_dir / f"feedback_{now.strftime('%Y%m%d_%H%M%S')}.md"

        with open(report_path, "w", encoding="utf-8") as f:
            f.write(clean_md)

        print(f"✨ [복습 리포트 저장 완료] {report_path.resolve()}\n")
        return report_path, level_result
    except Exception as e:
        print(f"[안내] 리포트 파일 저장 오류: {e}", file=sys.stderr)
        return None, default_result
