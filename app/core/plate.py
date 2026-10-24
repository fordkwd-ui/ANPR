"""Plate normalization and validation rules."""
import re
from typing import Optional

# Standard Indian State & Two-Wheeler series: 2 letters, 1-2 digits RTO, 0-3 letters series, 4 digits
STANDARD_PLATE_REGEX = re.compile(r"^[A-Z]{2}\d{1,2}[A-Z]{0,3}\d{4}$")

# Bharat (BH) series: 2 digits (year), "BH", 4 digits, 1-2 letters
BH_SERIES_REGEX = re.compile(r"^\d{2}BH\d{4}[A-Z]{1,2}$")

CONFUSION_MAP_LETTERS = {
    "0": "O",
    "1": "I",
    "2": "Z",
    "3": "E",
    "4": "A",
    "5": "S",
    "6": "G",
    "7": "T",
    "8": "B",
    "9": "P",
}

CONFUSION_MAP_DIGITS = {
    "O": "0",
    "D": "0",
    "Q": "0",
    "I": "1",
    "L": "1",
    "J": "1",
    "Z": "2",
    "E": "3",
    "A": "4",
    "S": "5",
    "G": "6",
    "B": "8",
    "T": "7",
    "Y": "7",
    "P": "9",
}

STATE_FIXES = {
    "C6": "CG",
    "CO": "CG",
    "CQ": "CG",
    "C0": "CG",
    "0G": "CG",
    "OG": "CG",
    "D1": "DL",
    "DO": "DL",
    "DI": "DL",
    "0L": "DL",
    "OL": "DL",
    "M8": "MH",
    "MR": "MH",
    "MO": "MP",
    "M0": "MP",
    "K4": "KA",
    "KO": "KA",
    "K0": "KA",
    "U0": "UP",
    "UD": "UP",
    "T1": "TN",
    "G3": "GJ",
    "R3": "RJ",
    "H1": "HR",
    "HA": "HR",
    "W8": "WB",
    "B8": "BR",
    "OD": "OD",
    "0D": "OD",
    "OR": "OD",
    "PB": "PB",
    "CH": "CH",
    "JK": "JK",
    "UK": "UK",
}


# Official Indian States and Union Territories (Motor Vehicles Act / CMVR 50)
VALID_INDIAN_STATE_CODES = {
    # 28 States
    "AP",  # Andhra Pradesh
    "AR",  # Arunachal Pradesh
    "AS",  # Assam
    "BR",  # Bihar
    "CG",  # Chhattisgarh
    "GA",  # Goa
    "GJ",  # Gujarat
    "HR",  # Haryana
    "HP",  # Himachal Pradesh
    "JH",  # Jharkhand
    "KA",  # Karnataka
    "KL",  # Kerala
    "MP",  # Madhya Pradesh
    "MH",  # Maharashtra
    "MN",  # Manipur
    "ML",  # Meghalaya
    "MZ",  # Mizoram
    "NL",  # Nagaland
    "OD",  # Odisha
    "PB",  # Punjab
    "RJ",  # Rajasthan
    "SK",  # Sikkim
    "TN",  # Tamil Nadu
    "TS",  # Telangana
    "TR",  # Tripura
    "UP",  # Uttar Pradesh
    "UK",  # Uttarakhand
    "WB",  # West Bengal
    # 8 Union Territories
    "AN",  # Andaman and Nicobar Islands
    "CH",  # Chandigarh
    "DH",  # Dadra and Nagar Haveli and Daman and Diu
    "DL",  # Delhi
    "JK",  # Jammu and Kashmir
    "LA",  # Ladakh
    "LD",  # Lakshadweep
    "PY",  # Puducherry
    # Legacy codes still active on registered vehicles
    "OR",  # Odisha (formerly Orissa)
    "UA",  # Uttarakhand (formerly Uttaranchal)
    "DD",  # Daman and Diu
    "DN",  # Dadra and Nagar Haveli
}


def normalize_plate(plate_raw: str) -> str:
    """Normalizes raw plate text by uppercasing and stripping whitespace and hyphens."""
    if not plate_raw:
        return ""
    # Strip spaces, hyphens, dots, equals, quotes, and convert to uppercase
    normalized = re.sub(r"[\s\-\.=#_:;]+", "", plate_raw).upper()
    return normalized


def validate_plate(normalized: str) -> bool:
    """
    Validates if normalized plate string strictly matches genuine Indian registration standards:
    1. Bharat (BH) Series: YY BH NNNN XX
    2. Standard State Series: Valid 2-letter Indian State/UT code + 1-2 digits RTO + 0-3 letters series + 4 digits.
    Never accepts non-Indian letter pairs or random text fragments.
    """
    if not normalized:
        return False
    if BH_SERIES_REGEX.match(normalized):
        return True
    if STANDARD_PLATE_REGEX.match(normalized):
        state_code = normalized[:2]
        if state_code in VALID_INDIAN_STATE_CODES:
            return True
    return False


