using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;

namespace TaxCollectData.Library.Infrastructure.Certificate;

/// <summary>
/// Interface for loading certificates and private keys
/// </summary>
public interface ICertificateLoader
{
    /// <summary>
    /// Loads certificate from file path
    /// </summary>
    X509Certificate LoadCertificate(string certificatePath);

    /// <summary>
    /// Loads private key from file path
    /// </summary>
    RSA LoadPrivateKey(string privateKeyPath);
}

