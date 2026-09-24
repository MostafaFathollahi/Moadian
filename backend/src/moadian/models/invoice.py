"""Invoice payload — RC_IITP_IS_V7_9_1 §9-3.

Field names are the wire names verbatim. A rename here is invisible in tests and
only surfaces as an organization-side rejection, so nothing is prettified.

Typing follows the official .NET DTOs (`TaxCollectData.Library/Dto/*.cs`):
C# ``long?`` money/counter fields become ``int | None``, C# ``decimal?`` fields
(quantities, rates, weights, per-unit prices) become ``float | None``.

``extra="forbid"``: a misspelt field that is silently dropped would be signed and
sent as an incomplete invoice. Fail at construction instead.

``allow_inf_nan=False``: ``float("nan")`` and ``float("inf")`` have no JSON
representation (see :func:`moadian.crypto.canonical_json`), and an amount that is
not a finite number is meaningless on an invoice anyway. Construction is the
right boundary to reject them — well before a tax id is spent.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from moadian.persian import fold_digits

__all__ = [
    "Invoice",
    "InvoiceBodyItem",
    "InvoiceHeader",
    "InvoicePayment",
    "ShippingGood",
]

_STRICT = ConfigDict(populate_by_name=True, extra="forbid", allow_inf_nan=False)


class ShippingGood(BaseModel):
    """کالای حمل‌شده — one entry of the header's `sg` list."""

    model_config = _STRICT

    sgid: str | None = None  # شناسه کالای حمل شده
    sgt: str | None = None  # شرح کالای حمل شده


class InvoiceHeader(BaseModel):
    """سرآیند صورتحساب. Only `indatim` and `ins` must be supplied by a caller.

    ``taxid`` is required *on the wire* and is not a caller's to invent: it
    encodes the fiscal memory, the issue date and a serial that must never
    repeat, so :class:`~moadian.pipeline.InvoicePipeline` derives it from the
    persisted counter at submission. Defaulting it to ``""`` is what lets a
    caller leave it out and get a correct one — declaring it required meant
    every draft, every اعتبارسنجی and every محاسبه مبالغ was rejected with
    "Field required (body,invoice,header,taxid)" before any of them reached the
    code that fills it in. The rule engine already treats a blank one as fine
    for exactly this reason.
    """

    model_config = _STRICT

    # --- required ---
    #: Left blank to have one generated. See the class docstring.
    taxid: str = ""  # شماره منحصر به فرد مالیاتی
    indatim: int  # تاریخ و زمان صدور صورتحساب (میلادی) — epoch millis
    ins: int  # نوع تسویه

    # --- identification / classification ---
    indati2m: int | None = None  # تاریخ و زمان ایجاد صورتحساب — epoch millis
    inty: int | None = None  # نوع صورتحساب
    ft: int | None = None  # موضوع صورتحساب
    inno: str | None = None  # سریال صورتحساب داخلی
    irtaxid: str | None = None  # شماره منحصر به فرد مالیاتی صورتحساب مرجع
    scln: str | None = None  # شماره پروانه گمرکی
    setm: int | None = None  # روش تسویه
    inp: int | None = None  # الگوی صورتحساب
    billid: str | None = None  # شماره قبض

    # --- seller (فروشنده) ---
    tins: str | None = None  # شماره/شناسه ملی فروشنده
    bpc: str | None = None  # کد پستی فروشنده  (note: `bpc` is the seller's, per DTO)
    scc: str | None = None  # کد شعبه فروشنده
    sbc: str | None = None  # کد شعبه فروشنده (شعبه صادرکننده)

    # --- insurance / capital ---
    cap: int | None = None  # سرمایه
    bid: str | None = None  # شناسه یکتای ...
    insp: int | None = None  # مبلغ بیمه
    tvop: int | None = None  # مجموع مالیات بر ارزش افزوده پرداختی
    tax17: int | None = None  # مالیات موضوع ماده ۱۷

    # --- totals (جمع‌ها) ---
    tprdis: int | None = None  # مجموع مبلغ قبل از کسر تخفیف
    tdis: int | None = None  # مجموع تخفیفات
    tadis: int | None = None  # مجموع مبلغ پس از کسر تخفیف
    tvam: int | None = None  # مجموع مالیات بر ارزش افزوده
    todam: int | None = None  # مجموع سایر مالیات، عوارض و وجوه قانونی
    tbill: int | None = None  # مجموع صورتحساب

    # --- buyer (خریدار) ---
    tob: int | None = None  # نوع شخص خریدار
    tinb: str | None = None  # شماره/شناسه ملی خریدار — leading zeros matter, keep str
    bbc: str | None = None  # کد شعبه خریدار
    bpn: str | None = None  # کد پستی خریدار
    crn: str | None = None  # شماره ثبت/شناسه مشارکت مدنی خریدار

    # --- customs / export (صادرات و گمرک) ---
    cdcn: str | None = None  # شماره کوتاژ اظهارنامه گمرکی
    cdcd: int | None = None  # تاریخ کوتاژ اظهارنامه گمرکی
    tonw: float | None = None  # وزن خالص کل
    torv: int | None = None  # ارزش ریالی کل
    tocv: float | None = None  # ارزش ارزی کل
    tinc: str | None = None  # شناسه ملی کارگزار گمرکی
    lno: str | None = None  # شماره بارنامه
    lrno: str | None = None  # شماره رهگیری بارنامه
    ocu: str | None = None  # کشور مبدا
    oci: str | None = None  # کشور مقصد
    dco: str | None = None  # مقصد بارگیری
    dci: str | None = None  # مبدا بارگیری

    # --- transport (حمل و نقل) ---
    tid: str | None = None  # شناسه یکتای وسیله نقلیه
    rid: str | None = None  # شماره راننده
    lt: int | None = None  # نوع حمل و نقل  (C# byte?)
    cno: str | None = None  # شماره قرارداد
    did: str | None = None  # شناسه یکتای راننده
    sg: list[ShippingGood] | None = None  # کالاهای حمل شده

    # --- assets / insurance policy ---
    asn: str | None = None  # شماره اموال
    asd: int | None = None  # تاریخ اموال
    in_: str | None = Field(default=None, alias="in")  # شناسه یکتای بیمه نامه
    an: str | None = None  # شماره بیمه نامه
    insr: int | None = None  # مبلغ بیمه
    nti1: str | None = None
    nti2: str | None = None


