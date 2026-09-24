"""Model tests. The wire-format rules under test are pinned in WIRE_FORMAT.md."""

import json

import pytest
from pydantic import ValidationError

from moadian.crypto import canonical_json
from moadian.errors import CryptographyError
from moadian.models import (
    ApiError,
    Article6Status,
    BatchResponse,
    ErrorEnvelope,
    FiscalInformationResult,
    InquiryResult,
    Invoice,
    InvoiceBodyItem,
    InvoiceHeader,
    InvoicePayment,
    InvoiceStatus,
    InvoiceStatusResult,
    NonceResponse,
    Packet,
    PacketHeader,
    PaymentMethod,
    RequestStatus,
    ServerInformation,
    ShippingGood,
    TaxpayerResult,
    ValidationDetail,
)

# RC_TICS.IS_v1.6 p.20 — the document's own Pattern-1 (inp=1) example.
P20_INVOICE = {
    "header": {
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
    },
    "body": [
        {
            "sstid": "2710000138624",
            "sstt": "سرسیلندر قطعات صنعت فولاد سازی",
            "mu": "164",
            "am": 2,
            "fee": 10000,
            "prdis": 20000,
            "dis": 500,
            "adis": 19500,
            "vra": 9,
            "vam": 1755,
            "tsstam": 21255,
        }
    ],
    "payments": [],
}


def minimal_header(**overrides) -> InvoiceHeader:
    return InvoiceHeader(taxid="A1121604C220002F095011", indatim=1683997837988, ins=1, **overrides)


# --------------------------------------------------------------------------
# the `in` / `in_` alias
# --------------------------------------------------------------------------


def test_in_accepted_under_wire_alias():
    header = InvoiceHeader.model_validate(
        {"taxid": "A11", "indatim": 1, "ins": 1, "in": "بیمه-۱۲۳"}
    )
    assert header.in_ == "بیمه-۱۲۳"


def test_in_accepted_under_python_name():
    """populate_by_name — construction from Python keeps `in` unusable as a kwarg."""
    header = minimal_header(in_="POLICY-1")
    assert header.in_ == "POLICY-1"
    assert InvoiceHeader.model_validate(
        {"taxid": "A11", "indatim": 1, "ins": 1, "in_": "POLICY-1"}
    ).in_ == "POLICY-1"


def test_in_emitted_as_in_not_in_underscore():
    wire = Invoice(header=minimal_header(in_="POLICY-1"), body=[]).to_wire_dict()
    assert wire["header"]["in"] == "POLICY-1"
    assert "in_" not in wire["header"]


def test_in_omitted_when_unset():
    wire = Invoice(header=minimal_header(), body=[]).to_wire_dict()
    assert "in" not in wire["header"]
    assert "in_" not in wire["header"]


def test_in_round_trips_through_wire_dict():
    original = Invoice(header=minimal_header(in_="POLICY-1"), body=[InvoiceBodyItem(sstid="1")])
    reparsed = Invoice.model_validate(original.to_wire_dict())
    assert reparsed == original


# --------------------------------------------------------------------------
# omission of unset fields
# --------------------------------------------------------------------------


def test_to_wire_dict_omits_unset_header_fields():
    wire = Invoice(header=minimal_header(), body=[]).to_wire_dict()
    assert wire["header"] == {"taxid": "A1121604C220002F095011", "indatim": 1683997837988, "ins": 1}


def test_to_wire_dict_omits_unset_body_fields():
    invoice = Invoice(header=minimal_header(), body=[InvoiceBodyItem(sstid="2710000138624")])
    wire = invoice.to_wire_dict()
    assert wire["body"] == [{"sstid": "2710000138624"}]


def test_to_wire_dict_omits_unset_fields_in_nested_list_models():
    """sg is a list of models one level below the header — exclude_none must reach it."""
    header = minimal_header(sg=[ShippingGood(sgid="SG-1"), ShippingGood(sgt="کالای دوم")])
    wire = Invoice(header=header, body=[]).to_wire_dict()
    assert wire["header"]["sg"] == [{"sgid": "SG-1"}, {"sgt": "کالای دوم"}]


