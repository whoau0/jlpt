import asyncio
import os
import sys
import time

# Ensure UTF-8 output on Windows terminal
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from config import (
    GEMINI_API_KEY,
    GEMINI_LIVE_MODEL,
    GEMINI_VOICE_NAME,
    SYSTEM_INSTRUCTION,
    TOTAL_CALL_SECONDS,
)
from audio_stream import AudioManager
from reporter import SessionReporter
from feedback_generator import generate_post_call_feedback


def get_current_stage_info(elapsed_seconds: int) -> tuple[int, str, str]:
    """Returns (stage_number, stage_title, level_description) based on elapsed time."""
    if elapsed_seconds < 90:
        return 1, "일상 및 취미 (日常・趣味)", "N5 기초 수준 (아이스브레이킹)"
    elif elapsed_seconds < 180:
        return 2, "내 일과 공부 (仕事・勉強)", "N4 기본 동사/형용사 및 루틴"
    elif elapsed_seconds < 300:
        return 3, "지난 경험과 에피소드 (過去の経験)", "N4 과거형 및 경험 묘사"
    elif elapsed_seconds < 390:
        return 4, "의견과 선택 (意見・考え)", "N4~N3 이유와 생각 표현 (~から, ~と思う)"
    else:
        return 5, "가정 상황 (仮定の状況)", "N4~N3 가정법 (~たら, もし~)"


