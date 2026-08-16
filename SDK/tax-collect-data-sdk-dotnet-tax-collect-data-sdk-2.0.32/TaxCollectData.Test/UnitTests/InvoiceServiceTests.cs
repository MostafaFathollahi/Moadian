using FluentAssertions;
using NSubstitute;
using TaxCollectData.Library.Application.DTOs;
using TaxCollectData.Library.Application.Services;
using TaxCollectData.Library.Application.Interfaces;
using TaxCollectData.Library.Infrastructure.ExternalApi;
using Xunit;

namespace TaxCollectData.Test.UnitTests;

public class InvoiceServiceTests
{
    private readonly ITaxApiClient _taxApiClient;
    private readonly IPacketService _packetService;
    private readonly InvoiceService _invoiceService;

    public InvoiceServiceTests()
    {
        _taxApiClient = Substitute.For<ITaxApiClient>();
        _packetService = Substitute.For<IPacketService>();
        _invoiceService = new InvoiceService(_taxApiClient, _packetService);
    }

    [Fact]
    public async Task SendInvoicesAsync_WithValidInvoices_ReturnsResponses()
    {
        // Arrange
        var invoices = new List<InvoiceDto>
        {
            new()
            {
                Header = new HeaderDto { taxid = "TAX001" },
                Body = new List<BodyItemDto>()
            }
        };

        var packet = new PacketDto
        {
            Payload = "encrypted",
            Header = new PacketHeaderDto { RequestTraceId = "trace1", FiscalId = "A111YO" }
        };

        var batchResponse = new BatchResponseDto
        {
            Timestamp = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
            Result = new List<ResponsePacketDto>
            {
                new()
                {
                    Uid = "trace1",
                    ReferenceNumber = "REF001",
                    Data = "success"
                }
            }
        };

        _packetService.CreateInvoicePacket(Arg.Any<InvoiceDto>()).Returns(packet);
        _taxApiClient.SendInvoicesAsync(Arg.Any<List<PacketDto>>(), Arg.Any<CancellationToken>())
            .Returns(batchResponse);

        // Act
        var result = await _invoiceService.SendInvoicesAsync(invoices);

        // Assert
        result.Should().NotBeNull();
        result.Should().HaveCount(1);
        result[0].TaxId.Should().Be("TAX001");
        result[0].ReferenceNumber.Should().Be("REF001");
    }

    [Fact]
    public async Task SendInvoicesAsync_WithNullInvoices_ThrowsArgumentException()
    {
        // Act & Assert
        await Assert.ThrowsAsync<ArgumentException>(() => 
            _invoiceService.SendInvoicesAsync(null!));
    }

    [Fact]
    public async Task SendInvoicesAsync_WithEmptyInvoices_ThrowsArgumentException()
    {
        // Act & Assert
        await Assert.ThrowsAsync<ArgumentException>(() => 
            _invoiceService.SendInvoicesAsync(new List<InvoiceDto>()));
    }

    [Fact]
    public async Task GetInvoiceStatusAsync_WithValidTaxIds_ReturnsStatuses()
    {
        // Arrange
        var taxIds = new List<string> { "TAX001", "TAX002" };
        var responses = new List<InvoiceStatusInquiryResponseDto>
        {
            new("TAX001", "SUCCESS", "ACTIVE", ""),
            new("TAX002", "PENDING", "INACTIVE", "")
        };

        _taxApiClient.InquiryInvoiceStatusAsync(taxIds, Arg.Any<CancellationToken>())
            .Returns(responses);

        // Act
        var result = await _invoiceService.GetInvoiceStatusAsync(taxIds);

        // Assert
        result.Should().NotBeNull();
        result.Should().HaveCount(2);
        result[0].TaxId.Should().Be("TAX001");
        result[1].TaxId.Should().Be("TAX002");
    }
}

