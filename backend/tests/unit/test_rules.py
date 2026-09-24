"""The RC_IITP rules engine.

The anchor test is :func:`test_the_documented_example_validates_cleanly`: the
invoice printed in RC_TICS p.20 is one the organization itself published as
well-formed, so an engine that rejects it is wrong regardless of how defensible
its rule looks. Everything else is built around not breaking that.
"""

from __future__ import annotations

import pytest

from moadian.errors import ConfigurationError, InvoiceValidationError
from moadian.models import Invoice, InvoiceBodyItem, InvoiceHeader
from moadian.rules import (
    Obligation,
    RuleEngine,
    Severity,
    check_arithmetic,
    load_rules,
    recompute,
)
from moadian.rules.spec import SPEC_PATH


@pytest.fixture(scope="module")
def engine() -> RuleEngine:
    return RuleEngine()


def documented_invoice(**header_overrides) -> Invoice:
    """The worked example from RC_TICS p.20, a genuine الگوی اول invoice."""
    header = {
        "taxid": "A1121604C220002F095011",
        "inno": "49321217",
        "indatim": 1683997837988,
        "inty": 1,
        "inp": 1,
        "ins": 1,
        "tins": "14003778990",
        "tob": 2,
        "bid": "10100302746",
        "tinb": "10100302746",
        "tprdis": 20000,
        "tdis": 500,
        "tadis": 19500,
        "tvam": 1755,
        "todam": 0,
        "tbill": 21255,
        "setm": 2,
    }
    header.update(header_overrides)
    return Invoice(
        header=InvoiceHeader(**header),
        body=[
            InvoiceBodyItem(
                sstid="2710000138624",
                sstt="سرسیلندر قطعات صنعت فولاد سازی",
                mu="164",
                am=2,
                fee=10000,
                prdis=20000,
                dis=500,
                adis=19500,
                vra=9,
                vam=1755,
                tsstam=21255,
            )
        ],
    )


def codes(report) -> set[str]:
    return {v.rule for v in report.violations}


# ----------------------------------------------------------------- the anchor


def test_the_documented_example_validates_cleanly(engine: RuleEngine) -> None:
    """RC_TICS p.20's own invoice must pass. If it does not, a rule is wrong."""
    report = engine.validate(documented_invoice())
    assert report.errors == (), [str(v) for v in report.errors]
    assert report.ok
    assert bool(report) is True


def test_the_documented_example_is_internally_consistent() -> None:
    """Sanity-check the fixture against the §8 formulas, independently of the engine.

    20000 - 500 = 19500; 19500 * 9% = 1755; 19500 + 1755 = 21255.
    """
    invoice = documented_invoice()
    item = invoice.body[0]
    assert item.prdis == item.am * item.fee
    assert item.adis == item.prdis - item.dis
    assert item.vam == pytest.approx(item.adis * item.vra / 100)
    assert item.tsstam == item.adis + item.vam
    assert invoice.header.tbill == item.tsstam


# ------------------------------------------------------------ line arithmetic


@pytest.mark.parametrize(
    "field,value,expected_rule",
    [
        ("prdis", 19000, "arithmetic.prdis"),  # != am * fee
        ("adis", 19000, "arithmetic.adis"),  # != prdis - dis
        ("vam", 1700, "arithmetic.vam"),  # != adis * vra / 100
        ("tsstam", 21000, "arithmetic.tsstam"),  # != adis + vam + odam + olam
    ],
)
def test_a_wrong_line_figure_is_caught(field: str, value: int, expected_rule: str) -> None:
    invoice = documented_invoice()
    setattr(invoice.body[0], field, value)
    report = RuleEngine().validate(invoice)
    assert expected_rule in codes(report)
    broken = next(v for v in report.violations if v.rule == expected_rule)
    assert broken.line == 0
    assert broken.actual == value
    assert broken.expected is not None
    assert broken.reference  # every violation cites the clause it came from


def test_discount_cannot_exceed_the_pre_discount_amount() -> None:
    invoice = documented_invoice()
    invoice.body[0].dis = 25_000  # more than prdis of 20000
    assert "arithmetic.dis.at_most_prdis" in codes(RuleEngine().validate(invoice))


