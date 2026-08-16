using FluentAssertions;
using NSubstitute;
using TaxCollectData.Library.Application.DTOs;
using TaxCollectData.Library.Application.Services;
using TaxCollectData.Library.Infrastructure.ExternalApi;
using Xunit;

namespace TaxCollectData.Test.UnitTests;

public class TaxpayerServiceTests
{
    private readonly ITaxApiClient _taxApiClient;
    private readonly TaxpayerService _taxpayerService;

    public TaxpayerServiceTests()
    {
        _taxApiClient = Substitute.For<ITaxApiClient>();
        _taxpayerService = new TaxpayerService(_taxApiClient);
    }

    [Fact]
    public async Task GetTaxpayerAsync_WithValidEconomicCode_ReturnsTaxpayer()
    {
        // Arrange
        var economicCode = "14003778990";
        var expectedTaxpayer = new TaxpayerDto
        {
            NationalId = economicCode,
            NameTrade = "Test Company"
        };

        _taxApiClient.GetTaxpayerAsync(economicCode, Arg.Any<CancellationToken>())
            .Returns(expectedTaxpayer);

        // Act
        var result = await _taxpayerService.GetTaxpayerAsync(economicCode);

        // Assert
        result.Should().NotBeNull();
        result.NationalId.Should().Be(economicCode);
        result.NameTrade.Should().Be("Test Company");
    }

    [Fact]
    public async Task GetTaxpayerAsync_WithNullEconomicCode_ThrowsArgumentException()
    {
        // Act & Assert
        await Assert.ThrowsAsync<ArgumentException>(() => 
            _taxpayerService.GetTaxpayerAsync(null!));
    }

    [Fact]
    public async Task GetTaxpayerAsync_WithEmptyEconomicCode_ThrowsArgumentException()
    {
        // Act & Assert
        await Assert.ThrowsAsync<ArgumentException>(() => 
            _taxpayerService.GetTaxpayerAsync(string.Empty));
    }
}

