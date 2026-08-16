using FluentAssertions;
using TaxCollectData.Library.Domain.Interfaces;
using TaxCollectData.Library.Infrastructure.Algorithms;
using TaxCollectData.Library.Infrastructure.Providers;
using Xunit;

namespace TaxCollectData.Test.UnitTests;

public class TaxIdProviderTests
{
    private readonly ITaxIdProvider _taxIdProvider;

    public TaxIdProviderTests()
    {
        var algorithm = new VerhoeffAlgorithm();
        _taxIdProvider = new TaxIdProvider(algorithm);
    }

    [Fact]
    public void GenerateTaxId_WithValidInput_ReturnsTaxId()
    {
        // Arrange
        var clientId = "A111YO";
        var serial = 123456789L;
        var date = new DateTime(2024, 1, 1);

        // Act
        var result = _taxIdProvider.GenerateTaxId(clientId, serial, date);

        // Assert
        result.Should().NotBeNullOrEmpty();
        result.Should().StartWith(clientId);
    }

    [Fact]
    public void GenerateTaxId_WithSameInput_ReturnsSameTaxId()
    {
        // Arrange
        var clientId = "A111YO";
        var serial = 123456789L;
        var date = new DateTime(2024, 1, 1);

        // Act
        var result1 = _taxIdProvider.GenerateTaxId(clientId, serial, date);
        var result2 = _taxIdProvider.GenerateTaxId(clientId, serial, date);

        // Assert
        result1.Should().Be(result2);
    }

    [Fact]
    public void GenerateTaxId_WithDifferentSerial_ReturnsDifferentTaxId()
    {
        // Arrange
        var clientId = "A111YO";
        var date = new DateTime(2024, 1, 1);

        // Act
        var result1 = _taxIdProvider.GenerateTaxId(clientId, 100L, date);
        var result2 = _taxIdProvider.GenerateTaxId(clientId, 200L, date);

        // Assert
        result1.Should().NotBe(result2);
    }

    [Fact]
    public void GenerateTaxId_WithNullClientId_ThrowsArgumentException()
    {
        // Act & Assert
        Assert.Throws<ArgumentException>(() => 
            _taxIdProvider.GenerateTaxId(null!, 100L, DateTime.Now));
    }

    [Fact]
    public void GenerateTaxId_WithNegativeSerial_ThrowsArgumentException()
    {
        // Act & Assert
        Assert.Throws<ArgumentException>(() => 
            _taxIdProvider.GenerateTaxId("A111YO", -1L, DateTime.Now));
    }
}

