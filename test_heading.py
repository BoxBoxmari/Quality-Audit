import re


def _is_heading_junk(text: str) -> bool:
    if not text or len(text) < 3:
        return True
    text_stripped = text.strip()
    if len(text_stripped) < 3:
        return True
    text_lower = text_stripped.lower()
    valid_patterns = [
        r"balance sheet",
        r"cân đối kế toán",
        r"income statement",
        r"kết quả kinh doanh",
        r"cash flow",
        r"lưu chuyển tiền",
        r"equity",
        r"vốn chủ sở hữu",
        r"note \d+:",  # Note with description
    ]
    if any(re.search(p, text_lower) for p in valid_patterns):
        return False
    words = text_lower.split()

    if re.match(r"^(unit|đơn\s*vị\s*(tính)?|đvt)\s*:?\s*.{0,20}$", text_lower):
        return True

    if len(words) <= 4:
        if any(re.match(r"^(19|20)\d{2}$", w) for w in words):
            return True
        if any(
            w in ["vnd", "usd", "eur", "đồng"] or "vnd'" in w or "usd'" in w
            for w in words
        ):
            return True
        if any(re.match(r"\d{1,2}/\d{1,2}/\d{2,4}", w) for w in words):
            return True
    digits = sum(1 for c in text_stripped if c.isdigit())
    currency_chars = sum(1 for c in text_stripped if c in "$.,()" or c == "\u00a0")
    total = len(text_stripped)
    if total > 0 and (digits + currency_chars) / total > 0.50:
        return True
    date_match = re.search(r"\d{1,2}/\d{1,2}/\d{2,4}", text_stripped)
    if date_match and len(date_match.group()) / len(text_stripped) > 0.5:
        return True
    if re.search(r"20\d{2}\s*$", text_stripped) and digits / max(1, total) > 0.2:
        return True
    if ":" in text_stripped:
        return False
    return (
        len(words) <= 2
        and text_lower.startswith(("note ", "table ", "appendix "))
        and bool(re.match(r"^(note|table|appendix)\s+\d+$", text_lower))
    )


test_cases = [
    "2018 VND'000",
    "31/12/2018 VND",
    "VND",
    "31/12/2018",
    "2018",
    "2018.",
    "Năm 2018",
    "For the year ended 2018",
    "Income statement",
    "Đơn vị tính: VND",
    "Mẫu số B 01 - DN",
    "(Ban hành theo Thông tư số 200/2014/TT-BTC)",
]

for t in test_cases:
    print(f"'{t}': {_is_heading_junk(t)}")
