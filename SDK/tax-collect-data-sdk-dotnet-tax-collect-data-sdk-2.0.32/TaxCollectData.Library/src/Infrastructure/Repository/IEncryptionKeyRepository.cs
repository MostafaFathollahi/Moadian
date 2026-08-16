using System.Security.Cryptography;

namespace TaxCollectData.Library.Infrastructure.Repository;

/// <summary>
/// Repository for encryption keys
/// </summary>
public interface IEncryptionKeyRepository
{
    RSA GetKey();
    string GetKeyId();
}

