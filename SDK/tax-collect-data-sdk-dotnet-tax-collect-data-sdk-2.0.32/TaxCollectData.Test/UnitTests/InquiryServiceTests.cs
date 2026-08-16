using FluentAssertions;
using NSubstitute;
using TaxCollectData.Library.Application.DTOs;
using TaxCollectData.Library.Application.Services;
using TaxCollectData.Library.Infrastructure.ExternalApi;
using Xunit;

namespace TaxCollectData.Test.UnitTests;

public class InquiryServiceTests
{
    private readonly ITaxApiClient _taxApiClient;
    private readonly InquiryService _inquiryService;

    public InquiryServiceTests()
    {
        _taxApiClient = Substitute.For<ITaxApiClient>();
        _inquiryService = new InquiryService(_taxApiClient);
    }

    [Fact]
    public async Task InquiryByTimeAsync_WithValidDto_ReturnsResults()
    {
        // Arrange
        var dto = new InquiryByTimeRangeDto(
            DateTime.Now.AddDays(-1),
            DateTime.Now,
            null,
            null);

        var expectedResults = new List<InquiryResultDto>
        {
            new()
            {
                ReferenceNumber = "REF001",
                Uid = "UID001",
                Status = "SUCCESS"
            }
        };

        _taxApiClient.InquiryByTimeAsync(dto, Arg.Any<CancellationToken>())
            .Returns(expectedResults);

        // Act
        var result = await _inquiryService.InquiryByTimeAsync(dto);

        // Assert
        result.Should().NotBeNull();
        result.Should().HaveCount(1);
        result[0].ReferenceNumber.Should().Be("REF001");
    }

    [Fact]
    public async Task InquiryByUidAsync_WithValidDto_ReturnsResults()
    {
        // Arrange
        var dto = new InquiryByUidDto(
            new List<string> { "UID001" },
            "FISCAL001");

        var expectedResults = new List<InquiryResultDto>();

        _taxApiClient.InquiryByUidAsync(dto, Arg.Any<CancellationToken>())
            .Returns(expectedResults);

        // Act
        var result = await _inquiryService.InquiryByUidAsync(dto);

        // Assert
        result.Should().NotBeNull();
    }

    [Fact]
    public async Task InquiryByReferenceIdAsync_WithNullDto_ThrowsArgumentNullException()
    {
        // Act & Assert
        await Assert.ThrowsAsync<ArgumentNullException>(() => 
            _inquiryService.InquiryByReferenceIdAsync(null!));
    }
}

