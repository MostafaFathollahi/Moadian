using FluentAssertions;
using TaxCollectData.Library.Domain.ValueObjects;
using Xunit;

namespace TaxCollectData.Test.UnitTests;

public class ClientIdTests
{
    [Fact]
    public void ClientId_WithValidValue_CreatesInstance()
    {
        // Act
        var clientId = new ClientId("A111YO");

        // Assert
        clientId.Value.Should().Be("A111YO");
    }

    [Fact]
    public void ClientId_WithNullValue_ThrowsArgumentException()
    {
        // Act & Assert
        Assert.Throws<ArgumentException>(() => new ClientId(null!));
    }

    [Fact]
    public void ClientId_WithEmptyValue_ThrowsArgumentException()
    {
        // Act & Assert
        Assert.Throws<ArgumentException>(() => new ClientId(string.Empty));
    }

    [Fact]
    public void ClientId_WithWhitespaceValue_ThrowsArgumentException()
    {
        // Act & Assert
        Assert.Throws<ArgumentException>(() => new ClientId("   "));
    }

    [Fact]
    public void ClientId_ImplicitConversion_Works()
    {
        // Arrange
        var clientId = new ClientId("A111YO");

        // Act
        string value = clientId;
        ClientId fromString = "A111YO";

        // Assert
        value.Should().Be("A111YO");
        fromString.Value.Should().Be("A111YO");
    }

    [Fact]
    public void ClientId_Equals_WithSameValue_ReturnsTrue()
    {
        // Arrange
        var clientId1 = new ClientId("A111YO");
        var clientId2 = new ClientId("A111YO");

        // Act & Assert
        clientId1.Equals(clientId2).Should().BeTrue();
        (clientId1 == clientId2).Should().BeFalse(); // No == operator, but Equals works
    }

    [Fact]
    public void ClientId_GetHashCode_WithSameValue_ReturnsSameHash()
    {
        // Arrange
        var clientId1 = new ClientId("A111YO");
        var clientId2 = new ClientId("A111YO");

        // Act & Assert
        clientId1.GetHashCode().Should().Be(clientId2.GetHashCode());
    }
}

