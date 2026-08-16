namespace TaxCollectData.Library.Application.Interfaces;

/// <summary>
/// Service for cryptography operations (signing and encryption)
/// </summary>
public interface ICryptographyService
{
    /// <summary>
    /// Signs the given data
    /// </summary>
    string Sign(string data);

    /// <summary>
    /// Signs the given object
    /// </summary>
    string Sign(object data);

    /// <summary>
    /// Encrypts the given data
    /// </summary>
    string Encrypt(string data);
}

