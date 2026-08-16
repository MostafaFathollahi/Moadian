using TaxCollectData.Library.Application.DTOs;

namespace TaxCollectData.Library.Infrastructure.ExternalApi;

/// <summary>
/// Low-level client for Tax API
/// </summary>
public interface ITaxApiClient
{
    Task<BatchResponseDto> SendInvoicesAsync(List<PacketDto> packets, CancellationToken cancellationToken = default);
    Task<List<InquiryResultDto>> InquiryByTimeAsync(InquiryByTimeRangeDto dto, CancellationToken cancellationToken = default);
    Task<List<InquiryResultDto>> InquiryByUidAsync(InquiryByUidDto dto, CancellationToken cancellationToken = default);
    Task<List<InquiryResultDto>> InquiryByReferenceIdAsync(InquiryByReferenceNumberDto dto, CancellationToken cancellationToken = default);
    Task<List<InvoiceStatusInquiryResponseDto>> InquiryInvoiceStatusAsync(List<string> taxIds, CancellationToken cancellationToken = default);
    Task<TaxpayerDto> GetTaxpayerAsync(string economicCode, CancellationToken cancellationToken = default);
    Task<ServerInformationDto> GetServerInformationAsync(CancellationToken cancellationToken = default);
    Task<RegisterPaymentResultDto> RegisterPaymentAsync(RegisterPaymentRequestDto request, CancellationToken cancellationToken = default);
}

