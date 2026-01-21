# core/sentiment.py — Advanced sentiment analysis for customer interactions
# Production-grade with multiple detection methods and confidence scoring

import re
import logging
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class SentimentType(Enum):
    """Types of sentiment we detect."""
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
    FRUSTRATED = "frustrated"
    ANGRY = "angry"
    CONFUSED = "confused"
    URGENT = "urgent"
    SATISFIED = "satisfied"


class IntentType(Enum):
    """Types of user intent we detect."""
    BOOKING = "booking"
    INQUIRY = "inquiry"
    COMPLAINT = "complaint"
    HUMAN_REQUEST = "human_request"
    CANCELLATION = "cancellation"
    GREETING = "greeting"
    FAREWELL = "farewell"
    GRATITUDE = "gratitude"
    UNKNOWN = "unknown"


@dataclass
class SentimentResult:
    """Result of sentiment analysis."""
    sentiment: SentimentType
    confidence: float  # 0.0 to 1.0
    intent: IntentType
    triggers_escalation: bool
    escalation_reason: Optional[str]
    details: Dict


# ============================================================================
# Pattern Definitions
# ============================================================================

# Patterns indicating desire to speak with human
HUMAN_REQUEST_PATTERNS = [
    r'\b(speak|talk|connect)\s+(to|with)\s+(a\s+)?(human|person|someone|agent|representative|staff|manager|real\s+person)',
    r'\b(get\s+me\s+)?(a\s+)?(human|person|someone|agent|representative|staff)',
    r'\b(i\s+)?(want|need|require)\s+(a\s+)?(human|person|someone|real)',
    r'\b(transfer|connect)\s+me',
    r'\breal\s+person\b',
    r'\bnot\s+(a\s+)?(bot|robot|ai|automated)',
    r'\bstop\s+(the\s+)?(bot|ai)\b',
    r'\bcan\s+i\s+(please\s+)?(speak|talk)',
    r'\bis\s+there\s+(a\s+)?(human|person|someone)',
    r'\bi\'?d\s+(rather|prefer)\s+(speak|talk)',
]

# Patterns indicating frustration/anger
FRUSTRATION_PATTERNS = [
    r'\b(this\s+is\s+)?(ridiculous|absurd|unacceptable|outrageous|terrible|horrible|awful)',
    r'\b(very|extremely|so|really)\s+(frustrat|annoy|upset|angry|mad|disappoint)',
    r'\b(frustrated|annoyed|upset|angry|furious|livid|pissed)\b',
    r'\b(what\s+the\s+|wtf|wth)\b',
    r'\b(useless|worthless|pathetic|incompetent)\b',
    r'\b(waste\s+of\s+(my\s+)?time)\b',
    r'\b(i\'?ve\s+been\s+(waiting|trying|calling))\s+(for\s+)?(hours|forever|ages|so\s+long)',
    r'\b(never\s+(coming|using|returning)\s+(back|again))',
    r'\b(this\s+is\s+the\s+)(worst|last\s+time)',
    r'[!]{2,}',  # Multiple exclamation marks
    r'[?!]{3,}',  # Multiple punctuation
]

# Patterns indicating urgency
URGENCY_PATTERNS = [
    r'\b(urgent|emergency|asap|immediately|right\s+now|today)\b',
    r'\b(can\'?t\s+wait|need\s+it\s+now|time\s+sensitive)\b',
    r'\b(in\s+pain|hurts?\s+(so\s+)?bad|severe\s+pain|excruciating)\b',
    r'\b(bleeding|swollen|infection|emergency)\b',
    r'\b(as\s+soon\s+as\s+possible|earliest\s+available)\b',
    r'\b(critical|life\s+or\s+death|serious)\b',
]

# Patterns indicating confusion
CONFUSION_PATTERNS = [
    r'\b(i\s+)?don\'?t\s+understand\b',
    r'\b(confused|confusing|unclear|makes?\s+no\s+sense)\b',
    r'\b(what\s+do\s+you\s+mean|what\s+does\s+that\s+mean)\b',
    r'\b(can\s+you\s+)(explain|clarify|rephrase)\b',
    r'\b(huh|what)\?+\b',
    r'\b(i\'?m\s+)?lost\b',
    r'\b(sorry|pardon)\s*\?',
]