def test_to_wire_dict_omits_unset_payment_fields():
    wire = Invoice(
        header=minimal_header(),
        body=[],
        payments=[InvoicePayment(pdt=1683997837988, pv=21255)],
    ).to_wire_dict()
    assert wire["payments"] == [{"pdt": 1683997837988, "pv": 21255}]


def test_empty_payments_survives_but_unset_extension_does_not():
    """The p.20 example ships `"payments":[]`; extension is absent entirely."""
    wire = Invoice(header=minimal_header(), body=[]).to_wire_dict()
    assert wire["payments"] == []
    assert "extension" not in wire


def test_zero_is_not_omitted():
    """exclude_none, not exclude falsy — todam=0 appears in the p.20 example."""
    wire = Invoice(header=minimal_header(todam=0), body=[]).to_wire_dict()
    assert wire["header"]["todam"] == 0


def test_no_nulls_anywhere_in_wire_dict():
    wire = Invoice.model_validate(P20_INVOICE).to_wire_dict()
    assert "null" not in json.dumps(wire, ensure_ascii=False)


# --------------------------------------------------------------------------
# non-finite numbers — NaN/Infinity are not JSON and must never reach a signature
# --------------------------------------------------------------------------


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_body_item_rejects_non_finite_amounts(value: float):
    """First boundary: construction. allow_inf_nan=False on the model config."""
    with pytest.raises(ValidationError):
        InvoiceBodyItem(sstid="2710000138624", am=value)
    with pytest.raises(ValidationError):
        InvoiceBodyItem(sstid="2710000138624", fee=value)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_header_rejects_non_finite_floats(value: float):
    with pytest.raises(ValidationError):
        minimal_header(tonw=value)


def test_body_item_still_accepts_ordinary_floats():
    item = InvoiceBodyItem(sstid="2710000138624", am=2.5, fee=10000.0, vra=9.0)
    assert item.am == 2.5


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_canonical_json_refuses_non_finite_numbers(value: float):
    """Second boundary: serialisation. Anything that reaches canonical_json is
    about to be signed, so a value with no JSON form must raise, not encode."""
    with pytest.raises(CryptographyError):
        canonical_json({"sstid": "S", "am": value})


def test_canonical_json_never_emits_the_javascript_literals():
    """Regression: json.dumps defaults to NaN/Infinity, which no RFC 8259 parser
    accepts. The failure would otherwise surface only after a tax id was spent."""
    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(CryptographyError) as excinfo:
            canonical_json({"body": [{"fee": value}]})
        assert "must not be signed" in str(excinfo.value)


def test_canonical_json_still_encodes_finite_floats():
    assert canonical_json({"am": 2.5, "vra": 9.0}) == b'{"am":2.5,"vra":9.0}'


# --------------------------------------------------------------------------
# Persian text
# --------------------------------------------------------------------------


def test_persian_text_survives_the_model():
    item = InvoiceBodyItem(sstid="2710000138624", sstt="سرسیلندر قطعات صنعت فولاد سازی")
    wire = Invoice(header=minimal_header(), body=[item]).to_wire_dict()
    assert wire["body"][0]["sstt"] == "سرسیلندر قطعات صنعت فولاد سازی"


def test_persian_text_is_not_escaped_when_serialised_for_the_wire():
    """WIRE_FORMAT.md: ensure_ascii=False, compact separators."""
    wire = Invoice.model_validate(P20_INVOICE).to_wire_dict()
    encoded = json.dumps(wire, ensure_ascii=False, separators=(",", ":"))
    assert "سرسیلندر" in encoded
    assert "\\u" not in encoded
    assert ", " not in encoded


# --------------------------------------------------------------------------
# the p.20 reference invoice
# --------------------------------------------------------------------------


def test_p20_example_parses_cleanly():
    invoice = Invoice.model_validate(P20_INVOICE)
    assert invoice.header.taxid == "A1121604C220002F095011"
    assert invoice.header.inp == 1  # الگوی صورتحساب ۱
    assert invoice.header.tbill == 21255
    assert invoice.payments == []
    assert len(invoice.body) == 1
    assert invoice.body[0].vra == 9.0


