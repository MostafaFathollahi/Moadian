using System.Globalization;
using TaxCollectData.Library.Domain.Interfaces;

namespace TaxCollectData.Library.Infrastructure.Providers;

/// <summary>
/// Current date provider implementation
/// </summary>
public class CurrentDateProvider : ICurrentDateProvider
{
    private const string Format = "yyyy-MM-dd'T'HH:mm:ss'Z'";

    public DateTime Now => DateTime.Now;
    public DateTime UtcNow => DateTime.UtcNow;

    public string ToDateFormat()
    {
        return DateTime.UtcNow.ToString(Format, CultureInfo.InvariantCulture);
    }
}

