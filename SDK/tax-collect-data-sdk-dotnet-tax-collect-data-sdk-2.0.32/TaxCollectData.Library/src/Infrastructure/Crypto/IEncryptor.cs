namespace TaxCollectData.Library.Infrastructure.Crypto;

/// <summary>
/// Interface for encryption operations
/// </summary>
public interface IEncryptor
{
    string Encrypt(string text);
}