def test_p20_example_wire_dict_keys_match_the_document():
    wire = Invoice.model_validate(P20_INVOICE).to_wire_dict()
    assert set(wire) == {"header", "body", "payments"}
    assert set(wire["header"]) == set(P20_INVOICE["header"])
    assert set(wire["body"][0]) == set(P20_INVOICE["body"][0])


def test_p20_wire_names_are_verbatim():
    """Guards against a well-meaning rename to snake_case."""
    wire = Invoice.model_validate(P20_INVOICE).to_wire_dict()
    for name in ("taxid", "indatim", "tprdis", "tadis", "tbill", "setm"):
        assert name in wire["header"]


# --------------------------------------------------------------------------
# typing rules
# --------------------------------------------------------------------------


def test_national_ids_keep_leading_zeros():
    header = InvoiceHeader.model_validate(
        {"taxid": "A11", "indatim": 1, "ins": 1, "tins": "0023457708", "tinb": "0012345678"}
    )
    assert header.tins == "0023457708"
    assert header.tinb == "0012345678"


def test_decimal_typed_fields_accept_fractions():
    item = InvoiceBodyItem(sstid="1", am=2.5, fee=10000.75, vra=9.0, nw=1.234)
    assert item.am == 2.5
    assert item.fee == 10000.75


def test_unknown_invoice_field_is_rejected_not_silently_dropped():
    with pytest.raises(ValidationError):
        InvoiceHeader.model_validate({"taxid": "A11", "indatim": 1, "ins": 1, "taxId": "A11"})


def test_required_header_fields_are_enforced():
    with pytest.raises(ValidationError):
        InvoiceHeader.model_validate({"taxid": "A11", "indatim": 1})
    with pytest.raises(ValidationError):
        InvoiceBodyItem.model_validate({"sstt": "بدون شناسه"})


# --------------------------------------------------------------------------
# enums
# --------------------------------------------------------------------------


def test_enums_are_their_wire_strings():
    assert RequestStatus.IN_PROGRESS == "IN_PROGRESS"
    assert RequestStatus.NOT_FOUND == "NOT_FOUND"
    assert InvoiceStatus.SYSTEMIC_APPROVED == "SYSTEMIC_APPROVED"
    assert Article6Status.NOT_EXCEEDED == "NOT_EXCEEDED"
    assert PaymentMethod.CHEQUE == "CHEQUE"
    assert json.dumps(PaymentMethod.TRANSFER) == '"TRANSFER"'


def test_payment_method_covers_the_documented_set():
    assert {m.value for m in PaymentMethod} == {
        "CHEQUE",
        "BARTER",
        "CASH",
        "POS",
        "INTERNET",
        "CARD",
        "TRANSFER",
        "OTHER",
    }


# --------------------------------------------------------------------------
# packet envelope
# --------------------------------------------------------------------------


def test_packet_serialises_to_the_submission_envelope():
    packet = Packet(
        payload="eyJhbGci.AAA.BBB.CCC.DDD",
        header=PacketHeader(
            requestTraceId="b3bd6327-1c57-4cae-85ed-5c88de28aea3", fiscalId="A11216"
        ),
    )
    assert packet.model_dump() == {
        "payload": "eyJhbGci.AAA.BBB.CCC.DDD",
        "header": {
            "requestTraceId": "b3bd6327-1c57-4cae-85ed-5c88de28aea3",
            "fiscalId": "A11216",
        },
    }


# --------------------------------------------------------------------------
# responses
# --------------------------------------------------------------------------


def test_error_envelope_parses_the_real_sandbox_response():
    raw = {
        "timestamp": 1786797257758,
        "requestTraceId": "2444eefbbe80d63ba3936dc992260fa3",
        "errors": [{"code": "4100", "message": "متد درخواست ارسالی پشتیبانی نمی‌شود."}],
    }
    envelope = ErrorEnvelope.model_validate(raw)
    assert envelope.timestamp == 1786797257758
    assert envelope.requestTraceId == "2444eefbbe80d63ba3936dc992260fa3"
    assert envelope.errors[0].code == "4100"
    assert envelope.errors[0].message == "متد درخواست ارسالی پشتیبانی نمی‌شود."