class InvoiceBodyItem(BaseModel):
    """قلم کالا/خدمت. Only `sstid` is required."""

    model_config = _STRICT

    sstid: str  # شناسه کالا/خدمت
    sstt: str | None = None  # شرح کالا/خدمت
    mu: str | None = None  # واحد اندازه‌گیری
    am: float | None = None  # تعداد/مقدار
    fee: float | None = None  # مبلغ واحد
    cfee: float | None = None  # مبلغ واحد ارزی
    cut: str | None = None  # نوع ارز
    exr: int | None = None  # نرخ برابری ارز با ریال
    prdis: int | None = None  # مبلغ قبل از تخفیف
    dis: int | None = None  # مبلغ تخفیف
    adis: int | None = None  # مبلغ پس از تخفیف
    vra: float | None = None  # نرخ مالیات بر ارزش افزوده
    vam: int | None = None  # مبلغ مالیات بر ارزش افزوده
    odt: str | None = None  # موضوع سایر مالیات و عوارض
    odr: float | None = None  # نرخ سایر مالیات و عوارض
    odam: int | None = None  # مبلغ سایر مالیات و عوارض
    olt: str | None = None  # موضوع سایر وجوه قانونی
    olr: float | None = None  # نرخ سایر وجوه قانونی
    olam: int | None = None  # مبلغ سایر وجوه قانونی
    consfee: int | None = None  # اجرت ساخت
    spro: int | None = None  # سود فروشنده
    bros: int | None = None  # حق العمل
    tcpbs: int | None = None  # جمع کل وجوه قانونی، اجرت و حق العمل
    cop: int | None = None  # ضریب ارزش افزوده فلزات گرانبها
    bsrn: str | None = None  # شماره سریال قبض
    vop: int | None = None  # مبلغ ارزش افزوده پرداختی
    tsstam: int | None = None  # مبلغ کل کالا/خدمت
    nw: float | None = None  # وزن خالص
    ssrv: int | None = None  # ارزش ریالی کالا
    sscv: float | None = None  # ارزش ارزی کالا
    cui: float | None = None  # شناسه یکتا ثبت قرارداد
    hs: str | None = None  # کد HS
    cpr: float | None = None  # قیمت مصرف‌کننده
    sovat: int | None = None  # موضوع مالیات بر ارزش افزوده
    vba: float | None = None  # مبنای محاسبه ارزش افزوده


    @field_validator("sstid", "mu", mode="before")
    @classmethod
    def _ascii_digits(cls, value: object) -> object:
        """Fold Persian and Arabic-Indic digits to ASCII on the numeric codes.

        ``۲۷۲۰۰۰۰۱۱۴۵۴۲`` is the same شناسه کالا/خدمت as ``2720000114542`` to a
        person and a different string to the tax service, and these are routinely
        pasted out of Persian PDFs and spreadsheets where they arrive in the first
        form. Sent unfolded they are simply refused.

        Python hides this particularly well: ``"۱۶۴".isdigit()`` is **True**, so a
        format check that looks numeric passes and the wrong bytes go out anyway.

        Only these two fields, and only because they are pure numeric codes.
        Descriptive text is never rewritten — the شرح goes on the invoice exactly
        as it was typed.
        """
        return fold_digits(value) if isinstance(value, str) else value


