"""
Transcription Service using faster-whisper.
Runs local, offline speech-to-text inference with medical prompt priming and audio validation.
"""

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import io
import time
import logging
import threading
from pathlib import Path
import numpy as np

logger = logging.getLogger("field_to_record.transcription")
logging.basicConfig(level=logging.INFO)

# Configurable defaults
DEFAULT_MODEL_NAME = os.environ.get("WHISPER_MODEL_NAME", "base")
DEFAULT_DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")
DEFAULT_COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")
MODELS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "models"))
AUDIO_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "audio"))

# Medical Domain Prompt for Whisper acoustic and linguistic priming
# Does NOT hardcode specific phrases; provides vocabulary priors for first responder terms.
CLINICAL_INITIAL_PROMPT = (
    "Emergency medical responder clinical field documentation. "
    "Patient vitals, blood pressure, pulse, heart rate, SpO2, respiratory rate, GCS, glucose. "
    "Medicines and dosages: paracetamol, ibuprofen, aspirin, morphine, naloxone, salbutamol, "
    "nitroglycerin, epinephrine, fentanyl, ondansetron, midazolam, oxygen. "
    "Routes: IV, IM, oral, sublingual, nebulized, mg, mcg, ml, bpm. "
    "Symptoms: chest pain, shortness of breath, trauma, laceration, denies pain."
)

class ModelStatus:
    UNINITIALIZED = "UNINITIALIZED"
    LOADING = "LOADING"
    READY = "READY"
    MISSING = "MISSING"
    ERROR = "ERROR"

class MissingModelError(RuntimeError):
    def __init__(self, language, message):
        super().__init__(message)
        self.language = language
        self.message = message

SUPPORTED_LANGUAGES = {
    "en": {"code": "en", "name": "English", "native_name": "English"},
    "ta": {"code": "ta", "name": "Tamil", "native_name": "தமிழ்"},
    "hi": {"code": "hi", "name": "Hindi", "native_name": "हिन्दी"}
}

