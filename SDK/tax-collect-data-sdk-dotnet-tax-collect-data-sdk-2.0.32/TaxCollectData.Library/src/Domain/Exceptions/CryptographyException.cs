namespace TaxCollectData.Library.Domain.Exceptions;

/// <summary>
/// Exception thrown when cryptography operations fail
/// </summary>
public class CryptographyException : DomainException
{
    public CryptographyException(string message) : base(message)
    {
    }

    public CryptographyException(string message, Exception innerException) 
        : base(message, innerException)
    {
    }
}

