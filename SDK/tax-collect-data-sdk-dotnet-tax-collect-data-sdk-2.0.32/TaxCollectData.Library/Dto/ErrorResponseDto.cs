using System.Text;
using System.Text.Json;
using TaxCollectData.Library.Configs;
using TaxCollectData.Library.Models;

namespace TaxCollectData.Library.Dto;

public class ErrorResponseDto
{
    public ErrorResponseDto(long timestamp, string requestTraceId, List<ErrorModel> errors)
    {
        Timestamp = timestamp;
        RequestTraceId = requestTraceId;
        Errors = errors;
    }

    public override string ToString()
    {
        return Encoding.UTF8.GetString(JsonSerializer.SerializeToUtf8Bytes(this, JsonSerializerConfig.JsonSerializerOptions));
    }

    public long Timestamp { get; }
    public string RequestTraceId { get; }
    public List<ErrorModel> Errors { get; }

}