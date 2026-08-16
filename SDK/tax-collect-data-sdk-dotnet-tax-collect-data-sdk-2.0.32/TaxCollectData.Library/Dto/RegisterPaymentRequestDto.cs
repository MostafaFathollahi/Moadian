using TaxCollectData.Library.Enums;

namespace TaxCollectData.Library.Dto;

public class RegisterPaymentRequestDto
{
    public string TaxId { get; set; }

    public long PaidAmount { get; set; }

    public long PaymentDate { get; set; }

    public PaymentMethod PaymentMethod { get; set; }

    public string TerminalNumber { get; set; }

    public string ReferenceNumber { get; set; }
}