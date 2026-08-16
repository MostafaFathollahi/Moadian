using TaxCollectData.Library.Application.DTOs;

namespace TaxCollectData.Library.Application.Interfaces;

/// <summary>
/// Service for authentication operations
/// </summary>
public interface IAuthenticationService
{
    /// <summary>
    /// Gets server information and public keys
    /// </summary>
    Task<ServerInformationDto> GetServerInformationAsync(CancellationToken cancellationToken = default);
}

