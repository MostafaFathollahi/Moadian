namespace TaxCollectData.Library.Models;

public class InvoiceValidationResponseModel
{
    public InvoiceValidationResponseModel(List<ErrorModel> error, List<ErrorModel> warning, bool success)
    {
        Error = error;
        Warning = warning;
        Success = success;
    }

    public List<ErrorModel> Error { get; }
    public List<ErrorModel> Warning { get; }
    public bool Success { get; }
}