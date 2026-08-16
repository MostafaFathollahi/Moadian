using FluentAssertions;
using TaxCollectData.Library.Infrastructure.Http;
using Xunit;

namespace TaxCollectData.Test.UnitTests;

public class UrlProviderTests
{
    [Fact]
    public void GetUrl_WithValidEndpoint_ReturnsCorrectUrl()
    {
        // Arrange
        var baseUrl = "https://api.example.com";
        var provider = new UrlProvider(baseUrl);

        // Act
        var result = provider.GetUrl("invoice");

        // Assert
        result.Should().Be("https://api.example.com/api/v2/invoice");
    }

    [Fact]
    public void GetUrl_WithCustomApiVersion_ReturnsCorrectUrl()
    {
        // Arrange
        var baseUrl = "https://api.example.com";
        var provider = new UrlProvider(baseUrl, "v3");

        // Act
        var result = provider.GetUrl("invoice");

        // Assert
        result.Should().Be("https://api.example.com/api/v3/invoice");
    }

    [Fact]
    public void GetUrl_WithEndpointStartingWithSlash_RemovesSlash()
    {
        // Arrange
        var baseUrl = "https://api.example.com";
        var provider = new UrlProvider(baseUrl);

        // Act
        var result = provider.GetUrl("/invoice");

        // Assert
        result.Should().Be("https://api.example.com/api/v2/invoice");
    }

    [Fact]
    public void GetUrl_WithNullEndpoint_ThrowsArgumentException()
    {
        // Arrange
        var provider = new UrlProvider("https://api.example.com");

        // Act & Assert
        Assert.Throws<ArgumentException>(() => provider.GetUrl(null!));
    }

    [Fact]
    public void GetUrl_WithEmptyEndpoint_ThrowsArgumentException()
    {
        // Arrange
        var provider = new UrlProvider("https://api.example.com");

        // Act & Assert
        Assert.Throws<ArgumentException>(() => provider.GetUrl(string.Empty));
    }
}

