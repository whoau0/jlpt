import datetime
import json
import os
import sys
from pathlib import Path

# Ensure UTF-8 output on Windows terminal
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


class SessionReporter:
    """
    Manages terminal live monitoring UI and conversation transcript logging (.txt and .json).
    """

    def __init__(self, target_duration_sec: int = 480):
        self.target_duration_sec = target_duration_sec
        self.start_time = None
        self.end_time = None
        self.logs_dir = Path("logs")
        self.logs_dir.mkdir(exist_ok=True)
        self.transcript_records: list[dict] = []
        self.current_stage_idx = 1
        self.current_stage_title = "일상 및 취미 (日常・趣味)"
        self.current_level = "JLPT N5"
        self.is_ai_speaking = False

    def start(self):
        self.start_time = datetime.datetime.now()

    def update_stage(self, stage_idx: int, title: str, level: str):
        self.current_stage_idx = stage_idx
        self.current_stage_title = title
        self.current_level = level

    def set_ai_speaking(self, speaking: bool):
        self.is_ai_speaking = speaking

    def add_transcript(self, speaker: str, text: str, elapsed_sec: int):
        time_tag = f"{elapsed_sec // 60:02d}:{elapsed_sec % 60:02d}"
        record = {
            "index": len(self.transcript_records) + 1,
            "timestamp": time_tag,
            "elapsed_seconds": elapsed_sec,
            "stage": self.current_stage_idx,
            "stage_name": self.current_stage_title,
            "speaker": speaker,
            "text": text.strip(),
        }
        self.transcript_records.append(record)

    def print_stage_banner(self, stage_idx: int, title: str, level_desc: str):
        print("\n" + "─" * 65)
        print(f" 🚩 [단계 전환] Step {stage_idx}/5 : {title}")
        print(f"    ▶ 목표 수준: {level_desc}")
        print("─" * 65 + "\n")

    def render_progress_status(self, elapsed_sec: int):
        """Prints a single-line dynamic progress bar in the terminal."""
        total = self.target_duration_sec
        elapsed_clamped = min(elapsed_sec, total)
        percent = int((elapsed_clamped / total) * 100)

        # Bar representation (20 chars)
        bar_len = 20
        filled = int((percent / 100) * bar_len)
        bar_str = "█" * filled + "░" * (bar_len - filled)

        el_min, el_sec = elapsed_sec // 60, elapsed_sec % 60
        tot_min, tot_sec = total // 60, total % 60

        state_icon = "🔊 키라키라 발화 중" if self.is_ai_speaking else "🎤 경청 중 (듣는 중)"

        status_line = (
            f"\r⏱️  [{el_min:02d}:{el_sec:02d}/{tot_min:02d}:{tot_sec:02d}] "
            f"[{bar_str}] {percent:3d}% | "
            f"Step {self.current_stage_idx}/5 | "
            f"{state_icon} "
        )
        sys.stdout.write(status_line)
        sys.stdout.flush()

    def finalize_and_save(self, total_seconds: int) -> tuple[Path, Path]:
        """Saves conversation transcript in both .txt and .json formats."""
        self.end_time = datetime.datetime.now()
        timestamp_str = (self.start_time or self.end_time).strftime("%Y%m%d_%H%M%S")

        txt_path = self.logs_dir / f"conversation_{timestamp_str}.txt"
        json_path = self.logs_dir / f"conversation_{timestamp_str}.json"

        minutes = total_seconds // 60
        seconds = total_seconds % 60

        # 1. Save TXT File (human-friendly review format)
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("=" * 65 + "\n")
            f.write("  🌟 키라키라(キラキラ) 일본어 프리토킹 세션 대화록\n")
            f.write("=" * 65 + "\n")
            f.write(f"• 시작 일시 : {self.start_time.strftime('%Y-%m-%d %H:%M:%S') if self.start_time else 'N/A'}\n")
            f.write(f"• 종료 일시 : {self.end_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"• 통화 시간 : {minutes}분 {seconds}초 (목표: 8분)\n")
            f.write(f"• 목표 등급 : JLPT N4\n")
            f.write(f"• 총 발화수 : {len(self.transcript_records)}회\n")
            f.write("=" * 65 + "\n\n")

            current_stage_in_log = 0
            for record in self.transcript_records:
                stage = record.get("stage", 1)
                stage_name = record.get("stage_name", "")
                if stage != current_stage_in_log:
                    current_stage_in_log = stage
                    f.write(f"\n--- [Step {stage}: {stage_name}] ---\n")

                t_str = record.get("timestamp", "00:00")
                spk = record.get("speaker", "키라키라")
                content = record.get("text", "")
                f.write(f"[{t_str}] {spk}: {content}\n")

            f.write("\n" + "=" * 65 + "\n")
            f.write("  대화가 종료되었습니다. 복습에 유용하게 활용하세요!\n")
            f.write("=" * 65 + "\n")

        # 2. Save JSON File (structured data for future expansion / analytics)
        json_data = {
            "session_id": timestamp_str,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat(),
            "duration_seconds": total_seconds,
            "duration_formatted": f"{minutes:02d}:{seconds:02d}",
            "target_level": "JLPT N4",
            "total_records": len(self.transcript_records),
            "transcript": self.transcript_records,
        }

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)

        # Print final summary to terminal
        print("\n\n" + "=" * 65)
        print("  🎉 [통화 완료] 세션이 성공적으로 기록되었습니다!")
        print(f"  • 총 통화 시간 : {minutes}분 {seconds}초")
        print(f"  • 대화 발화 수 : {len(self.transcript_records)}개")
        print(f"  • 텍스트 로그  : {txt_path.resolve()}")
        print(f"  • JSON 데이터  : {json_path.resolve()}")
        print("=" * 65 + "\n")

        return txt_path, json_path