# Patterns indicating satisfaction/positive sentiment
POSITIVE_PATTERNS = [
    r'\b(thank|thanks|thx|ty)\b',
    r'\b(great|excellent|amazing|wonderful|fantastic|perfect|awesome)\b',
    r'\b(appreciate|grateful|helpful)\b',
    r'\b(good\s+job|well\s+done|nice)\b',
    r'\b(love|loved)\s+(it|this|that)\b',
    r'\b(exactly\s+what\s+i\s+)(needed|wanted)\b',
]

# Patterns indicating complaint
COMPLAINT_PATTERNS = [
    r'\b(complain|complaint|report|issue|problem)\b',
    r'\b(not\s+happy|unhappy|dissatisfied)\b',
    r'\b(refund|money\s+back|compensation)\b',
    r'\b(speak\s+to\s+)(manager|supervisor|owner)\b',
    r'\b(file\s+a\s+complaint|write\s+a\s+review)\b',
    r'\b(poor\s+service|bad\s+experience)\b',
]

# Negative words and intensifiers
NEGATIVE_WORDS = {
    'hate', 'terrible', 'awful', 'horrible', 'worst', 'bad', 'poor',
    'disappointing', 'disappointed', 'frustrating', 'annoying', 'annoyed',
    'unacceptable', 'ridiculous', 'pathetic', 'useless', 'stupid',
    'incompetent', 'rude', 'unprofessional', 'disgusting', 'outrageous'
}

INTENSIFIERS = {
    'very', 'extremely', 'really', 'so', 'absolutely', 'completely',
    'totally', 'utterly', 'incredibly', 'highly', 'deeply'
}

NEGATIONS = {
    'not', "n't", 'no', 'never', 'none', 'nothing', 'neither', 'nobody',
    'nowhere', 'hardly', 'barely', 'scarcely'
}


# ============================================================================
# Analysis Functions
# ============================================================================

def _count_pattern_matches(text: str, patterns: List[str]) -> Tuple[int, List[str]]:
    """Count pattern matches and return matched patterns."""
    text_lower = text.lower()
    matches = []
    for pattern in patterns:
        if re.search(pattern, text_lower, re.IGNORECASE):
            matches.append(pattern)
    return len(matches), matches


def _analyze_word_sentiment(text: str) -> Dict[str, float]:
    """Analyze individual words for sentiment indicators."""
    words = re.findall(r'\b\w+\b', text.lower())

    negative_count = 0
    positive_count = 0
    intensifier_count = 0
    negation_positions = []

    for i, word in enumerate(words):
        if word in NEGATIVE_WORDS:
            # Check if preceded by negation
            negated = any(pos == i - 1 or pos == i - 2 for pos in negation_positions)
            if negated:
                positive_count += 1
            else:
                negative_count += 1

        if word in NEGATIONS:
            negation_positions.append(i)

        if word in INTENSIFIERS:
            intensifier_count += 1

    total_words = max(len(words), 1)

    return {
        'negative_ratio': negative_count / total_words,
        'positive_ratio': positive_count / total_words,
        'intensifier_ratio': intensifier_count / total_words,
        'negative_count': negative_count,
        'intensifier_count': intensifier_count,
    }


def _detect_caps_and_punctuation(text: str) -> Dict[str, float]:
    """Analyze caps and punctuation for emotional indicators."""
    words = text.split()
    caps_words = sum(1 for w in words if w.isupper() and len(w) > 1)

    exclamation_count = text.count('!')
    question_count = text.count('?')

    # Multiple punctuation is often a sign of frustration
    multi_punct = len(re.findall(r'[!?]{2,}', text))

    total_words = max(len(words), 1)

    return {
        'caps_ratio': caps_words / total_words,
        'exclamation_count': exclamation_count,
        'question_count': question_count,
        'multi_punctuation': multi_punct,
    }


