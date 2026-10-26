import asyncio
import json
import os
import sys
import time
import webbrowser
from pathlib import Path

# Ensure UTF-8 output on Windows terminal
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import (
    GEMINI_API_KEY,
    GEMINI_LIVE_MODEL,
    GEMINI_VOICE_NAME,
    TOTAL_CALL_SECONDS,
    build_system_instruction,
)
from level_manager import LevelManager, LEVELS
from reporter import SessionReporter
from feedback_generator import generate_post_call_feedback
from db import get_past_conversations

app = FastAPI(title="키라키라 (Kirakira) Web Call")

# Mount static assets
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
async def get_index():
    return FileResponse(static_dir / "index.html")


@app.get("/api/profile")
async def get_user_profile():
    """Returns user level stats and progression info."""
    mgr = LevelManager()
    return mgr.get_level_info()


class SetLevelRequest(BaseModel):
    level: str


@app.post("/api/set-level")
async def set_user_level(req: SetLevelRequest):
    """Allows user to manually change target level (N4, N3, N2, N1)."""
    if req.level in LEVELS:
        mgr = LevelManager()
        mgr.set_current_level(req.level)
        return mgr.get_level_info()
    return {"error": "Invalid level"}


@app.get("/api/history")
async def get_history():
    """Returns past call history and review reports from Supabase."""
    return get_past_conversations()


@app.post("/api/open-logs")
async def open_logs_folder():
    """Opens the logs folder in Windows File Explorer."""
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    if sys.platform == "win32":
        os.startfile(str(logs_dir.resolve()))
    return {"status": "ok"}


def get_stage_info(elapsed_seconds: int) -> tuple[int, str, str]:
    if elapsed_seconds < 90:
        return 1, "일상 및 취미", "아이스브레이킹"
    elif elapsed_seconds < 180:
        return 2, "내 일과 공부", "기본 루틴 및 동사"
    elif elapsed_seconds < 300:
        return 3, "지난 경험과 에피소드", "과거 경험 이야기"
    elif elapsed_seconds < 390:
        return 4, "의견과 선택", "이유와 생각 말하기"
    else:
        return 5, "가정 상황", "가정법 시뮬레이션"


# Explicit phrases indicating user wishes to quit the call
END_CALL_KEYWORDS = [
    "그만하자", "그만할래", "그만할게", "그만할", "통화 종료", "전화 끊",
    "끊을게", "끊자", "이제 갈게", "또 봐", "バイバイ", "ばいばい",
    "切るね", "じゃあね", "またね", "おしまい", "今日はここまで"
]


