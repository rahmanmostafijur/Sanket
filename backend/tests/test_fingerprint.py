import random

import pytest

from sanket.canonical.fingerprint import (
    FINGERPRINT_VERSION,
    fingerprint,
    normalise_company,
    normalise_location,
    normalise_title,
)


def fp(title: str | None, company: str | None, location: str | None = None) -> str | None:
    return fingerprint(title=title, company=company, location=location)


def test_fingerprint_is_versioned_sha256_hex() -> None:
    value = fp("Backend Engineer", "Acme", "Berlin")

    assert value is not None
    prefix, _, digest = value.partition(":")
    assert prefix == FINGERPRINT_VERSION == "fp1"
    assert len(digest) == 64
    int(digest, 16)


def test_fingerprint_is_stable_across_calls() -> None:
    assert fp("Backend Engineer", "Acme", "Berlin") == fp("Backend Engineer", "Acme", "Berlin")


def test_fingerprint_pins_the_algorithm_output() -> None:
    """A change here means fp1 changed: add fp2 and re-canonicalise on purpose."""
    value = fp("Backend Engineer", "Acme Inc.", "Remote - Worldwide")

    assert value == "fp1:0590e4adbec851042b66453d8963807a7ea48bb6c82cc3676c7cdd99398942cb"


@pytest.mark.parametrize(
    ("a", "b"),
    [
        # Same job across sources: legal suffix, case, punctuation, gender marker, id.
        (
            ("Senior Python Developer (m/f/d)", "Acme GmbH", "Berlin"),
            ("senior python developer", "ACME", "berlin"),
        ),
        (("Backend Engineer", "Acme, Inc.", "Remote"), ("Backend Engineer", "Acme", "Anywhere")),
        (
            ("Backend Engineer", "Acme", "Remote - Worldwide"),
            ("Backend Engineer", "Acme", "Worldwide"),
        ),
        (
            ("Data Engineer [f/m/x]", "The Acme Company", "Stockholm"),
            ("Data Engineer", "Acme", "Stockholm"),
        ),
        (("Data Engineer (REQ-12345)", "Acme", "Paris"), ("Data Engineer", "Acme", "Paris")),
        (("Data Engineer - R-98765", "Acme", "Paris"), ("Data Engineer", "Acme", "Paris")),
        (("Data Engineer #55555", "Acme", "Paris"), ("Data Engineer", "Acme", "Paris")),
        (("Data Engineer (Job ID: 99)", "Acme", "Paris"), ("Data Engineer", "Acme", "Paris")),
        (("Data Engineer (Remote)", "Acme", "Paris"), ("Data Engineer", "Acme", "Paris")),
        (("Data Engineer - Remote", "Acme", "Paris"), ("Data Engineer", "Acme", "Paris")),
        (("Sr. Data Engineer", "Acme", "Paris"), ("Senior Data Engineer", "Acme", "Paris")),
        (
            ("Data  Engineer / Analyst", "Acme", "Paris"),
            ("Data Engineer - Analyst", "Acme", "Paris"),
        ),
        (
            ("R&D Engineer", "Smith & Sons Ltd", "Paris"),
            ("R and D Engineer", "Smith and Sons", "Paris"),
        ),
        # Location order and separators do not matter.
        (("Engineer", "Acme", "Berlin; Munich"), ("Engineer", "Acme", "Munich, Berlin")),
        (("Engineer", "Acme", "Berlin, Germany"), ("Engineer", "Acme", "Germany / Berlin")),
        (("Engineer", "Acme", "Berlin (Hybrid)"), ("Engineer", "Acme", "Berlin")),
        (("Engineer", "Acme", "Remote, US"), ("Engineer", "Acme", "US (Remote)")),
        # Wide characters and compatibility forms fold under NFKC.
        (("Ｅｎｇｉｎｅｅｒ", "Acme", "Paris"), ("Engineer", "Acme", "Paris")),
        # Whitespace-only differences, including non-breaking spaces.
        (("Data Engineer ", " Acme", "Paris"), ("Data Engineer", "Acme", "Paris")),
    ],
)
def test_same_job_collapses(a: tuple[str, str, str], b: tuple[str, str, str]) -> None:
    first = fp(a[0], a[1], a[2])

    assert first is not None
    assert first == fp(b[0], b[1], b[2])