def test_a_negative_discount_is_caught() -> None:
    invoice = documented_invoice()
    invoice.body[0].dis = -1
    assert "arithmetic.dis.non_negative" in codes(RuleEngine().validate(invoice))


def test_pre_discount_must_be_positive() -> None:
    invoice = documented_invoice(tprdis=0, tadis=0, tvam=0, tbill=0)
    invoice.body[0].am = 0
    invoice.body[0].prdis = 0
    invoice.body[0].adis = 0
    invoice.body[0].vam = 0
    invoice.body[0].tsstam = 0
    invoice.body[0].dis = 0
    report = RuleEngine().validate(invoice)
    assert "arithmetic.prdis.positive" in codes(report)
    assert "arithmetic.tprdis.positive" in codes(report)


# ----------------------------------------------------------- header totals


@pytest.mark.parametrize(
    "field,value,expected_rule",
    [
        ("tprdis", 30_000, "arithmetic.tprdis"),
        ("tdis", 900, "arithmetic.tdis"),
        ("tadis", 19_000, "arithmetic.tadis"),
        ("tvam", 1_765, "arithmetic.tvam"),
        ("todam", 1_000, "arithmetic.todam"),
        ("tbill", 21_000, "arithmetic.tbill"),
    ],
)
def test_a_total_that_disagrees_with_the_body_is_caught(
    field: str, value: int, expected_rule: str
) -> None:
    invoice = documented_invoice(**{field: value})
    assert expected_rule in codes(RuleEngine().validate(invoice))


def test_totals_sum_across_several_lines() -> None:
    """Two identical lines: every header total must double."""
    invoice = documented_invoice(
        tprdis=40_000, tdis=1_000, tadis=39_000, tvam=3_510, tbill=42_510
    )
    invoice.body.append(invoice.body[0].model_copy(deep=True))
    report = RuleEngine().validate(invoice)
    assert report.errors == (), [str(v) for v in report.errors]


def test_the_sdk_guides_deliberately_invalid_invoice_is_rejected() -> None:
    """The SDK guide ships a 'CreateInvalidInvoice' example. It must not pass.

    Its totals contradict its single line: tprdis 30000 against a 20000 line,
    a vam of 0 at a 10% rate, and a tbill that matches neither.
    """
    invoice = documented_invoice(
        inp=7, tprdis=30_000, tdis=500, tadis=19_500, tvam=1_765, todam=1_000, tbill=21_255, setm=3
    )
    invoice.body[0] = InvoiceBodyItem(
        sstid="1710000138624",
        sstt="کالای اشتباه",
        mu="164",
        am=2,
        fee=10_000,
        prdis=20_000,
        dis=0,
        adis=19_500,
        vra=10,
        vam=0,
        tsstam=20_000,
    )
    report = RuleEngine().validate(invoice)
    assert not report.ok
    # adis != prdis - dis, vam != adis*vra/100, and the header totals disagree.
    assert {"arithmetic.adis", "arithmetic.vam", "arithmetic.tprdis"} <= codes(report)


# --------------------------------------------------------------- obligations


@pytest.mark.parametrize("missing", ["taxid", "indatim", "ins", "tins", "tob", "setm"])
def test_a_missing_required_header_field_is_reported(missing: str) -> None:
    invoice = documented_invoice()
    setattr(invoice.header, missing, None)
    report = RuleEngine().validate(invoice)
    assert any(
        v.field == missing and v.rule == "obligation.required" for v in report.violations
    ), f"{missing} was not reported as required"


@pytest.mark.parametrize("missing", ["sstid", "am", "fee", "vra", "vam", "tsstam"])
def test_a_missing_required_body_field_is_reported(missing: str) -> None:
    invoice = documented_invoice()
    setattr(invoice.body[0], missing, None)
    report = RuleEngine().validate(invoice)
    assert any(v.field == missing and v.line == 0 for v in report.violations)


def test_an_optional_field_may_be_absent() -> None:
    """tdis is اختیاری per §8-14 — dropping it must not produce an obligation error."""
    invoice = documented_invoice()
    invoice.header.tdis = None
    report = RuleEngine().validate(invoice)
    assert not any(
        v.rule.startswith("obligation") and v.field == "tdis" for v in report.violations
    )


