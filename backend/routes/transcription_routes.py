"""
Transcription Routes: Handles audio uploads and initiates local faster-whisper inference.
"""

import os
import uuid
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify
from werkzeug.utils import secure_filename
from backend.services.transcription_service import TranscriptionService, MissingModelError, AUDIO_DIR

transcription_bp = Blueprint("transcription", __name__)

ALLOWED_EXTENSIONS = {"webm", "wav", "mp3", "ogg", "m4a", "flac", "aac"}
MAX_CONTENT_LENGTH = 30 * 1024 * 1024  # 30 MB max

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

@transcription_bp.route("/api/transcription/transcribe", methods=["POST"])
def transcribe_audio():
    """
    Accepts multipart FormData audio file.
    Validates, saves to secure audio retention directory, and runs offline faster-whisper.
    """
    if "audio" not in request.files and "file" not in request.files:
        return jsonify({
            "success": False,
            "error": "No audio file provided in multipart form data ('audio' or 'file' key required)."
        }), 400

    audio_file = request.files.get("audio") or request.files.get("file")

    if not audio_file or not audio_file.filename:
        return jsonify({
            "success": False,
            "error": "Uploaded file has an empty filename."
        }), 400

    # Check extension
    orig_name = secure_filename(audio_file.filename)
    ext = orig_name.rsplit(".", 1)[1].lower() if "." in orig_name else "webm"
    if ext not in ALLOWED_EXTENSIONS:
        # If recorded from browser MediaRecorder, it might be audio/webm;codecs=opus without extension
        ext = "webm"

    # Generate secure retention filename
    unique_id = uuid.uuid4().hex
    saved_filename = f"rec_{unique_id}.{ext}"
    saved_filepath = os.path.join(AUDIO_DIR, saved_filename)

    try:
        # Save file to disk
        audio_file.save(saved_filepath)
        file_size = os.path.getsize(saved_filepath)

        if file_size == 0:
            if os.path.exists(saved_filepath):
                os.remove(saved_filepath)
            return jsonify({
                "success": False,
                "error": "Uploaded audio file is empty (0 bytes)."
            }), 400

        if file_size > MAX_CONTENT_LENGTH:
            if os.path.exists(saved_filepath):
                os.remove(saved_filepath)
            return jsonify({
                "success": False,
                "error": f"Audio file exceeds maximum allowed size of 30MB (received {file_size} bytes)."
            }), 413

        # Language selection (default: en)
        requested_lang = request.form.get("language") or request.args.get("language") or "en"
        requested_lang = requested_lang.lower().strip()

        # Transcribe locally
        service = TranscriptionService.get_instance()
        transcription_result = service.transcribe_audio_file(
            audio_filepath=saved_filepath,
            language=requested_lang
        )

        return jsonify({
            "success": True,
            "data": {
                "transcript": transcription_result["transcript"],
                "language": transcription_result["language"],
                "source_language": transcription_result.get("source_language", requested_lang),
                "detected_language": transcription_result.get("detected_language", transcription_result["language"]),
                "language_probability": transcription_result["language_probability"],
                "duration_seconds": transcription_result["duration"],
                "inference_duration": transcription_result["inference_duration"],
                "segments": transcription_result["segments"],
                "words": transcription_result.get("words", []),
                "word_count": len(transcription_result.get("words", [])),
                "speech_confidence_summary": transcription_result.get("speech_confidence_summary", {}),
                "audio_filename": saved_filename,
                "mimetype": audio_file.mimetype or f"audio/{ext}",
                "model_used": transcription_result["model_used"],
                "device": transcription_result["device"],
                "transcribed_at": datetime.now(timezone.utc).isoformat()
            }
        }), 200

    except MissingModelError as mm_err:
        return jsonify({
            "success": False,
            "error": "MODEL_MISSING",
            "message": mm_err.message,
            "language_requested": mm_err.language,
            "english_fallback_available": True
        }), 400
    except ValueError as val_err:
        return jsonify({
            "success": False,
            "error": f"Audio format or validation error: {str(val_err)}"
        }), 422
    except RuntimeError as r_err:
        return jsonify({
            "success": False,
            "error": str(r_err)
        }), 503
    except Exception as e:
        return jsonify({
            "success": False,
            "error": f"Internal transcription error: {str(e)}"
        }), 500

@transcription_bp.route("/api/transcription/languages", methods=["GET"])
def get_supported_languages():
    """
    Return available speech recognition models and language availability status.
    Clearly marks missing models without pretending unavailable languages are supported.
    """
    service = TranscriptionService.get_instance()
    return jsonify({
        "success": True,
        "data": service.get_available_languages()
    }), 200
