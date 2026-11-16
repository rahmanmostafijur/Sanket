import pytest

from sanket.extraction.prompt import (
    TRUNCATION_MARKER,
    PostingInput,
    build_posting_text,
    html_to_text,
    repair_message,
    truncate,
)

BIG_LIMIT = 10_000


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ("", ""),
        ("   \n\t  ", ""),
        ("plain text", "plain text"),
        ("<p>Hello</p><p>World</p>", "Hello\nWorld"),
        ("<p>a</p>\n\n<p>b</p>", "a\nb"),
        ("a<br>b<br/>c", "a\nb\nc"),
        ("<ul><li>One</li><li>Two</li></ul>", "One\nTwo"),
        ("<h2>Title</h2><p>Body</p>", "Title\nBody"),
    ],
)
def test_html_to_text_puts_block_elements_on_their_own_lines(html: str, expected: str) -> None:
    assert html_to_text(html) == expected


def test_html_to_text_does_not_break_lines_for_inline_tags() -> None:
    assert html_to_text("foo<b>bar</b> and <i>baz</i>") == "foobar and baz"


def test_html_to_text_handles_nested_lists() -> None:
    html = "<div><p>Intro</p><ul><li>A<ul><li>B</li></ul></li></ul></div>"

    assert html_to_text(html) == "Intro\nA\nB"


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ("Tom &amp; Jerry", "Tom & Jerry"),
        ("&eacute;t&eacute;", "été"),
        ("&#8364;100", "€100"),
        ("x&nbsp;&nbsp;y", "x y"),
        ("5 &lt; 6 &gt; 4", "5 < 6 > 4"),
        ("&unknown; stays", "&unknown; stays"),
        ("trailing &amp", "trailing &"),
    ],
)
def test_html_to_text_decodes_entities(html: str, expected: str) -> None:
    assert html_to_text(html) == expected


def test_html_to_text_keeps_escaped_markup_as_text() -> None:
    assert html_to_text("&lt;b&gt;not a tag&lt;/b&gt;") == "<b>not a tag</b>"


def test_html_to_text_collapses_whitespace_and_drops_blank_lines() -> None:
    assert html_to_text("  a   \t b \n\n\n c  ") == "a b\nc"


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ("<p>Hello <b>world", "Hello world"),
        ("</div>stray<p>a</p></p>", "stray\na"),
        ('<a href="x>y">link</a>', "link"),
        ("<!-- a comment -->text", "text"),
        ("a < b and c > d", "a < b and c > d"),
    ],
)
def test_html_to_text_survives_malformed_html(html: str, expected: str) -> None:
    assert html_to_text(html) == expected


def test_html_to_text_does_not_raise_on_a_truncated_tag() -> None:
    assert "Hello" in html_to_text("Hello <div")


def test_html_to_text_keeps_non_ascii_text() -> None:
    assert html_to_text("<p>Grüße — café</p>") == "Grüße — café"


def test_truncate_leaves_text_within_the_limit_alone() -> None:
    assert truncate("abcde", 5) == "abcde"
    assert truncate("", 5) == ""


def test_truncate_cuts_at_the_limit_and_marks_the_cut() -> None:
    assert truncate("abcdefgh", 5) == "abcde" + TRUNCATION_MARKER


def test_truncate_trims_whitespace_before_the_marker() -> None:
    assert truncate("abc    defgh", 5) == "abc" + TRUNCATION_MARKER


def test_build_posting_text_lists_every_field() -> None:
    posting = PostingInput(
        title="Backend Engineer",
        company="Acme",
        location="Berlin",
        salary_text="50000-80000 USD per year",
        description="<p>Build APIs.</p><p>Own uptime.</p>",
    )

    assert build_posting_text(posting, BIG_LIMIT) == (
        "<posting>\n"
        "Title: Backend Engineer\n"
        "Company: Acme\n"
        "Location: Berlin\n"
        "Salary: 50000-80000 USD per year\n"
        "\n"
        "Description:\n"
        "Build APIs.\n"
        "Own uptime.\n"
        "</posting>"
    )


def test_build_posting_text_omits_missing_and_empty_fields() -> None:
    posting = PostingInput("Engineer", None, "", None, "Text")

    assert build_posting_text(posting, BIG_LIMIT) == (
        "<posting>\nTitle: Engineer\n\nDescription:\nText\n</posting>"
    )


def test_build_posting_text_with_no_fields_still_returns_a_valid_envelope() -> None:
    posting = PostingInput(None, None, None, None, None)

    assert build_posting_text(posting, BIG_LIMIT) == "<posting>\n\n\nDescription:\n\n</posting>"


def test_build_posting_text_treats_an_empty_description_like_a_missing_one() -> None:
    empty = PostingInput("Engineer", None, None, None, "")
    missing = PostingInput("Engineer", None, None, None, None)

    assert build_posting_text(empty, BIG_LIMIT) == build_posting_text(missing, BIG_LIMIT)


def test_build_posting_text_strips_description_markup() -> None:
    description = "<div><b>Must</b> know SQL &amp; Python</div>"
    posting = PostingInput("Engineer", None, None, None, description)

    text = build_posting_text(posting, BIG_LIMIT)

    assert "Must know SQL & Python" in text
    assert "<div>" not in text
    assert "<b>" not in text


def test_build_posting_text_truncates_long_descriptions_and_marks_it() -> None:
    posting = PostingInput("Engineer", None, None, None, "x" * 100)

    text = build_posting_text(posting, 10)

    assert f"Description:\n{'x' * 10}{TRUNCATION_MARKER}\n</posting>" in text
    assert "x" * 11 not in text


def test_build_posting_text_counts_the_limit_on_text_not_markup() -> None:
    posting = PostingInput("Engineer", None, None, None, "<p><b>" + "x" * 10 + "</b></p>")

    text = build_posting_text(posting, 10)

    assert TRUNCATION_MARKER not in text


def test_build_posting_text_does_not_truncate_a_description_at_exactly_the_limit() -> None:
    posting = PostingInput("Engineer", None, None, None, "x" * 10)

    assert TRUNCATION_MARKER not in build_posting_text(posting, 10)


def test_repair_message_includes_the_validation_errors() -> None:
    message = repair_message("work_mode: bad value")

    assert "work_mode: bad value" in message
    assert "JSON" in message
