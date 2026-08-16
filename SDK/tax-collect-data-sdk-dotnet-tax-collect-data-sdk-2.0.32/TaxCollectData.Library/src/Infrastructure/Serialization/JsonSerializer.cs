using System.Text.Json;

namespace TaxCollectData.Library.Infrastructure.Serialization;

/// <summary>
/// JSON serializer implementation using System.Text.Json
/// </summary>
public class JsonSerializer : IJsonSerializer
{
    private readonly JsonSerializerOptions _options;

    public JsonSerializer(JsonSerializerOptions? options = null)
    {
        _options = options ?? CreateDefaultOptions();
    }

    public string Serialize<T>(T obj)
    {
        if (obj == null)
        {
            throw new ArgumentNullException(nameof(obj));
        }

        return System.Text.Json.JsonSerializer.Serialize(obj, _options);
    }

    public T? Deserialize<T>(string json)
    {
        if (string.IsNullOrWhiteSpace(json))
        {
            throw new ArgumentException("JSON string cannot be null or empty", nameof(json));
        }

        return System.Text.Json.JsonSerializer.Deserialize<T>(json, _options);
    }

    public JsonSerializerOptions GetJsonSerializerOptions() => _options;

    private static JsonSerializerOptions CreateDefaultOptions()
    {
        return new JsonSerializerOptions
        {
            PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
            WriteIndented = false,
            DefaultIgnoreCondition = System.Text.Json.Serialization.JsonIgnoreCondition.WhenWritingNull
        };
    }
}

