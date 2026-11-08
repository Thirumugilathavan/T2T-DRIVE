import re

# Strict Indian mobile number regex:
# Optional country code (+91, 91, or leading 0), followed by 10 digits starting with 6, 7, 8, or 9
INDIAN_MOBILE_REGEX = re.compile(r"^(?:\+91|91|0)?([6-9]\d{9})$")

def normalize_phone(phone: str) -> str:
    """
    Normalizes Indian mobile numbers into standard E.164 format (+91XXXXXXXXXX).
    Strips whitespace, hyphens, periods, and parentheses before validation.
    
    Accepts:
      - "9876543210"       -> "+919876543210"
      - "+919876543210"    -> "+919876543210"
      - "09876543210"      -> "+919876543210"
      - "+91 98765-43210"  -> "+919876543210"
      - "919876543210"     -> "+919876543210"
      
    Raises ValueError with a clear, user-facing error message for invalid inputs.
    """
    if not isinstance(phone, str) or not phone.strip():
        raise ValueError("Phone number must be a non-empty string.")

    cleaned = re.sub(r"[\s\-\(\)\.]", "", phone.strip())
    match = INDIAN_MOBILE_REGEX.match(cleaned)
    if not match:
        raise ValueError(
            "Invalid Indian mobile number. Must be a valid 10-digit number starting with 6, 7, 8, or 9."
        )

    return f"+91{match.group(1)}"
