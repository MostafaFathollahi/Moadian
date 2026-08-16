namespace TaxCollectData.Library.Application.DTOs;

/// <summary>
/// Server information DTO
/// </summary>
public class ServerInformationDto
{
    public long ServerTime { get; set; }
    public List<PublicKeyDto> PublicKeys { get; set; } = new();
}

/// <summary>
/// Public key DTO
/// </summary>
public class PublicKeyDto
{
    public string Id { get; set; } = string.Empty;
    public string Key { get; set; } = string.Empty;
    public string? Algorithm { get; set; }
    public int? Purpose { get; set; }
}

