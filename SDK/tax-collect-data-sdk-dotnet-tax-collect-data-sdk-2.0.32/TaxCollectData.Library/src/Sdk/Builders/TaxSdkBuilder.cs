using TaxCollectData.Library.Sdk.Configuration;

namespace TaxCollectData.Library.Sdk.Builders;

/// <summary>
/// Fluent builder for Tax SDK configuration
/// </summary>
public class TaxSdkBuilder
{
    private readonly TaxSdkOptions _options = new();

    /// <summary>
    /// Sets the base URL
    /// </summary>
    public TaxSdkBuilder WithBaseUrl(string baseUrl)
    {
        _options.BaseUrl = baseUrl;
        return this;
    }

    /// <summary>
    /// Sets the client ID
    /// </summary>
    public TaxSdkBuilder WithClientId(string clientId)
    {
        _options.ClientId = clientId;
        return this;
    }

    /// <summary>
    /// Configures PKCS#8 certificate (file-based)
    /// </summary>
    public TaxSdkBuilder WithPkcs8Certificate(string privateKeyPath, string certificatePath)
    {
        _options.PrivateKeyPath = privateKeyPath;
        _options.CertificatePath = certificatePath;
        return this;
    }

    /// <summary>
    /// Configures PKCS#11 certificate (hardware token)
    /// </summary>
    public TaxSdkBuilder WithPkcs11Certificate(string libraryPath, string tokenSerialNumber, string tokenPin)
    {
        _options.Pkcs11LibraryPath = libraryPath;
        _options.Pkcs11TokenSerialNumber = tokenSerialNumber;
        _options.Pkcs11TokenPin = tokenPin;
        return this;
    }

    /// <summary>
    /// Sets the request timeout
    /// </summary>
    public TaxSdkBuilder WithTimeout(TimeSpan timeout)
    {
        _options.RequestTimeout = timeout;
        return this;
    }

    /// <summary>
    /// Sets the API version
    /// </summary>
    public TaxSdkBuilder WithApiVersion(string version)
    {
        _options.ApiVersion = version;
        return this;
    }

    /// <summary>
    /// Adds a custom HTTP header
    /// </summary>
    public TaxSdkBuilder WithCustomHeader(string name, string value)
    {
        _options.CustomHeaders[name] = value;
        return this;
    }

    /// <summary>
    /// Builds the Tax SDK options
    /// </summary>
    public TaxSdkOptions Build()
    {
        _options.Validate();
        return _options;
    }
}

