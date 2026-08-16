namespace TaxCollectData.Library.Domain.Exceptions;

/// <summary>
/// Exception thrown when TaxId is invalid
/// </summary>
public class InvalidTaxIdException : DomainException
{
    public InvalidTaxIdException(string taxId) 
        : base($"Invalid TaxId: {taxId}")
    {
    }
}

