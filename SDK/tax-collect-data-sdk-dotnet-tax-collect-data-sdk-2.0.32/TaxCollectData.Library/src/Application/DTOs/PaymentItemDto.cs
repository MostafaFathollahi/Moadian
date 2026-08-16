namespace TaxCollectData.Library.Application.DTOs;

public class PaymentItemDto
{
    public string iinn { get; set; } = string.Empty;
    public string acn { get; set; } = string.Empty;
    public string trmn { get; set; } = string.Empty;
    public string trn { get; set; } = string.Empty;
    public string pcn { get; set; } = string.Empty;
    public string pid { get; set; } = string.Empty;
    public string vatpid { get; set; } = string.Empty;
    public string vatbid { get; set; } = string.Empty;
    public long? pdt { get; set; }
    public int? pmt { get; set; }
    public long? pv { get; set; }
}