def _calculate_frustration_score(
    pattern_matches: int,
    word_analysis: Dict,
    punct_analysis: Dict,
    message_count: int = 1
) -> float:
    """Calculate overall frustration score (0.0 to 1.0)."""
    score = 0.0

    # Pattern matches are strong indicators
    score += min(pattern_matches * 0.25, 0.5)

    # Negative word ratio
    score += word_analysis['negative_ratio'] * 0.3

    # Intensifiers amplify negative sentiment
    if word_analysis['negative_count'] > 0:
        score += word_analysis['intensifier_ratio'] * 0.2

    # Caps and punctuation
    score += punct_analysis['caps_ratio'] * 0.15
    score += min(punct_analysis['multi_punctuation'] * 0.1, 0.2)

    # Repeated messages can indicate frustration
    if message_count > 3:
        score += 0.1

    return min(score, 1.0)


def analyze_sentiment(
    text: str,
    conversation_history: Optional[List[Dict]] = None,
    failed_attempts: int = 0
) -> SentimentResult:
    """
    Analyze sentiment and intent of a message.

    Args:
        text: The message to analyze
        conversation_history: Previous messages in conversation
        failed_attempts: Number of failed booking/action attempts

    Returns:
        SentimentResult with sentiment, intent, and escalation decision
    """
    if not text:
        return SentimentResult(
            sentiment=SentimentType.NEUTRAL,
            confidence=0.5,
            intent=IntentType.UNKNOWN,
            triggers_escalation=False,
            escalation_reason=None,
            details={}
        )

    text_lower = text.lower()

    # Check for human request first (highest priority)
    human_matches, human_patterns = _count_pattern_matches(text, HUMAN_REQUEST_PATTERNS)
    if human_matches > 0:
        return SentimentResult(
            sentiment=SentimentType.NEUTRAL,
            confidence=0.95,
            intent=IntentType.HUMAN_REQUEST,
            triggers_escalation=True,
            escalation_reason="Customer explicitly requested to speak with a human",
            details={
                'matched_patterns': human_patterns,
                'trigger': 'human_request'
            }
        )

    # Analyze various patterns
    frustration_matches, frust_patterns = _count_pattern_matches(text, FRUSTRATION_PATTERNS)
    urgency_matches, urg_patterns = _count_pattern_matches(text, URGENCY_PATTERNS)
    confusion_matches, conf_patterns = _count_pattern_matches(text, CONFUSION_PATTERNS)
    positive_matches, pos_patterns = _count_pattern_matches(text, POSITIVE_PATTERNS)
    complaint_matches, comp_patterns = _count_pattern_matches(text, COMPLAINT_PATTERNS)

    # Word-level analysis
    word_analysis = _analyze_word_sentiment(text)
    punct_analysis = _detect_caps_and_punctuation(text)

    # Calculate frustration score
    message_count = len(conversation_history) if conversation_history else 1
    frustration_score = _calculate_frustration_score(
        frustration_matches, word_analysis, punct_analysis, message_count
    )

    # Check conversation history for escalating frustration
    history_frustration = 0.0
    if conversation_history:
        for msg in conversation_history[-5:]:  # Last 5 messages
            if msg.get('role') == 'user':
                hist_text = msg.get('content', '') or msg.get('text', '')
                hist_matches, _ = _count_pattern_matches(hist_text, FRUSTRATION_PATTERNS)
                history_frustration += hist_matches * 0.1

    frustration_score = min(frustration_score + history_frustration, 1.0)

    # Determine primary sentiment
    sentiment = SentimentType.NEUTRAL
    confidence = 0.5

    if frustration_score > 0.6:
        sentiment = SentimentType.ANGRY if frustration_score > 0.8 else SentimentType.FRUSTRATED
        confidence = frustration_score
    elif urgency_matches > 0:
        sentiment = SentimentType.URGENT
        confidence = 0.7 + (urgency_matches * 0.1)
    elif confusion_matches > 0:
        sentiment = SentimentType.CONFUSED
        confidence = 0.6 + (confusion_matches * 0.1)
    elif positive_matches > 0:
        sentiment = SentimentType.POSITIVE if positive_matches > 1 else SentimentType.SATISFIED
        confidence = 0.6 + (positive_matches * 0.1)
    elif word_analysis['negative_count'] > 0:
        sentiment = SentimentType.NEGATIVE
        confidence = 0.5 + word_analysis['negative_ratio']

    # Determine intent
    intent = IntentType.UNKNOWN
    if complaint_matches > 0:
        intent = IntentType.COMPLAINT
    elif 'book' in text_lower or 'appointment' in text_lower or 'schedule' in text_lower:
        intent = IntentType.BOOKING
    elif any(word in text_lower for word in ['cancel', 'reschedule', 'change']):
        intent = IntentType.CANCELLATION
    elif positive_matches > 0 and any(word in text_lower for word in ['thank', 'thanks', 'bye', 'goodbye']):
        intent = IntentType.GRATITUDE if 'thank' in text_lower else IntentType.FAREWELL
    elif any(word in text_lower for word in ['hi', 'hello', 'hey', 'good morning', 'good afternoon']):
        intent = IntentType.GREETING
    else:
        intent = IntentType.INQUIRY

    # Determine if escalation is needed
    triggers_escalation = False
    escalation_reason = None

    # Escalation triggers
    if sentiment in (SentimentType.ANGRY, SentimentType.FRUSTRATED) and frustration_score > 0.7:
        triggers_escalation = True
        escalation_reason = f"High frustration detected (score: {frustration_score:.2f})"
    elif intent == IntentType.COMPLAINT and word_analysis['negative_count'] >= 2:
        triggers_escalation = True
        escalation_reason = "Customer complaint with multiple negative indicators"
    elif failed_attempts >= 3:
        triggers_escalation = True
        escalation_reason = f"Multiple failed attempts ({failed_attempts})"
    elif urgency_matches >= 2 and any(word in text_lower for word in ['emergency', 'urgent', 'pain', 'bleeding']):
        triggers_escalation = True
        escalation_reason = "Urgent/emergency situation detected"

    return SentimentResult(
        sentiment=sentiment,
        confidence=min(confidence, 1.0),
        intent=intent,
        triggers_escalation=triggers_escalation,
        escalation_reason=escalation_reason,
        details={
            'frustration_score': frustration_score,
            'pattern_matches': {
                'frustration': frustration_matches,
                'urgency': urgency_matches,
                'confusion': confusion_matches,
                'positive': positive_matches,
                'complaint': complaint_matches,
            },
            'word_analysis': word_analysis,
            'punctuation_analysis': punct_analysis,
            'failed_attempts': failed_attempts,
        }
    )


