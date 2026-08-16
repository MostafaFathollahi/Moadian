using TaxCollectData.Library.Application.DTOs;
using TaxCollectData.Library.Application.Interfaces;
using TaxCollectData.Library.Infrastructure.ExternalApi;

namespace TaxCollectData.Library.Application.Services;

/// <summary>
/// Service for authentication operations
/// </summary>
public class AuthenticationService : IAuthenticationService
{
    private readonly ITaxApiClient _taxApiClient;

    public AuthenticationService(ITaxApiClient taxApiClient)
    {
        _taxApiClient = taxApiClient ?? throw new ArgumentNullException(nameof(taxApiClient));
    }

    public async Task<ServerInformationDto> GetServerInformationAsync(CancellationToken cancellationToken = default)
    {
        return await _taxApiClient.GetServerInformationAsync(cancellationToken).ConfigureAwait(false);
    }
}