@pytest.mark.parametrize(
    ("a", "b"),
    [
        (("Backend Engineer", "Acme", "Berlin"), ("Backend Engineer", "Globex", "Berlin")),
        (("Backend Engineer", "Acme", "Berlin"), ("Frontend Engineer", "Acme", "Berlin")),
        (("Backend Engineer", "Acme", "Berlin"), ("Backend Engineer", "Acme", "Munich")),
        (("Backend Engineer", "Acme", "Berlin"), ("Backend Engineer", "Acme", "Berlin, Munich")),
        (("Backend Engineer", "Acme", "Berlin"), ("Backend Engineer", "Acme", None)),
        (("Backend Engineer", "Acme", "Hybrid"), ("Backend Engineer", "Acme", None)),
        (("Backend Engineer", "Acme", "Remote"), ("Backend Engineer", "Acme", "Berlin")),
        # Seniority and levels are real differences.
        (("Senior Engineer", "Acme", "Berlin"), ("Junior Engineer", "Acme", "Berlin")),
        (("Engineer II", "Acme", "Berlin"), ("Engineer III", "Acme", "Berlin")),
        (("Engineer 2", "Acme", "Berlin"), ("Engineer 3", "Acme", "Berlin")),
        (("Intern Summer 2025", "Acme", "Berlin"), ("Intern Summer 2026", "Acme", "Berlin")),
        (("C++ Developer", "Acme", "Berlin"), ("C Developer", "Acme", "Berlin")),
        (("C# Developer", "Acme", "Berlin"), ("C++ Developer", "Acme", "Berlin")),
        (("Engineer", "Acme Labs", "Berlin"), ("Engineer", "Acme Group", "Berlin")),
        # Country codes are not guessed.
        (("Engineer", "Acme", "US"), ("Engineer", "Acme", "United States")),
        # Accents are not folded, so Swedish and German words stay distinct.
        (("Engineer", "Acme", "Malmö"), ("Engineer", "Acme", "Malmo")),
        (("Ingenjör", "Acme", "Malmö"), ("Ingenjor", "Acme", "Malmö")),
    ],
)
def test_different_jobs_stay_apart(
    a: tuple[str, str, str | None], b: tuple[str, str, str | None]
) -> None:
    assert fp(*a) != fp(*b)


def test_non_latin_scripts_survive_normalisation() -> None:
    assert normalise_title("সফটওয়্যার ইঞ্জিনিয়ার (m/f/d)") == "সফটওয়্যার ইঞ্জিনিয়ার"
    assert normalise_company("প্রোগ্রামার্স লিমিটেড") == "প্রোগ্রামার্স লিমিটেড"
    assert normalise_location("ঢাকা, বাংলাদেশ") == "ঢাকা|বাংলাদেশ"
    assert normalise_title("ソフトウェアエンジニア") == "ソフトウェアエンジニア"
    assert normalise_title("Инженер-программист") == "инженер программист"


def test_swedish_and_other_latin_letters_survive() -> None:
    assert normalise_title("Systemutvecklare Åre Ödeshög Älmhult") == (
        "systemutvecklare åre ödeshög älmhult"
    )
    assert normalise_location("Göteborg; Malmö") == "göteborg|malmö"
    assert normalise_company("Ericsson AB") == "ericsson"


def test_bengali_titles_distinguish_different_jobs() -> None:
    assert fp("সফটওয়্যার ইঞ্জিনিয়ার", "Acme", "ঢাকা") != fp("হিসাবরক্ষক", "Acme", "ঢাকা")
    assert fp("সফটওয়্যার ইঞ্জিনিয়ার", "Acme", "ঢাকা") is not None


@pytest.mark.parametrize(
    ("title", "company", "location"),
    [
        (None, "Acme", "Berlin"),
        ("", "Acme", "Berlin"),
        ("   ", "Acme", "Berlin"),
        ("(m/f/d)", "Acme", "Berlin"),
        ("!!!", "Acme", "Berlin"),
        ("Engineer", None, "Berlin"),
        ("Engineer", "", "Berlin"),
        ("Engineer", "   ", "Berlin"),
        ("Engineer", "---", "Berlin"),
        ("Engineer", "Confidential", "Berlin"),
        ("Engineer", "N/A", "Berlin"),
        ("Engineer", "Unknown", "Berlin"),
    ],
)
def test_unusable_title_or_company_gives_no_fingerprint(
    title: str | None, company: str | None, location: str | None
) -> None:
    assert fp(title, company, location) is None


def test_missing_location_still_fingerprints() -> None:
    assert fp("Engineer", "Acme", None) == fp("Engineer", "Acme", "  ")
    assert fp("Engineer", "Acme", None) is not None


def test_a_company_that_is_only_a_legal_suffix_keeps_its_name() -> None:
    assert normalise_company("Inc") == "inc"
    assert normalise_company("Acme Co Ltd") == "acme"
    assert normalise_company("Acme S.A.") == "acme"
    assert normalise_company("Acme Sdn Bhd") == "acme"
    assert normalise_company("Müller GmbH & Co. KG") == "müller"
    assert normalise_company("Johnson and Co") == "johnson"
    assert normalise_company("Smith and Sons Ltd") == "smith and sons"


