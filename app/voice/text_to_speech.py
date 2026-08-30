"""
Text-to-speech abstraction.

Keeps speech generation independent from the eventual TTS provider.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol


@dataclass
class SpeechResult:
    """Result produced by text-to-speech generation."""

    audio: bytes
    language: str
    content_type: str = "audio/mpeg"
    duration_seconds: Optional[float] = None
    raw_response: Optional[Dict[str, Any]] = None


class TextToSpeechProvider(Protocol):
    """Interface required by a TTS provider."""

    def synthesize(
        self,
        text: str,
        language: str,
    ) -> SpeechResult:
        ...


class TextToSpeechClient:
    """Provider-independent text-to-speech client."""

    def __init__(
        self,
        provider: Optional[TextToSpeechProvider] = None,
    ) -> None:
        self.provider = provider

    def synthesize(
        self,
        text: str,
        language: str,
    ) -> SpeechResult:
        """Convert text into spoken audio."""

        text = text.strip()

        if not text:
            raise ValueError(
                "Text cannot be empty."
            )

        if not language:
            raise ValueError(
                "Language must be provided."
            )

        if not self.provider:
            raise RuntimeError(
                "No text-to-speech provider is configured."
            )

        return self.provider.synthesize(
            text,
            language,
        )


class MockTextToSpeechProvider:
    """
    Local testing TTS provider.

    Returns encoded text instead of real audio so the voice pipeline
    can be tested without consuming TTS credits.
    """

    def synthesize(
        self,
        text: str,
        language: str,
    ) -> SpeechResult:
        """Return text encoded as test audio bytes."""

        return SpeechResult(
            audio=text.encode("utf-8"),
            language=language,
            content_type="text/plain",
            duration_seconds=None,
            raw_response={
                "mock": True,
                "text": text,
            },
        )