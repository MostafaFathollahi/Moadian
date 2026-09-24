"""The شناسه کالا/خدمت catalogue store.

Shaped after the real export: the same code appearing more than once with a
different VAT rate and the older row carrying an ExpirationDate, which is 74k of
the 208k rows in the services file.
"""

from __future__ import annotations

import pytest

from moadian.store import CatalogueStore


def row(stuff_id, description, vat=10.0, *, expired=False, run="1405-07-01", taxable="مشمول"):
    return {
        "stuff_id": stuff_id,
        "description": description,
        "vat_rate": vat,
        "taxable": taxable,
        "run_date": run,
        "expiration_date": "1405-07-01" if expired else None,
        "kind": "شناسه اختصاصی خدمت",
        "pricing": None,
        "is_current": 0 if expired else 1,
    }


ROWS = [
    row("2330003073403", "خدمات اموزش اشپزی/برگزاری دوره اموزش اشپزی مقدماتی"),
    row("2330004567413", "خدمات مجوز (license) نرم افزار یا سخت افزار کامپیوتر/تخصیص لایسنس"),
    row("2330004567420", "پشتیبانی و نگهداری نرم افزار خاص صنعت/پشتیبانی یک ساله"),
    row("2330000075516", "پشتیبانی و نگهداری تجهیزات شبکه/خدمات نگهداری شبکه"),
    # A rate change: the old row is expired, the new one is current.
    row("2330009999999", "خدمات مشاوره مدیریت", vat=9.0, expired=True, run="1403-09-04"),
    row("2330009999999", "خدمات مشاوره مدیریت", vat=10.0, run="1405-07-02"),
]


@pytest.fixture
def store(tmp_path):
    store = CatalogueStore(tmp_path / "catalogue.sqlite")
    store.replace_all(list(ROWS), source="test.csv")
    yield store
    store.close()


def ids(entries):
    return [e.stuff_id for e in entries]


# -- status -----------------------------------------------------------------


def test_an_unloaded_catalogue_reports_itself_empty(tmp_path) -> None:
    """The invoice form needs this to say so, rather than look broken."""
    store = CatalogueStore(tmp_path / "catalogue.sqlite")
    status = store.status()
    assert status["empty"] is True
    assert status["total"] == 0
    assert status["importedAt"] is None
    assert store.search("خدمات") == []


def test_status_counts_current_and_superseded_separately(store: CatalogueStore) -> None:
    status = store.status()
    assert status["total"] == len(ROWS)
    assert status["current"] == len(ROWS) - 1
    assert status["superseded"] == 1
    assert status["source"] == "test.csv"
    assert status["empty"] is False


# -- searching by number ----------------------------------------------------


def test_a_full_identifier_finds_exactly_one(store: CatalogueStore) -> None:
    assert ids(store.search("2330004567413")) == ["2330004567413"]


def test_a_partial_identifier_matches_by_prefix(store: CatalogueStore) -> None:
    assert set(ids(store.search("23300045"))) == {"2330004567413", "2330004567420"}


def test_persian_digits_find_the_same_code(store: CatalogueStore) -> None:
    """A شناسه pasted from a Persian PDF or spreadsheet arrives like this."""
    assert ids(store.search("۲۳۳۰۰۰۴۵۶۷۴۱۳")) == ["2330004567413"]


def test_a_number_that_matches_nothing_returns_nothing(store: CatalogueStore) -> None:
    assert store.search("9999999999999") == []


# -- searching by description -----------------------------------------------


def test_two_words_both_have_to_match(store: CatalogueStore) -> None:
    """Typing more words narrows. That is what the gesture means."""
    both = ids(store.search("نگهداری شبکه"))
    assert "2330000075516" in both
    assert "2330004567420" not in both, "matched on only one of the two words"


def test_an_unfinished_word_still_matches(store: CatalogueStore) -> None:
    """Results have to appear while typing, not only after a word is complete."""
    assert "2330004567413" in ids(store.search("لایسن"))


def test_a_query_typed_with_arabic_letters_matches_a_persian_row(
    store: CatalogueStore,
) -> None:
    """The row is spelled اشپزی; the operator types آشپزي. Same word."""
    assert "2330003073403" in ids(store.search("آشپزي"))


def test_latin_inside_a_persian_description_is_findable(store: CatalogueStore) -> None:
    assert "2330004567413" in ids(store.search("license"))


