namespace TaxCollectData.Library.Domain.Exceptions;

/// <summary>
/// Exception thrown when Tax API returns an error
/// </summary>
public class TaxApiException : DomainException
{
    public string? ErrorCode { get; }
    public string? ErrorMessage { get; }
    public int? StatusCode { get; }

    public TaxApiException(string message) : base(message)
    {
    }

    public TaxApiException(string message, string? errorCode, string? errorMessage) 
        : base(message)
    {
        ErrorCode = errorCode;
        ErrorMessage = errorMessage;
    }

    public TaxApiException(string message, int statusCode, string? errorCode = null, string? errorMessage = null) 
        : base(message)
    {
        StatusCode = statusCode;
        ErrorCode = errorCode;
        ErrorMessage = errorMessage;
    }
}

