"""Strict PCM and inline reference validation shared by hosted speech providers."""
import base64
import io
import re
import wave
from app.services.upload_validation import UploadValidationError


def wav_duration(source) -> float:
    try:
        with wave.open(source, "rb") as audio:
            if audio.getnchannels() != 1 or audio.getsampwidth() != 2 or audio.getframerate() != 16000:
                raise ValueError("Unsupported PCM format")
            frames = audio.getnframes()
            if len(audio.readframes(frames)) != frames * 2:
                raise ValueError("Truncated PCM")
            return frames / 16000
    except (wave.Error, EOFError, ValueError) as error:
        raise UploadValidationError(422, "음성을 16kHz 모노 WAV로 변환한 뒤 다시 시도해주세요.") from error


def validate_references(references: list[dict]) -> tuple[list[str], list[str]]:
    if not isinstance(references, list) or len(references) > 4:
        raise UploadValidationError(422, "화자 참조는 최대 4개입니다.")
    names, clips = [], []
    for ref in references:
        if not isinstance(ref, dict):
            raise UploadValidationError(422, "화자 참조 형식이 올바르지 않습니다.")
        name, clip = ref.get("name", ""), ref.get("audio", "")
        if not isinstance(name, str) or not re.fullmatch(r"speaker_[0-3]", name) or name in names:
            raise UploadValidationError(422, "화자 참조 이름이 올바르지 않습니다.")
        prefix = "data:audio/wav;base64,"
        if not isinstance(clip, str) or len(clip) > 175_000 or not clip.startswith(prefix):
            raise UploadValidationError(422, "화자 참조 오디오가 올바르지 않습니다.")
        try:
            data = base64.b64decode(clip[len(prefix):], validate=True)
        except ValueError as error:
            raise UploadValidationError(422, "화자 참조 오디오가 올바르지 않습니다.") from error
        if not 2 <= wav_duration(io.BytesIO(data)) <= 4:
            raise UploadValidationError(422, "화자 참조는 2~4초여야 합니다.")
        names.append(name)
        clips.append(clip)
    return names, clips

