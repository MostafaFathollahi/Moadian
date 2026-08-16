using TaxCollectData.Library.Application.DTOs;

namespace TaxCollectData.Library.Application.Interfaces;

/// <summary>
/// Service for payment operations
/// </summary>
public interface IPaymentService
{
    /// <summary>
    /// Registers a payment request
    /// </summary>
    Task<RegisterPaymentResultDto> RegisterPaymentAsync(RegisterPaymentRequestDto request, CancellationToken cancellationToken = default);
}