def get_sentiment_emoji(sentiment: SentimentType) -> str:
    """Get an emoji representation of sentiment (for logging/display)."""
    emoji_map = {
        SentimentType.POSITIVE: "😊",
        SentimentType.NEUTRAL: "😐",
        SentimentType.NEGATIVE: "😕",
        SentimentType.FRUSTRATED: "😤",
        SentimentType.ANGRY: "😠",
        SentimentType.CONFUSED: "😕",
        SentimentType.URGENT: "🚨",
        SentimentType.SATISFIED: "😌",
    }
    return emoji_map.get(sentiment, "❓")


def summarize_conversation(messages: List[Dict]) -> str:
    """Generate a brief summary of conversation for escalation."""
    if not messages:
        return "No conversation history available."

    user_messages = [m for m in messages if m.get('role') == 'user' or m.get('sender') == 'user']

    if not user_messages:
        return "No user messages in conversation."

    # Get key points from user messages
    summary_parts = []

    # First message (often contains main intent)
    first_msg = user_messages[0].get('content') or user_messages[0].get('text', '')
    if first_msg:
        summary_parts.append(f"Initial inquiry: {first_msg[:100]}{'...' if len(first_msg) > 100 else ''}")

    # Last message (current state)
    if len(user_messages) > 1:
        last_msg = user_messages[-1].get('content') or user_messages[-1].get('text', '')
        if last_msg:
            summary_parts.append(f"Latest message: {last_msg[:100]}{'...' if len(last_msg) > 100 else ''}")

    summary_parts.append(f"Total messages: {len(messages)}")

    return "\n".join(summary_parts)
