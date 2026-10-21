"""Date handling. A date is a day, a month or a quarter. Never guess a day."""
import datetime as dt
import hashlib
import re

_DAY = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_MON = re.compile(r"^(\d{4})-(\d{2})$")
_QTR = re.compile(r"^(\d{4})-Q([1-4])$")


def _eom(y, m):
    return dt.date(y + (1 if m == 12 else 0), (m % 12) + 1, 1) - dt.timedelta(days=1)


def parse_when(w):
    """Return (precision, start, end) or None if w is not a valid date string."""
    if not isinstance(w, str):
        return None
    try:
        m = _DAY.match(w)
        if m:
            d = dt.date(*map(int, m.groups()))
            return ("day", d, d)
        m = _MON.match(w)
        if m:
            y, mo = map(int, m.groups())
            return ("month", dt.date(y, mo, 1), _eom(y, mo))
        m = _QTR.match(w)
        if m:
            y, q = int(m.group(1)), int(m.group(2))
            return ("quarter", dt.date(y, 3 * q - 2, 1), _eom(y, 3 * q))
    except ValueError:
        return None
    return None


def slug(company, drug, indication):
    base = re.sub(r"[^a-z0-9]+", "-", f"{company} {drug}".lower()).strip("-")[:40]
    h = hashlib.sha1(f"{company}|{drug}|{indication}".lower().encode()).hexdigest()[:6]
    return f"{base}-{h}"
