using FluentAssertions;
using NSubstitute;
using TaxCollectData.Library.Application.DTOs;
using TaxCollectData.Library.Application.Services;
using TaxCollectData.Library.Domain.ValueObjects;
using TaxCollectData.Library.Infrastructure.Crypto;
using TaxCollectData.Library.Infrastructure.Serialization;
using Xunit;

namespace TaxCollectData.Test.UnitTests;

public class PacketServiceTests
{
    private readonly ClientId _clientId;
    private readonly ISignatory _signatory;
    private readonly IEncryptor _encryptor;
    private readonly IJsonSerializer _serializer;
    private readonly PacketService _packetService;

    public PacketServiceTests()
    {
        _clientId = new ClientId("A111YO");
        _signatory = Substitute.For<ISignatory>();
        _encryptor = Substitute.For<IEncryptor>();
        _serializer = Substitute.For<IJsonSerializer>();
        
        _packetService = new PacketService(_clientId, _signatory, _encryptor, _serializer);
    }

    [Fact]
    public void CreateInvoicePacket_WithValidInvoice_ReturnsPacket()
    {
        // Arrange
        var invoice = new InvoiceDto
        {
            Header = new HeaderDto { taxid = "TAX001" },
            Body = new List<BodyItemDto>()
        };

        _serializer.Serialize(invoice).Returns("{\"header\":{\"taxid\":\"TAX001\"}}");
        _signatory.Sign(Arg.Any<string>()).Returns("signed_data");
        _encryptor.Encrypt(Arg.Any<string>()).Returns("encrypted_data");

        // Act
        var result = _packetService.CreateInvoicePacket(invoice);

        // Assert
        result.Should().NotBeNull();
        result.Payload.Should().Be("encrypted_data");
        result.Header.Should().NotBeNull();
        result.Header.FiscalId.Should().Be("A111YO");
        result.Header.RequestTraceId.Should().NotBeNullOrEmpty();
    }

    [Fact]
    public void CreateInvoicePacket_WithNullInvoice_ThrowsArgumentNullException()
    {
        // Act & Assert
        Assert.Throws<ArgumentNullException>(() => 
            _packetService.CreateInvoicePacket(null!));
    }

    [Fact]
    public void CreateInvoicePacket_GeneratesUniqueRequestTraceId()
    {
        // Arrange
        var invoice = new InvoiceDto
        {
            Header = new HeaderDto { taxid = "TAX001" },
            Body = new List<BodyItemDto>()
        };

        _serializer.Serialize(invoice).Returns("{}");
        _signatory.Sign(Arg.Any<string>()).Returns("signed");
        _encryptor.Encrypt(Arg.Any<string>()).Returns("encrypted");

        // Act
        var result1 = _packetService.CreateInvoicePacket(invoice);
        var result2 = _packetService.CreateInvoicePacket(invoice);

        // Assert
        result1.Header.RequestTraceId.Should().NotBe(result2.Header.RequestTraceId);
    }
}

