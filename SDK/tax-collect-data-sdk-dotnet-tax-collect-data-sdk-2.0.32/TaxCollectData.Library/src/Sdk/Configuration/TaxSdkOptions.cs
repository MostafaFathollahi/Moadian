namespace TaxCollectData.Library.Sdk.Configuration;

/// <summary>
/// Configuration options for Tax SDK
/// </summary>
public class TaxSdkOptions
{
    /// <summary>
    /// Base URL of the tax administration API
    /// </summary>
    public string BaseUrl { get; set; } = string.Empty;

    /// <summary>
    /// Client ID (MemoryId)
    /// </summary>
    public string ClientId { get; set; } = string.Empty;

    /// <summary>
    /// Path to private key file (PKCS#8)
    /// </summary>
    public string? PrivateKeyPath { get; set; }

    /// <summary>
    /// Path to certificate file (X.509)
    /// </summary>
    public string? CertificatePath { get; set; }

    /// <summary>
    /// PKCS#11 library path (for hardware tokens)
    /// </summary>
    public string? Pkcs11LibraryPath { get; set; }

    /// <summary>
    /// PKCS#11 token serial number
    /// </summary>
    public string? Pkcs11TokenSerialNumber { get; set; }

    /// <summary>
    /// PKCS#11 token PIN
    /// </summary>
    public string? Pkcs11TokenPin { get; set; }

    /// <summary>
    /// HTTP request timeout
    /// </summary>
    public TimeSpan RequestTimeout { get; set; } = TimeSpan.FromMinutes(10);

    /// <summary>
    /// API version
    /// </summary>
    public string ApiVersion { get; set; } = "v2";

    /// <summary>
    /// Custom HTTP headers
    /// </summary>
    public Dictionary<string, string> CustomHeaders { get; set; } = new();

    /// <summary>
    /// Validates the configuration
    /// </summary>
    public void Validate()
    {
        if (string.IsNullOrWhiteSpace(BaseUrl))
        {
            throw new ArgumentException("BaseUrl is required", nameof(BaseUrl));
        }

        if (string.IsNullOrWhiteSpace(ClientId))
        {
            throw new ArgumentException("ClientId is required", nameof(ClientId));
        }

        // Validate certificate configuration
        var hasPkcs8Config = !string.IsNullOrWhiteSpace(PrivateKeyPath) && !string.IsNullOrWhiteSpace(CertificatePath);
        var hasPkcs11Config = !string.IsNullOrWhiteSpace(Pkcs11LibraryPath) && 
                             !string.IsNullOrWhiteSpace(Pkcs11TokenSerialNumber);

        if (!hasPkcs8Config && !hasPkcs11Config)
        {
            throw new ArgumentException("Either PKCS#8 (PrivateKeyPath + CertificatePath) or PKCS#11 configuration is required");
        }
    }
}

