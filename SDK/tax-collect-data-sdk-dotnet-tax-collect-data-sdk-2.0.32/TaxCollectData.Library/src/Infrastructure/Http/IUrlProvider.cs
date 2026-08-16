namespace TaxCollectData.Library.Infrastructure.Http;

/// <summary>
/// Provider for generating API URLs
/// </summary>
public interface IUrlProvider
{
    string GetUrl(string endpoint);
}

