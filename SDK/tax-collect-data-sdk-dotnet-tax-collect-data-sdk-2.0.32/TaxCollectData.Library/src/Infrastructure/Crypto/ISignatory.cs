namespace TaxCollectData.Library.Infrastructure.Crypto;

/// <summary>
/// Interface for signing data
/// </summary>
public interface ISignatory
{
    string Sign(string text);
    string Sign(object data);
}