def fix_optical_plate_confusion(raw_text: str) -> str:
    """
    Applies strict Indian RTO syntax-aware optical character confusion correction.
    Corrects:
      - State code (Pos 0-1): Always letters (e.g. C6 -> CG, D1 -> DL, K4 -> KA, M8 -> MH).
      - RTO code (Pos 2-3): Always digits. Specifically resolves '0Z'/'0T' to '07' (e.g. CG07 Durg/Bhilai).
      - Series code (Pos 4-5): Always letters. Fixes optical digits to letters (e.g. 4 -> A, 0 -> U as O/I are barred).
      - Serial digits (Last 4): Always digits (e.g. O -> 0, I -> 1, Z -> 2, S -> 5, B -> 8).
      - Bharat (BH) series: 2 digits + BH + 4 digits + 1-2 letters.
    """
    cleaned = re.sub(r"[^A-Z0-9]", "", raw_text.upper())
    n = len(cleaned)
    if n < 8 or n > 11:
        return cleaned

    chars = list(cleaned)

    # 1. Bharat (BH) series check: YY BH NNNN CC
    if n >= 4 and "".join(chars[2:4]) == "BH":
        for i in [0, 1]:
            if chars[i] in CONFUSION_MAP_DIGITS:
                chars[i] = CONFUSION_MAP_DIGITS[chars[i]]
        for i in range(4, min(8, n)):
            if chars[i] in CONFUSION_MAP_DIGITS:
                chars[i] = CONFUSION_MAP_DIGITS[chars[i]]
        for i in range(min(8, n), n):
            if chars[i] in CONFUSION_MAP_LETTERS:
                chars[i] = CONFUSION_MAP_LETTERS[chars[i]]
        return "".join(chars)

    # 2. State Code (Pos 0, 1) -> ALWAYS LETTERS
    for i in [0, 1]:
        if chars[i] in CONFUSION_MAP_LETTERS:
            chars[i] = CONFUSION_MAP_LETTERS[chars[i]]
    st = "".join(chars[:2])
    if st in STATE_FIXES:
        chars[0], chars[1] = STATE_FIXES[st][0], STATE_FIXES[st][1]

    # 3. Serial Number (Last 4 characters) -> ALWAYS DIGITS
    for i in range(n - 4, n):
        if chars[i] in CONFUSION_MAP_DIGITS:
            chars[i] = CONFUSION_MAP_DIGITS[chars[i]]

    # 4. Middle RTO & Series positions depend on length:
    if n == 8:
        # e.g. DL 1 S 1234
        if chars[2] in CONFUSION_MAP_DIGITS:
            chars[2] = CONFUSION_MAP_DIGITS[chars[2]]
        if chars[3] in CONFUSION_MAP_LETTERS:
            chars[3] = CONFUSION_MAP_LETTERS[chars[3]]
    elif n == 9:
        # e.g. CG 07 C 8902 or DL 10 A 1234
        if chars[2] in CONFUSION_MAP_DIGITS:
            chars[2] = CONFUSION_MAP_DIGITS[chars[2]]
        if chars[2] == "0" and chars[3] in ("Z", "T", "Y", "7"):
            chars[3] = "7"
        elif chars[3] in CONFUSION_MAP_DIGITS:
            chars[3] = CONFUSION_MAP_DIGITS[chars[3]]
        if chars[4] in CONFUSION_MAP_LETTERS:
            chars[4] = CONFUSION_MAP_LETTERS[chars[4]]
    elif n == 10:
        # e.g. CG 07 CU 8073, CG 07 AN 8902, KA 05 MN 4821
        if chars[2] in CONFUSION_MAP_DIGITS:
            chars[2] = CONFUSION_MAP_DIGITS[chars[2]]
        # If position 2 is '0', resolve 'Z', 'T', 'Y' to '7' (e.g. CG07)
        if chars[2] == "0" and chars[3] in ("Z", "T", "Y", "7"):
            chars[3] = "7"
        elif chars[3] in CONFUSION_MAP_DIGITS:
            chars[3] = CONFUSION_MAP_DIGITS[chars[3]]

        # Series Letters (Pos 4, 5):
        if chars[4] in CONFUSION_MAP_LETTERS:
            chars[4] = CONFUSION_MAP_LETTERS[chars[4]]
        # In Indian CMVR Rule 50, 'O' and 'I' are prohibited in registration series.
        # An optical '0' or 'O' in position 5 is usually 'U' (as in 'CU')
        if chars[5] in ("0", "O"):
            chars[5] = "U"
        elif chars[5] in CONFUSION_MAP_LETTERS:
            chars[5] = CONFUSION_MAP_LETTERS[chars[5]]

    return "".join(chars)


# Backward compatibility alias
fix_plate_chars = fix_optical_plate_confusion