class TranscriptionService:
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self.model = None
        self.status = ModelStatus.UNINITIALIZED
        self.status_message = "Model not yet loaded."
        self.model_name = DEFAULT_MODEL_NAME
        self.device = DEFAULT_DEVICE
        self.compute_type = DEFAULT_COMPUTE_TYPE
        self.download_progress = 0
        os.makedirs(MODELS_DIR, exist_ok=True)
        os.makedirs(AUDIO_DIR, exist_ok=True)

    @classmethod
    def get_instance(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def load_model(self, model_name=None, device=None, compute_type=None):
        """Load or reload the faster-whisper model."""
        from faster_whisper import WhisperModel

        if model_name:
            self.model_name = model_name
        if device:
            self.device = device
        if compute_type:
            self.compute_type = compute_type

        self.status = ModelStatus.LOADING
        self.status_message = f"Loading faster-whisper model '{self.model_name}' on {self.device} ({self.compute_type})..."
        logger.info(self.status_message)

        try:
            # download_root points to local models dir to ensure offline persistence
            self.model = WhisperModel(
                self.model_name,
                device=self.device,
                compute_type=self.compute_type,
                download_root=MODELS_DIR,
                cpu_threads=4
            )
            self.status = ModelStatus.READY
            self.status_message = f"Model '{self.model_name}' ready on {self.device}."
            logger.info(self.status_message)
            return True, self.status_message
        except Exception as e:
            self.status = ModelStatus.ERROR
            self.status_message = f"Failed to load Whisper model '{self.model_name}': {str(e)}"
            logger.error(self.status_message, exc_info=True)
            return False, self.status_message

    def check_language_support(self, language="en"):
        """
        Verify whether the requested language model is installed locally.
        Ensures we never claim Tamil or Hindi speech recognition is available
        until the appropriate local model is installed and tested.
        English remains functional even if regional models are missing.
        """
        lang = (language or "en").lower().strip()
        lang_info = SUPPORTED_LANGUAGES.get(lang, {"code": lang, "name": lang, "native_name": lang})

        if lang in ("en", "english"):
            has_whisper = os.path.exists(os.path.join(MODELS_DIR, "models--Systran--faster-whisper-base")) or self.model is not None
            return {
                "language": "en",
                "name": "English",
                "available": has_whisper,
                "status": "READY" if has_whisper else "MODEL_MISSING",
                "message": "English speech recognition model is ready." if has_whisper else "English model not downloaded."
            }

        # Check regional language models in MODELS_DIR (Vosk or dedicated Whisper weights)
        model_candidates = []
        if os.path.exists(MODELS_DIR):
            for entry in os.listdir(MODELS_DIR):
                entry_lower = entry.lower()
                # Skip the default English base model when searching for dedicated regional models
                if "faster-whisper-base" in entry_lower:
                    continue
                if (lang == "ta" and ("tamil" in entry_lower or "vosk-model-ta" in entry_lower or "-ta" in entry_lower or "_ta" in entry_lower)) or \
                   (lang == "hi" and ("hindi" in entry_lower or "vosk-model-hi" in entry_lower or "-hi" in entry_lower or "_hi" in entry_lower)):
                    model_candidates.append(entry)

        if model_candidates:
            return {
                "language": lang,
                "name": lang_info["name"],
                "available": True,
                "status": "READY",
                "model_path": os.path.join(MODELS_DIR, model_candidates[0]),
                "message": f"Speech model for {lang_info['name']} found: {model_candidates[0]}."
            }

        return {
            "language": lang,
            "name": lang_info["name"],
            "native_name": lang_info.get("native_name", ""),
            "available": False,
            "status": "MODEL_MISSING",
            "message": (
                f"Local speech recognition model for {lang_info['name']} ({lang_info.get('native_name', '')}) "
                f"is not installed in models/. English speech recognition remains active. "
                f"Please install the regional model in models/ to enable {lang_info['name']} speech transcription."
            )
        }

    def get_available_languages(self):
        """Return support and installation diagnostics for all configured languages."""
        return [self.check_language_support(code) for code in ("en", "ta", "hi")]

    def get_status(self):
        """Return diagnostic status information about the speech engine."""
        return {
            "status": self.status,
            "message": self.status_message,
            "model_name": self.model_name,
            "device": self.device,
            "compute_type": self.compute_type,
            "models_directory": MODELS_DIR,
            "is_ready": self.status == ModelStatus.READY,
            "offline_capable": True,
            "supported_languages": self.get_available_languages()
        }

    def convert_and_verify_audio(self, input_filepath):
        """
        Verify that audio is valid, non-empty, and extract duration and sample info using PyAV.
        Returns: (is_valid, duration_seconds, sample_rate, error_msg)
        """
        import av
        try:
            container = av.open(input_filepath)
            audio_streams = [s for s in container.streams if s.type == 'audio']
            if not audio_streams:
                return False, 0.0, 0, "No audio stream found in file."

            stream = audio_streams[0]
            # Duration in seconds
            duration = float(stream.duration * stream.time_base) if stream.duration and stream.time_base else 0.0
            sample_rate = stream.rate or 16000

            # If duration is 0, estimate from frames
            if duration <= 0.0:
                frame_count = 0
                sample_count = 0
                for frame in container.decode(stream):
                    sample_count += frame.samples
                    frame_count += 1
                if sample_count > 0 and sample_rate > 0:
                    duration = sample_count / sample_rate

            if duration < 0.2:
                return False, duration, sample_rate, "Audio recording is too short or empty (<0.2 seconds)."

            return True, duration, sample_rate, None
        except Exception as e:
            return False, 0.0, 0, f"Corrupted or unsupported audio file: {str(e)}"

    def transcribe_audio_file(self, audio_filepath, language="en", vad_filter=True, initial_prompt=None):
        """
        Transcribe an audio file using faster-whisper.
        Applies clinical domain prompting and strict deterministic decoding.
        Verifies local model presence for requested language before execution.
        """
        lang = (language or "en").lower().strip()
        lang_check = self.check_language_support(lang)
        if not lang_check["available"]:
            raise MissingModelError(
                language=lang,
                message=lang_check["message"]
            )

        if self.status != ModelStatus.READY or self.model is None:
            # Try to auto-load if uninitialized
            success, msg = self.load_model()
            if not success:
                raise RuntimeError(f"Transcription engine unavailable: {msg}")

        # Verify audio validity
        valid, duration, sample_rate, err = self.convert_and_verify_audio(audio_filepath)
        if not valid:
            raise ValueError(f"Audio validation failed: {err}")

        prompt = initial_prompt if initial_prompt is not None else CLINICAL_INITIAL_PROMPT

        start_time = time.time()

        # Run faster-whisper inference with word_timestamps enabled
        # temperature=0.0 prevents hallucination
        # beam_size=5 ensures high quality search
        # condition_on_previous_text=False prevents cascading errors on short notes
        segments_generator, info = self.model.transcribe(
            audio_filepath,
            language=language,
            task="transcribe",
            beam_size=5,
            best_of=5,
            temperature=0.0,
            condition_on_previous_text=False,
            initial_prompt=prompt,
            vad_filter=vad_filter,
            vad_parameters=dict(min_silence_duration_ms=400),
            word_timestamps=True
        )

        from backend.services.medicine_service import MedicineService

        segments = []
        transcript_parts = []
        all_words = []

        for seg in segments_generator:
            text = seg.text.strip()
            if text:
                transcript_parts.append(text)
                seg_words = []
                stop_words = {"patient", "has", "had", "and", "the", "with", "from", "over", "into", "after", "before", "gives", "given", "about"}
                for w in (getattr(seg, "words", None) or []):
                    clean_token = w.word.strip().strip(".,;:?!")
                    prob = round(float(w.probability), 3) if w.probability is not None else None
                    start_sec = round(float(w.start), 2) if w.start is not None else None
                    end_sec = round(float(w.end), 2) if w.end is not None else None

                    # Technically defensible uncertainty category
                    if prob is None:
                        conf_cat = "NOT_AVAILABLE"
                        conf_label = "Not available"
                    elif prob >= 0.80:
                        conf_cat = "HIGH"
                        conf_label = "High confidence"
                    elif prob >= 0.50:
                        conf_cat = "UNCERTAIN"
                        conf_label = "Uncertain"
                    else:
                        conf_cat = "LOW"
                        conf_label = "Low confidence"

                    # Medical term verification against catalogue
                    is_med = False
                    med_cat = None
                    med_status = None
                    med_canonical = None
                    candidates = []
                    req_verification = False
                    term_explanation = None

                    if clean_token and len(clean_token) > 2 and clean_token.lower() not in stop_words:
                        med_match = MedicineService.match_medicine(clean_token)
                        if med_match.get("status") in ("EXACT", "ALIAS"):
                            is_med = True
                            med_cat = "Medication"
                            med_status = med_match["status"]
                            med_canonical = med_match.get("matched_canonical")
                            term_explanation = f"Verified catalogue match: {med_canonical}"
                        elif med_match.get("status") == "AMBIGUOUS" and med_match.get("confidence_score", 0) >= 70:
                            is_med = True
                            med_cat = "Medication"
                            med_status = "AMBIGUOUS"
                            candidates = med_match.get("candidates", [])
                            req_verification = True
                            term_explanation = f"Ambiguous drug term. Human verification required among {len(candidates)} candidates."
                        elif clean_token.lower() in ("bp", "pulse", "spo2", "gcs", "glucose", "temp", "mmhg", "bpm", "mg", "mcg", "ml", "g", "iv", "im", "io", "in", "sc", "sq", "pr", "po", "sl", "oral", "orally", "sublingual", "sublingually", "nebulized", "inhaled", "chewable"):
                            is_med = True
                            med_cat = "Measurement / Vital"
                            med_status = "MEASUREMENT"
                            term_explanation = "Clinical unit or vital sign parameter"
                        elif clean_token.lower() in ("fever", "pain", "dyspnea", "wheezing", "chest", "cough", "trauma", "chills", "nausea"):
                            is_med = True
                            med_cat = "Symptom"
                            med_status = "SYMPTOM"
                            term_explanation = "Clinical symptom observation"

                    word_obj = {
                        "word": w.word,
                        "clean_text": clean_token,
                        "start": start_sec,
                        "end": end_sec,
                        "probability": prob,
                        "confidence_category": conf_cat,
                        "confidence_label": conf_label,
                        "is_medical_term": is_med,
                        "medical_category": med_cat,
                        "medical_status": med_status,
                        "canonical_name": med_canonical,
                        "candidates": candidates,
                        "requires_verification": req_verification or (is_med and conf_cat in ("UNCERTAIN", "LOW")),
                        "term_explanation": term_explanation,
                        "medical_match": {
                            "status": "EXACT_MATCH" if med_status == "EXACT" else "ALIAS_MATCH" if med_status == "ALIAS" else "AMBIGUOUS" if med_status == "AMBIGUOUS" else med_status or "NONE",
                            "matched_entity": med_canonical or (clean_token if is_med else None),
                            "requires_confirmation": req_verification or (is_med and conf_cat in ("UNCERTAIN", "LOW"))
                        }
                    }
                    seg_words.append(word_obj)
                    all_words.append(word_obj)

                segments.append({
                    "id": seg.id,
                    "start": round(seg.start, 2),
                    "end": round(seg.end, 2),
                    "text": text,
                    "avg_logprob": round(seg.avg_logprob, 3),
                    "no_speech_prob": round(seg.no_speech_prob, 3),
                    "words": seg_words
                })

        full_transcript = " ".join(transcript_parts).strip()
        elapsed = time.time() - start_time

        # If audio duration was unknown or zero from container header, use last segment end
        if duration <= 0.0 and segments:
            duration = segments[-1]["end"]

        return {
            "transcript": full_transcript,
            "language": info.language,
            "source_language": lang,
            "detected_language": info.language,
            "language_probability": round(info.language_probability, 3) if hasattr(info, "language_probability") else 1.0,
            "duration": round(duration, 2),
            "inference_duration": round(elapsed, 2),
            "segments": segments,
            "words": all_words,
            "confidence_metadata": {
                "calculation_method": "faster-whisper acoustic token softmax probability over vocabulary during beam search decoding",
                "meaning": "Reflects speech recognition acoustic certainty of the recognized token. Does NOT indicate clinical correctness or pharmacological appropriateness.",
                "word_count": len(all_words),
                "high_confidence_words": sum(1 for w in all_words if w.get("confidence_category") == "HIGH"),
                "uncertain_words": sum(1 for w in all_words if w.get("confidence_category") == "UNCERTAIN"),
                "low_confidence_words": sum(1 for w in all_words if w.get("confidence_category") == "LOW"),
                "medical_terms_count": sum(1 for w in all_words if w.get("is_medical_term"))
            },
            "model_used": self.model_name,
            "device": self.device
        }

if __name__ == "__main__":
    import sys
    svc = TranscriptionService.get_instance()
    if "--download-model" in sys.argv:
        m_name = sys.argv[sys.argv.index("--download-model") + 1] if len(sys.argv) > sys.argv.index("--download-model") + 1 else "base"
        print(f"Downloading model '{m_name}' to {MODELS_DIR}...")
        ok, res = svc.load_model(model_name=m_name)
        print(f"Result: {ok} -> {res}")
    else:
        print("Whisper service CLI helper.")
        print("Status:", svc.get_status())
