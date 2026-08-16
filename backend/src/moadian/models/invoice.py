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

from pydantic import BaseModel, ConfigDict, Field

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
    """سرآیند صورتحساب. Only `taxid`, `indatim` and `ins` are required."""

    model_config = _STRICT

    # --- required ---
    taxid: str  # شماره منحصر به فرد مالیاتی
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
        """
        return self.model_dump(exclude_none=True, by_alias=True)
