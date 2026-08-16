"""Closed value sets the API documents (RC_TICS.IS_v1.6).

All of these travel as their *name* on the wire. The .NET SDK confirms it:
``JsonSerializerConfig`` registers a ``JsonStringEnumConverter``, so its plain
C# enums serialise as ``"CHEQUE"``, not ``0``.
"""

from enum import StrEnum

__all__ = [
    "Article6Status",
    "InvoiceStatus",
    "PaymentMethod",
    "RequestStatus",
]


class RequestStatus(StrEnum):
    """Processing state of a submitted packet (`GET /inquiry*`, RC_TICS §8)."""

    IN_PROGRESS = "IN_PROGRESS"  # هنوز در صف بررسی
    SUCCESS = "SUCCESS"  # فاقد خطا، در کارپوشه ثبت شد
    FAILED = "FAILED"  # دارای خطا، رد شد
    TIMEOUT = "TIMEOUT"
    NOT_FOUND = "NOT_FOUND"  # شماره پیگیری یافت نشد


class InvoiceStatus(StrEnum):
    """Buyer-side reaction state in the کارپوشه (`GET /inquiry-invoice-status`)."""

    REJECTED = "REJECTED"  # رد شده
    APPROVED = "APPROVED"  # تایید شده
    SYSTEMIC_APPROVED = "SYSTEMIC_APPROVED"  # تایید سیستمی
    IMPOSSIBLE_REACTION = "IMPOSSIBLE_REACTION"  # عدم امکان واکنش
    AWAITING_REACTION = "AWAITING_REACTION"  # در انتظار واکنش
    NO_NEED_REACTION = "NO_NEED_REACTION"  # عدم نیاز به واکنش
    CANCELED = "CANCELED"  # باطل شده


class Article6Status(StrEnum):
    """Whether the taxpayer passed the Article-6 sales ceiling (حد مجاز ماده ۶)."""

    EXCEEDED = "EXCEEDED"  # عدول
    NOT_EXCEEDED = "NOT_EXCEEDED"  # عدم عدول


class PaymentMethod(StrEnum):
    """`paymentMethod` of `POST /invoice-payment` (RC_TICS §11).

    Distinct from the invoice body's numeric `pmt` — that one is an int code.
    """

    CHEQUE = "CHEQUE"  # چک
    BARTER = "BARTER"  # تهاتر
    CASH = "CASH"  # وجه نقد
    POS = "POS"  # دستگاه پوز
    INTERNET = "INTERNET"  # درگاه پرداخت اینترنتی
    CARD = "CARD"  # کارت به کارت
    TRANSFER = "TRANSFER"  # انتقال به حساب
    OTHER = "OTHER"  # سایر
