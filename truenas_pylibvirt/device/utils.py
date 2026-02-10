from __future__ import annotations
import string


def disk_from_number(number: int) -> str:
    def i_divmod(n: int) -> tuple[int, int]:
        a, b = divmod(n, 26)
        if b == 0:
            return a - 1, b + 26
        return a, b

    chars = []
    while number > 0:
        number, d = i_divmod(number)
        chars.append(string.ascii_lowercase[d - 1])

    return ''.join(reversed(chars))
