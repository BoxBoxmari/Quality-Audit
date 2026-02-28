import re


def _parse_inline_formula(text: str):
    if not isinstance(text, str):
        return None

    match = re.search(r"(\d{2})\s*=\s*([0-9\s\+\-\(\)]+)", text)
    if not match:
        return None

    target_code = match.group(1).strip()
    expression = match.group(2).strip()

    clean_exp = expression.replace(" ", "")
    # Remove trailing unclosed parenthesis if any
    if clean_exp.endswith(")") and clean_exp.count("(") < clean_exp.count(")"):
        clean_exp = clean_exp[:-1]

    children = []
    current_sign = 1
    sign_stack = [1]

    tokens = re.findall(r"(\d{2}|\+|\-|\(|\))", clean_exp)

    for token in tokens:
        if token == "+":
            current_sign = 1
        elif token == "-":
            current_sign = -1
        elif token == "(":
            sign_stack.append(sign_stack[-1] * current_sign)
            current_sign = 1
        elif token == ")":
            if len(sign_stack) > 1:
                sign_stack.pop()
        else:  # it's a number
            effective_sign = sign_stack[-1] * current_sign
            children.append(token if effective_sign == 1 else f"-{token}")

    return target_code, children


# Let's test what might be the text
texts = [
    "Accounting profit before tax (50 = 30 + 40)",
    "Accounting profit before tax (50=30+40)",
    "Operating profit (30 = 20 + (21-22) - 25 - 26)",
]
for t in texts:
    print(t, "->", _parse_inline_formula(t))
