"""Deterministic job fingerprint, algorithm "fp1".

Two postings describe the same job when their company, title and location agree after
normalisation. The fingerprint is `"fp1:" + sha256(company US title US locations)` where
US is the ASCII unit separator and each part is normalised as below. The function is pure:
the same inputs always give the same fingerprint, with no I/O and no clock.

Shared text normalisation (every field):
    1. Unicode NFKC, then casefold, then NFKC again (casefold can leave unnormalised text).
    2. Format characters (category Cf, such as soft hyphens and zero-width spaces) are
       dropped, except ZWJ and ZWNJ, which carry meaning in Indic and Persian scripts.
    3. Letters, digits and combining marks (categories L, N and M) are kept. Everything else
       becomes a space, so punctuation and symbols collapse and Bengali vowel signs survive.
    4. Whitespace is collapsed and trimmed.
Accents are NOT folded: "malmo" and "malmö" stay different. Folding would merge distinct
Swedish, German or Turkish words and is not worth the false merges; a missed duplicate is
the cheaper error here (see ADR 0002).

Company, after the shared steps (dots and apostrophes are deleted first, so "S.A." is "sa"):
    - "&" becomes "and".
    - A leading "the" is dropped.
    - Trailing legal-form words (inc, llc, ltd, gmbh, ab, ...; see LEGAL_SUFFIXES) are
      dropped, repeatedly, but never the last remaining word. Words like "group",
      "holdings" or "technologies" are kept: they often tell two companies apart.
    - Placeholders such as "confidential" or "unknown" count as no company.

Title, before the shared steps, in a loop until nothing changes:
    - Gender markers are removed: "(m/f/d)", "[f/m/x]", "(all genders)", "m/w/d".
    - Bracketed work-mode and urgency decorations are removed: "(Remote)", "[URGENT]",
      and a trailing "- Remote". Seniority words (senior, junior, lead, staff...) are
      never touched.
    - A trailing requisition or job id is removed: "(REQ-12345)", "- R-1234", "#12345",
      "Job ID: 99". Plain numbers shorter than five digits (years, levels) are kept.
    - After the shared steps, "&" becomes "and", "sr" becomes "senior" and "jr" becomes
      "junior". "+" and "#" stay when they end a word ("c++", "c#").
    A title that is nothing but noise becomes empty and so has no fingerprint.

Location, after the shared steps applied per part:
    - The text is split on ";", ",", "/" and "|" and newlines into parts.
    - Remote and worldwide wording ("Remote", "Anywhere", "Worldwide", "Global",
      "Work from home", "Remote - Worldwide") becomes the single token "remote". A part such
      as "Remote - European Union" yields "remote" plus "european union".
    - "hybrid" and "on-site" words are dropped.
    - Parts are de-duplicated and sorted, so order does not matter. Country codes are not
      guessed: "US" and "United States" stay different.
    - An empty location is allowed and is its own value.

A posting with no usable title or company gets no fingerprint (None), so it is never grouped
on empty fields. Changing anything above requires a new version prefix (fp2) and a deliberate
re-canonicalisation.
"""

import hashlib
import re
import unicodedata

FINGERPRINT_VERSION = "fp1"
FIELD_SEPARATOR = "\x1f"
LOCATION_JOINER = "|"
REMOTE_TOKEN = "remote"

ZERO_WIDTH_JOINERS = frozenset("‌‍")
KEPT_CATEGORIES = frozenset("LNM")
WORD_END_SYMBOLS = frozenset("+#")
MAX_NORMALISE_PASSES = 5

LEGAL_SUFFIXES = frozenset(
    {
        "inc",
        "incorporated",
        "llc",
        "llp",
        "lp",
        "ltd",
        "limited",
        "plc",
        "corp",
        "corporation",
        "co",
        "company",
        "gmbh",
        "ag",
        "kg",
        "ug",
        "se",
        "sa",
        "sarl",
        "srl",
        "spa",
        "bv",
        "nv",
        "ab",
        "oy",
        "oyj",
        "as",
        "asa",
        "aps",
        "pty",
        "pvt",
        "pte",
        "bhd",
        "sdn",
        "kk",
    }
)
PLACEHOLDER_COMPANIES = frozenset(
    {
        "confidential",
        "confidential company",
        "company confidential",
        "anonymous",
        "unknown",
        "undisclosed",
        "not specified",
        "not disclosed",
        "n a",
        "na",
        "none",
        "null",
        "tbd",
        "private employer",
        "private company",
        "hiring company",
        "various",
    }
)
TITLE_ABBREVIATIONS = {"sr": "senior", "jr": "junior"}