@pytest.mark.parametrize("optional_field", ["sstt", "mu"])
def test_description_and_unit_are_optional_not_required(optional_field: str) -> None:
    """Locks in a correction.

    A hand-written first cut of the matrix guessed شرح کالا/خدمت and واحد
    اندازه‌گیری were اجباری. جدول ۱ says اختیاری for الگوی اول. Guessing would have
    produced a confident, wrong rejection in the entry form.
    """
    invoice = documented_invoice()
    setattr(invoice.body[0], optional_field, None)
    report = RuleEngine().validate(invoice)
    assert not any(v.field == optional_field for v in report.violations)


def test_discount_amount_is_required_not_optional() -> None:
    """The other half of that correction: مبلغ تخفیف is اجباری, and was guessed optional."""
    invoice = documented_invoice()
    invoice.body[0].dis = None
    report = RuleEngine().validate(invoice)
    assert any(
        v.field == "dis" and v.rule == "obligation.required" for v in report.violations
    )


def test_total_other_taxes_is_required_for_pattern_1() -> None:
    """todam is اجباری per جدول ۱, though §8-17 only says «با توجه به الگو»."""
    invoice = documented_invoice()
    invoice.header.todam = None
    assert any(
        v.field == "todam" and v.rule == "obligation.required"
        for v in RuleEngine().validate(invoice).violations
    )


def test_an_empty_body_is_rejected() -> None:
    invoice = documented_invoice()
    invoice.body = []
    assert "obligation.body_not_empty" in codes(RuleEngine().validate(invoice))


# --------------------------------------------------------------- conditionals


def test_reference_taxid_is_required_only_for_a_referring_invoice() -> None:
    """irtaxid is اجباری در شرایط خاص — only when ins is 2, 3 or 4."""
    main = documented_invoice(ins=1)
    assert not any(v.field == "irtaxid" for v in RuleEngine().validate(main).violations)

    corrective = documented_invoice(ins=2)  # اصلاحی
    assert any(
        v.field == "irtaxid" and v.rule == "obligation.conditional"
        for v in RuleEngine().validate(corrective).violations
    )

    supplied = documented_invoice(ins=2, irtaxid="A1121604C220002F095011")
    assert not any(v.field == "irtaxid" for v in RuleEngine().validate(supplied).violations)


def test_the_cash_credit_split_is_required_only_for_setm_3() -> None:
    assert not any(
        v.field in {"cap", "insp"} for v in RuleEngine().validate(documented_invoice()).violations
    )

    split = documented_invoice(setm=3)
    reported = {v.field for v in RuleEngine().validate(split).violations}
    assert {"cap", "insp"} <= reported


def test_a_balanced_cash_credit_split_passes() -> None:
    """C = Xs - W2 - W - Cr, so cash + credit + VAT = the bill."""
    invoice = documented_invoice(setm=3, cap=9_500, insp=10_000)
    report = RuleEngine().validate(invoice)
    assert not any(v.rule.startswith("settlement") for v in report.violations), [
        str(v) for v in report.violations
    ]


def test_an_unbalanced_split_is_caught() -> None:
    invoice = documented_invoice(setm=3, cap=5_000, insp=10_000)
    assert "settlement.split_balances" in codes(RuleEngine().validate(invoice))


def test_indati2m_is_required_when_the_article_9_rule_is_used() -> None:
    """insr == 1 invokes ماده ۹, which makes the registration timestamp mandatory."""
    invoice = documented_invoice(insr=1)
    assert any(
        v.field == "indati2m" and v.rule == "obligation.conditional"
        for v in RuleEngine().validate(invoice).violations
    )


# ------------------------------------------------------------------- enums


@pytest.mark.parametrize(
    "field,bad", [("inty", 9), ("ins", 7), ("setm", 4), ("tob", 99), ("insr", 2)]
)
def test_an_out_of_range_enum_is_caught(field: str, bad: int) -> None:
    invoice = documented_invoice(**{field: bad})
    report = RuleEngine().validate(invoice)
    assert any(v.field == field and v.rule == "enum.out_of_range" for v in report.violations)


# ------------------------------------------------------ pattern-specific paths


