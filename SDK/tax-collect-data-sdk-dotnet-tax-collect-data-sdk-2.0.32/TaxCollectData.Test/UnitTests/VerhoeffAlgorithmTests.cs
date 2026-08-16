using FluentAssertions;
using TaxCollectData.Library.Domain.Interfaces;
using TaxCollectData.Library.Infrastructure.Algorithms;
using Xunit;

namespace TaxCollectData.Test.UnitTests;

public class VerhoeffAlgorithmTests
{
    private readonly IErrorDetectionAlgorithm _algorithm;

    public VerhoeffAlgorithmTests()
    {
        _algorithm = new VerhoeffAlgorithm();
    }

    [Fact]
    public void GenerateCheckDigit_WithValidNumber_ReturnsCheckDigit()
    {
        // Arrange
        var number = "123456";

        // Act
        var result = _algorithm.GenerateCheckDigit(number);

        // Assert
        result.Should().NotBeNullOrEmpty();
        result.Should().HaveLength(1);
        result.Should().MatchRegex("^[0-9]$");
    }

    [Fact]
    public void ValidateCheckDigit_WithValidNumber_ReturnsTrue()
    {
        // Arrange
        var number = "123456";
        var checkDigit = _algorithm.GenerateCheckDigit(number);
        var numberWithCheckDigit = number + checkDigit;

        // Act
        var result = _algorithm.ValidateCheckDigit(numberWithCheckDigit);

        // Assert
        result.Should().BeTrue();
    }

    [Fact]
    public void ValidateCheckDigit_WithInvalidNumber_ReturnsFalse()
    {
        // Arrange
        var number = "123456";
        var checkDigit = _algorithm.GenerateCheckDigit(number);
        var invalidNumber = number + ((int.Parse(checkDigit) + 1) % 10).ToString();

        // Act
        var result = _algorithm.ValidateCheckDigit(invalidNumber);

        // Assert
        result.Should().BeFalse();
    }

    [Fact]
    public void GenerateCheckDigit_WithNullNumber_ThrowsArgumentException()
    {
        // Act & Assert
        Assert.Throws<ArgumentException>(() => 
            _algorithm.GenerateCheckDigit(null!));
    }

    [Fact]
    public void GenerateCheckDigit_WithEmptyNumber_ThrowsArgumentException()
    {
        // Act & Assert
        Assert.Throws<ArgumentException>(() => 
            _algorithm.GenerateCheckDigit(string.Empty));
    }

    [Fact]
    public void GenerateCheckDigit_WithNonNumericCharacters_ThrowsArgumentException()
    {
        // Act & Assert
        Assert.Throws<ArgumentException>(() => 
            _algorithm.GenerateCheckDigit("123ABC"));
    }
}

