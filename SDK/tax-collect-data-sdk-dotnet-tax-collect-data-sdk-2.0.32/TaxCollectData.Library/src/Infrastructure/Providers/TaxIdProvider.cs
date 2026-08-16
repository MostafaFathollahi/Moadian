using System.Text;
using TaxCollectData.Library.Domain.Interfaces;

namespace TaxCollectData.Library.Infrastructure.Providers;

/// <summary>
/// Provider for generating Tax IDs
/// </summary>
public class TaxIdProvider : ITaxIdProvider
{
    private readonly IErrorDetectionAlgorithm _errorDetectionAlgorithm;

    public TaxIdProvider(IErrorDetectionAlgorithm errorDetectionAlgorithm)
    {
        _errorDetectionAlgorithm = errorDetectionAlgorithm ?? throw new ArgumentNullException(nameof(errorDetectionAlgorithm));
    }

    public string GenerateTaxId(string clientId, long serial, DateTime date)
    {
        if (string.IsNullOrWhiteSpace(clientId))
        {
            throw new ArgumentException("ClientId cannot be null or empty", nameof(clientId));
        }

        if (serial < 0)
        {
            throw new ArgumentException("Serial cannot be negative", nameof(serial));
        }

        var timeDayRange = (int)(new DateTimeOffset(date).ToUnixTimeSeconds() / (3600 * 24));
        var hexTime = Convert.ToString(timeDayRange, 16);
        var hexSerial = Convert.ToString(serial, 16);
        var initial = $"{clientId}{hexTime.PadLeft(5, '0')}{hexSerial.PadLeft(10, '0')}";
        var controlText = $"{ToDecimal(clientId)}{timeDayRange.ToString().PadLeft(6, '0')}{serial.ToString().PadLeft(12, '0')}";
        var result = $"{initial}{_errorDetectionAlgorithm.GenerateCheckDigit(controlText)}";
        return result.ToUpperInvariant();
    }

    private static string ToDecimal(string memoryId)
    {
        var decimalFormat = new StringBuilder();
        foreach (var ch in memoryId)
        {
            if (char.IsDigit(ch))
            {
                decimalFormat.Append(ch);
            }
            else
            {
                decimalFormat.Append((int)ch);
            }
        }

        return decimalFormat.ToString();
    }
}

