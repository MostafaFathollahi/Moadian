using TaxCollectData.Library.Application.DTOs;
using TaxCollectData.Library.Application.Interfaces;
using TaxCollectData.Library.Infrastructure.ExternalApi;

namespace TaxCollectData.Library.Application.Services;

/// <summary>
/// Service for taxpayer operations
/// </summary>
public class TaxpayerService : ITaxpayerService
{
    private readonly ITaxApiClient _taxApiClient;

    public TaxpayerService(ITaxApiClient taxApiClient)
    {
        _taxApiClient = taxApiClient ?? throw new ArgumentNullException(nameof(taxApiClient));
    }

    public async Task<TaxpayerDto> GetTaxpayerAsync(string economicCode, CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(economicCode))
        {
            throw new ArgumentException("Economic code cannot be null or empty", nameof(economicCode));
        }

        return await _taxApiClient.GetTaxpayerAsync(economicCode, cancellationToken).ConfigureAwait(false);
    }
}

