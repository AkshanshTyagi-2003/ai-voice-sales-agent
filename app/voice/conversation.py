# conversation.py
"""
Real-time conversation orchestration.

Connects speech recognition, the AI sales agent, and text-to-speech
without coupling them to a specific external provider.
"""

from dataclasses import dataclass
from typing import Optional, Protocol

from app.ai.agent import SalesAgent
from app.core.models import (
    Conversation,
    ConversationStatus,
    Lead,
    MessageRole,
)
from app.voice.speech_to_text import (
    SpeechToTextClient,
    TranscriptionResult,
)
from app.voice.text_to_speech import (
    SpeechResult,
    TextToSpeechClient,
)
from app.utils.helpers import utc_now


class VoiceConversationCallbacks(Protocol):
    """
    Optional callbacks used by the action layer.

    These callbacks allow mid-call actions such as WhatsApp and
    callback scheduling without placing action logic inside voice.py.
    """

    def on_high_intent(
        self,
        lead: Lead,
        conversation: Conversation,
    ) -> None:
        ...

    def on_callback_requested(
        self,
        lead: Lead,
        conversation: Conversation,
    ) -> None:
        ...


@dataclass
class VoiceTurnResult:
    """Result of processing one customer voice turn."""

    transcription: TranscriptionResult
    response_text: str
    response_audio: SpeechResult
    high_intent: bool
    lead_temperature: Optional[str]


class ConversationManager:
    """Manages one active voice conversation."""

    def __init__(
        self,
        speech_to_text: SpeechToTextClient,
        text_to_speech: TextToSpeechClient,
        sales_agent: SalesAgent,
        callbacks: Optional[VoiceConversationCallbacks] = None,
    ) -> None:
        self.speech_to_text = speech_to_text
        self.text_to_speech = text_to_speech
        self.sales_agent = sales_agent
        self.callbacks = callbacks

    def start(
        self,
        conversation: Conversation,
    ) -> Conversation:
        """Mark a conversation as active."""

        conversation.status = ConversationStatus.ACTIVE
        conversation.started_at = utc_now()

        return conversation

    def process_audio(
        self,
        conversation: Conversation,
        lead: Lead,
        audio: bytes,
        language: Optional[str] = None,
    ) -> VoiceTurnResult:
        """
        Process one complete customer speech turn.

        Flow:
            audio -> STT -> AI -> actions -> TTS
        """

        if conversation.status != ConversationStatus.ACTIVE:
            raise RuntimeError(
                "Conversation is not active."
            )

        transcription = self.speech_to_text.transcribe(
            audio,
            language=language,
        )

        if not transcription.text.strip():
            raise ValueError(
                "Speech recognition returned empty text."
            )

        detected_language = (
            transcription.language
            or language
            or lead.language
            or "en"
        )

        lead.language = detected_language

        ai_result = self.sales_agent.process_customer_message(
            conversation=conversation,
            lead=lead,
            customer_message=transcription.text,
            language=detected_language,
        )

        # Mid-call action trigger.
        if (
            ai_result.intent.high_intent
            and not conversation.whatsapp_sent_mid_call
            and self.callbacks
        ):
            self.callbacks.on_high_intent(
                lead,
                conversation,
            )

        if (
            ai_result.callback_request
            and self.callbacks
        ):
            self.callbacks.on_callback_requested(
                lead,
                conversation,
            )

        response_audio = self.text_to_speech.synthesize(
            ai_result.text,
            detected_language,
        )

        temperature = (
            lead.temperature.value
            if lead.temperature
            else None
        )

        return VoiceTurnResult(
            transcription=transcription,
            response_text=ai_result.text,
            response_audio=response_audio,
            high_intent=ai_result.intent.high_intent,
            lead_temperature=temperature,
        )

    def end(
        self,
        conversation: Conversation,
    ) -> Conversation:
        """Mark the conversation as completed."""

        conversation.status = ConversationStatus.COMPLETED
        conversation.ended_at = utc_now()

        return conversation

    def fail(
        self,
        conversation: Conversation,
    ) -> Conversation:
        """Mark the conversation as failed."""

        conversation.status = ConversationStatus.FAILED
        conversation.ended_at = utc_now()

        return conversation