namespace TaxCollectData.Library.Domain.Interfaces;

/// <summary>
/// Provider for generating Tax IDs
/// </summary>
public interface ITaxIdProvider
{
    /// <summary>
    /// Generates a Tax ID based on client ID, serial number, and date
    /// </summary>
    string GenerateTaxId(string clientId, long serial, DateTime date);
}

