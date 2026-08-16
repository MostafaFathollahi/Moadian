"""Exception hierarchy and the tax-organization error-code catalogue.

Every exception raised by this package derives from :class:`MoadianError`, so a
caller can wrap a whole submission in one ``except``.
"""

from __future__ import annotations

__all__ = [
    "MoadianError",
    "CryptographyError",
    "CertificateError",
    "InvalidTaxIdError",
    "InvoiceValidationError",
    "ConfigurationError",
    "TransportError",
    "TaxApiError",
    "AuthenticationError",
    "UnknownResponseError",
    "ERROR_CODES",
    "describe",
]


class MoadianError(Exception):
    """Base class for every error raised by this package."""


class CryptographyError(MoadianError):
    """Signing, encryption, or key handling failed."""


class CertificateError(CryptographyError):
    """The signing certificate is missing, malformed, or unusable."""


class InvalidTaxIdError(MoadianError):
    """A شماره منحصر به فرد مالیاتی is malformed or fails its check digit."""


class InvoiceValidationError(MoadianError):
    """An invoice broke RC_IITP rules and was not sent.

    Raised before signing, deliberately: the organization validates
    asynchronously, and by the time it refuses an invoice a tax id and a serial
    have already been spent on it and cannot be reused.
    """

    def __init__(self, violations) -> None:  # noqa: ANN001 - avoids a circular import
        self.violations = tuple(violations)
        joined = "؛ ".join(str(v) for v in self.violations[:5])
        more = f" (و {len(self.violations) - 5} مورد دیگر)" if len(self.violations) > 5 else ""
        super().__init__(f"صورتحساب معتبر نیست: {joined}{more}")

    @property
    def fields(self) -> list[str]:
        """The wire fields at fault, for a UI that highlights inputs."""
        return [v.field for v in self.violations]


class ConfigurationError(MoadianError):
    """Settings or stored credentials are missing, invalid, or undecryptable."""


class TransportError(MoadianError):
    """The request never produced an HTTP response.

    DNS failure, connection refused, TLS handshake failure, connect/read
    timeout — anything ``httpx`` raises as :class:`httpx.HTTPError` before a
    status line exists. The original exception is kept as ``__cause__``, so
    ``except TransportError as exc: exc.__cause__`` still tells retry logic
    which of those it was.

    A request that *did* get a response and was rejected is a
    :class:`TaxApiError`, never this.
    """


