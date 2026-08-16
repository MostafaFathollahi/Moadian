namespace TaxCollectData.Library.Infrastructure.Http;

/// <summary>
/// URL provider implementation
/// </summary>
public class UrlProvider : IUrlProvider
{
    private readonly string _baseUrl;
    private readonly string _apiVersion;

    public UrlProvider(string baseUrl, string apiVersion = "v2")
    {
        if (string.IsNullOrWhiteSpace(baseUrl))
        {
            throw new ArgumentException("Base URL cannot be null or empty", nameof(baseUrl));
        }

        _baseUrl = baseUrl.TrimEnd('/');
        _apiVersion = apiVersion;
    }

    public string GetUrl(string endpoint)
    {
        if (string.IsNullOrWhiteSpace(endpoint))
        {
            throw new ArgumentException("Endpoint cannot be null or empty", nameof(endpoint));
        }

        return $"{_baseUrl}/api/{_apiVersion}/{endpoint.TrimStart('/')}";
    }
}