@app.websocket("/ws/call")
async def websocket_call_endpoint(websocket: WebSocket):
    await websocket.accept()

    if not GEMINI_API_KEY or GEMINI_API_KEY.strip() == "":
        await websocket.send_text(
            json.dumps({
                "type": "ai_transcript",
                "text": "⚠️ .env 파일에 GEMINI_API_KEY가 설정되지 않았습니다. API 키를 입력해주세요!"
            })
        )
        await websocket.close()
        return

    from google import genai
    from google.genai import types

    # 1. Fetch current JLPT Level
    level_mgr = LevelManager()
    curr_level = level_mgr.get_current_level()
    system_prompt = build_system_instruction(curr_level)

    client = genai.Client(api_key=GEMINI_API_KEY)
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        output_audio_transcription=types.AudioTranscriptionConfig(),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=GEMINI_VOICE_NAME)
            )
        ),
        system_instruction=types.Content(
            parts=[types.Part.from_text(text=system_prompt)]
        ),
    )

    reporter = SessionReporter(target_duration_sec=TOTAL_CALL_SECONDS)
    reporter.start()
    start_time = time.time()
    call_active = True
    waiting_for_farewell = False  # Only True after user explicitly asks to end call

    print(f"\n🌐 [웹 통화 연결됨] 목표 레벨: JLPT {curr_level}")

    try:
        async with client.aio.live.connect(model=GEMINI_LIVE_MODEL, config=config) as session:
            # Send initial friendly greeting and first open question
            await session.send_client_content(
                turns=types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(
                            text=(
                                f"（通話が繋がりました。目標レベルはJLPT {curr_level}です。"
                                "親しい友達から電話がかかってきた時のように「もしもし〜！元気だった？今日何してたの？」と"
                                "明るく挨拶して短い質問を1つだけ投げかけ、相手の返事を待ってください。"
                                "絶対に自分から電話を切るような挨拶はしないでください。）"
                            )
                        )
                    ],
                ),
                turn_complete=True,
            )

            # 2. Receive Audio and Text from Browser
            async def receive_from_browser():
                nonlocal call_active, waiting_for_farewell
                while call_active:
                    try:
                        message = await websocket.receive()
                        if "bytes" in message and message["bytes"]:
                            chunk = message["bytes"]
                            # Stream PCM chunk to Gemini Live API (Google AI Studio protocol requires mediaChunks via media=)
                            await session.send_realtime_input(
                                media=types.Blob(
                                    data=chunk,
                                    mime_type="audio/pcm;rate=16000",
                                )
                            )
                        elif "text" in message and message["text"]:
                            data = json.loads(message["text"])
                            msg_type = data.get("type")
                            if msg_type == "sos":
                                await session.send_client_content(
                                    turns=types.Content(
                                        role="user",
                                        parts=[
                                            types.Part.from_text(
                                                text=(
                                                    f"（ユーザーが「どういう意味？」と困っています。"
                                                    f"直前の日本語の質問や内容の意味を、優しくわかりやすい韓国語で解説し、"
                                                    f"JLPT {curr_level}レベルの短い日本語の答え方の例を教えてあげてください！）"
                                                )
                                            )
                                        ],
                                    ),
                                    turn_complete=True,
                                )
                            elif msg_type == "end":
                                print("📱 사용자가 통화 종료 버튼을 클릭했습니다.")
                                call_active = False
                                break
                    except WebSocketDisconnect:
                        print("브라우저 웹소켓 연결이 해제되었습니다.")
                        call_active = False
                        break
                    except Exception as e:
                        if call_active:
                            await asyncio.sleep(0.01)

            # 3. Stream Gemini to Browser
            async def forward_gemini_to_browser():
                nonlocal call_active, waiting_for_farewell
                current_ai_text = ""
                current_user_text = ""

                try:
                    async for response in session.receive():
                        if not call_active:
                            break

                        sc = response.server_content
                        if sc is not None:
                            # Interruption (User spoke while AI was speaking)
                            if sc.interrupted:
                                try:
                                    await websocket.send_text(json.dumps({"type": "interrupted"}))
                                except Exception:
                                    pass

                            # User speech transcription
                            if sc.input_transcription and sc.input_transcription.text:
                                current_user_text += sc.input_transcription.text
                                try:
                                    await websocket.send_text(
                                        json.dumps({
                                            "type": "user_chunk_text",
                                            "text": current_user_text
                                        })
                                    )
                                except Exception:
                                    pass

                                if sc.input_transcription.finished:
                                    speech = current_user_text.strip()
                                    if speech:
                                        elapsed = int(time.time() - start_time)
                                        reporter.add_transcript("나(학습자)", speech, elapsed)
                                        try:
                                            await websocket.send_text(
                                                json.dumps({"type": "user_transcript", "text": speech})
                                            )
                                        except Exception:
                                            pass

                                        # Only detect verbal end after user has actually spoken in conversation
                                        if elapsed >= 20 and any(k in speech for k in END_CALL_KEYWORDS):
                                            print(f"👋 사용자 통화 종료 발화 감지: '{speech}'")
                                            waiting_for_farewell = True
                                            await session.send_client_content(
                                                turns=types.Content(
                                                    role="user",
                                                    parts=[
                                                        types.Part.from_text(
                                                            text=(
                                                                "（ユーザーが通話を終えたいと言いました。"
                                                                "今日のお礼と明るく温かいお別れの挨拶をして会話を締めくくってください。）"
                                                            )
                                                        )
                                                    ],
                                                ),
                                                turn_complete=True,
                                            )

                                    current_user_text = ""

                            # Audio Chunk to Browser
                            if sc.model_turn is not None:
                                for part in sc.model_turn.parts:
                                    if part.inline_data:
                                        await websocket.send_bytes(part.inline_data.data)

                            # AI speech transcription
                            if sc.output_transcription and sc.output_transcription.text:
                                current_ai_text += sc.output_transcription.text
                                try:
                                    await websocket.send_text(
                                        json.dumps({
                                            "type": "ai_chunk_text",
                                            "text": current_ai_text
                                        })
                                    )
                                except Exception:
                                    pass

                            # Turn Complete
                            if sc.turn_complete:
                                ai_speech = current_ai_text.strip()
                                if ai_speech:
                                    elapsed = int(time.time() - start_time)
                                    reporter.add_transcript("키라키라", ai_speech, elapsed)
                                    try:
                                        await websocket.send_text(
                                            json.dumps({"type": "ai_transcript", "text": ai_speech})
                                        )
                                    except Exception:
                                        pass
                                    current_ai_text = ""

                                    # ONLY end call if user previously expressed desire to end
                                    if waiting_for_farewell:
                                        print("🌟 키라키라가 작별 인사를 완료하여 통화를 정상 종료합니다.")
                                        await asyncio.sleep(2.5)  # Allow audio playback to complete
                                        try:
                                            await websocket.send_text(json.dumps({"type": "call_ended"}))
                                        except Exception:
                                            pass
                                        call_active = False
                                        break

                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    print(f"[Gemini 스트리밍 오류] {e}")

            # 4. Stage Progress Monitor (8-minute tracker)
            async def monitor_stages():
                nonlocal call_active
                last_stage = 0
                while call_active:
                    elapsed = int(time.time() - start_time)
                    stage_num, stage_title, level_desc = get_stage_info(elapsed)

                    if stage_num != last_stage:
                        last_stage = stage_num
                        reporter.update_stage(stage_num, stage_title, level_desc)
                        try:
                            await websocket.send_text(
                                json.dumps({
                                    "type": "stage_update",
                                    "stage": stage_num,
                                    "title": stage_title,
                                    "level": level_desc,
                                })
                            )
                        except Exception:
                            pass

                    if elapsed >= TOTAL_CALL_SECONDS:
                        print("⏰ 예정된 8분 통화 시간이 완료되었습니다.")
                        call_active = False
                        break

                    await asyncio.sleep(1)

            t_browser = asyncio.create_task(receive_from_browser())
            t_gemini = asyncio.create_task(forward_gemini_to_browser())
            t_monitor = asyncio.create_task(monitor_stages())

            # Keep session active until call_active is set to False
            while call_active:
                done, pending = await asyncio.wait(
                    [t_browser, t_gemini, t_monitor],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not call_active:
                    break

                # If any key stream ended or crashed, stop session
                if t_browser.done() or t_gemini.done():
                    print("📡 브라우저 또는 Gemini 스트림 세션이 종료되었습니다.")
                    break

                fatal_error = False
                for task in done:
                    if task.done() and not task.cancelled():
                        exc = task.exception()
                        if exc:
                            print(f"[세션 태스크 오류] {exc}")
                            fatal_error = True
                if fatal_error:
                    break

            call_active = False
            for t in [t_browser, t_gemini, t_monitor]:
                if not t.done():
                    t.cancel()

    except WebSocketDisconnect:
        print("\n브라우저 연결이 종료되었습니다.")
    except Exception as e:
        print(f"\n[세션 오류] {e}")
    finally:
        total_duration = int(time.time() - start_time)
        reporter.finalize_and_save(total_duration)

        # Generate JLPT Level assessment & Review Report
        report_path, level_result = generate_post_call_feedback(reporter.transcript_records, total_duration)
        report_md = ""
        if report_path and report_path.exists():
            with open(report_path, "r", encoding="utf-8") as f:
                report_md = f.read()

        try:
            await websocket.send_text(
                json.dumps({
                    "type": "feedback_report",
                    "markdown": report_md,
                    "level_result": level_result,
                })
            )
        except Exception:
            pass


def start_server():
    import uvicorn

    port = int(os.getenv("PORT", 8000))

    # Only auto-open browser on local Windows dev, not on cloud servers
    if sys.platform == "win32" and not os.getenv("RENDER"):
        def open_browser():
            time.sleep(1.2)
            webbrowser.open(f"http://localhost:{port}")

        import threading
        threading.Thread(target=open_browser, daemon=True).start()

    print("\n" + "=" * 65)
    print(f" 🌟 키라키라(キラキラ) 웹 화면이 열립니다! (포트: {port})")
    print(f" • 주소: http://localhost:{port}")
    print(" • 브라우저 화면에서 '통화 시작' 버튼을 누르면 통화가 시작됩니다.")
    print("=" * 65 + "\n")

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")


if __name__ == "__main__":
    start_server()
