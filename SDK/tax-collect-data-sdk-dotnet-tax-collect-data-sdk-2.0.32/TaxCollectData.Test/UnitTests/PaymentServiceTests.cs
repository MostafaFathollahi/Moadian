using FluentAssertions;
using NSubstitute;
using TaxCollectData.Library.Application.DTOs;
using TaxCollectData.Library.Application.Services;
using TaxCollectData.Library.Domain.Enums;
using TaxCollectData.Library.Infrastructure.ExternalApi;
using Xunit;

namespace TaxCollectData.Test.UnitTests;

public class PaymentServiceTests
{
    private readonly ITaxApiClient _taxApiClient;
    private readonly PaymentService _paymentService;

    public PaymentServiceTests()
    {
        _taxApiClient = Substitute.For<ITaxApiClient>();
        _paymentService = new PaymentService(_taxApiClient);
    }

    [Fact]
    public async Task RegisterPaymentAsync_WithValidRequest_ReturnsResult()
    {
        // Arrange
        var request = new RegisterPaymentRequestDto
        {
            TaxId = "TAX001",
            PaidAmount = 100000,
            PaymentDate = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
            PaymentMethod = PaymentMethod.Cash
        };

        var expectedResult = new RegisterPaymentResultDto
        {
            RequestStatus = RequestStatus.SUCCESS,
            CreateDate = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()
        };

        _taxApiClient.RegisterPaymentAsync(request, Arg.Any<CancellationToken>())
            .Returns(expectedResult);

        // Act
        var result = await _paymentService.RegisterPaymentAsync(request);

        // Assert
        result.Should().NotBeNull();
        result.RequestStatus.Should().Be(RequestStatus.SUCCESS);
    }

    [Fact]
    public async Task RegisterPaymentAsync_WithNullRequest_ThrowsArgumentNullException()
    {
        // Act & Assert
        await Assert.ThrowsAsync<ArgumentNullException>(() => 
            _paymentService.RegisterPaymentAsync(null!));
    }
}

