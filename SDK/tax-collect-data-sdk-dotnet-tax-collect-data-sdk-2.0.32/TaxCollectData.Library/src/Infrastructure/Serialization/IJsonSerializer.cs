using System.Text.Json;

namespace TaxCollectData.Library.Infrastructure.Serialization;

/// <summary>
/// JSON serialization interface
/// </summary>
public interface IJsonSerializer
{
    string Serialize<T>(T obj);
    T? Deserialize<T>(string json);
    JsonSerializerOptions GetJsonSerializerOptions();
}