def test_export_pattern_requires_a_zero_vat_rate() -> None:
    """§8-41 rule 5 fixes نرخ to zero for صادرات, بورس and فروش زنجیره‌ای."""
    invoice = documented_invoice(inp=7)
    report = RuleEngine().validate(invoice)
    assert "arithmetic.vra.zero_for_pattern" in codes(report)


def test_an_unencoded_pattern_warns_instead_of_silently_passing() -> None:
    """جدول ۱ defines 12 patterns; 10 and 12 do not exist in it.

    An invoice naming one must not validate silently — saying nothing would let a
    clean report read as approval.
    """
    invoice = documented_invoice(inp=12)
    report = RuleEngine().validate(invoice)
    warning = next(v for v in report.violations if v.rule == "coverage.pattern_not_encoded")
    assert warning.severity is Severity.WARNING
    assert "12" in warning.message


def test_every_pattern_in_the_table_is_encoded() -> None:
    """جدول ۱ has these twelve columns; all must be transcribed."""
    assert sorted(load_rules().patterns) == [1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 13, 14]


def test_a_complete_pattern_reports_no_coverage_warning() -> None:
    """Now that جدول ۱ is fully transcribed, pattern 1 no longer hedges."""
    report = RuleEngine().validate(documented_invoice())
    assert "coverage.partial" not in codes(report)
    assert report.ok


# ----------------------------------------------------------------- recompute


def test_recompute_derives_every_money_field_from_its_inputs() -> None:
    """The entry form's 'calculate': give quantity, price, discount and rate."""
    skeleton = Invoice(
        header=InvoiceHeader(taxid="A" * 22, indatim=1683997837988, ins=1, inp=1, inty=1, setm=2),
        body=[InvoiceBodyItem(sstid="2710000138624", am=2, fee=10_000, dis=500, vra=9)],
    )
    filled = recompute(skeleton)

    item = filled.body[0]
    assert (item.prdis, item.adis, item.vam, item.tsstam) == (20_000, 19_500, 1_755, 21_255)
    header = filled.header
    assert (header.tprdis, header.tdis, header.tadis) == (20_000, 500, 19_500)
    assert (header.tvam, header.todam, header.tbill) == (1_755, 0, 21_255)

    assert check_arithmetic(filled, 1) == []


def test_recompute_does_not_mutate_its_input() -> None:
    original = Invoice(
        header=InvoiceHeader(taxid="A" * 22, indatim=1, ins=1, inp=1),
        body=[InvoiceBodyItem(sstid="X", am=1, fee=100, vra=10)],
    )
    recompute(original)
    assert original.body[0].prdis is None
    assert original.header.tbill is None


def test_recompute_output_survives_its_own_validation() -> None:
    """Whatever recompute produces must satisfy the engine — else they disagree."""
    skeleton = Invoice(
        header=InvoiceHeader(
            taxid="A" * 22, indatim=1683997837988, ins=1, inp=1, inty=1,
            tins="14003778990", tob=2, setm=2,
        ),
        body=[
            InvoiceBodyItem(sstid="1", sstt="الف", mu="164", am=3, fee=7_000, dis=1_000, vra=9),
            InvoiceBodyItem(sstid="2", sstt="ب", mu="164", am=1, fee=250_000, dis=0, vra=10),
        ],
    )
    report = RuleEngine().validate(recompute(skeleton))
    assert report.errors == (), [str(v) for v in report.errors]


# ----------------------------------------------------------------- reporting


def test_every_violation_cites_a_clause() -> None:
    """A finding that cannot say which rule it broke is barely better than a boolean."""
    invoice = documented_invoice(tbill=1, tvam=2, setm=4)
    invoice.body[0].vam = 3
    report = RuleEngine().validate(invoice)
    assert report.violations
    for violation in report.violations:
        assert violation.reference, f"{violation.rule} cites nothing"
        assert violation.message


def test_raise_if_invalid_raises_only_on_errors() -> None:
    RuleEngine().validate(documented_invoice()).raise_if_invalid()  # warnings only

    bad = RuleEngine().validate(documented_invoice(tbill=1))
    with pytest.raises(InvoiceValidationError) as caught:
        bad.raise_if_invalid()
    assert "tbill" in caught.value.fields
    assert caught.value.violations