# -- what search must never return ------------------------------------------


def test_a_superseded_row_is_never_offered(store: CatalogueStore) -> None:
    """Offering an expired VAT rate produces a rejection whose cause is invisible
    on the screen that caused it."""
    hits = store.search("مشاوره مدیریت")
    assert ids(hits) == ["2330009999999"]
    assert [h.vat_rate for h in hits] == [10.0], "returned the expired 9% row"
    assert all(h.is_current for h in hits)


@pytest.mark.parametrize("query", ["", "   ", None])
def test_an_empty_query_returns_nothing_rather_than_everything(store, query) -> None:
    assert store.search(query or "") == []


@pytest.mark.parametrize(
    "query",
    ['"', 'خدمات"', "AND", "OR", "NOT", "NEAR", "*", "(", ")", "a:b", 'x" OR "y', "^"],
)
def test_fts5_operators_typed_as_text_do_not_break_the_search(store, query) -> None:
    """Every one of these means something to FTS5. Passed through, they are a
    syntax error or a silently different query — from an ordinary search box."""
    store.search(query)  # must not raise


def test_a_very_long_query_is_handled(store: CatalogueStore) -> None:
    store.search("نرم " * 200)


# -- history and lookup -----------------------------------------------------


def test_history_returns_every_rate_the_code_has_carried(store: CatalogueStore) -> None:
    """An اصلاحی has to reproduce the rate its original invoice was issued under."""
    history = store.history("2330009999999")
    assert len(history) == 2
    assert [h.vat_rate for h in history] == [10.0, 9.0], "not newest first"
    assert [h.is_current for h in history] == [True, False]


def test_get_prefers_the_current_row(store: CatalogueStore) -> None:
    entry = store.get("2330009999999")
    assert entry is not None
    assert entry.vat_rate == 10.0
    assert entry.is_current


def test_get_accepts_persian_digits(store: CatalogueStore) -> None:
    assert store.get("۲۳۳۰۰۰۴۵۶۷۴۱۳") is not None


def test_get_on_an_unknown_code_is_none(store: CatalogueStore) -> None:
    assert store.get("1111111111111") is None


# -- replacement ------------------------------------------------------------


def test_replacing_drops_what_the_organization_withdrew(store: CatalogueStore) -> None:
    """Merging instead of replacing would leave withdrawn codes on offer forever,
    indistinguishable from current ones."""
    assert store.get("2330004567413") is not None
    store.replace_all([row("2330001111111", "خدمات تازه")], source="second.csv")
    assert store.get("2330004567413") is None
    assert store.get("2330001111111") is not None
    assert store.status()["total"] == 1
    assert store.status()["source"] == "second.csv"


def test_the_index_is_rebuilt_on_replacement(store: CatalogueStore) -> None:
    """A stale FTS index would keep answering for rows that no longer exist."""
    store.replace_all([row("2330001111111", "خدمات تازه و بی‌سابقه")], source="second.csv")
    assert store.search("اشپزی") == []
    assert ids(store.search("تازه")) == ["2330001111111"]


def test_replacing_with_nothing_empties_the_catalogue(store: CatalogueStore) -> None:
    store.replace_all([])
    assert store.status()["empty"] is True
    assert store.search("خدمات") == []


def test_an_exactly_duplicated_row_is_stored_once(tmp_path) -> None:
    """The real export contains a handful of these."""
    store = CatalogueStore(tmp_path / "c.sqlite")
    entry = row("2330004567413", "خدمات مجوز")
    store.replace_all([entry, dict(entry)])
    assert store.status()["total"] == 1


def test_a_fourteen_digit_identifier_survives_the_round_trip(tmp_path) -> None:
    """One row of the official services export really is 14 digits. Storing these
    as INTEGER, or rejecting them at import, loses a code the organization
    published."""
    store = CatalogueStore(tmp_path / "c.sqlite")
    store.replace_all([row("23300032442921", "اماده سازی قبر")])
    entry = store.get("23300032442921")
    assert entry is not None and entry.stuff_id == "23300032442921"


def test_the_result_limit_is_honoured_and_bounded(store: CatalogueStore) -> None:
    assert len(store.search("خدمات", limit=2)) <= 2
    assert len(store.search("خدمات", limit=10_000)) <= 100
    assert len(store.search("خدمات", limit=0)) >= 0
