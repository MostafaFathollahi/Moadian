namespace TaxCollectData.Library.Application.DTOs;

public class InquiryResultDto
{
    public string ReferenceNumber { get; set; } = string.Empty;
    public string Uid { get; set; } = string.Empty;
    public string Status { get; set; } = string.Empty;
    public InvoiceValidationResponseDto Data { get; set; } = new(new List<ErrorDto>(), new List<ErrorDto>(), false);
    public string PacketType { get; set; } = string.Empty;
    public string FiscalId { get; set; } = string.Empty;
    public string Sign { get; set; } = string.Empty;
}

