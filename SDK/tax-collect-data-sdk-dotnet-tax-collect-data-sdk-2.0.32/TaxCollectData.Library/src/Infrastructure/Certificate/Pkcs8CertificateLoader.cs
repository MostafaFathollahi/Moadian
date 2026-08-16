using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using Org.BouncyCastle.Crypto.Parameters;
using Org.BouncyCastle.OpenSsl;
using Org.BouncyCastle.Security;
using TaxCollectData.Library.Domain.Exceptions;

namespace TaxCollectData.Library.Infrastructure.Certificate;

/// <summary>
/// PKCS#8 certificate loader (file-based)
/// </summary>
public class Pkcs8CertificateLoader : ICertificateLoader
{
    public X509Certificate LoadCertificate(string certificatePath)
    {
        if (string.IsNullOrWhiteSpace(certificatePath))
        {
            throw new ArgumentException("Certificate path cannot be null or empty", nameof(certificatePath));
        }

        if (!File.Exists(certificatePath))
        {
            throw new CertificateException($"Certificate file not found: {certificatePath}");
        }

        try
        {
            var certificateBytes = File.ReadAllBytes(certificatePath);
            return new X509Certificate(certificateBytes);
        }
        catch (Exception ex)
        {
            throw new CertificateException($"Failed to load certificate from {certificatePath}", ex);
        }
    }

    public RSA LoadPrivateKey(string privateKeyPath)
    {
        if (string.IsNullOrWhiteSpace(privateKeyPath))
        {
            throw new ArgumentException("Private key path cannot be null or empty", nameof(privateKeyPath));
        }

        if (!File.Exists(privateKeyPath))
        {
            throw new CertificateException($"Private key file not found: {privateKeyPath}");
        }

        try
        {
            using var reader = File.OpenText(privateKeyPath);
            var pemReader = new PemReader(reader);
            var keyPair = pemReader.ReadObject();
            
            if (keyPair is not Org.BouncyCastle.Crypto.AsymmetricCipherKeyPair bcKeyPair)
            {
                throw new CertificateException("Invalid private key format");
            }

            var privateKey = bcKeyPair.Private as RsaPrivateCrtKeyParameters;
            if (privateKey == null)
            {
                throw new CertificateException("Private key is not RSA");
            }

            return DotNetUtilities.ToRSA(privateKey);
        }
        catch (Exception ex)
        {
            throw new CertificateException($"Failed to load private key from {privateKeyPath}", ex);
        }
    }
}

