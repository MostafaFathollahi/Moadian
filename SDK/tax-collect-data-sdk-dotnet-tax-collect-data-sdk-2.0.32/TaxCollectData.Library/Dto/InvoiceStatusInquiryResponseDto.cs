namespace TaxCollectData.Library.Dto;

public class InvoiceStatusInquiryResponseDto
{
    public InvoiceStatusInquiryResponseDto(string taxId, string invoiceStatus, string article6Status, string error)
    {
        TaxId = taxId;
        InvoiceStatus = invoiceStatus;
        Article6Status = article6Status;
        Error = error;
    }

    public string TaxId { get; }
    public string InvoiceStatus { get; }
    public string Article6Status { get; }
    public string Error { get; }
}