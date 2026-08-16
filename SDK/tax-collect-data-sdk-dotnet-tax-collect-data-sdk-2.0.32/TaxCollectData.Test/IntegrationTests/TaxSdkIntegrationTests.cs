using FluentAssertions;
using Microsoft.Extensions.DependencyInjection;
using TaxCollectData.Library.Application.DTOs;
using TaxCollectData.Library.Sdk.Configuration;
using TaxCollectData.Library.Sdk.Extensions;
using TaxCollectData.Library.Sdk.Public;
using WireMock.RequestBuilders;
using WireMock.ResponseBuilders;
using WireMock.Server;
using Xunit;

namespace TaxCollectData.Test.IntegrationTests;

public class TaxSdkIntegrationTests : IDisposable
{
    private readonly WireMockServer _mockServer;
    private readonly IServiceProvider _serviceProvider;

    public TaxSdkIntegrationTests()
    {
        _mockServer = WireMockServer.Start();
        
        var services = new ServiceCollection();
        var options = new TaxSdkOptions
        {
            BaseUrl = _mockServer.Url!,
            ClientId = "TEST_CLIENT",
            PrivateKeyPath = "test_private_key.pem",
            CertificatePath = "test_certificate.crt"
        };

        // Note: In real tests, you would need actual certificate files
        // For now, this is a structure example
        // services.AddTaxSdk(options);
        // _serviceProvider = services.BuildServiceProvider();
        _serviceProvider = services.BuildServiceProvider();
    }

    [Fact(Skip = "Requires actual certificate files")]
    public async Task SendInvoicesAsync_WithMockServer_ReturnsSuccess()
    {
        // Arrange
        _mockServer
            .Given(Request.Create().WithPath("/api/v2/nonce").UsingGet())
            .RespondWith(Response.Create()
                .WithStatusCode(200)
                .WithBody("{\"nonce\":\"test-nonce\",\"expDate\":\"2024-12-31T23:59:59Z\"}"));

        _mockServer
            .Given(Request.Create().WithPath("/api/v2/invoice").UsingPost())
            .RespondWith(Response.Create()
                .WithStatusCode(200)
                .WithBody("{\"timestamp\":1234567890,\"result\":[{\"uid\":\"test-uid\",\"referenceNumber\":\"REF001\",\"data\":\"success\"}]}"));

        var sdk = _serviceProvider.GetRequiredService<TaxSdk>();
        var invoices = new List<InvoiceDto>
        {
            new()
            {
                Header = new HeaderDto { taxid = "TAX001" },
                Body = new List<BodyItemDto>()
            }
        };

        // Act
        var result = await sdk.SendInvoicesAsync(invoices);

        // Assert
        result.Should().NotBeNull();
        result.Should().HaveCount(1);
    }

    public void Dispose()
    {
        _mockServer?.Stop();
        _mockServer?.Dispose();
    }
}