def test_error_envelope_parses_a_body_without_a_timestamp():
    """Gateway-level bodies drop `timestamp`. Losing the codes over a missing
    clock reading would cost the operator the only actionable diagnostic."""
    envelope = ErrorEnvelope.model_validate(
        {"errors": [{"code": "4143", "message": "بیش از 1000 صورتحساب"}]}
    )
    assert envelope.timestamp is None
    assert [e.code for e in envelope.errors] == ["4143"]


def test_error_envelope_coerces_a_numeric_code_to_string():
    envelope = ErrorEnvelope.model_validate(
        {"timestamp": 1786797257758, "errors": [{"code": 4143, "message": "x"}]}
    )
    assert envelope.errors[0].code == "4143"
    assert isinstance(envelope.errors[0].code, str)


def test_error_envelope_accepts_a_null_message():
    envelope = ErrorEnvelope.model_validate(
        {"timestamp": 1786797257758, "errors": [{"code": "5199", "message": None}]}
    )
    assert envelope.errors[0].code == "5199"
    assert envelope.errors[0].message == ""


def test_error_envelope_accepts_a_null_errors_list_and_null_entries():
    assert ErrorEnvelope.model_validate({"timestamp": 1, "errors": None}).errors == []
    envelope = ErrorEnvelope.model_validate(
        {"timestamp": 1, "errors": [None, {"code": 4100, "message": None}]}
    )
    assert [e.code for e in envelope.errors] == ["4100"]


def test_error_envelope_keeps_the_leading_zero_of_transport_codes():
    """`04130` is a distinct code from `4130`; string codes are never renumbered."""
    envelope = ErrorEnvelope.model_validate({"timestamp": 1, "errors": [{"code": "04130"}]})
    assert envelope.errors[0].code == "04130"


@pytest.mark.parametrize(
    "raw",
    [
        {},  # nothing recognisable
        {"detail": "gateway timeout"},  # someone else's error shape
        {"message": "Service Unavailable", "status": 503},
        [],  # not even an object
        "Bad Gateway",
        {"timestamp": 1, "errors": "boom"},  # errors must still be a list
        {"timestamp": 1, "errors": [{"message": "no code at all"}]},
    ],
)
def test_error_envelope_still_rejects_genuine_garbage(raw):
    """Tolerance stops at bodies with none of the envelope's own keys: those must
    stay UnknownResponseError so the caller reports the raw body instead of an
    empty error list."""
    with pytest.raises(ValidationError):
        ErrorEnvelope.model_validate(raw)


def test_validation_detail_tolerates_null_error_lists():
    detail = ValidationDetail.model_validate({"error": None, "warning": None, "success": True})
    assert detail.error == []
    assert detail.warning == []


def test_nonce_response_keeps_expdate_verbatim():
    nonce = NonceResponse.model_validate(
        {"nonce": "34d1b5a2-9b17-4c33-9c5e-0d7a0e1b2f3a-1786797257758",
         "expDate": "2026-08-15T09:14:17.758Z"}
    )
    assert nonce.expDate == "2026-08-15T09:14:17.758Z"


def test_server_information_parses_keys():
    info = ServerInformation.model_validate(
        {"serverTime": 1786797257758,
         "publicKeys": [{"key": "MIIBIjAN", "id": "kid-1", "algorithm": "RSA", "purpose": 0}]}
    )
    assert info.publicKeys[0].id == "kid-1"


def test_batch_response_parses_submission_result():
    batch = BatchResponse.model_validate(
        {"timestamp": 1786797257758,
         "result": [{"uid": "b3bd6327", "packetType": "INVOICE.V01",
                     "referenceNumber": "780c7cb1", "data": ""}]}
    )
    assert batch.result[0].referenceNumber == "780c7cb1"


