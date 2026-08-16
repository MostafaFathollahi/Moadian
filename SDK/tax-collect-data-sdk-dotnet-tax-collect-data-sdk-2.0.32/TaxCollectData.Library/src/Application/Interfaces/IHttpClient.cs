namespace TaxCollectData.Library.Application.Interfaces;

/// <summary>
/// Abstraction for HTTP client operations
/// </summary>
public interface IHttpClient
{
    /// <summary>
    /// Sends an HTTP request and returns the response
    /// </summary>
    Task<T> SendAsync<T>(HttpRequestMessage request, HttpRequestMessage nonceRequest, CancellationToken cancellationToken = default);
}

