namespace TaxCollectData.Library.Application.DTOs;

/// <summary>
/// Response DTO for invoice submission
/// </summary>
public class InvoiceResponseDto
{
    public InvoiceResponseDto(string data, string uid, string referenceNumber, string taxId)
    {
        Data = data;
        Uid = uid;
        ReferenceNumber = referenceNumber;
        TaxId = taxId;
    }

    public string Data { get; }
    public string Uid { get; }
    public string ReferenceNumber { get; }
    public string TaxId { get; }
}