def test_inquiry_result_with_validation_detail():
    result = InquiryResult.model_validate(
        {
            "referenceNumber": "780c7cb1-84cf-4df8-a87d-160448f38c55",
            "uid": "b3bd6327-1c57-4cae-85ed-5c88de28aea3",
            "status": "FAILED",
            "data": {
                "error": [{"code": "011107", "message": "طول مقدار وارد شده ...",
                           "errorType": "ERROR"}],
                "warning": [{"code": "111208", "message": "طول مقدار وارد شده ...",
                             "errorType": "WARNING"}],
                "success": False,
            },
            "packetType": "receive_invoice_confirm",
            "fiscalId": "A111OK",
            "sign": "",
        }
    )
    assert result.status is RequestStatus.FAILED
    assert isinstance(result.data, ValidationDetail)
    assert result.data.success is False
    assert result.data.error[0].code == "011107"
    assert result.data.warning[0].errorType == "WARNING"


def test_inquiry_result_accepts_empty_data_object():
    result = InquiryResult.model_validate(
        {"referenceNumber": "780c7cb1", "uid": "b3bd6327", "status": "IN_PROGRESS", "data": {}}
    )
    assert result.status is RequestStatus.IN_PROGRESS
    assert result.data == {}


def test_inquiry_result_tolerates_unknown_status_and_extra_fields():
    result = InquiryResult.model_validate(
        {"uid": "b3bd6327", "status": "SOMETHING_NEW", "somethingElse": 1}
    )
    assert result.status == "SOMETHING_NEW"


def test_invoice_status_result_parses_the_documented_example():
    results = [
        InvoiceStatusResult.model_validate(r)
        for r in [
            {"taxId": "A111DW04E8300004349008", "invoiceStatus": "APPROVED",
             "article6Status": "NOT_EXCEEDED", "error": None},
            {"taxId": "A111DW04E8300003CC4EA5", "invoiceStatus": "APPROVED",
             "article6Status": "NOT_EXCEEDED", "error": None},
        ]
    ]
    assert results[0].invoiceStatus is InvoiceStatus.APPROVED
    assert results[0].article6Status is Article6Status.NOT_EXCEEDED
    assert results[1].error is None


def test_taxpayer_and_fiscal_information_results():
    taxpayer = TaxpayerResult.model_validate(
        {"nameTrade": "پیشخوان الکترونیک ایرانیان منطقه آزاد انزلی",
         "taxpayerStatus": "ACTIVE", "nationalId": "14003778990"}
    )
    assert taxpayer.nameTrade == "پیشخوان الکترونیک ایرانیان منطقه آزاد انزلی"
    assert taxpayer.taxpayerType is None

    fiscal = FiscalInformationResult.model_validate(
        {"nameTrade": "A11216", "fiscalStatus": "ACTIVE",
         "nationalId": "14003778990", "economicCode": "14003778990"}
    )
    assert fiscal.economicCode == "14003778990"


def test_responses_ignore_fields_the_org_adds_later():
    error = ApiError.model_validate({"code": "4100", "message": "x", "severity": "FATAL"})
    assert error.code == "4100"
    assert not hasattr(error, "severity")


# ------------------------------------------------- taxid is the app's to assign


def test_an_invoice_without_a_taxid_is_accepted():
    """The regression that broke every button on the entry form.

    `taxid: str` with no default made the *key* mandatory, so a header that
    simply omitted it was rejected with "Field required
    (body,invoice,header,taxid)" — before reaching any of the code that fills it
    in. That failed ذخیره پیش‌نویس, اعتبارسنجی and محاسبه مبالغ alike, none of
    which has any business demanding a number the operator cannot know.
    """
    invoice = Invoice.model_validate(
        {"header": {"indatim": 1683997837988, "ins": 1}, "body": [{"sstid": "2710000138624"}]}
    )
    assert invoice.header.taxid == ""


def test_a_supplied_taxid_is_kept():
    """Assigning one is the pipeline's job, but a caller may still pass its own."""
    invoice = Invoice.model_validate(
        {
            "header": {"taxid": "A1121604C220002F095011", "indatim": 1, "ins": 1},
            "body": [{"sstid": "x"}],
        }
    )
    assert invoice.header.taxid == "A1121604C220002F095011"


