using System.Net;
using System.Text;
using System.Text.Json;

namespace TaxCollectData.Test.Mocks;

/// <summary>
/// Mock HTTP message handler for testing
/// </summary>
public class MockHttpMessageHandler : HttpMessageHandler
{
    private readonly Func<HttpRequestMessage, Task<HttpResponseMessage>> _handler;

    public MockHttpMessageHandler(Func<HttpRequestMessage, Task<HttpResponseMessage>> handler)
    {
        _handler = handler;
    }

    protected override Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request,
        CancellationToken cancellationToken)
    {
        return _handler(request);
    }

    public static MockHttpMessageHandler CreateSuccessResponse<T>(T content)
    {
        return new MockHttpMessageHandler(async request =>
        {
            var json = JsonSerializer.Serialize(content);
            return new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(json, Encoding.UTF8, "application/json")
            };
        });
    }

    public static MockHttpMessageHandler CreateErrorResponse(HttpStatusCode statusCode, string errorMessage)
    {
        return new MockHttpMessageHandler(async request =>
        {
            return new HttpResponseMessage(statusCode)
            {
                Content = new StringContent(errorMessage, Encoding.UTF8, "application/json")
            };
        });
    }
}

