namespace TaxCollectData.Library.Application.DTOs;

public class InvoiceValidationResponseDto
{
    public InvoiceValidationResponseDto(List<ErrorDto> error, List<ErrorDto> warning, bool success)
    {
        Error = error;
        Warning = warning;
        Success = success;
    }

    public List<ErrorDto> Error { get; }
    public List<ErrorDto> Warning { get; }
    public bool Success { get; }
}

