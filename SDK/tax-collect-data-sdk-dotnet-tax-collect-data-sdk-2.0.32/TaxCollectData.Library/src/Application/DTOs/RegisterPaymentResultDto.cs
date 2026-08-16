using TaxCollectData.Library.Domain.Enums;

namespace TaxCollectData.Library.Application.DTOs;

public class RegisterPaymentResultDto
{
    public RequestStatus RequestStatus { get; set; }
    public List<ErrorDto> Error { get; set; } = new();
    public long CreateDate { get; set; }
}

