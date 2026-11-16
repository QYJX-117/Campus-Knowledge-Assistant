"""Input guardrails and output privacy sanitization for the RAG pipeline."""
import re
import unicodedata
from pathlib import Path

SENSITIVE_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "sensitive.txt"

_sensitive_words: list[str] | None = None

_PROMPT_INJECTION_PATTERNS = (
    re.compile(r"忽略(?:之前|以上|所有|系统)?(?:的)?(?:指令|规则|要求|提示词)"),
    re.compile(r"(?:显示|输出|泄露|告诉我|给我).{0,12}(?:系统提示词|systemprompt|api密钥|apikey|数据库密码|环境变量)"),
    re.compile(r"(?:进入|开启|切换到|扮演).{0,8}(?:开发者模式|无约束模式|越狱模式)"),
    re.compile(r"(?:绕过|关闭|禁用).{0,8}(?:安全|审核|过滤|权限|规则)"),
)

_MOBILE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_ID_CARD_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
_BANK_CARD_RE = re.compile(r"(?<!\d)\d{16,19}(?!\d)")
_API_KEY_RE = re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{16,}(?![A-Za-z0-9])", re.IGNORECASE)


def load_sensitive_words() -> list[str]:
    """Read sensitive words from data/sensitive.txt, one per line, skip comments."""
    words: list[str] = []
    if not SENSITIVE_FILE.exists():
        return words
    try:
        with open(SENSITIVE_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    words.append(line)
    except Exception as e:
        print(f"[guardrails] Failed to load sensitive words: {e}")
    return words


def _get_words() -> list[str]:
    global _sensitive_words
    if _sensitive_words is None:
        _sensitive_words = load_sensitive_words()
    return _sensitive_words


def _normalized(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).lower()


def input_risk(text: str) -> str | None:
    """Return a stable risk code, or None when the question is safe."""
    if not text:
        return None
    compact = _normalized(text)
    if _MOBILE_RE.search(compact) or _ID_CARD_RE.search(compact) or _BANK_CARD_RE.search(compact):
        return "personal_data"
    if any(pattern.search(compact) for pattern in _PROMPT_INJECTION_PATTERNS):
        return "prompt_injection"
    for word in _get_words():
        if word and _normalized(word) in compact:
            return "sensitive_content"
    return None


def check_input(text: str) -> bool:
    """True = clean, False = blocked."""
    return input_risk(text) is None


def sanitize_output(text: str) -> str:
    """Redact sensitive phrases, private identifiers, and leaked API keys."""
    if not text:
        return text
    result = text
    for word in _get_words():
        if word:
            result = result.replace(word, "***")
    result = _API_KEY_RE.sub("[API_KEY_REDACTED]", result)
    result = _ID_CARD_RE.sub("******************", result)
    result = _MOBILE_RE.sub(lambda match: f"{match.group()[:3]}****{match.group()[-4:]}", result)
    result = _BANK_CARD_RE.sub("**** **** **** ****", result)
    return result


def is_question_safe(question: str) -> tuple[bool, str]:
    """Return (is_safe, error_message)."""
    if not question or not question.strip():
        return False, "问题不能为空。"
    risk = input_risk(question)
    if risk == "personal_data":
        return False, "为保护您的隐私，请勿在问题中填写手机号、身份证号或银行卡号。您可以隐去具体号码后重新提问。"
    if risk == "prompt_injection":
        return False, "抱歉，我无法执行绕过系统规则、获取内部提示词或敏感配置的请求。请改为咨询正常的校园信息。"
    if risk == "sensitive_content":
        return False, "抱歉，您的问题包含不适当或高风险内容，暂时无法处理。请调整表述后重新提问。"
    return True, ""
