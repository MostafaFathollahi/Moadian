using TaxCollectData.Library.Application.DTOs;

namespace TaxCollectData.Library.Application.Interfaces;

/// <summary>
/// Service for taxpayer operations
/// </summary>
public interface ITaxpayerService
{
    /// <summary>
    /// Gets taxpayer information by economic code
    /// </summary>
    Task<TaxpayerDto> GetTaxpayerAsync(string economicCode, CancellationToken cancellationToken = default);
}

