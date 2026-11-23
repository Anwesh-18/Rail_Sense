import re
import nh3

OTP_PATTERN = re.compile(r"\b(\d{4,8})\b")
URL_PATTERN = re.compile(r"https?://[^\s<>\"']+")


def sanitize_html(raw_html: str | None) -> str | None:
    if not raw_html:
        return None
    return nh3.clean(
        raw_html,
        tags={"p", "br", "b", "strong", "i", "em", "u", "a", "ul", "ol", "li", "div", "span"},
        attributes={"a": {"href", "title"}},
        strip_comments=True,
    )


def extract_otp_and_link(text_body: str | None, html_body: str | None) -> tuple[str | None, str | None]:
    combined = f"{text_body or ''}\n{html_body or ''}"

    # 1. Extract verification/confirmation URL first
    urls = URL_PATTERN.findall(combined)
    verification_link = next(
        (u for u in urls if any(k in u.lower() for k in ("verify", "confirm", "activate", "token", "auth", "otp"))),
        urls[0] if urls else None,
    )

    # 2. Strip URLs before scanning for numeric OTPs so URL IDs aren't misread as codes
    text_without_urls = URL_PATTERN.sub(" ", combined)
    otp_match = OTP_PATTERN.search(text_without_urls)
    extracted_otp = otp_match.group(1) if otp_match else None

    return extracted_otp, verification_link