class InvoicePayment(BaseModel):
    """قلم پرداخت. All fields optional."""

    model_config = _STRICT

    iinn: str | None = None  # شماره شبا/شناسه پرداخت‌کننده
    acn: str | None = None  # شماره حساب
    trmn: str | None = None  # شماره پایانه
    trn: str | None = None  # شماره پیگیری/مرجع
    pcn: str | None = None  # شماره پذیرنده
    pid: str | None = None  # شناسه پرداخت
    vatpid: str | None = None  # شناسه پرداخت مالیات بر ارزش افزوده
    vatbid: str | None = None  # شناسه قبض مالیات بر ارزش افزوده
    pdt: int | None = None  # تاریخ پرداخت — epoch millis
    pmt: int | None = None  # روش پرداخت (کد عددی)
    pv: int | None = None  # مبلغ پرداختی


class Invoice(BaseModel):
    """صورتحساب الکترونیکی — the JWS payload before signing."""

    model_config = _STRICT

    header: InvoiceHeader
    body: list[InvoiceBodyItem]
    payments: list[InvoicePayment] = []
    extension: list[dict[str, Any]] | None = None

    def to_wire_dict(self) -> dict[str, Any]:
        """The dict the client canonicalises into signed bytes.

        Unset fields are dropped entirely — the spec's own p.20 example carries
        no nulls — and `in_` goes out under its wire alias `in`.

        **Blank strings are dropped too, and that is not cosmetic.** An optional
        field the organization validates against a code list is legal when absent
        and rejected when present-but-empty. A real invoice was refused with
        error 0103502 ("مقدار وارد شده در فیلد «واحد اندازه‌گیری» جز مقادیر مجاز
        نیست") because the entry form's blank ``mu`` travelled as ``""`` rather
        than not travelling at all — ``exclude_none`` drops ``None`` and keeps
        ``""``. Forty-six optional string fields on this model could do the same.

        An empty string is how a form says "nothing here"; on this wire, absence
        is how you say it.
        """
        packed = self.model_dump(exclude_none=True, by_alias=True)
        return _without_blanks(packed)


def _without_blanks(value: Any) -> Any:
    """Strip empty and whitespace-only strings, recursively.

    Recursive because the body and payment lines are where most of the optional
    text fields live; a pass over the header alone would have left the ``mu``
    that caused this.
    """
    if isinstance(value, dict):
        return {
            key: _without_blanks(inner)
            for key, inner in value.items()
            if not (isinstance(inner, str) and not inner.strip())
        }
    if isinstance(value, list):
        return [_without_blanks(item) for item in value]
    return value