async def run_kirakira_session():
    # 1. Check API Key
    if not GEMINI_API_KEY or GEMINI_API_KEY.strip() == "":
        print("\n" + "!" * 65)
        print(" [안내] GEMINI_API_KEY가 설정되지 않았습니다.")
        print(" 1) .env 파일을 열어 GEMINI_API_KEY= 뒤에 발급받으신 키를 입력해주세요.")
        print(" 2) 무료 키 발급: https://aistudio.google.com/")
        print("!" * 65 + "\n")
        sys.exit(1)

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        print("[오류] google-genai 라이브러리가 설치되지 않았습니다. pip install -r requirements.txt 를 먼저 실행해주세요.")
        sys.exit(1)

    reporter = SessionReporter(target_duration_sec=TOTAL_CALL_SECONDS)

    print("\n" + "=" * 65)
    print(" 🌟 키라키라(キラキラ) AI 일본어 실시간 전화 통화 시스템")
    print(" ─────────────────────────────────────────────────────────────")
    print(f" • 사용 모델 : {GEMINI_LIVE_MODEL}")
    print(" • 학습 목표 : JLPT N4 실전 프리토킹 (총 8분)")
    print(" • 대화 규칙 : 중간에 문법을 지적하지 않고 친구처럼 편하게 대화합니다.")
    print(" • 한국어 SOS: 언제든 한국어로 말하면 키라키라가 친절히 설명해줘요!")
    print(" • 통화 종료 : 8분이 지나거나 Ctrl+C를 누르면 자동 종료 및 기록 저장")
    print(" • 권장 환경 : 마이크 하울링 방지를 위해 이어폰/헤드셋 착용")
    print("=" * 65 + "\n")

    audio_manager = AudioManager()
    audio_manager.start_streams()

    client = genai.Client(api_key=GEMINI_API_KEY)

    # Configure Live API with Real-time Dual Transcription
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        output_audio_transcription=types.AudioTranscriptionConfig(),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=GEMINI_VOICE_NAME
                )
            )
        ),
        system_instruction=types.Content(
            parts=[types.Part.from_text(text=SYSTEM_INSTRUCTION)]
        ),
    )

    start_time = time.time()
    call_active = True

    print("📞 [전화 연결 중] 키라키라와 통화 세션을 연결하고 있습니다...")

    try:
        async with client.aio.live.connect(model=GEMINI_LIVE_MODEL, config=config) as session:
            reporter.start()
            print("\n✨ [통화 연결 성공!] 키라키라와 통화가 시작되었습니다.\n")

            # First greeting trigger
            await session.send_client_content(
                turns=types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(
                            text="（通話が繋がりました。明るく元気な日本語で、久しぶりに友達から電話がかかってきたような親しい挨拶をしてください！）"
                        )
                    ],
                ),
                turn_complete=True,
            )

            # Audio Player task
            player_task = asyncio.create_task(audio_manager.play_audio_loop())

            async def send_mic_audio():
                """Continuously streams microphone chunks to Gemini."""
                while call_active:
                    chunk = await audio_manager.read_microphone_chunk()
                    if chunk:
                        try:
                            await session.send_realtime_input(
                                media=types.Blob(
                                    data=chunk,
                                    mime_type="audio/pcm;rate=16000",
                                )
                            )
                        except Exception:
                            break
                    await asyncio.sleep(0.005)

            async def receive_gemini_responses():
                """Receives audio and text transcripts from Gemini."""
                nonlocal call_active
                current_ai_text = ""
                current_user_text = ""

                try:
                    async for response in session.receive():
                        sc = response.server_content
                        if sc is not None:
                            # 1. Interruption handling (User started speaking)
                            if sc.interrupted:
                                audio_manager.clear_playback_queue()
                                reporter.set_ai_speaking(False)

                            # 2. User speech transcription (Recognized from mic)
                            if sc.input_transcription and sc.input_transcription.text:
                                current_user_text += sc.input_transcription.text
                                if sc.input_transcription.finished:
                                    elapsed = int(time.time() - start_time)
                                    time_tag = f"{elapsed // 60:02d}:{elapsed % 60:02d}"
                                    user_speech = current_user_text.strip()
                                    if user_speech:
                                        reporter.add_transcript("나(학습자)", user_speech, elapsed)
                                        sys.stdout.write("\r" + " " * 75 + "\r")
                                        print(f"[{time_tag}] 👤 나: {user_speech}")
                                    current_user_text = ""

                            # 3. Model turn (Audio playback)
                            if sc.model_turn is not None:
                                reporter.set_ai_speaking(True)
                                for part in sc.model_turn.parts:
                                    if part.inline_data:
                                        audio_manager.queue_audio_for_playback(part.inline_data.data)

                            # 4. Model speech transcription
                            if sc.output_transcription and sc.output_transcription.text:
                                current_ai_text += sc.output_transcription.text

                            # 5. Model turn complete
                            if sc.turn_complete:
                                reporter.set_ai_speaking(False)
                                ai_speech = current_ai_text.strip()
                                if ai_speech:
                                    elapsed = int(time.time() - start_time)
                                    time_tag = f"{elapsed // 60:02d}:{elapsed % 60:02d}"
                                    reporter.add_transcript("키라키라", ai_speech, elapsed)

                                    sys.stdout.write("\r" + " " * 75 + "\r")
                                    print(f"[{time_tag}] 🌟 키라키라: {ai_speech}")
                                    current_ai_text = ""

                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    sys.stdout.write("\r" + " " * 75 + "\r")
                    print(f"\n[수신 안내] {e}")

            async def monitor_call_progress():
                """Monitors the 8-minute duration, stage transitions, and renders live UI."""
                nonlocal call_active
                last_stage = 0

                while call_active:
                    elapsed = int(time.time() - start_time)
                    stage_num, stage_title, level_desc = get_current_stage_info(elapsed)

                    if stage_num != last_stage:
                        last_stage = stage_num
                        reporter.update_stage(stage_num, stage_title, level_desc)
                        sys.stdout.write("\r" + " " * 75 + "\r")
                        reporter.print_stage_banner(stage_num, stage_title, level_desc)

                    if elapsed >= TOTAL_CALL_SECONDS:
                        sys.stdout.write("\r" + " " * 75 + "\r")
                        print("\n⏰ [8분 도달] 예정된 8분 통화 시간이 완료되었습니다.")
                        call_active = False
                        break

                    reporter.render_progress_status(elapsed)
                    await asyncio.sleep(0.5)

            # Gather all concurrent tasks
            mic_task = asyncio.create_task(send_mic_audio())
            recv_task = asyncio.create_task(receive_gemini_responses())
            monitor_task = asyncio.create_task(monitor_call_progress())

            done, pending = await asyncio.wait(
                [monitor_task, recv_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            call_active = False
            for task in [mic_task, recv_task, monitor_task, player_task]:
                task.cancel()

    except KeyboardInterrupt:
        sys.stdout.write("\r" + " " * 75 + "\r")
        print("\n\n👋 사용자가 통화를 종료했습니다.")
    except Exception as e:
        sys.stdout.write("\r" + " " * 75 + "\r")
        print(f"\n❌ [오류 발생] 세션 실행 중 문제가 발생했습니다: {e}")
    finally:
        total_duration = int(time.time() - start_time)
        audio_manager.close()
        reporter.finalize_and_save(total_duration)
        # Generate JLPT N4 review feedback report
        generate_post_call_feedback(reporter.transcript_records, total_duration)


def main():
    try:
        asyncio.run(run_kirakira_session())
    except KeyboardInterrupt:
        print("\n프로그램이 종료되었습니다.")


if __name__ == "__main__":
    main()