def test_all_violations_are_reported_not_just_the_first() -> None:
    """An operator fixing an invoice wants the whole list, not one per round trip."""
    invoice = documented_invoice(tprdis=1, tadis=2, tvam=3, tbill=4)
    report = RuleEngine().validate(invoice)
    assert len(report.errors) >= 4


def test_violation_str_is_readable() -> None:
    report = RuleEngine().validate(documented_invoice(tbill=999))
    rendered = str(next(v for v in report.errors if v.field == "tbill"))
    assert "tbill" in rendered and "§8-18" in rendered


# --------------------------------------------------------------- the spec file


def test_the_shipped_spec_loads_and_is_self_consistent() -> None:
    rules = load_rules()
    assert rules.version == 2
    pattern = rules.pattern(1)
    assert pattern is not None
    assert pattern.name == "فروش"
    for rule in list(pattern.header.values()) + list(pattern.body.values()):
        assert rule.reference, f"{rule.name} cites no clause"
        if rule.obligation is not Obligation.NOT_APPLICABLE:
            # Excluded fields never reach a form, so they need no UI label.
            assert rule.title, f"{rule.name} has no Persian title for the UI"
        if rule.obligation is Obligation.CONDITIONAL:
            # Either an evaluable condition, or the explicit "we do not know" marker.
            assert rule.when, f"{rule.name} is conditional but has no condition"


