using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text;
using Microsoft.Extensions.Http;
using Microsoft.Extensions.Logging;
using TaxCollectData.Library.Application.Interfaces;
using TaxCollectData.Library.Domain.Exceptions;
using TaxCollectData.Library.Domain.ValueObjects;
using TaxCollectData.Library.Infrastructure.Crypto;
using TaxCollectData.Library.Infrastructure.Serialization;

namespace TaxCollectData.Library.Infrastructure.Http;

/// <summary>
/// HTTP client implementation for Tax API
/// </summary>
public class TaxHttpClient : IHttpClient
{
    private const string Bearer = "Bearer ";
    private const string MediaType = "application/json";
    private const string Charset = "utf-8";

    private readonly System.Net.Http.HttpClient _httpClient;
    private readonly ISignatory _signatory;
    private readonly ClientId _clientId;
    private readonly IJsonSerializer _serializer;
    private readonly ILogger<TaxHttpClient>? _logger;
    private readonly Dictionary<string, string> _customHeaders;

    public TaxHttpClient(
        IHttpClientFactory httpClientFactory,
        ISignatory signatory,
        ClientId clientId,
        IJsonSerializer serializer,
        Dictionary<string, string>? customHeaders = null,
        ILogger<TaxHttpClient>? logger = null)
    {
        _httpClient = httpClientFactory.CreateClient("TaxSdk");
        _signatory = signatory ?? throw new ArgumentNullException(nameof(signatory));
        _clientId = clientId ?? throw new ArgumentNullException(nameof(clientId));
        _serializer = serializer ?? throw new ArgumentNullException(nameof(serializer));
        _customHeaders = customHeaders ?? new Dictionary<string, string>();
        _logger = logger;
    }

    public async Task<T> SendAsync<T>(HttpRequestMessage request, HttpRequestMessage nonceRequest, CancellationToken cancellationToken = default)
    {
        var authenticatedRequest = await GetAuthenticatedRequestAsync(request, nonceRequest, cancellationToken).ConfigureAwait(false);
        return await SendRequestAsync<T>(authenticatedRequest, cancellationToken).ConfigureAwait(false);
    }

    private async Task<T> SendRequestAsync<T>(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        var stopwatch = System.Diagnostics.Stopwatch.StartNew();
        
        try
        {
            AddCustomHeaders(request);
            
            using var response = await _httpClient.SendAsync(request, cancellationToken).ConfigureAwait(false);

            if (!response.IsSuccessStatusCode)
            {
                throw await GetApiExceptionAsync(response, cancellationToken).ConfigureAwait(false);
            }

            _logger?.LogDebug("Calling {Url}", request.RequestUri?.ToString());
            
            var result = await response.Content
                .ReadFromJsonAsync<T>(_serializer.GetJsonSerializerOptions(), cancellationToken)
                .ConfigureAwait(false);

            if (result == null)
            {
                throw new TaxApiException("Response deserialization returned null");
            }

            return result;
        }
        finally
        {
            stopwatch.Stop();
            _logger?.LogDebug("Request completed in {ElapsedMs} ms", stopwatch.ElapsedMilliseconds);
        }
    }

    private async Task<Exception> GetApiExceptionAsync(HttpResponseMessage response, CancellationToken cancellationToken)
    {
        try
        {
            var errorResponse = await response.Content
                .ReadFromJsonAsync<ErrorResponseDto>(_serializer.GetJsonSerializerOptions(), cancellationToken)
                .ConfigureAwait(false);

            if (errorResponse != null)
            {
                return new TaxApiException(
                    $"API Error: {errorResponse.RequestTraceId}",
                    (int)response.StatusCode,
                    errorResponse.Errors.FirstOrDefault()?.Code,
                    errorResponse.Errors.FirstOrDefault()?.Message);
            }
        }
        catch
        {
            // Fall through to unknown response exception
        }

        var body = await response.Content.ReadAsStringAsync().ConfigureAwait(false);
        return new TaxApiException(
            $"Unknown API error: {body}",
            (int)response.StatusCode);
    }

    private async Task<HttpRequestMessage> GetAuthenticatedRequestAsync(
        HttpRequestMessage request, 
        HttpRequestMessage nonceRequest, 
        CancellationToken cancellationToken)
    {
        var signedNonce = await GetSignedNonceAsync(nonceRequest, cancellationToken).ConfigureAwait(false);
        request.Headers.Add("Authorization", signedNonce);
        request.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue(MediaType));
        request.Headers.AcceptCharset.Add(new StringWithQualityHeaderValue(Charset));
        return request;
    }

    private async Task<string> GetSignedNonceAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        var nonce = await SendRequestAsync<NonceDto>(request, cancellationToken).ConfigureAwait(false);
        var tokenModel = new TokenDto(nonce.Nonce, _clientId.Value);
        var signedToken = _signatory.Sign(_serializer.Serialize(tokenModel));
        return $"{Bearer}{signedToken}";
    }

    private void AddCustomHeaders(HttpRequestMessage request)
    {
        foreach (var header in _customHeaders)
        {
            request.Headers.Add(header.Key, header.Value);
        }
    }

    private record NonceDto(string Nonce, string ExpDate);
    private record TokenDto(string Nonce, string ClientId);
    private record ErrorResponseDto(long Timestamp, string RequestTraceId, List<ErrorItemDto> Errors);
    private record ErrorItemDto(string Code, string Message);
}