REMOTE_WORDS = frozenset({"remote", "remotely", "wfh", "telecommute", "telework", "teleworking"})
REMOTE_PHRASES = frozenset(
    {
        "worldwide",
        "world wide",
        "fully remote",
        "100 remote",
        "remote first",
        "remote only",
        "anywhere",
        "anywhere in the world",
        "global",
        "globally",
        "work from home",
        "home office",
        "distributed",
    }
)
LOCATION_NOISE_WORDS = frozenset({"hybrid", "onsite"})
LOCATION_SPLIT = re.compile(r"[;,/|\n\r]+")

_GENDER_LETTERS = r"[mfwdxhgn]"
_GENDER_INNER = (
    rf"(?:{_GENDER_LETTERS}(?:\s*[/,|\-]\s*{_GENDER_LETTERS}){{1,3}}"
    r"|[mfwdxh](?:\s*/\s*[mfwdxh])*\s*/\s*(?:non[- ]?binary|divers[e]?|nb)"
    r"|all\s+genders?|gender[- ]neutral|gn)"
)
GENDER_BRACKETED = re.compile(rf"[(\[]\s*{_GENDER_INNER}\s*(?:\*|:in|\*in)?\s*[)\]]")
GENDER_BARE = re.compile(r"(?<![\w/])(?:[mfwd]/[mfwd]/[dxmfwn]\*?|m/[fw]|[fw]/m|h/f|f/h)(?![\w/])")
DECORATION_BRACKETED = re.compile(
    r"[(\[]\s*(?:remote|hybrid|on[- ]?site|urgent|hiring|now hiring|new|wfh"
    r"|immediate(?:ly)? start)\s*[)\]]"
)
DECORATION_TRAILING = re.compile(r"\s*[,\-–—|:]\s*(?:remote|hybrid)\s*$")

_ID_KEYWORD = (
    r"(?:job\s*(?:id|no|number|ref)|req(?:uisition)?(?:\s*(?:id|no|number))?"
    r"|ref(?:erence)?(?:\s*(?:id|no|number|code))?|id|jr|job)"
)
_LOOSE_CODE = r"[a-z]{0,5}[-_]?\d{2,}(?:[-_/.][a-z0-9]+)*"
_STRONG_CODE = (
    r"(?:[a-z]{1,5}[-_]\d{3,}|(?:req|jr|job|id)\d{3,}|#\d{3,}|\d{5,})(?:[-_/.][a-z0-9]+)*"
)
_ID_BODY = rf"(?:{_ID_KEYWORD}[\s.:#-]*{_LOOSE_CODE}|{_STRONG_CODE})"
ID_BRACKETED = re.compile(rf"[(\[]\s*{_ID_BODY}\s*[)\]]")
ID_TRAILING = re.compile(rf"(?<![a-z0-9])(?<=[\s,\-–—|:/])\s*{_ID_BODY}\s*$")
TITLE_NOISE_PATTERNS = (
    GENDER_BRACKETED,
    GENDER_BARE,
    DECORATION_BRACKETED,
    DECORATION_TRAILING,
    ID_BRACKETED,
    ID_TRAILING,
)


def _normalise_unicode(text: str) -> str:
    folded = unicodedata.normalize("NFKC", unicodedata.normalize("NFKC", text).casefold())
    return "".join(
        char for char in folded if char in ZERO_WIDTH_JOINERS or unicodedata.category(char) != "Cf"
    )


def _is_kept(char: str) -> bool:
    return unicodedata.category(char)[0] in KEPT_CATEGORIES or char in ZERO_WIDTH_JOINERS


def _keeps(text: str, index: int, keep_word_end_symbols: bool) -> bool:
    char = text[index]
    if _is_kept(char):
        return True
    return keep_word_end_symbols and char in WORD_END_SYMBOLS and _ends_word(text, index)


