using TaxCollectData.Library.Application.DTOs;
using TaxCollectData.Library.Application.Interfaces;
using TaxCollectData.Library.Infrastructure.ExternalApi;

namespace TaxCollectData.Library.Application.Services;

/// <summary>
/// Service for payment operations
/// </summary>
public class PaymentService : IPaymentService
{
    private readonly ITaxApiClient _taxApiClient;

    public PaymentService(ITaxApiClient taxApiClient)
    {
        _taxApiClient = taxApiClient ?? throw new ArgumentNullException(nameof(taxApiClient));
    }

    public async Task<RegisterPaymentResultDto> RegisterPaymentAsync(RegisterPaymentRequestDto request, CancellationToken cancellationToken = default)
    {
        if (request == null)
        {
            throw new ArgumentNullException(nameof(request));
        }

        return await _taxApiClient.RegisterPaymentAsync(request, cancellationToken).ConfigureAwait(false);
    }
}

