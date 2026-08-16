namespace TaxCollectData.Library.Domain.Interfaces;

/// <summary>
/// Algorithm for error detection (e.g., Verhoeff algorithm)
/// </summary>
public interface IErrorDetectionAlgorithm
{
    /// <summary>
    /// Generates a check digit for the given number
    /// </summary>
    string GenerateCheckDigit(string number);

    /// <summary>
    /// Validates the check digit
    /// </summary>
    bool ValidateCheckDigit(string number);
}
