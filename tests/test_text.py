import pytest

from plainmem.text import STOPWORDS, porter_stem, tokenize, words


@pytest.mark.parametrize(
    ("word", "stem"),
    [
        ("caresses", "caress"),
        ("ponies", "poni"),
        ("cats", "cat"),
        ("feed", "feed"),
        ("agreed", "agre"),
        ("plastered", "plaster"),
        ("motoring", "motor"),
        ("sing", "sing"),
        ("hopping", "hop"),
        ("falling", "fall"),
        ("filing", "file"),
        ("happy", "happi"),
        ("relational", "relat"),
        ("conditional", "condit"),
        ("rational", "ration"),
        ("digitizer", "digit"),
        ("generalization", "gener"),
        ("hopeful", "hope"),
        ("goodness", "good"),
        ("electrical", "electr"),
        ("adjustment", "adjust"),
        ("relocating", "reloc"),
        ("relocate", "reloc"),
    ],
)
def test_porter_reference_words(word: str, stem: str) -> None:
    assert porter_stem(word) == stem


def test_inflections_share_a_stem() -> None:
    assert porter_stem("meetings") == porter_stem("meeting") == porter_stem("meet")
    assert porter_stem("builds") == porter_stem("build")


def test_short_numeric_and_non_ascii_tokens_pass_through() -> None:
    assert porter_stem("is") == "is"
    assert porter_stem("2026") == "2026"
    assert porter_stem("v2beta") == "v2beta"
    assert porter_stem("日本語") == "日本語"


def test_words_casefold_and_strip_accents() -> None:
    assert words("Café CRÈME brûlée") == ["cafe", "creme", "brulee"]


def test_words_drop_possessive_and_keep_digits() -> None:
    assert words("Mara's phone: 555-0142") == ["mara", "phone", "555", "0142"]
    assert words("Mara’s") == ["mara"]


def test_words_unicode_scripts() -> None:
    assert words("東京 meeting") == ["東京", "meeting"]
    assert words("") == []
    assert words("   \n\t ") == []


def test_tokenize_removes_stopwords_and_stems() -> None:
    assert tokenize("The meetings were in the morning") == ["meet", "morn"]
    assert tokenize("The meetings", stem=False) == ["meetings"]
    assert tokenize("the a an", drop_stopwords=True) == []
    assert "the" in tokenize("the", drop_stopwords=False)


def test_stopword_list_is_lowercase() -> None:
    assert all(w == w.lower() for w in STOPWORDS)