def _collapse(text: str, *, keep_word_end_symbols: bool = False) -> str:
    """Keep letters, digits and marks; everything else becomes one space."""
    out = [
        char if _keeps(text, index, keep_word_end_symbols) else " "
        for index, char in enumerate(text)
    ]
    return " ".join("".join(out).split())


def _ends_word(text: str, index: int) -> bool:
    """True for the "+" or "#" of "c++" or "c#": after a letter or digit, then a boundary."""
    run_start = index
    while run_start > 0 and text[run_start - 1] in WORD_END_SYMBOLS:
        run_start -= 1
    run_end = index
    while run_end + 1 < len(text) and text[run_end + 1] in WORD_END_SYMBOLS:
        run_end += 1
    if run_start == 0 or unicodedata.category(text[run_start - 1])[0] not in "LN":
        return False
    return run_end + 1 >= len(text) or not _is_kept(text[run_end + 1])


def _strip_title_noise(text: str) -> str:
    """Apply every noise pattern once, never emptying the title."""
    for pattern in TITLE_NOISE_PATTERNS:
        stripped = pattern.sub(" ", text)
        if stripped.strip(" \t-–—|:,/"):
            text = stripped
    return text


def _normalise_title_pass(text: str) -> str:
    cleaned = _strip_title_noise(text.replace("&", " and "))
    words = _collapse(cleaned, keep_word_end_symbols=True).split()
    return " ".join(TITLE_ABBREVIATIONS.get(word, word) for word in words)


def normalise_title(title: str | None) -> str:
    text = _normalise_unicode(title or "")
    for _ in range(MAX_NORMALISE_PASSES):
        updated = _normalise_title_pass(text)
        if updated == text:
            break
        text = updated
    return text


def _strip_legal_suffixes(words: list[str]) -> list[str]:
    """Drop trailing legal-form words; "and" goes too when it only joined them ("GmbH & Co")."""
    remaining = list(words)
    stripped = False
    while len(remaining) > 1:
        last = remaining[-1]
        if last in LEGAL_SUFFIXES or (last == "and" and stripped):
            stripped = stripped or last in LEGAL_SUFFIXES
            remaining.pop()
        else:
            break
    return remaining


def normalise_company(company: str | None) -> str:
    text = _normalise_unicode(company or "").replace("&", " and ")
    words = _collapse(text.replace(".", "").replace("'", "").replace("’", "")).split()
    while words[:1] == ["the"] and len(words) > 1:
        words = words[1:]
    words = _strip_legal_suffixes(words)
    normalised = " ".join(words)
    return "" if normalised in PLACEHOLDER_COMPANIES else normalised


def _drop_noise_words(words: list[str]) -> list[str]:
    """Remove "hybrid", "onsite" and "on site" from a list of words."""
    kept: list[str] = []
    for index, word in enumerate(words):
        previous_is_on = index > 0 and words[index - 1] == "on"
        if word in LOCATION_NOISE_WORDS or (word == "site" and previous_is_on):
            if word == "site":
                kept.pop()
            continue
        kept.append(word)
    return kept


def _location_tokens(part: str) -> set[str]:
    """Normalise one part (already split on separators) into zero or more tokens."""
    words = _drop_noise_words(_collapse(_normalise_unicode(part)).split())
    text = " ".join(words)
    rest = " ".join(word for word in words if word not in REMOTE_WORDS)
    if text in REMOTE_PHRASES or rest in REMOTE_PHRASES:
        return {REMOTE_TOKEN}
    tokens = {rest} if rest else set()
    has_remote_word = rest != text
    return tokens | {REMOTE_TOKEN} if has_remote_word else tokens


def normalise_location(location: str | None) -> str:
    tokens: set[str] = set()
    for part in LOCATION_SPLIT.split(location or ""):
        tokens |= _location_tokens(part)
    return LOCATION_JOINER.join(sorted(tokens))


def fingerprint(*, title: str | None, company: str | None, location: str | None) -> str | None:
    """The versioned fingerprint of a job, or None when title or company is unusable."""
    normalised_title = normalise_title(title)
    normalised_company = normalise_company(company)
    if not normalised_title or not normalised_company:
        return None
    material = FIELD_SEPARATOR.join(
        (normalised_company, normalised_title, normalise_location(location))
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return f"{FINGERPRINT_VERSION}:{digest}"
