namespace TaxCollectData.Library.Domain.Exceptions;

/// <summary>
/// Exception thrown when certificate operations fail
/// </summary>
public class CertificateException : DomainException
{
    public CertificateException(string message) : base(message)
    {
    }

    public CertificateException(string message, Exception innerException) 
        : base(message, innerException)
    {
    }
}