def test_a_bare_remote_title_is_not_treated_as_a_decoration() -> None:
    assert normalise_title("Remote") == "remote"
    assert normalise_title("12345") == "12345"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Remote", "remote"),
        ("Anywhere", "remote"),
        ("Worldwide", "remote"),
        ("Remote - Worldwide", "remote"),
        ("Remote - Anywhere", "remote"),
        ("Anywhere in the World", "remote"),
        ("Work from home", "remote"),
        ("Fully Remote", "remote"),
        ("Remote - European Union", "european union|remote"),
        ("Remote; Berlin", "berlin|remote"),
        ("Berlin; Berlin", "berlin"),
        ("Zurich, Switzerland; Remote", "remote|switzerland|zurich"),
        ("Hybrid", "hybrid"),
        ("Berlin (Hybrid)", "berlin"),
        ("Berlin, On-site", "berlin|on site"),
        ("Berlin on-site", "berlin"),
        ("", ""),
        (None, ""),
    ],
)
def test_location_normalisation(raw: str | None, expected: str) -> None:
    assert normalise_location(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Senior Engineer (m/f/d)", "senior engineer"),
        ("Engineer (m/w/d)", "engineer"),
        ("Engineer (d/f/m)", "engineer"),
        ("Engineer m/f/d", "engineer"),
        ("Engineer (all genders)", "engineer"),
        ("Engineer (m/f/non-binary)", "engineer"),
        ("Engineer (REQ-12345) (m/f/d)", "engineer"),
        ("Engineer [URGENT]", "engineer"),
        ("Engineer (JR1234)", "engineer"),
        ("Engineer - 12345", "engineer"),
        ("Engineer 12345", "engineer"),
        ("Engineer (Ref: AB-77)", "engineer"),
        ("Web3 Engineer", "web3 engineer"),
        ("Windows Server 2019 Admin", "windows server 2019 admin"),
        ("Engineer L5", "engineer l5"),
        ("SDE-2", "sde 2"),
        ("Engineer (m)", "engineer m"),
        ("Remote Sales Representative", "remote sales representative"),
        ("Node.js Developer", "node js developer"),
        ("C++/C# Developer", "c++ c# developer"),
        ("Women's Health Lead", "women s health lead"),
    ],
)
def test_title_noise_is_stripped_and_signal_kept(raw: str, expected: str) -> None:
    assert normalise_title(raw) == expected


INPUTS = [
    ("Senior Python Developer (m/f/d) - REQ-12345", "Acme GmbH & Co. KG", "Berlin; Remote"),
    ("সফটওয়্যার ইঞ্জিনিয়ার", "প্রোগ্রামার্স লিমিটেড", "ঢাকা, বাংলাদেশ"),
    ("Systemutvecklare (m/k/x) #99999", "Ericsson AB", "Göteborg / Malmö"),
    ("C++ Developer - Remote", "The Trade Desk, Inc.", "Remote - Worldwide"),
    ("Ｅｎｇ ｉ ｎｅｅｒ  [URGENT] (Job ID: 12)", "  Acme   Corp ", "  "),
    ("Engineer - 12345 (m/f/d)", "O'Neil & Sons S.A.", "Hybrid; Anywhere"),
    ("A" * 200, "Zeta" + "­" * 3 + "Corp", "a,b;c|d/e"),
]


@pytest.mark.parametrize(("title", "company", "location"), INPUTS)
def test_normalisation_is_idempotent(title: str, company: str, location: str) -> None:
    once_title = normalise_title(title)
    once_company = normalise_company(company)
    once_location = normalise_location(location)

    assert normalise_title(once_title) == once_title
    assert normalise_company(once_company) == once_company
    assert normalise_location(once_location) == once_location
    assert fp(once_title, once_company, once_location) == fp(title, company, location)


@pytest.mark.parametrize("seed", range(5))
def test_fingerprint_ignores_location_order(seed: int) -> None:
    parts = ["Berlin", "Munich", "Remote", "Hamburg", "Köln", "Wien"]
    shuffled = random.Random(seed).sample(parts, len(parts))

    assert fp("Engineer", "Acme", "; ".join(parts)) == fp("Engineer", "Acme", ", ".join(shuffled))


def test_fingerprint_changes_with_each_field() -> None:
    base = fp("Engineer", "Acme", "Berlin")
    assert base != fp("Engineer 2", "Acme", "Berlin")
    assert base != fp("Engineer", "Acme2", "Berlin")
    assert base != fp("Engineer", "Acme", "Berlin2")


def test_fields_cannot_bleed_into_each_other() -> None:
    assert fp("b c", "a", "d") != fp("c", "a b", "d")
    assert fp("x", "a", "b y") != fp("x y", "a", "b")


ALPHABET = "abcXYZ019 -_/()[]#+&.,;|'*:åöকী‍­Ａmfdwxrqeid"


@pytest.mark.parametrize("seed", range(20))
def test_normalisation_is_idempotent_on_random_text(seed: int) -> None:
    rng = random.Random(seed)
    text = "".join(rng.choice(ALPHABET) for _ in range(rng.randint(0, 60)))

    assert normalise_title(normalise_title(text)) == normalise_title(text)
    assert normalise_company(normalise_company(text)) == normalise_company(text)
    assert normalise_location(normalise_location(text)) == normalise_location(text)