def test_an_unknown_condition_is_refused_at_load_time(tmp_path) -> None:
    """A typo in `when` must fail loudly, not silently disable the rule."""
    spec = tmp_path / "patterns.yaml"
    spec.write_text(
        "version: 1\n"
        "patterns:\n"
        "  1:\n"
        "    name: فروش\n"
        "    header:\n"
        "      cap:\n"
        "        obligation: conditional\n"
        "        when: setm == 42\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="unknown condition"):
        load_rules(spec)


def test_the_shipped_spec_is_transcribed_in_full() -> None:
    """جدول ۱ is now transcribed mechanically, so coverage is complete."""
    pattern = load_rules().pattern(1)
    assert pattern.coverage == "complete"
    assert pattern.is_complete is True
    assert pattern.types == (1, 2)
    assert SPEC_PATH.is_file()


def test_obligations_can_differ_between_invoice_types() -> None:
    """نوع اول and نوع دوم are separate column bands and genuinely disagree."""
    pattern = load_rules().pattern(1)
    assert pattern.header["tob"].for_type(1) is Obligation.REQUIRED
    assert pattern.header["tob"].for_type(2) is Obligation.OPTIONAL
    # روش تسویه is not sent at all for نوع دوم — §8-22 rule 2 makes it implicit.
    assert pattern.header["setm"].for_type(2) is Obligation.NOT_APPLICABLE


def test_a_field_outside_the_pattern_is_reported() -> None:
    """صورتحساب‌های الکترونیکی صرفا شامل اقلام مذکور بوده (RC_IITP §4)."""
    invoice = documented_invoice(cdcn="12345")  # customs field, صادرات only
    assert any(
        v.field == "cdcn" and v.rule == "obligation.not_applicable"
        for v in RuleEngine().validate(invoice).violations
    )


# ------------------------------------------------------------- verify() for UI


def test_verify_renders_persian_titles_and_a_summary() -> None:
    result = RuleEngine().verify(documented_invoice(tbill=999))
    assert result.ok is False
    assert result.pattern == 1
    assert result.pattern_name == "فروش"
    assert "خطا" in result.summary
    tbill = next(e for e in result.errors if e["field"] == "tbill")
    assert tbill["title"], "the UI needs a Persian label, not a wire name"
    assert tbill["expected"] is not None and tbill["actual"] == 999


def test_verify_says_so_when_the_invoice_is_valid() -> None:
    result = RuleEngine().verify(documented_invoice())
    assert result.ok is True
    assert result.summary.startswith("صورتحساب معتبر است")
    assert result.errors == ()


def test_verify_output_is_json_serialisable() -> None:
    """It goes straight into an API response, so it must survive json.dumps."""
    import json

    payload = RuleEngine().verify(documented_invoice(tbill=1)).as_dict()
    assert json.loads(json.dumps(payload, ensure_ascii=False))["ok"] is False


def test_verify_names_the_missing_field_in_persian() -> None:
    invoice = documented_invoice()
    invoice.header.tins = None
    result = RuleEngine().verify(invoice)
    message = next(e["message"] for e in result.errors if e["field"] == "tins")
    assert "شماره اقتصادي فروشنده" in message


# --------------------------------------------- nested کالاهای حمل شده (الگو ۸)


def test_shipped_goods_rows_are_checked_for_the_bill_of_lading_pattern() -> None:
    """sg is an array nested on the header, so it needs its own obligation pass.

    It was silently dropped by the loader until the full-table cross-check
    surfaced it: the generated matrix carried the rules, nothing read them.
    """
    from moadian.models import ShippingGood

    spec = load_rules().pattern(8)
    assert set(spec.sg) == {"sgid", "sgt"}
    assert spec.sg["sgid"].obligation is Obligation.REQUIRED

    invoice = documented_invoice(inp=8)
    invoice.header.sg = [ShippingGood(sgid="X1")]  # sgt missing
    report = RuleEngine().validate(invoice)
    assert any(
        v.field == "sg.sgt" and v.rule == "obligation.required" for v in report.violations
    ), [str(v) for v in report.violations]


def test_a_complete_shipped_goods_row_passes() -> None:
    from moadian.models import ShippingGood

    invoice = documented_invoice(inp=8)
    invoice.header.sg = [ShippingGood(sgid="X1", sgt="کالای حمل‌شده")]
    report = RuleEngine().validate(invoice)
    assert not any(v.field.startswith("sg.") for v in report.violations)


def test_other_patterns_do_not_demand_shipped_goods() -> None:
    """الگوی اول has no bill of lading, so an empty sg must not be an error."""
    report = RuleEngine().validate(documented_invoice(inp=1))
    assert not any(v.field.startswith("sg.") for v in report.violations)


# ------------------------------------------------- شرح کالا/خدمت length (§8-28)


def _line(**over):
    line = {
        "sstid": "2710000138624", "sstt": "سرسیلندر", "mu": "164", "am": 2,
        "fee": 10000, "prdis": 20000, "dis": 500, "adis": 19500, "vra": 9,
        "vam": 1755, "tsstam": 21255,
    }
    line.update(over)
    return line


def _invoice(*lines):
    return Invoice.model_validate({
        "header": {
            "taxid": "", "indatim": 1683997837988, "inty": 1, "inp": 1, "ins": 1,
            "tins": "14003778990", "tob": 2, "tprdis": 20000 * len(lines),
            "tdis": 500 * len(lines), "tadis": 19500 * len(lines),
            "tvam": 1755 * len(lines), "todam": 0, "tbill": 21255 * len(lines),
            "setm": 1,
        },
        "body": list(lines),
    })


def _sstt_errors(invoice):
    return [v for v in RuleEngine().validate(invoice).violations if v.rule == "length.sstt"]


def test_a_400_character_description_is_accepted():
    """The cap is inclusive; 400 is legal."""
    assert _sstt_errors(_invoice(_line(sstt="ا" * 400))) == []


def test_a_401_character_description_is_rejected():
    violations = _sstt_errors(_invoice(_line(sstt="ا" * 401)))
    assert len(violations) == 1
    assert violations[0].expected == 400
    assert violations[0].actual == 401
    assert violations[0].line == 0
    assert "RC_IITP" in violations[0].reference


def test_the_longest_real_catalogue_description_is_caught():
    """The organization's own services export contains 13 current entries whose
    شرح exceeds 400 characters, the longest at 625. Filling an invoice line from
    one of those unmodified builds an invoice that is refused — so the check has
    to fire on real data, not only on a synthetic string."""
    violations = _sstt_errors(_invoice(_line(sstt="ا" * 625)))
    assert len(violations) == 1
    assert violations[0].actual == 625


def test_the_offending_line_is_identified():
    """With several lines, "too long" is useless without saying which one."""
    violations = _sstt_errors(
        _invoice(_line(sstt="کوتاه"), _line(sstt="ا" * 500), _line(sstt="ا" * 600))
    )
    assert [v.line for v in violations] == [1, 2]


def test_an_absent_description_is_not_a_length_error():
    """sstt is optional — §8-28 says اختیاری, and the spec records no content rule."""
    assert _sstt_errors(_invoice(_line(sstt=None))) == []
    assert _sstt_errors(_invoice(_line(sstt=""))) == []


def test_two_lines_may_carry_different_descriptions_for_the_same_code():
    """What the operator actually asked about.

    §8-28 defines sstt as "عنوان هر قلم کالا/خدمت در صورتحساب" — the title of the
    line *in the invoice* — and records "در حال حاضر قاعده‌ای ندارد" for its
    content. Nothing ties it to the catalogue's شرح for that شناسه, so the same
    code may be described differently on different lines and on different
    invoices.
    """
    invoice = _invoice(
        _line(sstid="2720000114542", sstt="پشتیبانی سالانه — قرارداد الف"),
        _line(sstid="2720000114542", sstt="پشتیبانی سالانه — قرارداد ب"),
    )
    report = RuleEngine().validate(invoice)
    assert [v for v in report.violations if v.field == "sstt"] == []
    assert [v for v in report.violations if v.field == "sstid"] == []


# --------------------------------------- واحد اندازه‌گیری (§8-30، جدول ۳۲)


def _mu_issues(mu):
    invoice = _invoice(_line(mu=mu))
    return [v for v in RuleEngine().validate(invoice).violations if v.field == "mu"]


def test_an_omitted_unit_is_accepted():
    """§8-30 declares mu اختیاری. Omitting it is the legal way to say nothing."""
    assert _mu_issues(None) == []


def test_a_blank_unit_is_accepted_because_it_never_reaches_the_wire():
    """to_wire_dict strips it, so a blank cannot produce 0103502 again."""
    assert _mu_issues("") == []
    assert _mu_issues("   ") == []


def test_the_documented_unit_code_is_accepted_without_comment():
    """164 is what the RC_TICS p.20 example and the official SDK samples use."""
    assert _mu_issues("164") == []


@pytest.mark.parametrize("mu", ["abc", "16 4", "12.5", "-1", "123456789"])
def test_a_unit_that_is_not_a_short_numeric_code_is_an_error(mu):
    """§8-30 declares it "رشته عددی، حداکثر ۸"."""
    issues = _mu_issues(mu)
    assert [i.rule for i in issues] == ["format.mu"]
    assert issues[0].severity is Severity.ERROR


def test_a_unit_typed_in_persian_digits_is_folded_rather_than_refused():
    """۱۶۴ is 164 to a person and a different string to the tax service.

    These are pasted out of Persian PDFs constantly, so the model folds them to
    ASCII instead of rejecting them. Python makes this easy to miss:
    ``"۱۶۴".isdigit()`` is True, so a numeric check passes and the wrong bytes go
    out regardless.
    """
    invoice = _invoice(_line(mu="۱۶۴"))
    assert invoice.body[0].mu == "164"
    assert [v for v in RuleEngine().validate(invoice).violations if v.field == "mu"] == []
    assert invoice.to_wire_dict()["body"][0]["mu"] == "164"


def test_a_goods_code_typed_in_persian_digits_is_folded_too():
    """Same class of failure, and fatal in the same way: the شناسه is what the
    organization matches and taxes on."""
    invoice = _invoice(_line(sstid="۲۷۲۰۰۰۰۱۱۴۵۴۲"))
    assert invoice.body[0].sstid == "2720000114542"
    assert invoice.to_wire_dict()["body"][0]["sstid"] == "2720000114542"


def test_an_unrecognised_numeric_code_is_only_a_warning():
    """The real table (RC_UMGS.ST, intamedia.ir) is not bundled here.

    Treating everything outside the one code we can evidence as invalid would
    reject every legitimate unit but that one. The organization checks it for
    real; this only says we cannot vouch for it.
    """
    issues = _mu_issues("9999")
    assert [i.rule for i in issues] == ["format.mu_unverified"]
    assert issues[0].severity is Severity.WARNING
    assert RuleEngine().validate(_invoice(_line(mu="9999"))).ok is True


def test_the_offending_line_is_named():
    issues = [
        v
        for v in RuleEngine().validate(_invoice(_line(mu="164"), _line(mu="abc"))).violations
        if v.field == "mu"
    ]
    assert [v.line for v in issues] == [1]
