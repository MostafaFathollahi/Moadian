namespace TaxCollectData.Library.Domain.Interfaces;

/// <summary>
/// Provider for current date/time (for testability)
/// </summary>
public interface ICurrentDateProvider
{
    DateTime Now { get; }
    DateTime UtcNow { get; }
    string ToDateFormat();
}