class TaxApiError(MoadianError):
    """The tax API rejected a request.

    ``errors`` carries the ``errors`` array of the response envelope as
    ``(code, message)`` pairs; see WIRE_FORMAT.md "Error envelope".
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        errors: list[tuple[str, str]] | None = None,
        request_trace_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.errors: list[tuple[str, str]] = list(errors or [])
        self.request_trace_id = request_trace_id

    @property
    def codes(self) -> list[str]:
        """The error codes reported by the server, in response order."""
        return [code for code, _ in self.errors]

    def __str__(self) -> str:
        parts = [self.message]
        if self.status_code is not None:
            parts.append(f"HTTP {self.status_code}")
        if self.errors:
            parts.append("; ".join(f"{code}: {msg}" for code, msg in self.errors))
        if self.request_trace_id:
            parts.append(f"requestTraceId={self.request_trace_id}")
        return " | ".join(parts)

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}({self.message!r}, status_code={self.status_code!r}, "
            f"errors={self.errors!r}, request_trace_id={self.request_trace_id!r})"
        )


class AuthenticationError(TaxApiError):
    """The bearer token was rejected — bad nonce, expired token, or no permission."""


class UnknownResponseError(TaxApiError):
    """The response did not match any documented shape."""


# --------------------------------------------------------------------------
# Error-code catalogue
#
# Source: Docs/کدهای خطا.pdf (RC_TXPS.EC_V02, اسفند ۱۴۰۲). Raw pypdf dump kept
# at tests/vectors/error_codes_extracted.txt.
#
# 94 codes, transcribed by hand from the extracted tables. The codes themselves
# are high confidence: every one was cross-checked against a second extraction
# in pypdf `layout` mode, which preserves the table geometry and therefore shows
# which cell each number sits in. RTL extraction mangles word spacing, so the
# messages are normalised — whitespace collapsed and ZWNJ (U+200C) restored in
# the standard places (نمی‌شود, بسته‌ی, غیرمنتظره‌ای). Treat the codes as exact
# and the messages as display text, not as strings to compare against.
#
# Only 4100 and 5199 are byte-verified against live sandbox responses.
#
# The content layer (RC_TXPS.EC_V02 §5) does not have a flat catalogue: those
# codes are *generated* per field — digit 1 error/warning, digit 2 validation
# kind, digits 3-5 field number, digits 6-7 detail. Only the §7 "frequent
# errors" sample is listed here; do not expect describe() to cover the rest.
#
# Doc bug: the auth table prints "4101" on two consecutive rows. The live
# sandbox returns 4100 for "متد درخواست ارسالی پشتیبانی نمی‌شود.", so the first
# of those two rows is a typo for 4100 and 4101 is the payload-structure error.
# --------------------------------------------------------------------------
ERROR_CODES: dict[str, str] = {
    # §4.2 — authentication, v2 (signing certificate). HTTP 401 unless noted.
    "4100": "متد درخواست ارسالی پشتیبانی نمی‌شود.",
    "4101": (
        "ساختار payload در توکن JWT فرستاده شده مطابق با ساختار "
        '{"nonce":"string","clientId":"string"} نمی‌باشد.'
    ),
    "4102": (
        "چالش تصادفی امضا شده در توکن JWT معتبر نمی‌باشد "
        "(قبلا استفاده شده یا زمان استفاده آن گذشته است)."
    ),
    "4103": (
        "کد ملی گواهی امضایی که توکن JWT با آن امضا شده با کد ملی مربوط به "
        "شناسه کلاینت قرار داده شده در توکن مطابقت ندارد."
    ),
    "4110": "شناسه کلاینت (شناسه حافظه) وارد شده در توکن JWT یافت نشد.",
    "4120": "شناسه کلاینت (شناسه شرکت معتمد) وارد شده در توکن JWT یافت نشد.",
    "4130": "ساختار توکن JWT فرستاده شده صحیح نیست.",
    "4131": "امضای توکن JWT یا گواهی امضای فرستاده شده معتبر نمی‌باشد.",
    "4132": "کلید عمومی معتبر یافت نشد.",
    "4133": "امضا نامعتبر است.",
    "4134": "Encoding برابر با UTF-8 نیست.",
    "4135": "گواهی امضایی در فیلد x5c یافت نشد.",
    "4136": "فرمت گواهی امضای ارسالی در فیلد x5c معتبر نمی‌باشد.",
    "4137": (
        "کلید عمومی مربوط به شناسه یکتا معتبر نمی‌باشد. "
        "لطفا از طریق کارپوشه مجددا کلید عمومی خود را آپلود نمایید."
    ),
    "4146": "زمان اعتبار چالش تصادفی باید بین 10 تا 200 ثانیه باشد.",  # HTTP 400
    "4148": "شناسه یکتای ارسالی نامعتبر است.",  # HTTP 400
    "5119": "مشکل غیرمنتظره در دریافت اطلاعات پرونده مالیاتی رخ داد.",  # HTTP 500
    "5129": "مشکل غیرمنتظره در دریافت اطلاعات شرکت معتمد رخ داد.",  # HTTP 500
    "5139": "خطای غیرمنتظره‌ای در بررسی صحت امضای توکن JWT رخ داد.",  # HTTP 500
    # §4.3 — POST /invoice. All HTTP 400.
    "4143": "در یک درخواست نمی‌توانید بیشتر از 1000 صورتحساب ارسال نمایید.",
    "4144": "بدنه‌ی درخواست ارسالی خالی است یا از نظر ساختار JSON معتبر نیست.",
    "4145": (
        "در بدنه‌ی درخواست ارسالی، بعضی از فیلدهای ضروری خالی است "
        "(برای هر صورتحساب باید payload، requestTraceId و fiscalId موجود باشد)."
    ),
    "4162": "شناسه درخواست (requestTraceId) داخل درخواست معتبر نمی‌باشد.",
    "4163": "در درخواست ارسالی شناسه درخواست تکراری وجود دارد.",
    # §4.4 — GET /inquiry, /inquiry-by-uid, /inquiry-by-reference-id. All HTTP 400.
    "4140": "زمان شروع بازه‌ی استعلام باید قبل از زمان پایان آن باشد.",
    "4141": "نمی‌توانید در یک درخواست وضعیت بیش از 100 صورتحساب را استعلام بگیرید.",
    "4142": (
        "مقدار status وارد شده نامعتبر است. "
        "مقادیر مجاز: [SUCCESS, FAILED, IN_PROGRESS, TIMEOUT]"
    ),
    "4164": "بازه زمانی استعلام حداکثر یک هفته است.",
    # §4.5 — everything else under /api/v2/.
    "4147": "فرمت ورودی‌های درخواست نادرست می‌باشد.",  # HTTP 400
    "4160": "دسترسی مشاهده اطلاعات شناسه یکتای درخواست شده ممکن نیست.",  # HTTP 403
    "4170": "شماره اقتصادی وارد شده یافت نشد.",  # HTTP 404
    "4171": "شماره اقتصادی وارد شده از نظر طول معتبر نیست.",  # HTTP 404
    "5199": "خطای غیر منتظره‌ای در انجام درخواست رخ داد.",  # HTTP 500
    # §4.6 — transport layer. Not returned by the POST; these surface later in
    # the inquiry result, and carry a leading zero.
    "04111": "قرارداد شناسه یکتا و شرکت معتمد یافت نشد.",
    "04130": "ساختار بسته‌ی صورتحساب (encrypted payload) امضا شده صحیح نیست.",
    "04131": (
        "امضای صورتحساب ارسالی یا گواهی امضایی که صورتحساب با آن امضا شده "
        "معتبر نمی‌باشد."
    ),
    "04132": (
        "گواهی امضایی که صورتحساب با آن امضا شده، دسترسی صدور و امضای صورتحساب "
        "برای این شناسه یکتا را ندارد."
    ),
    "04133": "شناسه حافظه امضاکننده‌ی صورتحساب یافت نشد/غیر فعال می‌باشد.",
    "04134": "شناسه شرکت معتمد امضاکننده‌ی صورتحساب یافت نشد/غیرفعال می‌باشد.",
    "04148": "شناسه یکتای ارسالی نامعتبر است.",
    "04150": (
        "بسته‌ی JWE صورتحساب ارسالی از نظر ساختاری معتبر نمی‌باشد و امکان "
        "رمزگشایی آن وجود ندارد."
    ),
    "04152": "الگوریتم مورد استفاده برای رمزنگاری معتبر نمی‌باشد.",
    "04153": "طول فیلد IV باید 96 بیت باشد.",
    "05139": "خطای غیرمنتظره‌ای در فرآیند بررسی امضای صورتحساب رخ داد.",
    "05151": "خطایی غیر منتظره در رمزگشایی صورتحساب ارسالی رخ داد.",
    "05159": "خطای غیرمنتظره‌ای در فرآیند بررسی دسترسی امضاکننده صورتحساب رخ داد.",
    # §4.7 — legacy (pre-v2) collection web service. Kept for diagnosing calls
    # that accidentally hit the deprecated endpoints; do not target these.
    "4001": "ساختار JSON درخواست داده شده اشتباه است.",
    "4002": "نوع بسته با محتوای بسته یکسان نیست.",
    "4003": "بسته ارسالی پشتیبانی نمی‌شود.",
    "4004": "برای این نوع بسته، ارسال هدر Authorization الزامی می‌باشد.",
    "4005": "ارسال این نوع بسته به صورت همگام مجاز نمی‌باشد.",
    "4006": "ارسال این بسته به صورت غیرهمگام مجاز نمی‌باشد.",
    "4007": "برای این نوع بسته، ارسال امضا الزامی می‌باشد.",
    "4008": "شناسه کلید رمزنگاری اشتباه است.",
    "4009": "شناسه حافظه در بسته الزامی است.",
    "4010": "ساختار JSON بسته داده شده اشتباه است.",
    "4011": "امضای بسته صحیح نمی‌باشد. (در APIهای جمع‌آوری)",
    "4012": "تعداد بسته‌ها داخل درخواست بیش از حد مجاز است.",
    "4015": "ساختار تاریخ ارسال شده صحیح نمی‌باشد.",
    "4016": "ساختار توکن دسترسی صحیح نمی‌باشد.",
    "4017": "اعتبار توکن دسترسی به پایان رسیده است.",
    "4018": "اعتبار درخواست داده شده منقضی شده است.",
    "4019": "درخواست تکراری است.",
    "4020": "توکن دسترسی معتبری یافت نشد.",
    "4021": "ارسال فیلد packet الزامی است.",
    "4022": "امضای توکن دسترسی صحیح نمی‌باشد.",
    "4024": "شما مجاز به استفاده از این سرویس نیستید.",
    "4200": "شما مجاز به ارسال بسته برای این شناسه یکتای حافظه مالیاتی نیستید.",
    "4202": "فیلد packet الزامی است.",
    "4204": "رمزنگاری بسته الزامی است.",
    "4205": "ارسال کلید متقارن الزامی است.",
    "4206": "داده‌های ورودی برای رمزگشایی معتبر نمی‌باشد.",
    "4207": "ساختار کلید متقارن صحیح نمی‌باشد.",
    "4208": "داده‌ها با کلید متقارن رمزگشایی نشد.",
    "4209": "وارد کردن کد اقتصادی الزامی است. (در متد دریافت اطلاعات کد اقتصادی)",
    "4210": "نوع بسته استعلام کد اقتصادی معتبر نمی‌باشد.",
    "4212": "امضا بسته صحیح نمی‌باشد. (هنگام استعلام وضعیت صورتحساب)",
    "5051": "پردازه مدیریت کلید در دسترس نمی‌باشد، مدتی بعد تلاش کنید.",
    "5052": "امکان پردازش این نوع بسته وجود ندارد.",
    "5056": "خطا در ارتباط با صف",
    "5057": "خطا در ارتباط با سرویس توزیع، مدتی بعد تلاش کنید.",
    "5200": "خطای ناشناخته‌ای در هنگام پردازش درخواست شما رخ داده است.",
    "5201": "سرویس احراز هویت در دسترس نمی‌باشد، مدتی بعد تلاش کنید.",
    "5202": "سرویس مدیریت کلید سازمان در دسترس نمی‌باشد، مدتی بعد تلاش کنید.",
    "5203": "خطا در رمزگشایی بسته.",
    "5205": "خطا در نرمال کردن بسته.",
    "5206": "سرویس مدیریت کلید در دسترس نمی‌باشد، مدتی بعد تلاش کنید.",
    "5207": "سرویس اطلاعات پرونده مالیاتی در دسترس نمی‌باشد، مدتی بعد تلاش کنید.",
    # §5/§7 — content layer. Generated per field; these are the documented
    # frequent ones plus the truncation warning.
    "00000": (
        "تعداد پیام‌های خطا/هشدار بیشتر از 50 مورد است و امکان نمایش بیشتر از "
        "این تعداد وجود ندارد."
    ),
    "02002": (
        "مقدار فیلد تاریخ و زمان صدور صورتحساب از لحاظ قواعد محاسباتی و منطقی "
        "معتبر نیست."
    ),
    "0300101": "مقدار فیلد شماره منحصر به فرد مالیاتی با اطلاعات سامانه منطبق نیست.",
    "0300601": "مقدار فیلد شماره مالیاتی صورتحساب مرجع با اطلاعات سامانه منطبق نیست.",
    "0301201": "مقدار فیلد شماره اقتصادی خریدار با اطلاعات سامانه منطبق نیست.",
    "0304401": "مقدار فیلد نرخ مالیات بر ارزش افزوده با اطلاعات سامانه منطبق نیست.",
}


def describe(code: str) -> str | None:
    """Return the Persian message for an error code, or ``None`` if unknown."""
    return ERROR_CODES.get(code)
