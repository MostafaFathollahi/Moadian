using TaxCollectData.Library.Domain.Enums;

namespace TaxCollectData.Library.Application.DTOs;

public class RegisterPaymentRequestDto
{
    public string TaxId { get; set; } = string.Empty;
    public long PaidAmount { get; set; }
    public long PaymentDate { get; set; }
    public PaymentMethod PaymentMethod { get; set; }
    public string TerminalNumber { get; set; } = string.Empty;
    public string ReferenceNumber { get; set; } = string.Empty;
}