def test_a_blank_taxid_passes_the_rule_engine():
    """The other half of the contract.

    An empty taxid has to be acceptable to validation too, or the entry form
    would trade a 422 for an error banner and the operator would be no better
    off. The engine treats it as satisfied because the application supplies it.
    """
    from moadian.rules import RuleEngine

    invoice = Invoice.model_validate(
        {
            "header": {
                "indatim": 1683997837988, "inty": 1, "inp": 1, "ins": 1,
                "tins": "14003778990", "tob": 2, "tprdis": 20000, "tdis": 500,
                "tadis": 19500, "tvam": 1755, "todam": 0, "tbill": 21255, "setm": 1,
            },
            "body": [{
                "sstid": "2710000138624", "sstt": "سرسیلندر", "mu": "164", "am": 2,
                "fee": 10000, "prdis": 20000, "dis": 500, "adis": 19500, "vra": 9,
                "vam": 1755, "tsstam": 21255,
            }],
        }
    )
    assert invoice.header.taxid == ""
    assert RuleEngine().verify(invoice).ok


# ------------------------------------- blank strings must not reach the wire


def test_a_blank_optional_string_is_dropped_from_the_wire():
    """The bug that got a real invoice refused.

    Sent with `"mu": ""`, the organization answered 0103502 — "مقدار وارد شده در
    فیلد «واحد اندازه‌گیری» جز مقادیر مجاز نیست". The field is اختیاری, so leaving
    it out is legal; ``""`` is present-and-invalid. `exclude_none` dropped None
    and kept the empty string, and the entry form's blank input produced exactly
    that. Forty-six optional string fields on this model could do the same.
    """
    invoice = Invoice.model_validate(
        {
            "header": {"indatim": 1683997837988, "ins": 1, "bid": "", "scln": "", "billid": ""},
            "body": [{"sstid": "2710000138624", "sstt": "", "mu": "", "cut": ""}],
        }
    )
    wire = invoice.to_wire_dict()
    assert "mu" not in wire["body"][0]
    assert "sstt" not in wire["body"][0]
    assert "cut" not in wire["body"][0]
    assert "bid" not in wire["header"]
    assert "scln" not in wire["header"]
    assert "billid" not in wire["header"]


def test_whitespace_only_counts_as_blank():
    """A space typed into a field is not a code either."""
    invoice = Invoice.model_validate(
        {"header": {"indatim": 1, "ins": 1}, "body": [{"sstid": "x", "mu": "   "}]}
    )
    assert "mu" not in invoice.to_wire_dict()["body"][0]


def test_a_blank_taxid_does_not_travel():
    """It is filled by the pipeline at submission; an empty one is not a value."""
    invoice = Invoice.model_validate({"header": {"indatim": 1, "ins": 1}, "body": [{"sstid": "x"}]})
    assert "taxid" not in invoice.to_wire_dict()["header"]


def test_a_real_value_still_travels():
    """The obvious regression in the other direction."""
    invoice = Invoice.model_validate(
        {
            "header": {"taxid": "A459XR050F000000000018", "indatim": 1, "ins": 1},
            "body": [{"sstid": "x", "mu": "164", "sstt": "شرح"}],
        }
    )
    wire = invoice.to_wire_dict()
    assert wire["header"]["taxid"] == "A459XR050F000000000018"
    assert wire["body"][0]["mu"] == "164"
    assert wire["body"][0]["sstt"] == "شرح"


def test_zero_is_not_blank():
    """0 is a real amount; only strings are stripped."""
    invoice = Invoice.model_validate(
        {"header": {"indatim": 1, "ins": 1, "todam": 0}, "body": [{"sstid": "x", "dis": 0}]}
    )
    wire = invoice.to_wire_dict()
    assert wire["header"]["todam"] == 0
    assert wire["body"][0]["dis"] == 0


def test_payment_lines_are_stripped_too():
    """Most optional text fields are on the lines, not the header."""
    invoice = Invoice.model_validate(
        {
            "header": {"indatim": 1, "ins": 1},
            "body": [{"sstid": "x"}],
            "payments": [{"iinn": "", "acn": "", "trmn": "123"}],
        }
    )
    payment = invoice.to_wire_dict()["payments"][0]
    assert "iinn" not in payment
    assert "acn" not in payment
    assert payment["trmn"] == "123"
