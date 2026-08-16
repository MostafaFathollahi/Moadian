namespace TaxCollectData.Library.Application.DTOs;

public class InvoiceDto
{
    public HeaderDto Header { get; set; } = new();
    public List<BodyItemDto> Body { get; set; } = new();
    public List<PaymentItemDto> Payments { get; set; } = new();
    public List<ExtensionItemDto> Extension { get; set; } = new();
}

