"""
Speech-to-text abstraction.

The module defines a stable interface for converting customer audio
into text without tying the application to a specific STT provider.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol


@dataclass
class TranscriptionResult:
    """Result produced by speech recognition."""

    text: str
    language: Optional[str] = None
    confidence: Optional[float] = None
    final: bool = True
    raw_response: Optional[Dict[str, Any]] = None


class SpeechToTextProvider(Protocol):
    """Interface required by an STT provider."""

    def transcribe(
        self,
        audio: bytes,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        ...


class SpeechToTextClient:
    """Provider-independent speech-to-text client."""

    def __init__(
        self,
        provider: Optional[SpeechToTextProvider] = None,
    ) -> None:
        self.provider = provider

    def transcribe(
        self,
        audio: bytes,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """Convert audio bytes into text."""

        if not audio:
            raise ValueError("Audio data cannot be empty.")

        if not self.provider:
            raise RuntimeError(
                "No speech-to-text provider is configured."
            )

        return self.provider.transcribe(
            audio,
            language=language,
        )


class MockSpeechToTextProvider:
    """
    Local testing STT provider.

    Useful for testing the conversation pipeline without audio APIs.
    """

    def __init__(
        self,
        text: str = "",
        language: str = "en",
    ) -> None:
        self.text = text
        self.language = language

    def transcribe(
        self,
        audio: bytes,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """Return configured test transcription."""

        if not audio:
            raise ValueError("Audio data cannot be empty.")

        return TranscriptionResult(
            text=self.text,
            language=language or self.language,
            confidence=1.0,
            final=True,
        )