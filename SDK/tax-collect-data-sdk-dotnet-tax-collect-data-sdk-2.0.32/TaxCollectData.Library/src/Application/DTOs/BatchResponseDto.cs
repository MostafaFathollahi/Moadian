namespace TaxCollectData.Library.Application.DTOs;

public class BatchResponseDto
{
    public long Timestamp { get; set; }
    public List<ResponsePacketDto> Result { get; set; } = new();
}

