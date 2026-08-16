namespace TaxCollectData.Library.Application.DTOs;

public class PacketDto
{
    public string Payload { get; set; } = string.Empty;
    public PacketHeaderDto Header { get; set; } = new();
}

